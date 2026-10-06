import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from database import get_db_connection, db_transaction
from services.digital_twin import ShockConfig
from services.digital_twin.simulator import DigitalTwinEngine
from services.digital_twin.scenarios import get_canonical_shock_presets
from utils.errors import ValidationError, NotFoundError
from utils.logger import app_logger


class SimulationService:
    """
    High-level Domain Service coordinating Digital Twin stress simulations,
    scenario persistence, and canonical shock libraries (Spec §21, §22, §23).
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.engine = DigitalTwinEngine(db_path=db_path)

    def get_canonical_presets(self) -> List[Dict[str, Any]]:
        """Returns the library of standard canonical stress shocks (Spec §22)."""
        return get_canonical_shock_presets()

    def run_stress_test(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a stress test simulation and persists the scenario and comparative results.
        """
        shock_type = params.get("shock_type", "SUPPLIER_OUTAGE").upper()
        name = params.get("name") or f"Stress Test: {shock_type}"
        description = params.get("description", "Disruption scenario evaluation")
        start_day = int(params.get("start_day", 5))
        duration_days = int(params.get("duration_days", 30))
        magnitude = float(params.get("magnitude", 1.0))
        target_supplier_id = params.get("target_supplier_id")
        target_sku = params.get("target_sku")
        target_category = params.get("target_category")
        budget_limit = params.get("budget_limit_inr")
        horizon_days = int(params.get("horizon_days", 45))

        shock_config = ShockConfig(
            shock_type=shock_type,
            name=name,
            description=description,
            target_supplier_id=int(target_supplier_id) if target_supplier_id is not None else None,
            target_sku=target_sku,
            target_category=target_category,
            start_day=start_day,
            duration_days=duration_days,
            magnitude=magnitude,
            budget_limit_inr=float(budget_limit) if budget_limit is not None else None
        )

        sim_result = self.engine.run_stress_test(shock_config, horizon_days=horizon_days)

        # Persist to scenarios and scenario_results tables
        summary = sim_result["impact_summary"]
        crit_skus_str = json.dumps(sim_result["critical_skus"])
        mitigations_str = json.dumps(sim_result["mitigation_options"])
        params_str = json.dumps(params)
        snapshot_meta = json.dumps({"horizon_days": horizon_days, "seed": 42})

        with db_transaction(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO scenarios (name, description, baseline_snapshot_json, shock_parameters_json, status)
                VALUES (?, ?, ?, ?, 'COMPLETED')
                """,
                (name, description, snapshot_meta, params_str)
            )
            scenario_id = cursor.lastrowid

            conn.execute(
                """
                INSERT INTO scenario_results 
                (scenario_id, projected_stockouts, revenue_exposure, resilience_score_delta, critical_skus_json, recovery_options_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id,
                    summary["projected_stockout_incidents"],
                    summary["revenue_exposure_inr"],
                    summary["resilience_score_delta"],
                    crit_skus_str,
                    mitigations_str
                )
            )

        sim_result["scenario_id"] = scenario_id
        app_logger.info(f"Digital Twin simulation '{name}' completed successfully (ID: {scenario_id}).")
        return sim_result

    def list_scenarios(self) -> List[Dict[str, Any]]:
        """Retrieves list of past executed simulation runs with impact scores."""
        conn = get_db_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT s.id, s.name, s.description, s.created_at, s.status,
                       sr.projected_stockouts, sr.revenue_exposure, sr.resilience_score_delta
                FROM scenarios s
                LEFT JOIN scenario_results sr ON s.id = sr.scenario_id
                ORDER BY s.created_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_scenario_detail(self, scenario_id: int) -> Dict[str, Any]:
        """Retrieves specific scenario result with parameters and mitigation advice."""
        conn = get_db_connection(self.db_path)
        try:
            scen = conn.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
            if not scen:
                raise NotFoundError(f"Scenario with ID {scenario_id} not found.")

            res = conn.execute("SELECT * FROM scenario_results WHERE scenario_id = ?", (scenario_id,)).fetchone()

            crit_skus = json.loads(res["critical_skus_json"]) if res and res["critical_skus_json"] else []
            mitigations = json.loads(res["recovery_options_json"]) if res and res["recovery_options_json"] else []
            params = json.loads(scen["shock_parameters_json"]) if scen["shock_parameters_json"] else {}

            return {
                "id": scen["id"],
                "name": scen["name"],
                "description": scen["description"],
                "status": scen["status"],
                "created_at": scen["created_at"],
                "parameters": params,
                "results": {
                    "projected_stockouts": res["projected_stockouts"] if res else 0,
                    "revenue_exposure": res["revenue_exposure"] if res else 0.0,
                    "resilience_score_delta": res["resilience_score_delta"] if res else 0.0,
                    "critical_skus": crit_skus,
                    "mitigation_options": mitigations
                }
            }
        finally:
            conn.close()
