from typing import Any, Dict, List, Optional
from repositories.base_repository import BaseRepository
from database import db_transaction


class MovementRepository(BaseRepository):
    """
    Data repository for the immutable stock movement audit ledger.
    Every physical or manual inventory transition is permanently recorded here.
    """

    def __init__(self, db_path: Optional[str] = None):
        super().__init__(table_name="stock_movements", db_path=db_path)

    def find_by_product(self, product_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves chronological movement ledger for a specific product."""
        query = """
            SELECT m.*, p.sku, p.name as product_name, l.name as location_name
            FROM stock_movements m
            JOIN products p ON m.product_id = p.id
            LEFT JOIN locations l ON m.location_id = l.id
            WHERE m.product_id = ?
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT ?
        """
        return self.execute_query(query, (product_id, limit))

    def find_all_filtered(
        self,
        product_id: Optional[int] = None,
        movement_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Filters movements by product, movement type, and limit."""
        sql = """
            SELECT m.*, p.sku, p.name as product_name, l.name as location_name
            FROM stock_movements m
            JOIN products p ON m.product_id = p.id
            LEFT JOIN locations l ON m.location_id = l.id
            WHERE 1=1
        """
        params: List[Any] = []

        if product_id is not None:
            sql += " AND m.product_id = ?"
            params.append(product_id)

        if movement_type:
            sql += " AND m.movement_type = ?"
            params.append(movement_type.strip().upper())

        sql += " ORDER BY m.created_at DESC, m.id DESC LIMIT ?"
        params.append(limit)

        return self.execute_query(sql, tuple(params))
