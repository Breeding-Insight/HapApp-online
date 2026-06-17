from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from hapapp_python import config

try:
    import pyodbc

    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False


class DatabaseManager:
    def __init__(self, connection_string: str | None = None) -> None:
        if not PYODBC_AVAILABLE:
            raise ImportError("pyodbc is required for Microsoft SQL Server connections.")
        self.connection_string = connection_string or config.DATABASE_CONNECTION_STRING

    @contextmanager
    def get_connection(self):
        conn = pyodbc.connect(self.connection_string)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute_query(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]

    def execute_update(self, query: str, params: tuple[Any, ...] = ()) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.rowcount
