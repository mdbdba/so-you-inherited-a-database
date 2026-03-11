"""Unit tests for dbx.pg.client utilities (no live database required)."""

import pytest
from dbx.pg.client import dsn_for_database


class TestDsnForDatabase:
    def test_replaces_database_simple(self):
        dsn = "postgresql://user:pass@localhost:5432/bluebox"
        result = dsn_for_database(dsn, "postgres")
        assert result == "postgresql://user:pass@localhost:5432/postgres"

    def test_replaces_database_no_port(self):
        dsn = "postgresql://user:pass@localhost/bluebox"
        result = dsn_for_database(dsn, "postgres")
        assert result == "postgresql://user:pass@localhost/postgres"

    def test_preserves_query_params(self):
        dsn = "postgresql://user:pass@localhost:5432/bluebox?sslmode=disable&application_name=dbx"
        result = dsn_for_database(dsn, "postgres")
        assert "/postgres?" in result
        assert "sslmode=disable" in result
        assert "application_name=dbx" in result

    def test_preserves_credentials(self):
        dsn = "postgresql://myuser:s3cr3t@db.example.com:5432/app"
        result = dsn_for_database(dsn, "other")
        assert "myuser:s3cr3t" in result
        assert "db.example.com" in result
        assert result.endswith("/other")

    def test_does_not_modify_original(self):
        dsn = "postgresql://user:pass@localhost/bluebox"
        _ = dsn_for_database(dsn, "postgres")
        assert dsn == "postgresql://user:pass@localhost/bluebox"

    def test_same_database_is_idempotent(self):
        dsn = "postgresql://user:pass@localhost/bluebox"
        result = dsn_for_database(dsn, "bluebox")
        assert result == dsn
