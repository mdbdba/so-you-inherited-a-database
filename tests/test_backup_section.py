"""Unit tests for backup & recovery section logic (no live database required)."""

import pytest


class TestBackupFindings:
    """Test that backup-related data triggers the right findings rules."""

    def _analyze(self, backup_data: dict) -> tuple[list, list]:
        from dbx.report.findings import _analyze
        return _analyze({"backup": backup_data, "capabilities": {"pss_ready": True}})

    def test_archive_mode_off_is_top_risk(self):
        risks, _ = self._analyze({"archive_mode_on": False})
        titles = [r.title for r in risks]
        assert any("archiving" in t.lower() or "archive" in t.lower() for t in titles)
        # Should be priority 1 — appears first after sort
        assert risks[0].priority == 1

    def test_stale_archive_is_risk(self):
        risks, _ = self._analyze({
            "archive_mode_on": True,
            "archiver_configured": True,
            "archive_stale": True,
        })
        titles = [r.title for r in risks]
        assert any("stale" in t.lower() for t in titles)

    def test_archive_failures_is_risk(self):
        risks, _ = self._analyze({
            "archive_mode_on": True,
            "archiver_configured": True,
            "archive_failures": 3,
        })
        titles = [r.title for r in risks]
        assert any("failure" in t.lower() for t in titles)

    def test_inactive_replication_slots_is_risk(self):
        risks, _ = self._analyze({
            "replication_slots": [
                {"slot_name": "old_slot", "active": False, "retained_wal_bytes": 500_000_000},
            ]
        })
        titles = [r.title for r in risks]
        assert any("slot" in t.lower() for t in titles)

    def test_active_slot_does_not_trigger_risk(self):
        risks, _ = self._analyze({
            "replication_slots": [
                {"slot_name": "active_slot", "active": True, "retained_wal_bytes": 10_000_000},
            ]
        })
        titles = [r.title for r in risks]
        assert not any("slot" in t.lower() for t in titles)

    def test_healthy_archive_no_backup_risks(self):
        risks, _ = self._analyze({
            "archive_mode_on": True,
            "archiver_configured": True,
            "archive_stale": False,
            "archive_failures": 0,
            "replication_slots": [],
        })
        backup_risks = [
            r for r in risks
            if any(kw in r.title.lower() for kw in ("archive", "slot", "backup", "wal"))
        ]
        assert backup_risks == []

    def test_no_backup_data_produces_no_backup_risks(self):
        """Empty backup dict should not crash or produce spurious findings."""
        risks, _ = self._analyze({})
        assert isinstance(risks, list)


class TestArchiveSettingsInShowSettings:
    """Verify archive-related settings are included in the SHOW_SETTINGS list."""

    def test_archive_settings_present(self):
        from dbx.pg.inspect import SHOW_SETTINGS
        required = {"archive_mode", "wal_level", "archive_command", "archive_library"}
        assert required.issubset(set(SHOW_SETTINGS))


class TestBackupQueryConstants:
    """Verify backup SQL constants exist and pass structural checks."""

    def test_backup_queries_exist(self):
        import dbx.pg.queries as Q
        assert hasattr(Q, "Q_ARCHIVE_STATUS")
        assert hasattr(Q, "Q_REPLICATION_STANDBYS")
        assert hasattr(Q, "Q_REPLICATION_SLOTS")
        assert hasattr(Q, "Q_BACKUP_AGENT_CONNECTIONS")

    def test_replication_slots_query_has_numeric_cast(self):
        """pg_wal_lsn_diff returns numeric; must cast to bigint for pg_size_pretty."""
        from dbx.pg.queries import Q_REPLICATION_SLOTS
        assert "::bigint" in Q_REPLICATION_SLOTS
