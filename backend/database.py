import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Generator
from flask import current_app, has_app_context


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "database" / "trinetra.db"


def resolve_db_path(db_path: Optional[str | Path] = None) -> Path:
    """Resolve database path from argument, Flask config, or default location."""
    if db_path:
        return Path(db_path)
    if has_app_context() and current_app.config.get("DATABASE_PATH"):
        return Path(current_app.config["DATABASE_PATH"])
    return DEFAULT_DB_PATH


def get_db_connection(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    """
    Creates and returns a SQLite connection configured for TRINETRA:
    - Foreign keys enforced (PRAGMA foreign_keys = ON)
    - Row factory enabled for column name access
    - Timeout configured to handle concurrent reads
    """
    resolved_path = resolve_db_path(db_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(resolved_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_transaction(db_path: Optional[str | Path] = None) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager providing safe transactional execution.
    Automatically commits on normal completion or rolls back if an exception occurs.
    """
    conn = get_db_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
