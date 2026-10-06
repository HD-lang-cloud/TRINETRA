import copy
import math
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple

from database import get_db_connection
from services.digital_twin import ShockConfig, DailySimState
from utils.logger import app_logger


class DigitalTwinEngine:
    """
    In-Memory Digital Twin Discrete-Event Supply Network Simulator (Spec §21, §22, §23).
    Decoupled from production database to safely evaluate stress shocks,
    multi-node correlated disruptions, and automated mitigation trade-offs.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def clone_network_state(self) -> Dict[str, Any]:
        """
        Extracts a deep in-memory clone of live products, inventory, suppliers,
        and demand profiles. Never mutates live SQLite state (Spec §21).
        """
        conn = get_db_connection(self.db_path)
        try:
            # 1. Products
            prod_rows = conn.execute(
                """
                SELECT id, sku, name, category, quantity, price, reorder_threshold, target_stock_level
                FROM products WHERE status = 'ACTIVE'
                """
            ).fetchall()

            # 2. Suppliers
            supp_rows = conn.execute("SELECT * FROM suppliers WHERE status != 'SUSPENDED'").fetchall()

            # 3. Supplier Products
            sp_rows = conn.execute("SELECT * FROM supplier_products").fetchall()

            # 4. Recent Demand Stats (mean & std per product)
            dh_rows = conn.execute(
                """
                SELECT product_id, AVG(quantity_demanded) as avg_d, 
                       AVG(quantity_demanded * quantity_demanded) - AVG(quantity_demanded)*AVG(quantity_demanded) as var_d
                FROM demand_history
                GROUP BY product_id
                """
            ).fetchall()

            demand_stats = {}
            for r in dh_rows:
                var = max(0.25, float(r["var_d"] or 1.0))
                demand_stats[r["product_id"]] = {
                    "mean": max(1.0, float(r["avg_d"] or 5.0)),
                    "std": math.sqrt(var)
                }

            products = {}
            for p in prod_rows:
                p_id = p["id"]
                d_stat = demand_stats.get(p_id, {
                    "mean": max(1.0, float(p["reorder_threshold"]) / 7.0),
                    "std": 1.5
                })

                # Find primary supplier
                supp_map = [sp for sp in sp_rows if sp["product_id"] == p_id]
                primary_supp = next((sp for sp in supp_map if sp["is_primary"] == 1), None)
                if not primary_supp and supp_map:
                    primary_supp = supp_map[0]

                products[p["sku"]] = {
                    "id": p_id,
                    "sku": p["sku"],
                    "name": p["name"],
                    "category": p["category"],
                    "quantity": int(p["quantity"]),
                    "price": float(p["price"]),
                    "reorder_threshold": int(p["reorder_threshold"]),
                    "target_stock_level": int(p["target_stock_level"] or 50),
                    "mean_daily_demand": d_stat["mean"],
                    "std_daily_demand": d_stat["std"],
                    "supplier_id": primary_supp["supplier_id"] if primary_supp else 1,
                    "lead_time_days": int(primary_supp["supplier_lead_time_days"]) if primary_supp else 7,
                    "unit_cost": float(primary_supp["unit_cost"]) if primary_supp else float(p["price"]) * 0.7,
                    "moq": int(primary_supp["moq"]) if primary_supp else 10
                }

            suppliers = {s["id"]: dict(s) for s in supp_rows}

            return {
                "products": products,
                "suppliers": suppliers,
                "snapshot_time": datetime.now(timezone.utc).isoformat()
            }
        finally:
            conn.close()

    def simulate_run(
        self,
        network_state: Dict[str, Any],
        shock: Optional[ShockConfig] = None,
        horizon_days: int = 45,
        seed: int = 42
    ) -> List[DailySimState]:
        """
        Executes discrete-event stepping over horizon_days.
        Daily Step Pipeline:
          1. Receive arriving purchase orders -> update on-hand stock
          2. Generate stochastic daily demand (with active shock multipliers)
          3. Fulfill orders -> compute stockouts, unmet units, and revenue lost
          4. Replenish inventory (ROP checks) -> dispatch new purchase orders
          5. Snapshot daily network KPIs
        """
        np.random.seed(seed)
        state_copy = copy.deepcopy(network_state["products"])
        suppliers_copy = copy.deepcopy(network_state["suppliers"])

        # Track inventory levels
        stocks = {sku: p["quantity"] for sku, p in state_copy.items()}
        # In-transit orders: list of dicts {sku, quantity, arrival_day, supplier_id, unit_cost}
        in_transit_pos: List[Dict[str, Any]] = []

        daily_states: List[DailySimState] = []
        base_date = datetime.now(timezone.utc).date()

        for day in range(1, horizon_days + 1):
            curr_date = base_date + timedelta(days=day)
            date_str = curr_date.strftime("%Y-%m-%d")

            # --- 1. Inbound Deliveries Receipt ---
            delivered_today = [po for po in in_transit_pos if po["arrival_day"] <= day]
            in_transit_pos = [po for po in in_transit_pos if po["arrival_day"] > day]

            for po in delivered_today:
                stocks[po["sku"]] += po["quantity"]

            # --- 2. Demand Generation & Fulfillment ---
            total_demanded = 0
            total_fulfilled = 0
            total_lost_units = 0
            daily_revenue_lost = 0.0
            daily_stockouts = 0

            # Check if shock is active today
            is_shock_active = False
            if shock:
                is_shock_active = shock.start_day <= day < (shock.start_day + shock.duration_days)

            sku_snapshots = {}

            for sku, p in state_copy.items():
                mean_d = p["mean_daily_demand"]
                std_d = p["std_daily_demand"]

                # Generate stochastic demand (clipped at 0)
                d_sample = max(0.0, np.random.normal(mean_d, std_d))

                # Apply Demand Shocks
                if is_shock_active and shock:
                    if shock.shock_type in ("DEMAND_SURGE", "CORRELATED_FAILURE"):
                        target_match = False
                        if shock.target_sku and shock.target_sku == sku:
                            target_match = True
                        elif shock.target_category and shock.target_category == p["category"]:
                            target_match = True
                        elif not shock.target_sku and not shock.target_category:
                            target_match = True

                        if target_match:
                            d_sample *= max(1.0, shock.magnitude)

                d_int = int(round(d_sample))
                total_demanded += d_int

                # Fulfillment
                current_on_hand = stocks[sku]
                if current_on_hand >= d_int:
                    stocks[sku] -= d_int
                    total_fulfilled += d_int
                    lost_for_sku = 0
                else:
                    # Stockout occurred!
                    fulfilled = current_on_hand
                    lost_for_sku = d_int - current_on_hand
                    stocks[sku] = 0
                    total_fulfilled += fulfilled
                    total_lost_units += lost_for_sku
                    daily_revenue_lost += lost_for_sku * p["price"]
                    daily_stockouts += 1

                sku_snapshots[sku] = {
                    "on_hand": stocks[sku],
                    "demanded": d_int,
                    "lost": lost_for_sku,
                    "stockout": lost_for_sku > 0
                }

            # --- 3. Replenishment Dispatch (ROP Engine) ---
            for sku, p in state_copy.items():
                on_hand = stocks[sku]
                # Outstanding in-transit for this SKU
                open_qty = sum(po["quantity"] for po in in_transit_pos if po["sku"] == sku)
                effective_position = on_hand + open_qty

                # Trigger replenishment when position <= reorder threshold
                rop = p["reorder_threshold"]
                target_stock = p["target_stock_level"]

                if effective_position <= rop:
                    # Check supplier outage shock
                    supplier_id = p["supplier_id"]
                    is_supplier_blocked = False

                    if is_shock_active and shock:
                        if shock.shock_type in ("SUPPLIER_OUTAGE", "CORRELATED_FAILURE"):
                            if shock.target_supplier_id is None or shock.target_supplier_id == supplier_id:
                                is_supplier_blocked = True

                    if not is_supplier_blocked:
                        order_qty = max(p["moq"], target_stock - effective_position)
                        order_cost = order_qty * p["unit_cost"]

                        # Check capital freeze limit
                        if is_shock_active and shock and shock.shock_type == "CAPITAL_FREEZE":
                            if shock.budget_limit_inr and order_cost > shock.budget_limit_inr:
                                # Constrain order to budget
                                order_qty = max(1, int(shock.budget_limit_inr / p["unit_cost"]))

                        # Calculate lead time
                        lead_time = p["lead_time_days"]
                        if is_shock_active and shock and shock.shock_type == "LEAD_TIME_INFLATION":
                            lead_time += int(shock.magnitude)

                        in_transit_pos.append({
                            "sku": sku,
                            "quantity": order_qty,
                            "arrival_day": day + lead_time,
                            "supplier_id": supplier_id,
                            "unit_cost": p["unit_cost"]
                        })

            # --- 4. Daily Metrics Consolidation ---
            total_on_hand_all = sum(stocks.values())
            total_in_transit_all = sum(po["quantity"] for po in in_transit_pos)
            capital_tied_up = sum(stocks[sku] * state_copy[sku]["price"] for sku in stocks)

            daily_states.append(DailySimState(
                day=day,
                date_str=date_str,
                total_on_hand=total_on_hand_all,
                total_in_transit=total_in_transit_all,
                stockout_count=daily_stockouts,
                units_demanded=total_demanded,
                units_fulfilled=total_fulfilled,
                units_lost=total_lost_units,
                revenue_lost_inr=round(daily_revenue_lost, 2),
                capital_tied_up_inr=round(capital_tied_up, 2),
                sku_states=sku_snapshots
            ))

        return daily_states

    def run_stress_test(
        self,
        shock_config: ShockConfig,
        horizon_days: int = 45,
        seed: int = 42
    ) -> Dict[str, Any]:
        """
        Executes paired simulation:
        1. Baseline Simulation (Normal Operating Conditions)
        2. Shocked Simulation (Under Specified Supply Disruption)
        Calculates delta impact metrics, service level degradation, and automated mitigation advice (Spec §23).
        """
        network_state = self.clone_network_state()

        # Run Baseline (Unshocked)
        baseline_states = self.simulate_run(network_state, shock=None, horizon_days=horizon_days, seed=seed)

        # Run Shocked
        shocked_states = self.simulate_run(network_state, shock=shock_config, horizon_days=horizon_days, seed=seed)

        # Aggregate Comparatives
        base_stockouts = sum(s.stockout_count for s in baseline_states)
        shock_stockouts = sum(s.stockout_count for s in shocked_states)
        delta_stockouts = shock_stockouts - base_stockouts

        base_rev_lost = sum(s.revenue_lost_inr for s in baseline_states)
        shock_rev_lost = sum(s.revenue_lost_inr for s in shocked_states)
        revenue_exposure = max(0.0, shock_rev_lost - base_rev_lost)

        base_demanded = max(1, sum(s.units_demanded for s in baseline_states))
        shock_demanded = max(1, sum(s.units_demanded for s in shocked_states))

        base_fulfilled = sum(s.units_fulfilled for s in baseline_states)
        shock_fulfilled = sum(s.units_fulfilled for s in shocked_states)

        base_fill_rate = round((base_fulfilled / base_demanded) * 100.0, 1)
        shock_fill_rate = round((shock_fulfilled / shock_demanded) * 100.0, 1)

        # Time-to-Recovery (TTR): Day when inventory recovers after shock ends
        shock_end_day = shock_config.start_day + shock_config.duration_days
        time_to_recovery = shock_config.duration_days
        for day_idx in range(min(shock_end_day - 1, len(shocked_states)), len(shocked_states)):
            if shocked_states[day_idx].stockout_count == 0:
                time_to_recovery = day_idx + 1 - shock_config.start_day
                break

        # Resilience Index Impact Delta (Spec §23)
        # Drop proportional to service level drop and stockout volume
        fill_rate_drop = max(0.0, base_fill_rate - shock_fill_rate)
        resilience_score_delta = round(min(50.0, fill_rate_drop * 1.5 + (delta_stockouts * 0.5)), 1)

        # Identify Critical SKUs impacted during shock
        sku_impacts = {}
        for s in shocked_states:
            for sku, snap in s.sku_states.items():
                if snap["stockout"]:
                    sku_impacts[sku] = sku_impacts.get(sku, 0) + 1

        top_critical_skus = sorted(sku_impacts.items(), key=lambda x: x[1], reverse=True)[:5]
        critical_skus_list = [{"sku": k, "stockout_days": v} for k, v in top_critical_skus]

        # Actionable Mitigation Strategies formulation
        mitigations = self._generate_mitigation_strategies(
            shock_config, revenue_exposure, delta_stockouts, critical_skus_list
        )

        # Simplified trajectory for chart rendering
        trajectory = []
        for b, s in zip(baseline_states, shocked_states):
            trajectory.append({
                "day": b.day,
                "date": b.date_str,
                "baseline_stock": b.total_on_hand,
                "shocked_stock": s.total_on_hand,
                "baseline_stockouts": b.stockout_count,
                "shocked_stockouts": s.stockout_count,
                "revenue_lost_inr": s.revenue_lost_inr,
                "is_shock_active": shock_config.start_day <= b.day < shock_end_day
            })

        return {
            "scenario_name": shock_config.name,
            "shock_type": shock_config.shock_type,
            "description": shock_config.description,
            "horizon_days": horizon_days,
            "impact_summary": {
                "projected_stockout_incidents": delta_stockouts,
                "total_shock_stockout_days": shock_stockouts,
                "revenue_exposure_inr": round(revenue_exposure, 2),
                "baseline_service_level_pct": base_fill_rate,
                "shocked_service_level_pct": shock_fill_rate,
                "service_level_drop_pct": round(fill_rate_drop, 1),
                "resilience_score_delta": -resilience_score_delta,
                "time_to_recovery_days": time_to_recovery
            },
            "critical_skus": critical_skus_list,
            "mitigation_options": mitigations,
            "trajectory": trajectory
        }

    @staticmethod
    def _generate_mitigation_strategies(
        shock: ShockConfig,
        revenue_exposure: float,
        stockout_days: int,
        critical_skus: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Calculates trade-offs for actionable response options (Spec §23).
        """
        options = []

        # Strategy 1: Dual Sourcing & Emergency Expediting
        expedite_cost = round(revenue_exposure * 0.18 + 15000, 2)
        options.append({
            "strategy": "EMERGENCY_SECONDARY_SOURCING",
            "title": "Dual-Sourcing Emergency Air-Freight Expedite",
            "action": "Divert 50% purchase orders to qualified secondary suppliers with premium freight.",
            "implementation_cost_inr": expedite_cost,
            "risk_mitigation_pct": 75.0,
            "net_capital_saved_inr": round(max(0.0, revenue_exposure * 0.75 - expedite_cost), 2),
            "recommendation": "HIGHLY RECOMMENDED" if revenue_exposure > expedite_cost else "CONSIDER ALTERNATIVES"
        })

        # Strategy 2: Pre-buffer Safety Stock
        buffer_cost = round(revenue_exposure * 0.12 + 8000, 2)
        options.append({
            "strategy": "SAFETY_STOCK_PRE_BUFFERING",
            "title": "Pre-Shock Dynamic Safety Stock Buffering (+30%)",
            "action": "Elevate Reorder Threshold and target buffer by +30% prior to forecasted disruption.",
            "implementation_cost_inr": buffer_cost,
            "risk_mitigation_pct": 60.0,
            "net_capital_saved_inr": round(max(0.0, revenue_exposure * 0.60 - buffer_cost), 2),
            "recommendation": "FEASIBLE"
        })

        # Strategy 3: Customer Order Rationing
        options.append({
            "strategy": "DEMAND_RATIONING_AND_SHAPING",
            "title": "Tier-1 Customer Order Allocation & Lead-Time Quotas",
            "action": "Cap maximum bulk order per customer to 20 units; protect tier-1 contract SLAs.",
            "implementation_cost_inr": 0.0,
            "risk_mitigation_pct": 40.0,
            "net_capital_saved_inr": round(revenue_exposure * 0.40, 2),
            "recommendation": "ZERO CAPITAL COST"
        })

        return options
