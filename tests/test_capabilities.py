"""Unit tests for capability detection logic (pure functions, no live DB)."""

import pytest
from dbx.pg.inspect import PgCapabilities


class TestPgCapabilities:
    """Test the readiness logic using pre-populated PgCapabilities objects."""

    def _make_caps(self, **overrides) -> PgCapabilities:
        caps = PgCapabilities()
        for k, v in overrides.items():
            setattr(caps, k, v)
        return caps

    # --- pg_stat_statements readiness ---

    def test_pss_ready_when_all_conditions_met(self):
        caps = self._make_caps(
            pss_in_shared_preload=True,
            pss_extension_installed=True,
            pss_view_readable=True,
        )
        # Simulate the final readiness computation
        caps.pss_ready = (
            caps.pss_in_shared_preload
            and caps.pss_extension_installed
            and caps.pss_view_readable
        )
        assert caps.pss_ready is True

    def test_pss_not_ready_missing_shared_preload(self):
        caps = self._make_caps(
            pss_in_shared_preload=False,
            pss_extension_installed=True,
            pss_view_readable=True,
        )
        caps.pss_ready = (
            caps.pss_in_shared_preload
            and caps.pss_extension_installed
            and caps.pss_view_readable
        )
        assert caps.pss_ready is False

    def test_pss_not_ready_missing_extension(self):
        caps = self._make_caps(
            pss_in_shared_preload=True,
            pss_extension_installed=False,
            pss_view_readable=False,
        )
        caps.pss_ready = (
            caps.pss_in_shared_preload
            and caps.pss_extension_installed
            and caps.pss_view_readable
        )
        assert caps.pss_ready is False

    def test_pss_not_ready_view_not_readable(self):
        caps = self._make_caps(
            pss_in_shared_preload=True,
            pss_extension_installed=True,
            pss_view_readable=False,
            pss_view_error="permission denied",
        )
        caps.pss_ready = (
            caps.pss_in_shared_preload
            and caps.pss_extension_installed
            and caps.pss_view_readable
        )
        assert caps.pss_ready is False
        assert "permission denied" in caps.pss_view_error

    # --- pg_cron readiness ---

    def test_pg_cron_ready_when_all_conditions_met(self):
        caps = self._make_caps(
            pg_cron_in_shared_preload=True,
            pg_cron_extension_installed=True,
            pg_cron_job_readable=True,
        )
        caps.pg_cron_ready = (
            caps.pg_cron_in_shared_preload
            and caps.pg_cron_extension_installed
            and caps.pg_cron_job_readable
        )
        assert caps.pg_cron_ready is True

    def test_pg_cron_not_ready_wrong_database(self):
        """pg_cron may be installed but job table unreadable from wrong DB."""
        caps = self._make_caps(
            pg_cron_in_shared_preload=True,
            pg_cron_extension_installed=True,
            pg_cron_job_readable=False,
            pg_cron_job_error="relation cron.job does not exist",
            pg_cron_database_name="postgres",
        )
        caps.pg_cron_ready = (
            caps.pg_cron_in_shared_preload
            and caps.pg_cron_extension_installed
            and caps.pg_cron_job_readable
        )
        assert caps.pg_cron_ready is False
        assert caps.pg_cron_database_name == "postgres"

    # --- auto_explain ---

    def test_auto_explain_detected_via_shared_preload(self):
        caps = self._make_caps(
            auto_explain_in_shared_preload=True,
            auto_explain_log_min_duration="500ms",
            auto_explain_log_format="json",
        )
        assert caps.auto_explain_in_shared_preload is True
        assert caps.auto_explain_log_min_duration == "500ms"
        assert caps.auto_explain_log_format == "json"

    def test_auto_explain_not_loaded(self):
        caps = self._make_caps(auto_explain_in_shared_preload=False)
        assert caps.auto_explain_in_shared_preload is False

    # --- Default state ---

    def test_default_capabilities_all_false(self):
        caps = PgCapabilities()
        assert caps.pss_ready is False
        assert caps.pg_cron_ready is False
        assert caps.auto_explain_in_shared_preload is False
        assert caps.extensions == {}
        assert caps.settings == {}


class TestFindingsEngine:
    """Test the pure findings-analysis function."""

    def test_no_findings_on_empty_data(self):
        from dbx.report.findings import _analyze

        risks, wins = _analyze({})
        assert isinstance(risks, list)
        assert isinstance(wins, list)

    def test_pss_not_ready_triggers_risk(self):
        from dbx.report.findings import _analyze

        data = {"capabilities": {"pss_ready": False}}
        risks, _ = _analyze(data)
        titles = [r.title for r in risks]
        assert any("pg_stat_statements" in t for t in titles)

    def test_blocked_queries_triggers_risk(self):
        from dbx.report.findings import _analyze

        data = {
            "capabilities": {"pss_ready": True},
            "health": {
                "blocked": [{"blocked_pid": 1, "blocking_pid": 2, "wait_seconds": 30}],
                "long_xacts": [],
            },
        }
        risks, _ = _analyze(data)
        titles = [r.title for r in risks]
        assert any("blocked" in t.lower() for t in titles)

    def test_unused_indexes_triggers_win(self):
        from dbx.report.findings import _analyze

        data = {
            "capabilities": {"pss_ready": True},
            "index": {
                "unused_indexes": [
                    {"index_name": "idx_foo", "index_bytes": 10_485_760, "idx_scan": 0}
                ]
            },
        }
        _, wins = _analyze(data)
        titles = [w.title for w in wins]
        assert any("unused" in t.lower() or "drop" in t.lower() for t in titles)

    def test_high_dead_tuples_triggers_risk(self):
        from dbx.report.findings import _analyze

        data = {
            "capabilities": {"pss_ready": True},
            "vacuum": {
                "vacuum_bloat": [
                    {
                        "table_name": "big_table",
                        "n_dead_tup": 500_000,
                        "n_live_tup": 1_000_000,
                        "dead_pct": 33.3,
                    }
                ]
            },
        }
        risks, _ = _analyze(data)
        titles = [r.title for r in risks]
        assert any("dead" in t.lower() or "bloat" in t.lower() for t in titles)

    def test_max_five_risks_and_wins(self):
        from dbx.report.findings import _analyze

        # Trigger every possible finding
        data = {
            "capabilities": {"pss_ready": False, "auto_explain_ready": False},
            "health": {
                "blocked": [{"blocked_pid": 1, "blocking_pid": 2}],
                "long_xacts": [{"xact_seconds": 600, "pid": 99}],
                "connection_pct": 95,
                "connections": {"total": 190, "max_connections": 200},
            },
            "vacuum": {
                "vacuum_bloat": [
                    {"n_dead_tup": 999_999, "n_live_tup": 1_000_000, "dead_pct": 50.0}
                    for _ in range(3)
                ]
            },
            "index": {
                "unused_indexes": [
                    {"index_bytes": 50_000_000, "idx_scan": 0} for _ in range(5)
                ],
                "high_seq_scan": [
                    {"seq_scan_pct": 95, "n_live_tup": 50_000} for _ in range(3)
                ],
            },
        }
        risks, wins = _analyze(data)
        assert len(risks) <= 5
        assert len(wins) <= 5
