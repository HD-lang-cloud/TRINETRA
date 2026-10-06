import json
from typing import Any, Dict, List, Optional
from database import db_transaction, get_db_connection
from services.dna_service import InventoryDNAService
from repositories.product_repository import ProductRepository
from utils.errors import NotFoundError


class RiskScoringEngine:
    """
    Transparent 8-dimensional operational risk evaluation engine.
    Calculates deterministic risk scores with explicit evidence attribution (Spec §17, §18).
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.dna_service = InventoryDNAService(db_path=db_path)
        self.product_repo = ProductRepository(db_path=db_path)

    def evaluate_product_risk(self, product_id: int) -> Dict[str, Any]:
        """Calculates 8 risk dimensions and updates the risk_scores table."""
        dna = self.dna_service.calculate_dna(product_id)
        metrics = dna["metrics"]
        product = self.product_repo.find_by_id(product_id)
        if not product:
            raise NotFoundError(f"Product with ID {product_id} not found.")

        current_qty = product["quantity"]
        target_stock = product["target_stock_level"]
        unit_price = product["price"]
        daily_velocity = metrics["demand_velocity_daily"]
        days_of_coverage = metrics["days_of_coverage"]
        lead_time = metrics["lead_time_days"]
        supplier_count = metrics["supplier_count"]
        volatility_cv = metrics["demand_volatility_cv"]

        # 1. Stockout Risk (%)
        if current_qty == 0:
            stockout_risk = 100.0
            stockout_reason = "Product is currently completely stocked out (0 units on hand)."
        elif days_of_coverage < lead_time:
            ratio = days_of_coverage / max(lead_time, 1)
            stockout_risk = min(98.0, round(100.0 - (ratio * 40.0), 1))
            stockout_reason = (
                f"Coverage ({days_of_coverage} days) is less than lead time ({lead_time} days). "
                f"Stockout projected in approximately {int(days_of_coverage)} days before new orders can arrive."
            )
        elif days_of_coverage < (lead_time * 1.5):
            stockout_risk = round(45.0 + (1.5 - (days_of_coverage / lead_time)) * 40.0, 1)
            stockout_reason = f"Thin safety buffer: coverage ({days_of_coverage} days) is close to reorder lead time ({lead_time} days)."
        else:
            stockout_risk = max(2.0, round(20.0 - (days_of_coverage / lead_time) * 3.0, 1))
            stockout_reason = f"Adequate stock buffer: {days_of_coverage} days of coverage vs {lead_time} days lead time."

        # 2. Overstock Risk (%)
        if target_stock > 0 and current_qty > (target_stock * 2.0):
            overstock_risk = min(95.0, round(50.0 + ((current_qty - (target_stock * 2.0)) / target_stock) * 30.0, 1))
            overstock_reason = f"On-hand inventory ({current_qty} units) is more than double the target level ({target_stock} units)."
        elif days_of_coverage > 90.0:
            overstock_risk = min(85.0, round(40.0 + (days_of_coverage - 90.0) * 0.5, 1))
            overstock_reason = f"Extreme inventory duration: current stock covers {days_of_coverage} days of consumption."
        else:
            overstock_risk = 5.0
            overstock_reason = "Inventory levels remain within balanced operational boundaries."

        # 3. Dead Stock Risk (%)
        is_dead = any(c["tag"] == "DEAD STOCK" for c in dna["classifications"])
        if is_dead:
            dead_stock_risk = 95.0
            dead_stock_reason = "Zero demand recorded in over 45 days. High capital stagnation."
        elif daily_velocity < 0.2 and current_qty > 0:
            dead_stock_risk = 60.0
            dead_stock_reason = "Extremely low velocity with stagnant turnover."
        else:
            dead_stock_risk = 2.0
            dead_stock_reason = "Normal active inventory movement."

        # 4. Supplier Risk (%)
        supplier_risk = 10.0
        supplier_reasons = []
        if supplier_count == 1:
            supplier_risk += 40.0
            supplier_reasons.append("Single-point-of-failure (100% vendor concentration)")
        elif supplier_count == 0:
            supplier_risk += 80.0
            supplier_reasons.append("No active suppliers linked")

        if lead_time > 14:
            supplier_risk += 20.0
            supplier_reasons.append(f"Extended procurement lead time ({lead_time} days)")

        supplier_risk = min(98.0, supplier_risk)
        supplier_reason = "; ".join(supplier_reasons) if supplier_reasons else "Diversified reliable vendor base."

        # 5. Demand Spike Risk (%)
        if volatility_cv > 0.5:
            spike_risk = min(90.0, round(volatility_cv * 100.0, 1))
            spike_reason = f"Erratic demand pattern (CV = {volatility_cv}). Susceptible to unexpected buffer depletion."
        else:
            spike_risk = 12.0
            spike_reason = "Stable, predictable consumption pattern."

        # 6. Demand Collapse Risk (%)
        if daily_velocity > 0 and days_of_coverage > 60:
            collapse_risk = 40.0
            collapse_reason = "Elevated inventory holding if market demand softens."
        else:
            collapse_risk = 8.0
            collapse_reason = "Low collapse vulnerability."

        # 7. Lead-Time Risk (%)
        lead_time_risk = min(90.0, round((lead_time / 21.0) * 60.0, 1))
        lead_time_reason = f"Procurement cycle of {lead_time} days requires advance order placement."

        # 8. Capital at Risk (₹)
        projected_shortfall_units = max(0, int((lead_time * daily_velocity) - current_qty))
        lost_sales_val = projected_shortfall_units * unit_price
        dead_capital_val = (current_qty * unit_price) if is_dead else 0.0
        capital_at_risk = round(lost_sales_val + dead_capital_val, 2)

        # Composite Rating
        composite_score = (
            stockout_risk * 0.35 +
            supplier_risk * 0.25 +
            dead_stock_risk * 0.15 +
            overstock_risk * 0.15 +
            spike_risk * 0.10
        )

        if composite_score >= 70.0 or stockout_risk >= 80.0 or dead_stock_risk >= 90.0:
            rating = "CRITICAL"
        elif composite_score >= 50.0:
            rating = "HIGH"
        elif composite_score >= 30.0:
            rating = "MEDIUM"
        else:
            rating = "LOW"

        evidence_payload = {
            "stockout": {"score": stockout_risk, "reason": stockout_reason},
            "overstock": {"score": overstock_risk, "reason": overstock_reason},
            "dead_stock": {"score": dead_stock_risk, "reason": dead_stock_reason},
            "supplier": {"score": supplier_risk, "reason": supplier_reason},
            "demand_spike": {"score": spike_risk, "reason": spike_reason},
            "demand_collapse": {"score": collapse_risk, "reason": collapse_reason},
            "lead_time": {"score": lead_time_risk, "reason": lead_time_reason},
            "capital_at_risk_inr": capital_at_risk,
            "composite_score": round(composite_score, 1)
        }

        # Store to database
        with db_transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO risk_scores 
                (product_id, stockout_risk_pct, overstock_risk_pct, supplier_risk_pct, capital_at_risk, composite_rating, evidence_json, calculated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    product_id, stockout_risk, overstock_risk, supplier_risk,
                    capital_at_risk, rating, json.dumps(evidence_payload)
                )
            )

        return {
            "product_id": product_id,
            "sku": product["sku"],
            "name": product["name"],
            "composite_rating": rating,
            "composite_score": round(composite_score, 1),
            "dimensions": {
                "stockout_risk_pct": stockout_risk,
                "overstock_risk_pct": overstock_risk,
                "dead_stock_risk_pct": dead_stock_risk,
                "supplier_risk_pct": supplier_risk,
                "demand_spike_risk_pct": spike_risk,
                "demand_collapse_risk_pct": collapse_risk,
                "lead_time_risk_pct": lead_time_risk,
                "capital_at_risk_inr": capital_at_risk
            },
            "evidence": evidence_payload,
            "dna_classifications": dna["classifications"]
        }

    def evaluate_portfolio(self) -> List[Dict[str, Any]]:
        """Evaluates all active products and returns prioritized risk queue."""
        products = self.product_repo.find_all()
        results = [self.evaluate_product_risk(p["id"]) for p in products if p.get("status") != "DISCONTINUED"]
        # Sort by critical severity first, then by capital at risk descending
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        results.sort(key=lambda r: (severity_order.get(r["composite_rating"], 99), -r["dimensions"]["capital_at_risk_inr"]))
        return results
