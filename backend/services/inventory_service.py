from typing import Any, Dict, List, Optional
from database import db_transaction, get_db_connection
from repositories.product_repository import ProductRepository
from repositories.movement_repository import MovementRepository
from repositories.location_repository import LocationRepository
from repositories.supplier_repository import SupplierRepository
from utils.errors import ValidationError, NotFoundError
from utils.logger import app_logger


VALID_MOVEMENT_TYPES = {
    "PURCHASE", "SALE", "ADJUSTMENT", "TRANSFER",
    "RETURN", "DAMAGE", "EXPIRY", "EMERGENCY"
}


class InventoryService:
    """
    Core Domain Service managing inventory operations, stock movements,
    and business rule invariants (non-negative stock, atomic audit ledger).
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.product_repo = ProductRepository(db_path=db_path)
        self.movement_repo = MovementRepository(db_path=db_path)
        self.location_repo = LocationRepository(db_path=db_path)
        self.supplier_repo = SupplierRepository(db_path=db_path)

    def record_stock_movement(
        self,
        product_id: int,
        movement_type: str,
        quantity: int,
        reason: str,
        location_id: Optional[int] = None,
        reference_id: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes an immutable, auditable stock movement.
        Enforces:
        1. Valid movement type
        2. Non-negative stock balance invariant (stockout protection)
        3. Atomic update to product, inventory location, movement ledger, and audit log
        """
        m_type = movement_type.strip().upper()
        if m_type not in VALID_MOVEMENT_TYPES:
            raise ValidationError(
                f"Invalid movement type '{movement_type}'. Allowed types: {', '.join(sorted(VALID_MOVEMENT_TYPES))}"
            )

        if not reason or not str(reason).strip():
            raise ValidationError("A clear operational reason is required for every stock movement.")

        product = self.product_repo.find_by_id(product_id)
        if not product:
            raise NotFoundError(f"Product with ID {product_id} not found.")

        current_qty = product["quantity"]

        # Determine net signed quantity change
        if m_type in ("SALE", "DAMAGE", "EXPIRY"):
            qty_change = -abs(int(quantity))
        elif m_type in ("PURCHASE", "RETURN", "EMERGENCY"):
            qty_change = abs(int(quantity))
        elif m_type == "ADJUSTMENT":
            qty_change = int(quantity)
        else:
            qty_change = int(quantity)

        balance_after = current_qty + qty_change

        # Invariant: Inventory cannot become negative through normal operations (Spec §10, §85)
        if balance_after < 0:
            raise ValidationError(
                f"Insufficient stock for '{product['name']}' ({product['sku']}). "
                f"Available on-hand: {current_qty}, requested deduction: {abs(qty_change)}. "
                f"Negative inventory is strictly prohibited."
            )

        # Resolve warehouse location (default to WH-MAIN if omitted)
        if not location_id:
            loc = self.location_repo.get_or_create_default()
            location_id = loc["id"]

        # Atomic transaction execution
        with db_transaction(self.db_path) as conn:
            # 1. Update product catalogue total stock
            conn.execute(
                "UPDATE products SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (balance_after, product_id)
            )

            # 2. Update or insert inventory location balance
            conn.execute(
                """
                INSERT INTO inventory (product_id, location_id, quantity, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(product_id, location_id) DO UPDATE SET
                    quantity = ?,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (product_id, location_id, balance_after, balance_after)
            )

            # 3. Insert immutable stock movement record
            cursor = conn.execute(
                """
                INSERT INTO stock_movements 
                (product_id, location_id, movement_type, quantity_change, balance_after, reference_id, reason, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (product_id, location_id, m_type, qty_change, balance_after, reference_id, reason.strip(), user_id)
            )
            movement_id = cursor.lastrowid

            # 4. Insert audit log record
            conn.execute(
                """
                INSERT INTO audit_logs (user_id, action, entity_type, entity_id, before_state_json, after_state_json, reason)
                VALUES (?, ?, 'PRODUCT', ?, ?, ?, ?)
                """,
                (
                    user_id,
                    f"STOCK_{m_type}",
                    product_id,
                    f'{{"quantity": {current_qty}}}',
                    f'{{"quantity": {balance_after}, "movement_id": {movement_id}}}',
                    reason.strip()
                )
            )

        app_logger.info(
            f"Stock movement recorded: {product['sku']} | Type: {m_type} | Delta: {qty_change} | New Balance: {balance_after}"
        )

        updated_product = self.product_repo.find_by_id(product_id)
        movement = self.movement_repo.find_by_id(movement_id)

        return {
            "movement": movement,
            "product": updated_product
        }

    def get_product_details(self, product_id: int) -> Dict[str, Any]:
        """Gathers complete 360-degree operational profile for a single product."""
        product = self.product_repo.find_by_id(product_id)
        if not product:
            raise NotFoundError(f"Product with ID {product_id} not found.")

        suppliers = self.supplier_repo.get_suppliers_for_product(product_id)
        recent_movements = self.movement_repo.find_by_product(product_id, limit=20)

        # Inventory location breakdown
        conn = get_db_connection(self.db_path)
        try:
            loc_rows = conn.execute(
                """
                SELECT i.*, l.name as location_name, l.code as location_code
                FROM inventory i
                JOIN locations l ON i.location_id = l.id
                WHERE i.product_id = ?
                """,
                (product_id,)
            ).fetchall()
            locations = [dict(r) for r in loc_rows]
        finally:
            conn.close()

        return {
            "product": product,
            "suppliers": suppliers,
            "locations": locations,
            "recent_movements": recent_movements
        }
