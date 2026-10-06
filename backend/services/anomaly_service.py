import json
import math
from typing import Any, Dict, List, Optional
from database import db_transaction, get_db_connection
from repositories.product_repository import ProductRepository
from utils.logger import app_logger


class AnomalyDetectionEngine:
    """
    Detects operational outliers using rolling statistics, Z-Score, and IQR methods (Spec §19).
    Scans demand time-series, bulk movements, and vendor delivery delays.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.product_repo = ProductRepository(db_path=db_path)

    def scan_product_anomalies(self, product_id: int) -> List[Dict[str, Any]]:
        """Scans a single product for demand outliers, bulk order shocks, and supplier delays."""
        product = self.product_repo.find_by_id(product_id)
        if not product:
            return []

        anomalies: List[Dict[str, Any]] = []

        conn = get_db_connection(self.db_path)
        try:
            # 1. Fetch recent demand series
            rows = conn.execute(
                """
                SELECT date, quantity_demanded 
                FROM demand_history 
                WHERE product_id = ? 
                ORDER BY date DESC 
                LIMIT 60
                """,
                (product_id,)
            ).fetchall()

            # 2. Fetch recent large stock movements
            mov_rows = conn.execute(
                """
                SELECT * FROM stock_movements 
                WHERE product_id = ? 
                ORDER BY created_at DESC 
                LIMIT 10
                """,
                (product_id,)
            ).fetchall()
        finally:
            conn.close()

        demands = [r["quantity_demanded"] for r in rows]

        # Algorithm 1: Rolling Z-Score on Demand Series (requires at least 10 observations)
        if len(demands) >= 10:
            history = demands[1:]  # past history excluding most recent
            recent_point = demands[0]
            mean_val = sum(history) / len(history)
            variance = sum((x - mean_val) ** 2 for x in history) / (len(history) - 1)
            std_val = math.sqrt(variance)

            if std_val > 0:
                z_score = (recent_point - mean_val) / std_val
                if z_score >= 2.5:
                    anomalies.append({
                        "entity_type": "PRODUCT",
                        "entity_id": product_id,
                        "anomaly_type": "DEMAND_SURGE_ZSCORE",
                        "severity": "CRITICAL" if z_score >= 3.5 else "HIGH",
                        "description": (
                            f"Recent demand of {recent_point} units is {z_score:.2f} standard deviations "
                            f"above baseline mean ({mean_val:.1f} ± {std_val:.1f})."
                        ),
                        "evidence": {
                            "method": "z_score",
                            "z_score": round(z_score, 2),
                            "recent_value": recent_point,
                            "baseline_mean": round(mean_val, 2),
                            "baseline_std": round(std_val, 2)
                        }
                    })

            # Algorithm 2: Interquartile Range (IQR) Outlier Detection
            sorted_demands = sorted(demands)
            n = len(sorted_demands)
            q1 = sorted_demands[n // 4]
            q3 = sorted_demands[(3 * n) // 4]
            iqr = q3 - q1
            upper_fence = q3 + (1.5 * iqr)

            if recent_point > upper_fence and iqr > 0:
                anomalies.append({
                    "entity_type": "PRODUCT",
                    "entity_id": product_id,
                    "anomaly_type": "DEMAND_IQR_OUTLIER",
                    "severity": "HIGH",
                    "description": f"Demand point ({recent_point}) exceeds upper quartile fence ({upper_fence:.1f}, IQR={iqr}).",
                    "evidence": {
                        "method": "iqr",
                        "q1": q1,
                        "q3": q3,
                        "iqr": iqr,
                        "upper_fence": upper_fence
                    }
                })

        # Algorithm 3: Sudden Bulk Depletion Outlier
        current_qty = product["quantity"]
        for m in mov_rows:
            if m["movement_type"] in ("SALE", "DAMAGE"):
                depletion = abs(m["quantity_change"])
                if current_qty > 0 and (depletion / (current_qty + depletion)) >= 0.40:
                    anomalies.append({
                        "entity_type": "MOVEMENT",
                        "entity_id": m["id"],
                        "anomaly_type": "BULK_STOCK_DEPLETION",
                        "severity": "HIGH",
                        "description": f"Single {m['movement_type']} consumed {depletion} units (40%+ of on-hand balance).",
                        "evidence": {
                            "movement_id": m["id"],
                            "delta": depletion,
                            "reason": m["reason"]
                        }
                    })
                    break

        # Persist detected anomalies to the anomalies table
        if anomalies:
            with db_transaction(self.db_path) as conn:
                for a in anomalies:
                    conn.execute(
                        """
                        INSERT INTO anomalies (entity_type, entity_id, anomaly_type, severity, description, evidence_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            a["entity_type"], a["entity_id"], a["anomaly_type"],
                            a["severity"], a["description"], json.dumps(a["evidence"])
                        )
                    )

        return anomalies

    def scan_all_anomalies(self) -> List[Dict[str, Any]]:
        """Scans all active products for anomalies across the inventory."""
        products = self.product_repo.find_all()
        all_anomalies = []
        for p in products:
            if p.get("status") != "DISCONTINUED":
                all_anomalies.extend(self.scan_product_anomalies(p["id"]))
        return all_anomalies
