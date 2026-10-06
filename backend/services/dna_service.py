import math
from typing import Any, Dict, List, Optional
from database import get_db_connection
from repositories.product_repository import ProductRepository
from repositories.supplier_repository import SupplierRepository
from utils.errors import NotFoundError


class InventoryDNAService:
    """
    Computes behavioral profiles and behavioral classifications for inventory SKUs:
    - Demand velocity and volatility
    - Turnover ratio and days of coverage
    - Lead-time sensitivity and supplier concentration
    - Data confidence score
    - Behavioral tags with explainable evidence
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.product_repo = ProductRepository(db_path=db_path)
        self.supplier_repo = SupplierRepository(db_path=db_path)

    def calculate_dna(self, product_id: int) -> Dict[str, Any]:
        """Calculates comprehensive operational DNA for a given SKU."""
        product = self.product_repo.find_by_id(product_id)
        if not product:
            raise NotFoundError(f"Product with ID {product_id} not found.")

        conn = get_db_connection(self.db_path)
        try:
            # 1. Fetch historical demand series
            rows = conn.execute(
                """
                SELECT date, quantity_demanded 
                FROM demand_history 
                WHERE product_id = ? 
                ORDER BY date DESC
                """,
                (product_id,)
            ).fetchall()
        finally:
            conn.close()

        demands = [r["quantity_demanded"] for r in rows]
        n_obs = len(demands)

        # Data Confidence (Spec §9, §15)
        # Minimum reliable window is 60 observations; <14 observations is sparse
        data_confidence = min(100.0, round((n_obs / 60.0) * 100.0, 1))

        # Recent windows: 30-day and 14-day
        demands_30 = demands[:30] if demands else [0]
        demands_14 = demands[:14] if demands else [0]

        mean_demand_30 = sum(demands_30) / len(demands_30) if demands_30 else 0.0
        mean_demand_14 = sum(demands_14) / len(demands_14) if demands_14 else 0.0

        # Variance & Volatility (Coefficient of Variation)
        if len(demands_30) > 1 and mean_demand_30 > 0:
            variance = sum((x - mean_demand_30) ** 2 for x in demands_30) / (len(demands_30) - 1)
            std_dev = math.sqrt(variance)
            volatility_cv = round(std_dev / mean_demand_30, 2)
        else:
            std_dev = 0.0
            volatility_cv = 0.0

        current_qty = product["quantity"]
        unit_price = product["price"]
        capital_exposure = round(current_qty * unit_price, 2)

        # Days of Inventory Coverage (DOI)
        daily_rate = max(mean_demand_30, 0.05)
        days_of_coverage = round(current_qty / daily_rate, 1)

        # Annualized Turnover Ratio: (Annual Demand * Price) / (Inventory Value)
        annual_units_sold = mean_demand_30 * 365.0
        turnover_ratio = round(annual_units_sold / max(current_qty, 1), 2)

        # Supplier dependency metrics
        suppliers = self.supplier_repo.get_suppliers_for_product(product_id)
        supplier_count = len(suppliers)
        primary_supplier = next((s for s in suppliers if s["is_primary"]), suppliers[0] if suppliers else None)

        lead_time_days = primary_supplier["supplier_lead_time_days"] if primary_supplier else 7
        lead_time_variance = primary_supplier.get("lead_time_variance", 1.0) if primary_supplier else 1.0
        lead_time_sensitivity = round(lead_time_days / max(days_of_coverage, 0.5), 2)

        # Recent 45-day activity for dead stock detection
        demands_45 = demands[:45] if demands else [0]
        sum_45 = sum(demands_45)

        # 2. Derive Classifications with Evidence (Spec §9)
        classifications: List[Dict[str, str]] = []

        if sum_45 == 0 and current_qty > 0 and n_obs >= 45:
            classifications.append({
                "tag": "DEAD STOCK",
                "severity": "CRITICAL",
                "evidence": f"Zero units consumed in the last 45+ days with {current_qty} units on hand (₹{capital_exposure:,.2f} tied capital)."
            })
        elif mean_demand_30 >= 8.0 or turnover_ratio >= 8.0:
            classifications.append({
                "tag": "FAST MOVER",
                "severity": "NORMAL",
                "evidence": f"High velocity of {mean_demand_30:.1f} units/day with turnover ratio {turnover_ratio}x."
            })
        elif mean_demand_30 < 1.0 and sum_45 > 0:
            classifications.append({
                "tag": "SLOW MOVER",
                "severity": "WARNING",
                "evidence": f"Low velocity of {mean_demand_30:.2f} units/day. Capital turnover is slow."
            })

        if volatility_cv >= 0.45:
            classifications.append({
                "tag": "VOLATILE",
                "severity": "WARNING",
                "evidence": f"High demand variability (Coefficient of Variation = {volatility_cv}, σ={std_dev:.1f})."
            })

        if mean_demand_14 > (mean_demand_30 * 1.8) and mean_demand_14 >= 5:
            classifications.append({
                "tag": "DEMAND SPIKE",
                "severity": "CRITICAL",
                "evidence": f"14-day velocity ({mean_demand_14:.1f}/day) is 180%+ of 30-day baseline ({mean_demand_30:.1f}/day)."
            })

        if supplier_count == 1:
            classifications.append({
                "tag": "SUPPLIER DEPENDENT",
                "severity": "WARNING",
                "evidence": f"Single point of failure: 100% reliant on vendor '{primary_supplier['supplier_name']}'."
            })

        if capital_exposure >= 100000.0:
            classifications.append({
                "tag": "CAPITAL HEAVY",
                "severity": "WARNING",
                "evidence": f"High capital commitment of ₹{capital_exposure:,.2f} ({current_qty} units @ ₹{unit_price:,.2f}/unit)."
            })

        if days_of_coverage < lead_time_days:
            classifications.append({
                "tag": "CRITICAL EXPOSURE",
                "severity": "CRITICAL",
                "evidence": f"Stock coverage ({days_of_coverage} days) is less than supplier replenishment lead time ({lead_time_days} days). Stockout imminent."
            })

        if n_obs < 14:
            classifications.append({
                "tag": "SPARSE DATA",
                "severity": "INFO",
                "evidence": f"Only {n_obs} historical observations available (minimum 60 required for deep sequence modeling)."
            })

        return {
            "product_id": product_id,
            "sku": product["sku"],
            "name": product["name"],
            "metrics": {
                "observations_count": n_obs,
                "data_confidence_pct": data_confidence,
                "demand_velocity_daily": round(mean_demand_30, 2),
                "demand_volatility_cv": volatility_cv,
                "demand_std_dev": round(std_dev, 2),
                "days_of_coverage": days_of_coverage,
                "turnover_ratio": turnover_ratio,
                "capital_exposure": capital_exposure,
                "lead_time_days": lead_time_days,
                "lead_time_sensitivity": lead_time_sensitivity,
                "supplier_count": supplier_count
            },
            "classifications": classifications
        }
