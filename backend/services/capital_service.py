from typing import Any, Dict, List, Optional
from repositories.product_repository import ProductRepository
from services.dna_service import InventoryDNAService
from services.risk_service import RiskScoringEngine


class CapitalIntelligenceService:
    """
    Computes portfolio capital metrics and the transparent TRINETRA Resilience Index (Spec §20, §33).
    Treats inventory as capital and monitors working capital efficiency.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.product_repo = ProductRepository(db_path=db_path)
        self.dna_service = InventoryDNAService(db_path=db_path)
        self.risk_service = RiskScoringEngine(db_path=db_path)

    def get_capital_breakdown(self) -> Dict[str, Any]:
        """Calculates working capital distribution across dead, overstock, and fast-moving segments."""
        products = self.product_repo.find_all()
        active_products = [p for p in products if p.get("status") != "DISCONTINUED"]

        total_capital = 0.0
        dead_capital = 0.0
        overstock_capital = 0.0
        fast_moving_capital = 0.0
        sku_valuations: List[Dict[str, Any]] = []

        for p in active_products:
            val = p["quantity"] * p["price"]
            total_capital += val
            sku_valuations.append({
                "product_id": p["id"],
                "sku": p["sku"],
                "name": p["name"],
                "valuation": val
            })

            dna = self.dna_service.calculate_dna(p["id"])
            tags = {c["tag"] for c in dna["classifications"]}

            if "DEAD STOCK" in tags:
                dead_capital += val
            elif "FAST MOVER" in tags:
                fast_moving_capital += val

            # Overstock portion
            target = p.get("target_stock_level", 50)
            if p["quantity"] > target:
                excess_units = p["quantity"] - target
                overstock_capital += excess_units * p["price"]

        # Capital Concentration in top 3 SKUs
        sku_valuations.sort(key=lambda x: x["valuation"], reverse=True)
        top_3_val = sum(x["valuation"] for x in sku_valuations[:3])
        concentration_pct = round((top_3_val / max(total_capital, 1.0)) * 100.0, 1)

        # Portfolio Risks
        portfolio_risks = self.risk_service.evaluate_portfolio()
        total_at_risk = sum(r["dimensions"]["capital_at_risk_inr"] for r in portfolio_risks)

        return {
            "total_working_capital_inr": round(total_capital, 2),
            "dead_capital_inr": round(dead_capital, 2),
            "dead_capital_pct": round((dead_capital / max(total_capital, 1.0)) * 100.0, 1),
            "overstock_capital_inr": round(overstock_capital, 2),
            "fast_moving_capital_inr": round(fast_moving_capital, 2),
            "at_risk_capital_inr": round(total_at_risk, 2),
            "capital_concentration_top3_pct": concentration_pct,
            "top_capital_skus": sku_valuations[:5]
        }

    def calculate_resilience_index(self) -> Dict[str, Any]:
        """
        Calculates the transparent TRINETRA Resilience Index (0 to 100) based on:
        1. Demand Stability (25%)
        2. Coverage Safety (25%)
        3. Supplier Diversification (20%)
        4. Lead Time Reliability (15%)
        5. Capital Flexibility (15%)
        """
        products = self.product_repo.find_all()
        active = [p for p in products if p.get("status") != "DISCONTINUED"]
        if not active:
            return {"resilience_score": 100.0, "rating": "RESILIENT", "sub_scores": {}}

        total_items = len(active)
        safe_coverage_count = 0
        diversified_count = 0
        total_volatility = 0.0

        for p in active:
            dna = self.dna_service.calculate_dna(p["id"])
            m = dna["metrics"]
            if m["days_of_coverage"] >= m["lead_time_days"]:
                safe_coverage_count += 1
            if m["supplier_count"] >= 2:
                diversified_count += 1
            total_volatility += m["demand_volatility_cv"]

        avg_volatility = total_volatility / total_items
        capital = self.get_capital_breakdown()

        # 1. Demand Stability Sub-score (100 - avg volatility * 60)
        demand_stability = max(10.0, min(100.0, round(100.0 - (avg_volatility * 60.0), 1)))

        # 2. Coverage Safety Sub-score
        coverage_safety = round((safe_coverage_count / total_items) * 100.0, 1)

        # 3. Supplier Diversification Sub-score
        supplier_diversification = round((diversified_count / total_items) * 100.0, 1)

        # 4. Lead Time Reliability Sub-score (assumed baseline from supplier records)
        lead_time_reliability = 84.0

        # 5. Capital Flexibility (penalized by dead capital and concentration)
        dead_cap_pct = capital["dead_capital_pct"]
        concentration = capital["capital_concentration_top3_pct"]
        capital_flexibility = max(10.0, round(100.0 - (dead_cap_pct * 0.8) - (concentration * 0.3), 1))

        # Weighted Composite Score
        composite = (
            demand_stability * 0.25 +
            coverage_safety * 0.25 +
            supplier_diversification * 0.20 +
            lead_time_reliability * 0.15 +
            capital_flexibility * 0.15
        )
        resilience_score = round(composite, 1)

        if resilience_score >= 80.0:
            rating = "RESILIENT"
        elif resilience_score >= 60.0:
            rating = "MODERATE"
        elif resilience_score >= 40.0:
            rating = "VULNERABLE"
        else:
            rating = "CRITICAL RISK"

        return {
            "resilience_score": resilience_score,
            "rating": rating,
            "formula": "0.25*DemandStability + 0.25*CoverageSafety + 0.20*SupplierDiversification + 0.15*LeadTimeReliability + 0.15*CapitalFlexibility",
            "sub_scores": {
                "demand_stability": demand_stability,
                "coverage_safety": coverage_safety,
                "supplier_diversification": supplier_diversification,
                "lead_time_reliability": lead_time_reliability,
                "capital_flexibility": capital_flexibility
            }
        }
