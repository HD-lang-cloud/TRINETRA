from typing import Any, Dict, List, Optional
from repositories.base_repository import BaseRepository


class LocationRepository(BaseRepository):
    """Data repository for warehouse and storage locations."""

    def __init__(self, db_path: Optional[str] = None):
        super().__init__(table_name="locations", db_path=db_path)

    def find_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Finds a location by unique alphanumeric code."""
        return self.execute_query_one("SELECT * FROM locations WHERE code = ?", (code.strip().upper(),))

    def get_or_create_default(self) -> Dict[str, Any]:
        """Ensures a primary central warehouse exists and returns it."""
        primary = self.find_by_code("WH-MAIN")
        if primary:
            return primary

        loc_id = self.insert({
            "code": "WH-MAIN",
            "name": "Central Fulfilment Hub",
            "address": "Zone 1 Logistics Park, Sector 4",
            "location_type": "WAREHOUSE"
        })
        return self.find_by_id(loc_id)
