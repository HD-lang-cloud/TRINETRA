from flask import Blueprint, request
from repositories.product_repository import ProductRepository
from repositories.category_repository import CategoryRepository
from services.inventory_service import InventoryService
from utils.errors import format_response, ValidationError, NotFoundError

products_bp = Blueprint("products", __name__)
product_repo = ProductRepository()
category_repo = CategoryRepository()
inventory_service = InventoryService()


@products_bp.route("/api/products", methods=["POST"])
def create_product():
    """
    Creates a new product SKU.
    Enforces validation: non-negative quantity, price, and reorder threshold.
    If initial quantity > 0, automatically creates an opening stock audit movement.
    """
    data = request.get_json() or {}

    name = data.get("name")
    category = data.get("category")
    quantity = data.get("quantity", 0)
    price = data.get("price")
    reorder_threshold = data.get("reorder_threshold", 10)
    target_stock_level = data.get("target_stock_level", 50)
    sku = data.get("sku")
    description = data.get("description", "")

    # Validation Checks (College Requirement Section 3)
    if not name or not str(name).strip():
        raise ValidationError("Product name is required.")

    if not category or not str(category).strip():
        raise ValidationError("Category is required.")

    if quantity is None or not isinstance(quantity, (int, float)) or quantity < 0:
        raise ValidationError("Quantity cannot be negative and must be a valid number.")

    if price is None or not isinstance(price, (int, float)) or price < 0:
        raise ValidationError("Price cannot be negative and must be a valid number.")

    if reorder_threshold is None or not isinstance(reorder_threshold, (int, float)) or reorder_threshold < 0:
        raise ValidationError("Reorder threshold cannot be negative.")

    # Ensure category exists in categories table
    category_id = category_repo.get_or_create(category.strip())

    # Auto-generate clean SKU if omitted
    if not sku:
        existing_count = product_repo.count()
        sku = f"SKU-{existing_count + 1:04d}"
    else:
        existing = product_repo.find_by_sku(sku)
        if existing:
            raise ValidationError(f"Product with SKU '{sku}' already exists.")

    product_data = {
        "sku": sku.strip().upper(),
        "name": name.strip(),
        "category": category.strip(),
        "category_id": category_id,
        "quantity": 0,  # Initially 0; will be incremented via movement ledger if initial qty > 0
        "price": float(price),
        "reorder_threshold": int(reorder_threshold),
        "target_stock_level": int(target_stock_level),
        "description": description.strip() if description else None,
        "status": "ACTIVE"
    }

    product_id = product_repo.insert(product_data)

    # If opening stock > 0, record auditable opening balance movement
    initial_qty = int(quantity)
    if initial_qty > 0:
        inventory_service.record_stock_movement(
            product_id=product_id,
            movement_type="PURCHASE",
            quantity=initial_qty,
            reason="Opening stock initialization on SKU creation."
        )

    created_product = product_repo.find_by_id(product_id)

    return format_response(
        data=created_product,
        message="Product created successfully.",
        status_code=201
    )


@products_bp.route("/api/products", methods=["GET"])
def get_products():
    """
    Lists products with optional search query, category, status, and low_stock filtering.
    """
    query = request.args.get("q")
    category = request.args.get("category")
    status = request.args.get("status")
    low_stock_only = request.args.get("low_stock", "").lower() in ("true", "1")

    if low_stock_only:
        products = product_repo.get_low_stock_products()
    elif query or category or status:
        products = product_repo.search_products(query=query, category=category, status=status)
    else:
        products = product_repo.find_all(order_by="id ASC")

    return format_response(
        data={"products": products, "count": len(products)},
        message="Products retrieved successfully.",
        status_code=200
    )


@products_bp.route("/api/products/<int:product_id>", methods=["GET"])
def get_product(product_id: int):
    """Retrieves 360-degree product details including stock locations, suppliers, and movement history."""
    details = inventory_service.get_product_details(product_id)
    return format_response(
        data=details,
        message="Product details retrieved successfully.",
        status_code=200
    )


@products_bp.route("/api/products/<int:product_id>", methods=["PUT"])
def update_product(product_id: int):
    """
    Updates product catalogue attributes (name, category, price, reorder_threshold, target_stock_level, description).
    Stock quantity cannot be directly changed via PUT; use /api/movements for auditable stock adjustments.
    """
    product = product_repo.find_by_id(product_id)
    if not product:
        raise NotFoundError(f"Product with ID {product_id} not found.")

    data = request.get_json() or {}
    updates = {}

    if "name" in data and str(data["name"]).strip():
        updates["name"] = str(data["name"]).strip()

    if "category" in data and str(data["category"]).strip():
        cat_name = str(data["category"]).strip()
        updates["category"] = cat_name
        updates["category_id"] = category_repo.get_or_create(cat_name)

    if "price" in data:
        price = float(data["price"])
        if price < 0:
            raise ValidationError("Price cannot be negative.")
        updates["price"] = price

    if "reorder_threshold" in data:
        threshold = int(data["reorder_threshold"])
        if threshold < 0:
            raise ValidationError("Reorder threshold cannot be negative.")
        updates["reorder_threshold"] = threshold

    if "target_stock_level" in data:
        target = int(data["target_stock_level"])
        if target < 0:
            raise ValidationError("Target stock level cannot be negative.")
        updates["target_stock_level"] = target

    if "description" in data:
        updates["description"] = str(data["description"]).strip()

    if "status" in data:
        status_val = str(data["status"]).strip().upper()
        if status_val not in ("ACTIVE", "DISCONTINUED", "SEASONAL"):
            raise ValidationError(f"Invalid status '{status_val}'.")
        updates["status"] = status_val

    if "quantity" in data and data["quantity"] != product["quantity"]:
        raise ValidationError(
            "Direct quantity modification is disallowed. Record a stock movement via POST /api/movements to maintain auditability."
        )

    if updates:
        product_repo.update(product_id, updates)

    updated_product = product_repo.find_by_id(product_id)
    return format_response(
        data=updated_product,
        message="Product updated successfully.",
        status_code=200
    )


@products_bp.route("/api/products/<int:product_id>", methods=["DELETE"])
def delete_product(product_id: int):
    """
    Soft-deletes a product by changing status to 'DISCONTINUED'.
    Preserves audit history and prevents dangling references.
    """
    product = product_repo.find_by_id(product_id)
    if not product:
        raise NotFoundError(f"Product with ID {product_id} not found.")

    product_repo.soft_delete(product_id)

    return format_response(
        data={"product_id": product_id, "status": "DISCONTINUED"},
        message=f"Product '{product['name']}' ({product['sku']}) marked as DISCONTINUED.",
        status_code=200
    )