from flask import Blueprint, request
from repositories.supplier_repository import SupplierRepository
from repositories.product_repository import ProductRepository
from utils.errors import format_response, ValidationError, NotFoundError

suppliers_bp = Blueprint("suppliers", __name__)
supplier_repo = SupplierRepository()
product_repo = ProductRepository()


@suppliers_bp.route("/api/suppliers", methods=["GET"])
def get_suppliers():
    """Lists all active suppliers with reliability metrics and lead times."""
    suppliers = supplier_repo.find_all(order_by="name ASC")
    return format_response(
        data={"suppliers": suppliers, "count": len(suppliers)},
        message="Suppliers retrieved successfully.",
        status_code=200
    )


@suppliers_bp.route("/api/suppliers", methods=["POST"])
def create_supplier():
    """Registers a new supplier profile."""
    data = request.get_json() or {}

    name = data.get("name")
    contact_email = data.get("contact_email")
    phone = data.get("phone")
    lead_time_days = data.get("lead_time_days", 7)
    lead_time_variance = data.get("lead_time_variance", 1.0)
    reliability_score = data.get("reliability_score", 1.0)

    if not name or not str(name).strip():
        raise ValidationError("Supplier name is required.")

    if lead_time_days < 0:
        raise ValidationError("Lead time days cannot be negative.")

    if reliability_score < 0.0 or reliability_score > 1.0:
        raise ValidationError("Reliability score must be between 0.0 and 1.0.")

    existing = supplier_repo.find_by_name(name)
    if existing:
        raise ValidationError(f"Supplier '{name}' already exists.")

    supplier_id = supplier_repo.insert({
        "name": name.strip(),
        "contact_email": contact_email.strip() if contact_email else None,
        "phone": phone.strip() if phone else None,
        "lead_time_days": int(lead_time_days),
        "lead_time_variance": float(lead_time_variance),
        "reliability_score": float(reliability_score),
        "status": "ACTIVE"
    })

    new_supplier = supplier_repo.find_by_id(supplier_id)
    return format_response(
        data=new_supplier,
        message="Supplier registered successfully.",
        status_code=201
    )


@suppliers_bp.route("/api/suppliers/<int:supplier_id>", methods=["GET"])
def get_supplier(supplier_id: int):
    """Retrieves a single supplier by ID."""
    supplier = supplier_repo.find_by_id(supplier_id)
    if not supplier:
        raise NotFoundError(f"Supplier with ID {supplier_id} not found.")

    return format_response(
        data=supplier,
        message="Supplier retrieved successfully.",
        status_code=200
    )


@suppliers_bp.route("/api/suppliers/<int:supplier_id>/products", methods=["POST"])
def link_supplier_product(supplier_id: int):
    """Links a supplier to a product SKU with contract pricing and lead-time terms."""
    supplier = supplier_repo.find_by_id(supplier_id)
    if not supplier:
        raise NotFoundError(f"Supplier with ID {supplier_id} not found.")

    data = request.get_json() or {}
    product_id = data.get("product_id")
    unit_cost = data.get("unit_cost")
    moq = data.get("moq", 1)
    lead_time_days = data.get("supplier_lead_time_days", supplier["lead_time_days"])
    is_primary = data.get("is_primary", False)

    if not product_id:
        raise ValidationError("product_id is required.")

    if unit_cost is None or float(unit_cost) < 0:
        raise ValidationError("Unit cost cannot be negative.")

    if int(moq) < 1:
        raise ValidationError("Minimum Order Quantity (MOQ) must be at least 1.")

    product = product_repo.find_by_id(product_id)
    if not product:
        raise NotFoundError(f"Product with ID {product_id} not found.")

    supplier_repo.link_product(
        supplier_id=supplier_id,
        product_id=product_id,
        unit_cost=float(unit_cost),
        moq=int(moq),
        lead_time_days=int(lead_time_days),
        is_primary=bool(is_primary)
    )

    return format_response(
        data={"supplier_id": supplier_id, "product_id": product_id},
        message=f"Supplier '{supplier['name']}' linked to product '{product['name']}'.",
        status_code=201
    )
