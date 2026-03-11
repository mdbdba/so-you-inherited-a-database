"""Minimal psycopg v3 connection wrapper with timeouts and dict-row output.

All queries execute synchronously. A short connect_timeout prevents hanging
when the DB is unreachable.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row


def dsn_for_database(dsn: str, dbname: str) -> str:
    """Return *dsn* with the database component replaced by *dbname*.

    Works with standard ``postgresql://user:pass@host:port/dbname`` URIs.
    Query-string parameters (e.g. ``?sslmode=disable``) are preserved.
    """
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(dsn)
    new = parsed._replace(path=f"/{dbname}")
    return urlunparse(new)


class PgClient:
    """Synchronous Postgres client. Use as a context manager."""

    def __init__(self, dsn: str, connect_timeout: int = 10) -> None:
        self.dsn = dsn
        self.connect_timeout = connect_timeout
        self._conn: psycopg.Connection | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "PgClient":
        self._conn = psycopg.connect(
            self.dsn,
            connect_timeout=self.connect_timeout,
            row_factory=dict_row,
        )
        return self

    def __exit__(self, *_args: object) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def fetchall(self, sql: str, params: Any = None) -> list[dict]:
        """Execute *sql* and return all rows as a list of dicts."""
        assert self._conn is not None, "Not connected – use as a context manager"
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()  # type: ignore[return-value]

    def fetchone(self, sql: str, params: Any = None) -> dict | None:
        """Execute *sql* and return the first row as a dict (or None)."""
        assert self._conn is not None, "Not connected – use as a context manager"
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()  # type: ignore[return-value]

    def show(self, setting: str) -> str:
        """Run ``SHOW <setting>`` and return the value as a string.

        *setting* must be a name from our own constant list (not user input),
        so SQL injection via the format string is not a concern here.
        """
        assert self._conn is not None, "Not connected – use as a context manager"
        with self._conn.cursor(row_factory=psycopg.rows.tuple_row) as cur:
            cur.execute(f"SHOW {setting}")  # noqa: S608 – internal use only
            row = cur.fetchone()
            return row[0] if row else ""

    def probe(self, sql: str) -> tuple[bool, str]:
        """Execute *sql* and return (success, error_message).

        Used to test whether a view/table is accessible.
        """
        assert self._conn is not None, "Not connected – use as a context manager"
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql)
                cur.fetchone()
            return True, ""
        except Exception as exc:
            # Roll back the failed transaction so subsequent queries work.
            self._conn.rollback()
            return False, str(exc)
