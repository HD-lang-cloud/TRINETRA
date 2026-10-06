from typing import Any, Dict, List, Optional
from repositories.base_repository import BaseRepository


class CategoryRepository(BaseRepository):
    """Data repository for product categories."""

    def __init__(self, db_path: Optional[str] = None):
        super().__init__(table_name="categories", db_path=db_path)

    def find_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Finds a category by its unique name."""
        return self.execute_query_one("SELECT * FROM categories WHERE name = ?", (name.strip(),))

    def get_or_create(self, name: str, description: Optional[str] = None) -> int:
        """Finds an existing category by name or inserts a new one."""
        existing = self.find_by_name(name)
        if existing:
            return existing["id"]
        return self.insert({"name": name.strip(), "description": description})
