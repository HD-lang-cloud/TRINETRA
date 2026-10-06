from typing import Any, Dict, List, Optional
from repositories.base_repository import BaseRepository
from database import db_transaction


class SupplierRepository(BaseRepository):
    """Data repository for suppliers and product-supplier vendor mappings."""

    def __init__(self, db_path: Optional[str] = None):
        super().__init__(table_name="suppliers", db_path=db_path)

    def find_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Finds supplier record by business name."""
        return self.execute_query_one("SELECT * FROM suppliers WHERE name = ?", (name.strip(),))

    def get_suppliers_for_product(self, product_id: int) -> List[Dict[str, Any]]:
        """
        Retrieves all suppliers providing a given product SKU,
        including negotiated unit cost, MOQ, lead time, and primary status.
        """
        query = """
            SELECT 
                s.id as supplier_id,
                s.name as supplier_name,
                s.contact_email,
                s.reliability_score,
                s.status as supplier_status,
                sp.id as mapping_id,
                sp.unit_cost,
                sp.moq,
                sp.supplier_lead_time_days,
                sp.is_primary
            FROM suppliers s
            JOIN supplier_products sp ON s.id = sp.supplier_id
            WHERE sp.product_id = ?
            ORDER BY sp.is_primary DESC, s.reliability_score DESC
        """
        return self.execute_query(query, (product_id,))

    def link_product(
        self,
        supplier_id: int,
        product_id: int,
        unit_cost: float,
        moq: int = 1,
        lead_time_days: int = 7,
        is_primary: bool = False
    ) -> int:
        """Links a supplier to a product or updates existing pricing/terms."""
        query = """
            INSERT INTO supplier_products (supplier_id, product_id, unit_cost, moq, supplier_lead_time_days, is_primary)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(supplier_id, product_id) DO UPDATE SET
                unit_cost = excluded.unit_cost,
                moq = excluded.moq,
                supplier_lead_time_days = excluded.supplier_lead_time_days,
                is_primary = excluded.is_primary
        """
        with db_transaction(self.db_path) as conn:
            cursor = conn.execute(query, (supplier_id, product_id, unit_cost, moq, lead_time_days, 1 if is_primary else 0))
            return cursor.lastrowid
