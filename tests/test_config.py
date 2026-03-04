"""Unit tests for dbx.config – settings parsing from environment variables."""

import os
import pytest
from pydantic import ValidationError


def test_settings_requires_pg_dsn(monkeypatch):
    """Settings must raise ValidationError when DBX_PG_DSN is absent."""
    monkeypatch.delenv("DBX_PG_DSN", raising=False)
    from dbx.config import Settings  # noqa: PLC0415

    with pytest.raises(ValidationError) as exc_info:
        Settings()
    errors = exc_info.value.errors()
    field_names = [".".join(str(f) for f in e["loc"]) for e in errors]
    assert any("pg_dsn" in name or "DBX_PG_DSN" in name for name in field_names)


def test_settings_parses_pg_dsn(monkeypatch):
    monkeypatch.setenv("DBX_PG_DSN", "postgresql://user:pass@localhost/db")
    monkeypatch.delenv("DBX_GRAFANA_URL", raising=False)
    monkeypatch.delenv("DBX_GRAFANA_TOKEN", raising=False)
    from importlib import reload
    import dbx.config as cfg_module
    reload(cfg_module)
    from dbx.config import Settings

    s = Settings()
    assert s.pg_dsn == "postgresql://user:pass@localhost/db"
    assert s.grafana_url is None
    assert s.grafana_token is None


def test_settings_grafana_configured(monkeypatch):
    monkeypatch.setenv("DBX_PG_DSN", "postgresql://localhost/db")
    monkeypatch.setenv("DBX_GRAFANA_URL", "http://localhost:3000")
    monkeypatch.setenv("DBX_GRAFANA_TOKEN", "glsa_abc123")
    from dbx.config import Settings

    s = Settings()
    assert s.grafana_configured is True
    assert s.grafana_missing_vars == []


def test_settings_grafana_missing_token(monkeypatch):
    monkeypatch.setenv("DBX_PG_DSN", "postgresql://localhost/db")
    monkeypatch.setenv("DBX_GRAFANA_URL", "http://localhost:3000")
    monkeypatch.delenv("DBX_GRAFANA_TOKEN", raising=False)
    from dbx.config import Settings

    s = Settings()
    assert s.grafana_configured is False
    assert "DBX_GRAFANA_TOKEN" in s.grafana_missing_vars


def test_settings_grafana_missing_url(monkeypatch):
    monkeypatch.setenv("DBX_PG_DSN", "postgresql://localhost/db")
    monkeypatch.delenv("DBX_GRAFANA_URL", raising=False)
    monkeypatch.setenv("DBX_GRAFANA_TOKEN", "tok")
    from dbx.config import Settings

    s = Settings()
    assert "DBX_GRAFANA_URL" in s.grafana_missing_vars


def test_redacted_pg_dsn(monkeypatch):
    monkeypatch.setenv("DBX_PG_DSN", "postgresql://user:s3cr3t@localhost:5432/mydb")
    from dbx.config import Settings

    s = Settings()
    redacted = s.redacted_pg_dsn()
    assert "s3cr3t" not in redacted
    assert "***" in redacted
    assert "localhost" in redacted


def test_redacted_pg_dsn_no_password(monkeypatch):
    monkeypatch.setenv("DBX_PG_DSN", "postgresql://localhost/mydb")
    from dbx.config import Settings

    s = Settings()
    # No password to redact – should not crash
    redacted = s.redacted_pg_dsn()
    assert "localhost" in redacted
