import json
import math
import numpy as np
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import get_db_connection, db_transaction
from services.inventory_service import InventoryService
from utils.errors import ValidationError, NotFoundError
from utils.logger import app_logger


class ReplenishmentService:
    """
    Core Domain Service for Replenishment Policy & Order Optimization (Spec §17, §18, §19, §20).
    Implements stochastic Reorder Point (ROP) with lead-time demand variance,
    Economic Order Quantity (EOQ) with MOQ constraints, automated recommendation generation,
    and purchase order consolidation & receipt booking.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.inventory_service = InventoryService(db_path=db_path)

    @staticmethod
    def _get_z_score(service_level: float) -> float:
        """Standard normal quantile Z-factor for desired cycle-service level (Spec §17)."""
        z_table = {
            0.85: 1.036,
            0.90: 1.282,
            0.95: 1.645,
            0.98: 2.054,
            0.99: 2.326,
            0.999: 3.090
        }
        # Find closest match or default to 95%
        closest = min(z_table.keys(), key=lambda sl: abs(sl - service_level))
        return z_table[closest]

    def calculate_rop(self, product_id: int, service_level: float = 0.95) -> Dict[str, Any]:
        """
        Calculates stochastic Reorder Point (ROP) and Safety Stock (SS) (Spec §17).
        Formula:
          SS = Z * sqrt( L * sigma_d^2 + d_bar^2 * sigma_L^2 )
          ROP = (d_bar * L) + SS
        """
        conn = get_db_connection(self.db_path)
        try:
            prod = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if not prod:
                raise NotFoundError(f"Product ID {product_id} not found.")

            # 1. Demand Velocity (d_bar) & Volatility (sigma_d) from demand_history (last 90 days)
            dh_rows = conn.execute(
                """
                SELECT quantity_demanded 
                FROM demand_history 
                WHERE product_id = ? 
                ORDER BY date DESC LIMIT 90
                """,
                (product_id,)
            ).fetchall()

            if dh_rows and len(dh_rows) >= 5:
                demands = [r["quantity_demanded"] for r in dh_rows]
                d_bar = float(np.mean(demands))
                sigma_d = float(np.std(demands, ddof=1)) if len(demands) > 1 else 1.0
            else:
                # Fallback estimate
                d_bar = max(1.0, float(prod["reorder_threshold"]) / 7.0)
                sigma_d = d_bar * 0.3

            # 2. Supplier Lead Time (L) & Lead Time Variance (sigma_L)
            supp_row = conn.execute(
                """
                SELECT sp.supplier_lead_time_days, sp.unit_cost, sp.moq, s.lead_time_variance, s.name as supplier_name, s.id as supplier_id
                FROM supplier_products sp
                JOIN suppliers s ON sp.supplier_id = s.id
                WHERE sp.product_id = ?
                ORDER BY sp.is_primary DESC, sp.unit_cost ASC
                LIMIT 1
                """,
                (product_id,)
            ).fetchone()

            if supp_row:
                lead_time = float(supp_row["supplier_lead_time_days"])
                sigma_L = float(supp_row["lead_time_variance"] or 1.5)
                supplier_info = {
                    "supplier_id": supp_row["supplier_id"],
                    "supplier_name": supp_row["supplier_name"],
                    "unit_cost": float(supp_row["unit_cost"]),
                    "moq": int(supp_row["moq"])
                }
            else:
                lead_time = 7.0
                sigma_L = 1.5
                supplier_info = {
                    "supplier_id": None,
                    "supplier_name": "Unassigned",
                    "unit_cost": float(prod["price"]) * 0.7,
                    "moq": 10
                }

            z = self._get_z_score(service_level)

            # Combined variance: (L * sigma_d^2) + (d_bar^2 * sigma_L^2)
            combined_var = (lead_time * (sigma_d ** 2)) + ((d_bar ** 2) * (sigma_L ** 2))
            safety_stock = z * math.sqrt(max(0.1, combined_var))
            lead_time_demand = d_bar * lead_time
            reorder_point = lead_time_demand + safety_stock

            return {
                "product_id": product_id,
                "sku": prod["sku"],
                "name": prod["name"],
                "current_stock": prod["quantity"],
                "service_level": service_level,
                "z_score": round(z, 3),
                "avg_daily_demand": round(d_bar, 2),
                "demand_std_dev": round(sigma_d, 2),
                "lead_time_days": round(lead_time, 1),
                "lead_time_std_dev": round(sigma_L, 2),
                "lead_time_demand": round(lead_time_demand, 1),
                "safety_stock": int(math.ceil(safety_stock)),
                "reorder_point": int(math.ceil(reorder_point)),
                "supplier": supplier_info
            }
        finally:
            conn.close()

    def calculate_eoq(
        self,
        product_id: int,
        order_cost: float = 500.0,
        holding_rate: float = 0.20
    ) -> Dict[str, Any]:
        """
        Calculates Economic Order Quantity (EOQ) with supplier MOQ constraint handling (Spec §18).
        Formula:
          EOQ = sqrt( (2 * D * S) / H )
          where D = annual demand, S = order setup cost, H = annual holding cost per unit
        """
        rop_data = self.calculate_rop(product_id)
        d_bar = rop_data["avg_daily_demand"]
        annual_demand = max(10.0, d_bar * 365.0)

        unit_cost = rop_data["supplier"]["unit_cost"]
        moq = rop_data["supplier"]["moq"]

        # Annual holding cost per unit H = unit_cost * holding_rate
        h_unit = max(1.0, unit_cost * holding_rate)

        # Theoretical EOQ
        theoretical_eoq = math.sqrt((2.0 * annual_demand * order_cost) / h_unit)
        rounded_eoq = int(round(theoretical_eoq))

        # Adjusted for MOQ constraint: Q* = max(EOQ, MOQ)
        moq_constrained_qty = max(rounded_eoq, moq)

        # Cost comparisons:
        # Annual Ordering Cost = (D / Q) * S
        # Annual Holding Cost = (Q / 2) * H
        order_cost_annual = (annual_demand / moq_constrained_qty) * order_cost
        holding_cost_annual = (moq_constrained_qty / 2.0) * h_unit
        total_policy_cost = order_cost_annual + holding_cost_annual

        # Generate 5-point cost curve points for frontend visual inspection
        cost_curve = []
        for factor in [0.5, 0.75, 1.0, 1.5, 2.0]:
            q_cand = max(1, int(round(theoretical_eoq * factor)))
            ord_c = (annual_demand / q_cand) * order_cost
            hld_c = (q_cand / 2.0) * h_unit
            cost_curve.append({
                "quantity": q_cand,
                "ordering_cost": round(ord_c, 2),
                "holding_cost": round(hld_c, 2),
                "total_cost": round(ord_c + hld_c, 2)
            })

        return {
            "product_id": product_id,
            "sku": rop_data["sku"],
            "annual_demand": round(annual_demand, 1),
            "order_setup_cost_inr": order_cost,
            "holding_rate_pct": round(holding_rate * 100.0, 1),
            "unit_cost_inr": round(unit_cost, 2),
            "annual_holding_cost_per_unit_inr": round(h_unit, 2),
            "theoretical_eoq": rounded_eoq,
            "moq": moq,
            "optimized_order_quantity": moq_constrained_qty,
            "annual_ordering_cost_inr": round(order_cost_annual, 2),
            "annual_holding_cost_inr": round(holding_cost_annual, 2),
            "total_annual_cost_inr": round(total_policy_cost, 2),
            "cost_curve": cost_curve
        }

    def generate_recommendations(self, service_level: float = 0.95) -> List[Dict[str, Any]]:
        """
        Scans entire active catalogue and generates automated replenishment recommendations (Spec §19).
        Triggers replenishment when Current Inventory Position <= ROP.
        """
        conn = get_db_connection(self.db_path)
        try:
            products = conn.execute("SELECT id, sku, name, quantity, target_stock_level FROM products WHERE status = 'ACTIVE'").fetchall()
        finally:
            conn.close()

        recommendations_list = []

        for p in products:
            p_id = p["id"]
            rop_info = self.calculate_rop(p_id, service_level=service_level)
            eoq_info = self.calculate_eoq(p_id)

            current_stock = p["quantity"]
            rop = rop_info["reorder_point"]
            ss = rop_info["safety_stock"]
            moq = rop_info["supplier"]["moq"]
            opt_qty = eoq_info["optimized_order_quantity"]
            target_stock = p["target_stock_level"] or (rop + opt_qty)

            # Check for stock on pending/approved purchase orders
            on_order = self._get_stock_on_order(p_id)
            inventory_position = current_stock + on_order

            # Replenishment Trigger: Inventory Position <= ROP
            if inventory_position <= rop:
                # Urgency Classification (Spec §19)
                if current_stock <= ss or current_stock == 0:
                    urgency = "CRITICAL"
                    reason_desc = (
                        f"Stockout risk imminent. On-hand ({current_stock}) has breached Safety Stock ({ss}). "
                        f"Projected depletion within lead time ({rop_info['lead_time_days']} days)."
                    )
                elif current_stock <= rop:
                    urgency = "HIGH"
                    reason_desc = (
                        f"Inventory position ({inventory_position}) is below Reorder Point ({rop}). "
                        f"Lead-time demand is {rop_info['lead_time_demand']} units."
                    )
                else:
                    urgency = "PLANNED"
                    reason_desc = f"Inventory position approaching ROP ({rop}). Order to maintain optimal target buffer."

                # Quantity to order: bring position back to Target Stock Level, respecting MOQ and EOQ
                deficit = target_stock - inventory_position
                order_qty = max(opt_qty, moq, deficit)

                unit_cost = rop_info["supplier"]["unit_cost"]
                total_cost = round(order_qty * unit_cost, 2)

                evidence = {
                    "rop": rop,
                    "safety_stock": ss,
                    "lead_time_demand": rop_info["lead_time_demand"],
                    "lead_time_days": rop_info["lead_time_days"],
                    "avg_daily_demand": rop_info["avg_daily_demand"],
                    "current_stock": current_stock,
                    "on_order": on_order,
                    "inventory_position": inventory_position,
                    "eoq": eoq_info["theoretical_eoq"],
                    "moq": moq,
                    "target_stock": target_stock
                }

                rec = {
                    "product_id": p_id,
                    "sku": p["sku"],
                    "name": p["name"],
                    "recommendation_type": "PURCHASE_ORDER",
                    "urgency": urgency,
                    "what": f"Issue Purchase Order for {order_qty} units of '{p['name']}' ({p['sku']})",
                    "why": reason_desc,
                    "recommended_quantity": order_qty,
                    "unit_cost": unit_cost,
                    "total_investment_inr": total_cost,
                    "supplier_id": rop_info["supplier"]["supplier_id"],
                    "supplier_name": rop_info["supplier"]["supplier_name"],
                    "confidence_pct": 95.0,
                    "evidence": evidence
                }

                recommendations_list.append(rec)

                # Persist to recommendations table
                self._persist_recommendation(rec)

        # Sort recommendations by urgency (CRITICAL first, then HIGH, then PLANNED)
        urgency_rank = {"CRITICAL": 0, "HIGH": 1, "PLANNED": 2}
        recommendations_list.sort(key=lambda r: urgency_rank.get(r["urgency"], 3))

        return recommendations_list

    def _get_stock_on_order(self, product_id: int) -> int:
        """Calculates quantity on open purchase orders that are not yet received."""
        conn = get_db_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT SUM(poi.quantity) as on_order
                FROM purchase_order_items poi
                JOIN purchase_orders po ON poi.purchase_order_id = po.id
                WHERE poi.product_id = ? AND po.status IN ('APPROVED', 'SENT', 'PENDING_APPROVAL')
                """,
                (product_id,)
            ).fetchone()
            return int(row["on_order"] or 0) if row else 0
        finally:
            conn.close()

    def _persist_recommendation(self, rec: Dict[str, Any]):
        """Upserts replenishment recommendation into recommendations table."""
        with db_transaction(self.db_path) as conn:
            # Check for existing pending recommendation for this product
            existing = conn.execute(
                "SELECT id FROM recommendations WHERE product_id = ? AND status = 'PENDING'",
                (rec["product_id"],)
            ).fetchone()

            evidence_str = json.dumps(rec["evidence"])
            alt_options = json.dumps([{
                "action": "ORDER_MINIMUM_MOQ",
                "quantity": rec["evidence"]["moq"],
                "rationale": "Conserve working capital if cash is constrained."
            }])

            if existing:
                conn.execute(
                    """
                    UPDATE recommendations
                    SET what = ?, why = ?, evidence_json = ?, confidence_pct = ?, alternative_options_json = ?, created_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (rec["what"], rec["why"], evidence_str, rec["confidence_pct"], alt_options, existing["id"])
                )
                rec["id"] = existing["id"]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO recommendations
                    (product_id, recommendation_type, what, why, evidence_json, confidence_pct, alternative_options_json, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (rec["product_id"], rec["recommendation_type"], rec["what"], rec["why"], evidence_str, rec["confidence_pct"], alt_options)
                )
                rec["id"] = cursor.lastrowid

    def consolidate_purchase_orders(
        self,
        recommendation_ids: List[int],
        notes: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Groups selected replenishment items by supplier to generate consolidated Purchase Orders (Spec §19, §20).
        Reduces logistics freight and order processing overhead.
        """
        if not recommendation_ids:
            raise ValidationError("At least one recommendation ID is required for PO generation.")

        conn = get_db_connection(self.db_path)
        try:
            placeholders = ",".join("?" * len(recommendation_ids))
            rows = conn.execute(
                f"""
                SELECT r.id as rec_id, r.product_id, r.evidence_json, p.sku, p.name as product_name,
                       sp.supplier_id, s.name as supplier_name, sp.unit_cost, sp.moq
                FROM recommendations r
                JOIN products p ON r.product_id = p.id
                LEFT JOIN supplier_products sp ON p.id = sp.product_id AND sp.is_primary = 1
                LEFT JOIN suppliers s ON sp.supplier_id = s.id
                WHERE r.id IN ({placeholders}) AND r.status = 'PENDING'
                """,
                recommendation_ids
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            raise ValidationError("No pending recommendations found for the provided IDs.")

        # Group by supplier
        supplier_groups: Dict[int, List[Dict[str, Any]]] = {}
        for r in rows:
            supp_id = r["supplier_id"] or 1  # Default to fallback supplier if none mapped
            if supp_id not in supplier_groups:
                supplier_groups[supp_id] = []

            ev = json.loads(r["evidence_json"]) if r["evidence_json"] else {}
            # Quantity recommended from evidence
            opt_qty = max(ev.get("eoq", 10), ev.get("moq", 1), ev.get("target_stock", 50) - ev.get("current_stock", 0))

            supplier_groups[supp_id].append({
                "rec_id": r["rec_id"],
                "product_id": r["product_id"],
                "product_name": r["product_name"],
                "sku": r["sku"],
                "quantity": opt_qty,
                "unit_cost": float(r["unit_cost"] or 100.0),
                "subtotal": round(opt_qty * float(r["unit_cost"] or 100.0), 2)
            })

        created_pos = []
        now_date = datetime.now(timezone.utc).strftime("%Y%m%d")

        with db_transaction(self.db_path) as conn:
            for supp_id, items in supplier_groups.items():
                total_amount = sum(item["subtotal"] for item in items)
                # Generate unique PO number
                random_suffix = np.random.randint(1000, 9999)
                po_number = f"PO-{now_date}-{random_suffix}"

                cursor = conn.execute(
                    """
                    INSERT INTO purchase_orders (po_number, supplier_id, status, total_amount, currency, notes)
                    VALUES (?, ?, 'DRAFT', ?, 'INR', ?)
                    """,
                    (po_number, supp_id, total_amount, notes or "Auto-consolidated replenishment PO")
                )
                po_id = cursor.lastrowid

                # Insert PO Items
                for item in items:
                    conn.execute(
                        """
                        INSERT INTO purchase_order_items (purchase_order_id, product_id, quantity, unit_cost, subtotal)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (po_id, item["product_id"], item["quantity"], item["unit_cost"], item["subtotal"])
                    )

                # Mark recommendations as APPROVED
                rec_ids = [item["rec_id"] for item in items]
                rec_ph = ",".join("?" * len(rec_ids))
                conn.execute(
                    f"UPDATE recommendations SET status = 'APPROVED' WHERE id IN ({rec_ph})",
                    rec_ids
                )

                created_pos.append({
                    "id": po_id,
                    "po_number": po_number,
                    "supplier_id": supp_id,
                    "item_count": len(items),
                    "total_amount": total_amount,
                    "status": "DRAFT",
                    "items": items
                })

        return created_pos

    def update_po_status(self, po_id: int, new_status: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Manages Purchase Order approval workflow (Spec §20, §35).
        Transitions: DRAFT -> PENDING_APPROVAL -> APPROVED -> SENT -> RECEIVED / CANCELLED.
        When marked RECEIVED: automatically books inbound inventory movement and updates stock.
        """
        valid_statuses = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "SENT", "RECEIVED", "CANCELLED")
        if new_status not in valid_statuses:
            raise ValidationError(f"Invalid PO status '{new_status}'. Valid values: {valid_statuses}")

        conn = get_db_connection(self.db_path)
        try:
            po = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
            if not po:
                raise NotFoundError(f"Purchase Order ID {po_id} not found.")

            items = conn.execute(
                "SELECT * FROM purchase_order_items WHERE purchase_order_id = ?",
                (po_id,)
            ).fetchall()
        finally:
            conn.close()

        old_status = po["status"]

        with db_transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE purchase_orders 
                SET status = ?, updated_at = CURRENT_TIMESTAMP,
                    approved_at = CASE WHEN ? = 'APPROVED' AND approved_at IS NULL THEN CURRENT_TIMESTAMP ELSE approved_at END
                WHERE id = ?
                """,
                (new_status, new_status, po_id)
            )

        # Trigger Inbound Movement Receipt if transitioning to RECEIVED
        if new_status == "RECEIVED" and old_status != "RECEIVED":
            for item in items:
                self.inventory_service.record_stock_movement(
                    product_id=item["product_id"],
                    movement_type="PURCHASE",
                    quantity=item["quantity"],
                    reason=f"PO Receipt: {po['po_number']}",
                    reference_id=po["po_number"],
                    user_id=user_id
                )
            app_logger.info(f"PO {po['po_number']} marked RECEIVED: Stock movements recorded.")

        return {
            "id": po_id,
            "po_number": po["po_number"],
            "previous_status": old_status,
            "current_status": new_status
        }

    def list_purchase_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves purchase orders with supplier metadata and item tallies."""
        conn = get_db_connection(self.db_path)
        try:
            query = """
                SELECT po.*, s.name as supplier_name, COUNT(poi.id) as item_count
                FROM purchase_orders po
                JOIN suppliers s ON po.supplier_id = s.id
                LEFT JOIN purchase_order_items poi ON po.id = poi.purchase_order_id
            """
            params = []
            if status:
                query += " WHERE po.status = ?"
                params.append(status)
            query += " GROUP BY po.id ORDER BY po.created_at DESC"

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_purchase_order_detail(self, po_id: int) -> Dict[str, Any]:
        """Retrieves full Purchase Order detail including item list and supplier contacts."""
        conn = get_db_connection(self.db_path)
        try:
            po = conn.execute(
                """
                SELECT po.*, s.name as supplier_name, s.email as supplier_email, s.contact_phone as supplier_phone
                FROM purchase_orders po
                JOIN suppliers s ON po.supplier_id = s.id
                WHERE po.id = ?
                """,
                (po_id,)
            ).fetchone()

            if not po:
                raise NotFoundError(f"Purchase Order ID {po_id} not found.")

            items = conn.execute(
                """
                SELECT poi.*, p.sku, p.name as product_name
                FROM purchase_order_items poi
                JOIN products p ON poi.product_id = p.id
                WHERE poi.purchase_order_id = ?
                """,
                (po_id,)
            ).fetchall()

            return {
                **dict(po),
                "items": [dict(i) for i in items]
            }
        finally:
            conn.close()
