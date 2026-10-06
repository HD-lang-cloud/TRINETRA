from flask import Blueprint, request
from services.replenishment_service import ReplenishmentService
from utils.errors import format_response, ValidationError

replenishment_bp = Blueprint("replenishment", __name__)
replenishment_service = ReplenishmentService()


@replenishment_bp.route("/api/replenishment/rop/<int:product_id>", methods=["GET"])
def get_product_rop(product_id: int):
    """
    Calculates dynamic Reorder Point (ROP) and Safety Stock (SS) integrating
    demand volatility and supplier lead-time variance (Spec §17).
    """
    service_level = request.args.get("service_level", default=0.95, type=float)
    data = replenishment_service.calculate_rop(product_id, service_level=service_level)
    return format_response(
        data=data,
        message=f"ROP calculated for SKU '{data['sku']}' at {int(service_level*100)}% cycle-service level.",
        status_code=200
    )


@replenishment_bp.route("/api/replenishment/eoq/<int:product_id>", methods=["GET"])
def get_product_eoq(product_id: int):
    """
    Calculates Economic Order Quantity (EOQ) with MOQ constraints and cost curve (Spec §18).
    """
    order_cost = request.args.get("order_cost", default=500.0, type=float)
    holding_rate = request.args.get("holding_rate", default=0.20, type=float)

    data = replenishment_service.calculate_eoq(product_id, order_cost=order_cost, holding_rate=holding_rate)
    return format_response(
        data=data,
        message=f"EOQ calculated for SKU '{data['sku']}': {data['optimized_order_quantity']} units (MOQ={data['moq']}).",
        status_code=200
    )


@replenishment_bp.route("/api/replenishment/recommendations", methods=["GET"])
def get_recommendations():
    """
    Scans entire catalogue and returns prioritized replenishment recommendations (Spec §19).
    """
    service_level = request.args.get("service_level", default=0.95, type=float)
    recommendations = replenishment_service.generate_recommendations(service_level=service_level)
    return format_response(
        data={
            "count": len(recommendations),
            "recommendations": recommendations
        },
        message=f"Generated {len(recommendations)} replenishment recommendations.",
        status_code=200
    )


@replenishment_bp.route("/api/replenishment/purchase-orders/consolidate", methods=["POST"])
def consolidate_purchase_orders():
    """
    Groups selected replenishment recommendations by supplier into consolidated Purchase Orders (Spec §19, §20).
    """
    payload = request.get_json(silent=True) or {}
    recommendation_ids = payload.get("recommendation_ids", [])
    notes = payload.get("notes")

    if not recommendation_ids or not isinstance(recommendation_ids, list):
        raise ValidationError("Field 'recommendation_ids' must be a non-empty list of IDs.")

    created_pos = replenishment_service.consolidate_purchase_orders(recommendation_ids, notes=notes)
    return format_response(
        data={
            "created_purchase_orders_count": len(created_pos),
            "purchase_orders": created_pos
        },
        message=f"Consolidated into {len(created_pos)} supplier purchase order(s).",
        status_code=201
    )


@replenishment_bp.route("/api/replenishment/purchase-orders", methods=["GET"])
def list_purchase_orders():
    """Lists purchase orders with supplier and status filters (Spec §20)."""
    status = request.args.get("status")
    pos = replenishment_service.list_purchase_orders(status=status)
    return format_response(
        data={"count": len(pos), "purchase_orders": pos},
        message=f"Retrieved {len(pos)} purchase order(s).",
        status_code=200
    )


@replenishment_bp.route("/api/replenishment/purchase-orders/<int:po_id>", methods=["GET"])
def get_purchase_order(po_id: int):
    """Retrieves full Purchase Order detail including item list and costs."""
    po_detail = replenishment_service.get_purchase_order_detail(po_id)
    return format_response(
        data=po_detail,
        message=f"Purchase order '{po_detail['po_number']}' retrieved.",
        status_code=200
    )


@replenishment_bp.route("/api/replenishment/purchase-orders/<int:po_id>/status", methods=["PATCH"])
def update_po_status(po_id: int):
    """
    Updates Purchase Order lifecycle status (DRAFT -> PENDING_APPROVAL -> APPROVED -> SENT -> RECEIVED).
    When marked RECEIVED: automatically books inbound inventory movement.
    """
    payload = request.get_json(silent=True) or {}
    new_status = payload.get("status", "").upper()
    user_id = payload.get("user_id")

    if not new_status:
        raise ValidationError("Field 'status' is required.")

    result = replenishment_service.update_po_status(po_id, new_status, user_id=user_id)
    return format_response(
        data=result,
        message=f"Purchase order status updated from {result['previous_status']} to {result['current_status']}.",
        status_code=200
    )
