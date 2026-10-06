from flask import Blueprint, request
from services.simulation_service import SimulationService
from utils.errors import format_response, ValidationError

simulation_bp = Blueprint("simulation", __name__)
simulation_service = SimulationService()


@simulation_bp.route("/api/simulation/presets", methods=["GET"])
def get_canonical_presets():
    """
    Returns the canonical shock presets library for stress testing (Spec §22).
    """
    presets = simulation_service.get_canonical_presets()
    return format_response(
        data={"presets": presets},
        message=f"Retrieved {len(presets)} canonical shock presets.",
        status_code=200
    )


@simulation_bp.route("/api/simulation/run", methods=["POST"])
def run_simulation():
    """
    Executes an in-memory Digital Twin discrete-event stress simulation (Spec §21, §23).
    Compares baseline vs. shocked supply network trajectories and generates mitigation trade-offs.
    """
    payload = request.get_json(silent=True) or {}
    shock_type = payload.get("shock_type")

    valid_shocks = (
        "SUPPLIER_OUTAGE", "DEMAND_SURGE", "LEAD_TIME_INFLATION",
        "CAPITAL_FREEZE", "CORRELATED_FAILURE"
    )
    if shock_type and shock_type.upper() not in valid_shocks:
        raise ValidationError(f"Invalid shock_type '{shock_type}'. Allowed types: {valid_shocks}")

    sim_result = simulation_service.run_stress_test(payload)
    return format_response(
        data=sim_result,
        message=f"Stress test '{sim_result['scenario_name']}' completed successfully.",
        status_code=200
    )


@simulation_bp.route("/api/simulation/scenarios", methods=["GET"])
def list_scenarios():
    """Lists historical simulation stress test runs."""
    scenarios = simulation_service.list_scenarios()
    return format_response(
        data={"count": len(scenarios), "scenarios": scenarios},
        message=f"Retrieved {len(scenarios)} past simulation runs.",
        status_code=200
    )


@simulation_bp.route("/api/simulation/scenarios/<int:scenario_id>", methods=["GET"])
def get_scenario_detail(scenario_id: int):
    """Retrieves full detail and mitigation strategy breakdown for a scenario ID."""
    detail = simulation_service.get_scenario_detail(scenario_id)
    return format_response(
        data=detail,
        message=f"Scenario '{detail['name']}' retrieved successfully.",
        status_code=200
    )
