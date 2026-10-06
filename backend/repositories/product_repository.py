from typing import Any, Dict, List, Optional
from repositories.base_repository import BaseRepository


class ProductRepository(BaseRepository):
    """
    Data repository for the products catalogue.
    Abstracts all SQL queries and schema details for products.
    """

    def __init__(self, db_path: Optional[str] = None):
        super().__init__(table_name="products", db_path=db_path)

    def find_by_sku(self, sku: str) -> Optional[Dict[str, Any]]:
        """Look up a product by its unique SKU."""
        query = "SELECT * FROM products WHERE sku = ?"
        return self.execute_query_one(query, (sku.strip(),))

    def search_products(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Dynamic search across SKU and name with category and status filters.
        """
        sql = "SELECT * FROM products WHERE 1=1"
        params: List[Any] = []

        if query:
            sql += " AND (name LIKE ? OR sku LIKE ? OR description LIKE ?)"
            wildcard = f"%{query.strip()}%"
            params.extend([wildcard, wildcard, wildcard])

        if category:
            sql += " AND category = ?"
            params.append(category.strip())

        if status:
            sql += " AND status = ?"
            params.append(status.strip())

        sql += " ORDER BY id ASC"
        return self.execute_query(sql, tuple(params))

    def get_low_stock_products(self) -> List[Dict[str, Any]]:
        """Finds all products where quantity is at or below reorder threshold."""
        query = """
            SELECT * FROM products
            WHERE quantity <= reorder_threshold AND status = 'ACTIVE'
            ORDER BY quantity ASC
        """
        return self.execute_query(query)

    def get_inventory_summary(self) -> Dict[str, Any]:
        """Calculates portfolio-level statistics: total items, total units, total capital value."""
        query = """
            SELECT 
                COUNT(*) as total_skus,
                COALESCE(SUM(quantity), 0) as total_units,
                COALESCE(SUM(quantity * price), 0.0) as total_capital_value,
                COALESCE(SUM(CASE WHEN quantity <= reorder_threshold THEN 1 ELSE 0 END), 0) as low_stock_count
            FROM products
            WHERE status != 'DISCONTINUED'
        """
        res = self.execute_query_one(query)
        return res or {
            "total_skus": 0,
            "total_units": 0,
            "total_capital_value": 0.0,
            "low_stock_count": 0
        }

    def update_quantity(self, product_id: int, new_quantity: int) -> bool:
        """Updates product quantity and updated_at timestamp."""
        return self.update(product_id, {"quantity": new_quantity})

    def soft_delete(self, product_id: int) -> bool:
        """Marks product as DISCONTINUED rather than physically dropping records."""
        return self.update(product_id, {"status": "DISCONTINUED"})
