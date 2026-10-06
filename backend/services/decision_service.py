import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from database import get_db_connection, db_transaction
from services.replenishment_service import ReplenishmentService
from utils.errors import ValidationError, NotFoundError
from utils.logger import app_logger


class DecisionService:
    """
    Core Domain Service for Human-in-the-Loop Decision Ledger & Action Studio (Spec §25, §26, §27).
    Enforces governance, operator override accountability, action execution,
    and closed-loop outcome verification.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.replenishment_service = ReplenishmentService(db_path=db_path)

    def get_active_recommendations(self, status: str = "PENDING") -> List[Dict[str, Any]]:
        """
        Retrieves active recommendations formatted as structured decision cards (Spec §25).
        Contains WHAT, WHY, EVIDENCE, CONFIDENCE, and ALTERNATIVES.
        """
        conn = get_db_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT r.*, p.sku, p.name as product_name, p.quantity as current_stock, p.price as unit_price,
                       sp.unit_cost, sp.moq, s.name as supplier_name, s.id as supplier_id
                FROM recommendations r
                JOIN products p ON r.product_id = p.id
                LEFT JOIN supplier_products sp ON p.id = sp.product_id AND sp.is_primary = 1
                LEFT JOIN suppliers s ON sp.supplier_id = s.id
                WHERE r.status = ?
                ORDER BY r.created_at DESC
                """,
                (status,)
            ).fetchall()

            cards = []
            for r in rows:
                ev = json.loads(r["evidence_json"]) if r["evidence_json"] else {}
                alts = json.loads(r["alternative_options_json"]) if r["alternative_options_json"] else []

                cards.append({
                    "id": r["id"],
                    "product_id": r["product_id"],
                    "sku": r["sku"],
                    "product_name": r["product_name"],
                    "current_stock": r["current_stock"],
                    "unit_cost": float(r["unit_cost"] or r["unit_price"] * 0.7),
                    "supplier_id": r["supplier_id"],
                    "supplier_name": r["supplier_name"] or "Vendor",
                    "recommendation_type": r["recommendation_type"],
                    "what": r["what"],
                    "why": r["why"],
                    "confidence_pct": r["confidence_pct"],
                    "status": r["status"],
                    "evidence": ev,
                    "alternative_options": alts,
                    "created_at": r["created_at"]
                })
            return cards
        finally:
            conn.close()

    def record_decision(
        self,
        recommendation_id: int,
        decision_type: str,
        override_reason: Optional[str] = None,
        modified_params: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Processes human operator interaction on an AI recommendation (Spec §26).
        Enforces accountability:
        - APPROVED: Executes the recommendation.
        - MODIFIED: Requires explicit override reason and custom adjustments.
        - REJECTED: Requires explicit dismissal rationale.
        """
        valid_decisions = ("APPROVED", "MODIFIED", "REJECTED")
        d_type = decision_type.strip().upper()
        if d_type not in valid_decisions:
            raise ValidationError(f"Invalid decision_type '{decision_type}'. Allowed: {valid_decisions}")

        # Mandatory override rationale rule (Spec §26)
        if d_type in ("MODIFIED", "REJECTED"):
            if not override_reason or len(override_reason.strip()) < 5:
                raise ValidationError(
                    f"A clear operational reason (min 5 characters) is required when performing {d_type}."
                )

        conn = get_db_connection(self.db_path)
        try:
            rec = conn.execute(
                """
                SELECT r.*, p.sku, p.name as product_name, p.price as unit_price,
                       sp.supplier_id, sp.unit_cost
                FROM recommendations r
                JOIN products p ON r.product_id = p.id
                LEFT JOIN supplier_products sp ON p.id = sp.product_id AND sp.is_primary = 1
                WHERE r.id = ?
                """,
                (recommendation_id,)
            ).fetchone()

            if not rec:
                raise NotFoundError(f"Recommendation ID {recommendation_id} not found.")
            if rec["status"] != "PENDING":
                raise ValidationError(f"Recommendation ID {recommendation_id} has already been {rec['status']}.")
        finally:
            conn.close()

        ev = json.loads(rec["evidence_json"]) if rec["evidence_json"] else {}
        executed_qty = ev.get("eoq", 10)
        if modified_params and "quantity" in modified_params:
            executed_qty = int(modified_params["quantity"])

        with db_transaction(self.db_path) as conn:
            # 1. Update recommendation status
            conn.execute(
                "UPDATE recommendations SET status = ? WHERE id = ?",
                (d_type, recommendation_id)
            )

            # Ensure user_id actually exists in users table to prevent FK violations
            effective_user_id = user_id
            if effective_user_id is not None:
                user_row = conn.execute("SELECT id FROM users WHERE id = ?", (effective_user_id,)).fetchone()
                if not user_row:
                    effective_user_id = None

            # 2. Insert decision audit record
            cursor = conn.execute(
                """
                INSERT INTO decisions (recommendation_id, user_id, decision_type, override_reason, execution_status)
                VALUES (?, ?, ?, ?, 'EXECUTED')
                """,
                (recommendation_id, effective_user_id, d_type, override_reason)
            )
            decision_id = cursor.lastrowid

            # 3. Closed-loop outcome initialization (Spec §27)
            savings_val = 0.0
            stockout_flag = 1
            if d_type in ("APPROVED", "MODIFIED"):
                # Estimate revenue preserved by preventing stockout
                unit_price = float(rec["unit_price"])
                savings_val = round(executed_qty * unit_price, 2)
                observed_msg = f"Order dispatched for {executed_qty} units of SKU {rec['sku']}."

                # Automatically trigger Purchase Order creation if approved/modified
                po_num = f"PO-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{decision_id+1000}"
                supp_id = rec["supplier_id"] or 1
                u_cost = float(rec["unit_cost"] or unit_price * 0.7)
                tot_amount = round(executed_qty * u_cost, 2)

                cursor_po = conn.execute(
                    """
                    INSERT INTO purchase_orders (po_number, supplier_id, status, total_amount, notes)
                    VALUES (?, ?, 'APPROVED', ?, ?)
                    """,
                    (po_num, supp_id, tot_amount, f"Auto-generated from Decision #{decision_id}: {override_reason or 'Approved recommendation'}")
                )
                po_id = cursor_po.lastrowid

                conn.execute(
                    """
                    INSERT INTO purchase_order_items (purchase_order_id, product_id, quantity, unit_cost, subtotal)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (po_id, rec["product_id"], executed_qty, u_cost, tot_amount)
                )

            else:
                # Rejected
                stockout_flag = 0
                savings_val = 0.0
                observed_msg = f"Recommendation dismissed by operator. Reason: {override_reason}"

            # Insert initial outcome log
            conn.execute(
                """
                INSERT INTO decision_outcomes (decision_id, outcome_type, observed_result, stockout_avoided, savings_amount)
                VALUES (?, ?, ?, ?, ?)
                """,
                (decision_id, d_type, observed_msg, stockout_flag, savings_val)
            )

        app_logger.info(
            f"Decision recorded: Recommendation #{recommendation_id} -> {d_type} by user {user_id}."
        )

        return {
            "decision_id": decision_id,
            "recommendation_id": recommendation_id,
            "decision_type": d_type,
            "execution_status": "EXECUTED",
            "override_reason": override_reason,
            "executed_quantity": executed_qty if d_type != "REJECTED" else 0,
            "stockout_avoided": bool(stockout_flag),
            "estimated_savings_inr": savings_val
        }

    def get_decision_ledger(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieves full immutable chronological Decision Ledger with outcome telemetry (Spec §27).
        """
        conn = get_db_connection(self.db_path)
        try:
            rows = conn.execute(
                f"""
                SELECT d.id as decision_id, d.decision_type, d.override_reason, d.execution_status, d.decided_at,
                       r.id as recommendation_id, r.what, r.why, r.confidence_pct,
                       p.sku, p.name as product_name,
                       COALESCE(u.username, 'System Operator') as operator_name,
                       doc.observed_result, doc.stockout_avoided, doc.savings_amount
                FROM decisions d
                JOIN recommendations r ON d.recommendation_id = r.id
                JOIN products p ON r.product_id = p.id
                LEFT JOIN users u ON d.user_id = u.id
                LEFT JOIN decision_outcomes doc ON d.id = doc.decision_id
                ORDER BY d.decided_at DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()

            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_governance_metrics(self) -> Dict[str, Any]:
        """
        Computes governance analytics: approval rates, operator overrides,
        avoided stockouts, and capital preserved (Spec §27, §34).
        """
        conn = get_db_connection(self.db_path)
        try:
            # Decisions counts by type
            counts = conn.execute(
                """
                SELECT decision_type, COUNT(*) as cnt
                FROM decisions
                GROUP BY decision_type
                """
            ).fetchall()

            total_decisions = sum(c["cnt"] for c in counts)
            approved = next((c["cnt"] for c in counts if c["decision_type"] == "APPROVED"), 0)
            modified = next((c["cnt"] for c in counts if c["decision_type"] == "MODIFIED"), 0)
            rejected = next((c["cnt"] for c in counts if c["decision_type"] == "REJECTED"), 0)

            approval_rate = round((approved / total_decisions * 100.0), 1) if total_decisions > 0 else 0.0
            modification_rate = round((modified / total_decisions * 100.0), 1) if total_decisions > 0 else 0.0
            rejection_rate = round((rejected / total_decisions * 100.0), 1) if total_decisions > 0 else 0.0

            # Outcome sums
            outcomes = conn.execute(
                """
                SELECT SUM(stockout_avoided) as total_avoided, SUM(savings_amount) as total_savings
                FROM decision_outcomes
                """
            ).fetchone()

            total_stockouts_avoided = int(outcomes["total_avoided"] or 0) if outcomes else 0
            total_capital_preserved = float(outcomes["total_savings"] or 0.0) if outcomes else 0.0

            pending_count = conn.execute("SELECT COUNT(*) FROM recommendations WHERE status = 'PENDING'").fetchone()[0]

            return {
                "total_decisions": total_decisions,
                "pending_recommendations_count": pending_count,
                "approval_rate_pct": approval_rate,
                "modification_rate_pct": modification_rate,
                "rejection_rate_pct": rejection_rate,
                "stockouts_avoided_count": total_stockouts_avoided,
                "total_capital_preserved_inr": round(total_capital_preserved, 2),
                "breakdown": {
                    "approved": approved,
                    "modified": modified,
                    "rejected": rejected
                }
            }
        finally:
            conn.close()

    def record_outcome_verification(
        self,
        decision_id: int,
        observed_result: str,
        stockout_avoided: bool,
        savings_amount: float
    ) -> Dict[str, Any]:
        """Records manual or automated closed-loop outcome verification (Spec §27)."""
        with db_transaction(self.db_path) as conn:
            existing = conn.execute("SELECT id FROM decision_outcomes WHERE decision_id = ?", (decision_id,)).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE decision_outcomes
                    SET observed_result = ?, stockout_avoided = ?, savings_amount = ?, recorded_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (observed_result, 1 if stockout_avoided else 0, savings_amount, existing["id"])
                )
            else:
                conn.execute(
                    """
                    INSERT INTO decision_outcomes (decision_id, outcome_type, observed_result, stockout_avoided, savings_amount)
                    VALUES (?, 'VERIFICATION', ?, ?, ?)
                    """,
                    (decision_id, observed_result, 1 if stockout_avoided else 0, savings_amount)
                )

        return {
            "decision_id": decision_id,
            "status": "VERIFIED",
            "stockout_avoided": stockout_avoided,
            "savings_amount": savings_amount
        }
