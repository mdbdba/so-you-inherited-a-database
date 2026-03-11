"""Tests for SQL query constants in dbx.pg.queries.

These tests do NOT require a live database. They validate the structure and
type-safety of query strings to catch common Postgres gotchas at development
time rather than at runtime against a real cluster.
"""

import re
import pytest
import dbx.pg.queries as Q


# Collect every module-level string constant that contains SELECT
ALL_QUERIES = {
    name: value
    for name, value in vars(Q).items()
    if isinstance(value, str) and "SELECT" in value.upper()
}


class TestRoundCasts:
    """PostgreSQL's round(value, scale) only accepts numeric, not double precision.

    Any call to round(..., <int>) must have the first argument cast to ::numeric,
    otherwise the query will fail at runtime on Postgres with:
      "function round(double precision, integer) does not exist"
    """

    def _find_bare_round_calls(self, sql: str) -> list[str]:
        """Return round(..., N) calls whose argument is NOT cast to ::numeric."""
        # Match round( <expr> , <digits> ) where the expr does NOT end in ::numeric
        pattern = re.compile(
            r"round\s*\((?P<expr>[^)]+),\s*\d+\)",
            re.IGNORECASE,
        )
        bad: list[str] = []
        for m in pattern.finditer(sql):
            expr = m.group("expr").strip()
            # The cast must appear immediately before the closing paren / comma
            if "::numeric" not in expr.lower():
                bad.append(m.group(0))
        return bad

    @pytest.mark.parametrize("name,sql", list(ALL_QUERIES.items()))
    def test_round_calls_cast_to_numeric(self, name: str, sql: str):
        bad = self._find_bare_round_calls(sql)
        assert bad == [], (
            f"Query {name!r} has round() call(s) without ::numeric cast "
            f"(will fail on double-precision columns in Postgres):\n"
            + "\n".join(f"  {b}" for b in bad)
        )


class TestQueryStructure:
    """Basic structural sanity checks on all query constants."""

    @pytest.mark.parametrize("name,sql", list(ALL_QUERIES.items()))
    def test_queries_end_with_semicolon(self, name: str, sql: str):
        assert sql.strip().endswith(";"), (
            f"Query {name!r} does not end with a semicolon."
        )

    @pytest.mark.parametrize("name,sql", list(ALL_QUERIES.items()))
    def test_queries_not_empty(self, name: str, sql: str):
        assert len(sql.strip()) > 10, f"Query {name!r} appears to be empty."

    def test_all_expected_queries_present(self):
        """Ensure key query constants exist and haven't been accidentally removed."""
        expected = [
            "Q_EXTENSIONS",
            "Q_INSTANCE_DATABASES",
            "Q_DB_SIZE",
            "Q_TOP_TABLES_BY_SIZE",
            "Q_TOP_INDEXES_BY_SIZE",
            "Q_CONNECTION_STATS",
            "Q_LONG_RUNNING_TRANSACTIONS",
            "Q_BLOCKED_QUERIES",
            "Q_VACUUM_BLOAT",
            "Q_UNUSED_INDEXES",
            "Q_HIGH_SEQ_SCAN_TABLES",
            "Q_PSS_PROBE",
            "Q_PSS_TOP_QUERIES",
            "Q_CRON_PROBE",
        ]
        for name in expected:
            assert hasattr(Q, name), f"Expected query constant {name!r} is missing from queries.py"
