from typing import Any, Dict, List, Optional
from database import get_db_connection, db_transaction


class BaseRepository:
    """
    Abstract base repository encapsulating data access logic.
    Provides parameterized query execution, transaction support,
    and decouples the service layer from direct SQLite dependencies.
    """

    def __init__(self, table_name: str, db_path: Optional[str] = None):
        self.table_name = table_name
        self.db_path = db_path

    def _row_to_dict(self, row) -> Optional[Dict[str, Any]]:
        """Converts an sqlite3.Row instance into a standard Python dictionary."""
        if row is None:
            return None
        return dict(row)

    def execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Executes a SELECT query with parameters and returns a list of dictionaries."""
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def execute_query_one(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Executes a SELECT query with parameters and returns a single dictionary or None."""
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return self._row_to_dict(row)
        finally:
            conn.close()

    def find_by_id(self, entity_id: int) -> Optional[Dict[str, Any]]:
        """Finds an entity by its primary key ID."""
        query = f"SELECT * FROM {self.table_name} WHERE id = ?"
        return self.execute_query_one(query, (entity_id,))

    def find_all(self, order_by: str = "id ASC", limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetches all records from the table with optional sorting and limit."""
        query = f"SELECT * FROM {self.table_name} ORDER BY {order_by}"
        if limit:
            query += f" LIMIT {int(limit)}"
        return self.execute_query(query)

    def insert(self, data: Dict[str, Any]) -> int:
        """
        Inserts a single record into the repository's table.
        Returns the newly generated primary key lastrowid.
        """
        columns = list(data.keys())
        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(columns)
        query = f"INSERT INTO {self.table_name} ({col_names}) VALUES ({placeholders})"
        values = tuple(data[col] for col in columns)

        with db_transaction(self.db_path) as conn:
            cursor = conn.execute(query, values)
            return cursor.lastrowid

    def update(self, entity_id: int, data: Dict[str, Any]) -> bool:
        """
        Updates fields of an existing entity by ID.
        Returns True if a row was updated, False otherwise.
        """
        if not data:
            return False

        set_clause = ", ".join([f"{col} = ?" for col in data.keys()])
        query = f"UPDATE {self.table_name} SET {set_clause} WHERE id = ?"
        values = tuple(list(data.values()) + [entity_id])

        with db_transaction(self.db_path) as conn:
            cursor = conn.execute(query, values)
            return cursor.rowcount > 0

    def delete(self, entity_id: int) -> bool:
        """
        Deletes a record by ID.
        Returns True if a row was deleted, False otherwise.
        """
        query = f"DELETE FROM {self.table_name} WHERE id = ?"
        with db_transaction(self.db_path) as conn:
            cursor = conn.execute(query, (entity_id,))
            return cursor.rowcount > 0

    def count(self) -> int:
        """Returns the total number of records in the table."""
        res = self.execute_query_one(f"SELECT COUNT(*) as cnt FROM {self.table_name}")
        return res["cnt"] if res else 0
