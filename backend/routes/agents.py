"""
TRINETRA — Governed Autonomous Agent Operations Routes
Exposes endpoints for running governed autonomous agents (Autopilot, Shock Mitigator),
inspecting tool invocation traces, and auditing pre-execution policy guardrail evaluations.
"""

from flask import Blueprint, jsonify, request
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = BASE_DIR / "backend"
for p in [str(BASE_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from services.agent_governance_service import AgentGovernanceService
from utils.logger import app_logger

agents_bp = Blueprint("agents", __name__, url_prefix="/api/agents")
agent_service = AgentGovernanceService()


@agents_bp.route("/autopilot/run", methods=["POST"])
def run_autopilot_agent():
    """
    Executes the Replenishment Autopilot Agent.
    Request body: { "service_level": 0.95, "max_budget_inr": 250000.0, "require_human_gate": true }
    """
    payload = request.get_json(silent=True) or {}
    service_level = float(payload.get("service_level", 0.95))
    max_budget = float(payload.get("max_budget_inr", 250000.0))
    human_gate = bool(payload.get("require_human_gate", True))

    try:
        result = agent_service.run_replenishment_autopilot(
            service_level=service_level,
            max_budget_inr=max_budget,
            require_human_gate=human_gate
        )
        return jsonify({
            "status": "success",
            "message": f"Agent {result['agent_name']} executed successfully. Governance: {result['governance_mode']}",
            "data": result
        }), 200
    except Exception as e:
        app_logger.error(f"Autopilot agent execution failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@agents_bp.route("/shock-mitigation/run", methods=["POST"])
def run_shock_mitigation_agent():
    """
    Executes the Shock Mitigation Agent for a supplier experiencing lead-time inflation.
    Request body: { "supplier_id": 1, "lead_time_inflation_days": 14 }
    """
    payload = request.get_json(silent=True) or {}
    supplier_id = int(payload.get("supplier_id", 1))
    inflation_days = int(payload.get("lead_time_inflation_days", 14))

    try:
        result = agent_service.run_shock_mitigation_agent(
            supplier_id=supplier_id,
            lead_time_inflation_days=inflation_days
        )
        return jsonify({
            "status": "success",
            "message": f"Agent {result['agent_name']} completed shock mitigation plan.",
            "data": result
        }), 200
    except Exception as e:
        app_logger.error(f"Shock mitigation agent failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@agents_bp.route("/runs", methods=["GET"])
def list_agent_runs():
    """Lists recent agent runs and high-level guardrail verdicts."""
    limit = int(request.args.get("limit", 50))
    try:
        runs = agent_service.list_agent_runs(limit=limit)
        return jsonify({
            "status": "success",
            "data": {"runs": runs, "count": len(runs)}
        }), 200
    except Exception as e:
        app_logger.error(f"Failed to list agent runs: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@agents_bp.route("/runs/<run_id>", methods=["GET"])
def get_agent_run_detail(run_id: str):
    """Retrieves full tool execution traces, policy evaluations, and proposed actions for a run."""
    try:
        detail = agent_service.get_agent_run(run_id)
        if not detail:
            return jsonify({"status": "error", "message": f"Run ID '{run_id}' not found."}), 404
        return jsonify({
            "status": "success",
            "data": detail
        }), 200
    except Exception as e:
        app_logger.error(f"Failed to fetch agent run detail: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
