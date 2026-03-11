"""Unit tests for extension health evaluation (no live DB needed)."""

from __future__ import annotations

import pytest

from dbx.pg.extension_health import (
    ACTIVE_EXTENSIONS,
    PASSIVE_EXTENSIONS,
    ExtensionHealth,
    check_all_extensions,
    _check_dblink,
    _check_pg_cron,
    _check_pg_stat_statements,
    _check_postgis,
    _check_postgres_fdw,
    _check_vector,
)
from dbx.pg.inspect import PgCapabilities


# ---------------------------------------------------------------------------
# Minimal mock client
# ---------------------------------------------------------------------------


class MockPgClient:
    """Simple mock that returns configurable results for client methods."""

    def __init__(
        self,
        fetchone_result: dict | None = None,
        probe_result: tuple[bool, str] = (True, ""),
        fetchall_result: list[dict] | None = None,
    ):
        self._fetchone_result = fetchone_result
        self._probe_result = probe_result
        self._fetchall_result = fetchall_result or []

    def fetchone(self, sql: str, params=None) -> dict | None:
        return self._fetchone_result

    def probe(self, sql: str) -> tuple[bool, str]:
        return self._probe_result

    def fetchall(self, sql: str, params=None) -> list[dict]:
        return self._fetchall_result


def _make_caps(**overrides) -> PgCapabilities:
    caps = PgCapabilities()
    for k, v in overrides.items():
        setattr(caps, k, v)
    return caps


# ---------------------------------------------------------------------------
# TestPassiveExtensionSet
# ---------------------------------------------------------------------------


class TestPassiveExtensionSet:
    def test_plpgsql_is_passive(self):
        assert "plpgsql" in PASSIVE_EXTENSIONS

    def test_citext_is_passive(self):
        assert "citext" in PASSIVE_EXTENSIONS

    def test_pg_stat_statements_not_passive(self):
        assert "pg_stat_statements" not in PASSIVE_EXTENSIONS

    def test_postgis_not_passive(self):
        assert "postgis" not in PASSIVE_EXTENSIONS

    def test_vector_not_passive(self):
        assert "vector" not in PASSIVE_EXTENSIONS


# ---------------------------------------------------------------------------
# TestActiveExtensionMap
# ---------------------------------------------------------------------------


class TestActiveExtensionMap:
    def test_all_six_keys_present(self):
        expected = {
            "pg_stat_statements",
            "pg_cron",
            "postgres_fdw",
            "postgis",
            "vector",
            "dblink",
        }
        assert set(ACTIVE_EXTENSIONS.keys()) == expected

    def test_values_are_callable(self):
        for name, fn in ACTIVE_EXTENSIONS.items():
            assert callable(fn), f"{name} value is not callable"


# ---------------------------------------------------------------------------
# TestCheckAllExtensions
# ---------------------------------------------------------------------------


class TestCheckAllExtensions:
    def test_unknown_extension_gets_unknown_status(self):
        caps = _make_caps(extensions={"some_custom_ext": "1.0"})
        client = MockPgClient()
        results = check_all_extensions(client, caps)
        assert len(results) == 1
        assert results[0].name == "some_custom_ext"
        assert results[0].status == "Unknown"

    def test_passive_extension_gets_passive_status(self):
        caps = _make_caps(extensions={"citext": "1.6"})
        client = MockPgClient()
        results = check_all_extensions(client, caps)
        assert results[0].status == "Passive"

    def test_exception_in_check_yields_warning_not_crash(self):
        caps = _make_caps(
            extensions={"pg_stat_statements": "1.10"},
            settings={"server_version": "16.1"},
        )
        # fetchone raises to simulate a broken connection
        class BrokenClient:
            def fetchone(self, sql, params=None):
                raise RuntimeError("connection lost")
            def probe(self, sql):
                return True, ""
            def fetchall(self, sql, params=None):
                return []

        results = check_all_extensions(BrokenClient(), caps)
        assert results[0].status == "Warning"
        assert any("Health check failed" in n for n in results[0].notes)

    def test_pg_cron_runs_elsewhere_yields_passive(self):
        caps = _make_caps(
            extensions={"pg_cron": "1.6"},
            pg_cron_runs_elsewhere=True,
        )
        client = MockPgClient()
        results = check_all_extensions(client, caps)
        assert results[0].status == "Passive"
        assert any("another database" in n for n in results[0].notes)

    def test_results_are_alphabetically_sorted(self):
        caps = _make_caps(
            extensions={"vector": "0.7.0", "citext": "1.6", "pg_cron": "1.6"},
            settings={"server_version": "16.1"},
        )
        client = MockPgClient(
            fetchone_result={"total_runs": 0, "failed_runs": 0},
            probe_result=(True, ""),
        )
        results = check_all_extensions(client, caps)
        names = [r.name for r in results]
        assert names == sorted(names)

    def test_empty_extensions_returns_empty_list(self):
        caps = _make_caps(extensions={})
        results = check_all_extensions(MockPgClient(), caps)
        assert results == []


# ---------------------------------------------------------------------------
# TestCheckPgStatStatements
# ---------------------------------------------------------------------------


class TestCheckPgStatStatements:
    def test_pg14_no_dealloc_is_healthy(self):
        caps = _make_caps(settings={"server_version": "16.1"}, pss_ready=True)
        client = MockPgClient(fetchone_result={"dealloc": 0, "stats_reset": None})
        result = _check_pg_stat_statements(client, caps)
        assert result.status == "Healthy"

    def test_pg14_nonzero_dealloc_is_warning(self):
        caps = _make_caps(settings={"server_version": "14.5"}, pss_ready=True)
        client = MockPgClient(fetchone_result={"dealloc": 1243, "stats_reset": None})
        result = _check_pg_stat_statements(client, caps)
        assert result.status == "Warning"
        assert any("1,243" in n for n in result.notes)

    def test_pg13_pss_ready_is_healthy(self):
        caps = _make_caps(settings={"server_version": "13.9"}, pss_ready=True)
        client = MockPgClient()
        result = _check_pg_stat_statements(client, caps)
        assert result.status == "Healthy"

    def test_pg13_pss_not_ready_is_warning(self):
        caps = _make_caps(settings={"server_version": "13.9"}, pss_ready=False)
        client = MockPgClient()
        result = _check_pg_stat_statements(client, caps)
        assert result.status == "Warning"

    def test_unknown_version_falls_back_to_pss_ready(self):
        caps = _make_caps(settings={"server_version": ""}, pss_ready=True)
        client = MockPgClient()
        result = _check_pg_stat_statements(client, caps)
        assert result.status == "Healthy"


# ---------------------------------------------------------------------------
# TestCheckPostgresfdw
# ---------------------------------------------------------------------------


class TestCheckPostgresfdw:
    def test_zero_servers_is_warning(self):
        caps = _make_caps()
        client = MockPgClient(fetchone_result={"server_count": 0})
        result = _check_postgres_fdw(client, caps)
        assert result.status == "Warning"
        assert any("not configured" in n for n in result.notes)

    def test_nonzero_servers_is_healthy(self):
        caps = _make_caps()
        client = MockPgClient(fetchone_result={"server_count": 2})
        result = _check_postgres_fdw(client, caps)
        assert result.status == "Healthy"


# ---------------------------------------------------------------------------
# TestCheckPostgis
# ---------------------------------------------------------------------------


class TestCheckPostgis:
    def test_probe_ok_is_healthy(self):
        caps = _make_caps()
        client = MockPgClient(
            probe_result=(True, ""),
            fetchone_result={"version": "3.4 USE_GEOS=1"},
        )
        result = _check_postgis(client, caps)
        assert result.status == "Healthy"

    def test_probe_fail_is_degraded(self):
        caps = _make_caps()
        client = MockPgClient(probe_result=(False, "function does not exist"))
        result = _check_postgis(client, caps)
        assert result.status == "Degraded"
        assert any("PostGIS_Version()" in n for n in result.notes)


# ---------------------------------------------------------------------------
# TestCheckVector
# ---------------------------------------------------------------------------


class TestCheckVector:
    def test_probe_ok_is_healthy(self):
        caps = _make_caps()
        client = MockPgClient(probe_result=(True, ""))
        result = _check_vector(client, caps)
        assert result.status == "Healthy"

    def test_probe_fail_is_degraded(self):
        caps = _make_caps()
        client = MockPgClient(probe_result=(False, "type vector does not exist"))
        result = _check_vector(client, caps)
        assert result.status == "Degraded"
        assert any("vector type probe failed" in n for n in result.notes)


# ---------------------------------------------------------------------------
# TestCheckDblink
# ---------------------------------------------------------------------------


class TestCheckDblink:
    def test_fn_found_is_healthy(self):
        caps = _make_caps()
        client = MockPgClient(fetchone_result={"fn_count": 3})
        result = _check_dblink(client, caps)
        assert result.status == "Healthy"

    def test_fn_missing_is_degraded(self):
        caps = _make_caps()
        client = MockPgClient(fetchone_result={"fn_count": 0})
        result = _check_dblink(client, caps)
        assert result.status == "Degraded"
        assert any("not found" in n for n in result.notes)


# ---------------------------------------------------------------------------
# TestCheckPgCron
# ---------------------------------------------------------------------------


class TestCheckPgCron:
    def test_zero_failures_is_healthy(self):
        caps = _make_caps()
        client = MockPgClient(fetchone_result={"total_runs": 10, "failed_runs": 0})
        result = _check_pg_cron(client, caps)
        assert result.status == "Healthy"

    def test_failures_is_warning(self):
        caps = _make_caps()
        client = MockPgClient(fetchone_result={"total_runs": 5, "failed_runs": 2})
        result = _check_pg_cron(client, caps)
        assert result.status == "Warning"
        assert any("2 failed" in n for n in result.notes)

    def test_zero_total_is_healthy_with_note(self):
        caps = _make_caps()
        client = MockPgClient(fetchone_result={"total_runs": 0, "failed_runs": 0})
        result = _check_pg_cron(client, caps)
        assert result.status == "Healthy"
        assert any("No job runs" in n for n in result.notes)


# ---------------------------------------------------------------------------
# TestExtensionHealthFindings
# ---------------------------------------------------------------------------


class TestExtensionHealthFindings:
    def _analyze(self, data):
        from dbx.report.findings import _analyze
        return _analyze(data)

    def _caps_with_health(self, health_list):
        return {
            "capabilities": {
                "pss_ready": True,
                "auto_explain_ready": True,
                "pg_cron_ready": False,
                "extension_health": health_list,
            }
        }

    def test_pss_evictions_triggers_risk(self):
        data = self._caps_with_health([
            {"name": "pg_stat_statements", "status": "Warning", "notes": ["1,243 evictions; query history is incomplete"]},
        ])
        risks, _ = self._analyze(data)
        titles = [r.title for r in risks]
        assert any("evict" in t.lower() for t in titles)

    def test_cron_failures_triggers_risk(self):
        data = self._caps_with_health([
            {"name": "pg_cron", "status": "Warning", "notes": ["3 failed run(s) in the last 24 hours"]},
        ])
        risks, _ = self._analyze(data)
        titles = [r.title for r in risks]
        assert any("cron" in t.lower() for t in titles)

    def test_degraded_extension_triggers_risk(self):
        data = self._caps_with_health([
            {"name": "postgis", "status": "Degraded", "notes": ["PostGIS_Version() failed"]},
        ])
        risks, _ = self._analyze(data)
        titles = [r.title for r in risks]
        assert any("degraded" in t.lower() for t in titles)

    def test_unknown_extension_triggers_win(self):
        data = self._caps_with_health([
            {"name": "some_custom_ext", "status": "Unknown", "notes": ["No health check available — verify manually"]},
        ])
        _, wins = self._analyze(data)
        titles = [w.title for w in wins]
        assert any("unknown" in t.lower() for t in titles)

    def test_no_crash_on_empty_extension_health(self):
        data = self._caps_with_health([])
        risks, wins = self._analyze(data)
        assert isinstance(risks, list)
        assert isinstance(wins, list)

    def test_no_crash_on_missing_extension_health_key(self):
        data = {"capabilities": {"pss_ready": True}}
        risks, wins = self._analyze(data)
        assert isinstance(risks, list)
        assert isinstance(wins, list)

    def test_healthy_extensions_produce_no_findings(self):
        data = self._caps_with_health([
            {"name": "pg_stat_statements", "status": "Healthy", "notes": []},
            {"name": "citext", "status": "Passive", "notes": ["No ongoing health check needed"]},
        ])
        risks, wins = self._analyze(data)
        ext_titles = [f.title for f in risks + wins if "extension" in f.title.lower() or "evict" in f.title.lower() or "cron" in f.title.lower() or "degraded" in f.title.lower() or "unknown" in f.title.lower()]
        assert ext_titles == []
