from flask import Blueprint, request
from services.inventory_service import InventoryService
from repositories.movement_repository import MovementRepository
from repositories.location_repository import LocationRepository
from repositories.category_repository import CategoryRepository
from utils.errors import format_response, ValidationError

inventory_bp = Blueprint("inventory", __name__)
inventory_service = InventoryService()
movement_repo = MovementRepository()
location_repo = LocationRepository()
category_repo = CategoryRepository()


@inventory_bp.route("/api/movements", methods=["POST"])
def record_movement():
    """
    Records an auditable stock movement (Purchase, Sale, Adjustment, Damage, Return, etc.).
    Enforces non-negative inventory balances and writes to audit logs.
    """
    data = request.get_json() or {}

    product_id = data.get("product_id")
    movement_type = data.get("movement_type")
    quantity = data.get("quantity")
    reason = data.get("reason")
    location_id = data.get("location_id")
    reference_id = data.get("reference_id")

    if not product_id:
        raise ValidationError("product_id is required.")

    if not movement_type:
        raise ValidationError("movement_type is required.")

    if quantity is None or not isinstance(quantity, (int, float)):
        raise ValidationError("A valid non-zero quantity is required.")

    if int(quantity) == 0:
        raise ValidationError("Movement quantity cannot be zero.")

    if not reason or not str(reason).strip():
        raise ValidationError("Reason is required to maintain audit compliance.")

    result = inventory_service.record_stock_movement(
        product_id=int(product_id),
        movement_type=str(movement_type),
        quantity=int(quantity),
        reason=str(reason),
        location_id=int(location_id) if location_id else None,
        reference_id=str(reference_id) if reference_id else None
    )

    return format_response(
        data=result,
        message=f"Stock movement '{movement_type.upper()}' recorded successfully.",
        status_code=201
    )


@inventory_bp.route("/api/movements", methods=["GET"])
def get_movements():
    """Retrieves chronological stock movement audit trail with optional product and type filters."""
    product_id = request.args.get("product_id", type=int)
    movement_type = request.args.get("type")
    limit = request.args.get("limit", default=100, type=int)

    movements = movement_repo.find_all_filtered(
        product_id=product_id,
        movement_type=movement_type,
        limit=limit
    )

    return format_response(
        data={"movements": movements, "count": len(movements)},
        message="Stock movements retrieved successfully.",
        status_code=200
    )


@inventory_bp.route("/api/locations", methods=["GET"])
def get_locations():
    """Retrieves list of active warehouse and distribution locations."""
    # Ensure default warehouse exists
    location_repo.get_or_create_default()
    locations = location_repo.find_all(order_by="code ASC")
    return format_response(
        data={"locations": locations, "count": len(locations)},
        message="Locations retrieved successfully.",
        status_code=200
    )


@inventory_bp.route("/api/locations", methods=["POST"])
def create_location():
    """Registers a new warehouse or storage facility."""
    data = request.get_json() or {}
    code = data.get("code")
    name = data.get("name")
    address = data.get("address")
    loc_type = data.get("location_type", "WAREHOUSE").upper()

    if not code or not str(code).strip():
        raise ValidationError("Location code is required (e.g. WH-NORTH).")

    if not name or not str(name).strip():
        raise ValidationError("Location name is required.")

    if loc_type not in ("WAREHOUSE", "STORE", "IN_TRANSIT"):
        raise ValidationError("Invalid location_type. Must be WAREHOUSE, STORE, or IN_TRANSIT.")

    existing = location_repo.find_by_code(code)
    if existing:
        raise ValidationError(f"Location with code '{code}' already exists.")

    loc_id = location_repo.insert({
        "code": code.strip().upper(),
        "name": name.strip(),
        "address": address.strip() if address else None,
        "location_type": loc_type
    })

    new_loc = location_repo.find_by_id(loc_id)
    return format_response(
        data=new_loc,
        message="Storage location registered successfully.",
        status_code=201
    )


@inventory_bp.route("/api/categories", methods=["GET"])
def get_categories():
    """Retrieves all product categories."""
    categories = category_repo.find_all(order_by="name ASC")
    return format_response(
        data={"categories": categories, "count": len(categories)},
        message="Categories retrieved successfully.",
        status_code=200
    )
