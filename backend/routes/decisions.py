from flask import Blueprint, request
from services.decision_service import DecisionService
from utils.errors import format_response, ValidationError

decisions_bp = Blueprint("decisions", __name__)
decision_service = DecisionService()


@decisions_bp.route("/api/decisions/recommendations", methods=["GET"])
def get_recommendations():
    """
    Retrieves active AI recommendations formatted as structured decision cards (Spec §25).
    Contains WHAT, WHY, EVIDENCE, CONFIDENCE, and ALTERNATIVES.
    """
    status = request.args.get("status", default="PENDING")
    cards = decision_service.get_active_recommendations(status=status)
    return format_response(
        data={"count": len(cards), "recommendations": cards},
        message=f"Retrieved {len(cards)} active recommendation card(s).",
        status_code=200
    )


@decisions_bp.route("/api/decisions/act", methods=["POST"])
def record_decision():
    """
    Records an auditable human operator decision (APPROVED, MODIFIED, REJECTED) (Spec §26).
    Enforces accountability: requiring operational override rationale for modifications and dismissals.
    """
    payload = request.get_json(silent=True) or {}
    recommendation_id = payload.get("recommendation_id")
    decision_type = payload.get("decision_type")
    override_reason = payload.get("override_reason")
    modified_params = payload.get("modified_params")
    user_id = payload.get("user_id", 1)

    if not recommendation_id or not decision_type:
        raise ValidationError("Fields 'recommendation_id' and 'decision_type' are required.")

    result = decision_service.record_decision(
        recommendation_id=int(recommendation_id),
        decision_type=str(decision_type),
        override_reason=override_reason,
        modified_params=modified_params,
        user_id=int(user_id) if user_id else 1
    )

    return format_response(
        data=result,
        message=f"Decision #{result['decision_id']} recorded: {result['decision_type']} with execution status {result['execution_status']}.",
        status_code=201
    )


@decisions_bp.route("/api/decisions/ledger", methods=["GET"])
def get_decision_ledger():
    """
    Retrieves the full immutable chronological Decision Ledger with outcome telemetry (Spec §27).
    """
    limit = request.args.get("limit", default=100, type=int)
    ledger = decision_service.get_decision_ledger(limit=limit)
    return format_response(
        data={"count": len(ledger), "ledger": ledger},
        message=f"Retrieved {len(ledger)} decision ledger record(s).",
        status_code=200
    )


@decisions_bp.route("/api/decisions/governance", methods=["GET"])
def get_governance_metrics():
    """
    Returns governance analytics: approval rates, operator overrides,
    avoided stockouts, and capital preserved (Spec §27, §34).
    """
    metrics = decision_service.get_governance_metrics()
    return format_response(
        data=metrics,
        message="Governance metrics retrieved successfully.",
        status_code=200
    )


@decisions_bp.route("/api/decisions/<int:decision_id>/outcome", methods=["POST"])
def record_outcome(decision_id: int):
    """
    Records closed-loop outcome verification for a historical decision (Spec §27).
    """
    payload = request.get_json(silent=True) or {}
    observed_result = payload.get("observed_result", "Verified operational outcome.")
    stockout_avoided = payload.get("stockout_avoided", True)
    savings_amount = float(payload.get("savings_amount", 0.0))

    result = decision_service.record_outcome_verification(
        decision_id=decision_id,
        observed_result=observed_result,
        stockout_avoided=stockout_avoided,
        savings_amount=savings_amount
    )
    return format_response(
        data=result,
        message=f"Outcome verification recorded for decision #{decision_id}.",
        status_code=200
    )
