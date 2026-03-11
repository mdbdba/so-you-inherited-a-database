"""Unit tests for memory effectiveness metrics (no live DB needed)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dbx.pg.sections import _build_memory_effectiveness


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------


class MockClient:
    def __init__(self, hit_row=None, temp_row=None, raise_on=None):
        self._hit_row = hit_row
        self._temp_row = temp_row
        self._raise_on = raise_on or set()

    def fetchone(self, sql):
        from dbx.pg.queries import Q_BUFFER_HIT_RATE, Q_TEMP_FILE_STATS
        if sql == Q_BUFFER_HIT_RATE:
            if "hit" in self._raise_on:
                raise RuntimeError("permission denied for pg_statio_user_tables")
            return self._hit_row
        if sql == Q_TEMP_FILE_STATS:
            if "temp" in self._raise_on:
                raise RuntimeError("permission denied for pg_stat_database")
            return self._temp_row
        return None


def _stats_reset(days_ago=14):
    from datetime import timedelta
    return datetime.now(tz=timezone.utc) - timedelta(days=days_ago)


# ---------------------------------------------------------------------------
# Signal thresholds
# ---------------------------------------------------------------------------


class TestHitRateSignals:
    def test_good_at_99_percent(self):
        client = MockClient(hit_row={"table_hit_pct": 99.5, "index_hit_pct": 99.8})
        md, raw = _build_memory_effectiveness(client)
        assert "Good" in md
        assert raw["table_hit_pct"] == 99.5

    def test_ok_at_97_percent(self):
        client = MockClient(hit_row={"table_hit_pct": 97.0, "index_hit_pct": 98.0})
        md, raw = _build_memory_effectiveness(client)
        assert "OK" in md

    def test_investigate_below_95(self):
        client = MockClient(hit_row={"table_hit_pct": 88.0, "index_hit_pct": 91.0})
        md, raw = _build_memory_effectiveness(client)
        assert "Investigate" in md
        assert raw["table_hit_pct"] == 88.0

    def test_no_data_when_null(self):
        client = MockClient(hit_row={"table_hit_pct": None, "index_hit_pct": None})
        md, raw = _build_memory_effectiveness(client)
        assert "No data" in md
        assert raw["table_hit_pct"] is None

    def test_boundary_exactly_99(self):
        client = MockClient(hit_row={"table_hit_pct": 99.0, "index_hit_pct": 99.0})
        md, _ = _build_memory_effectiveness(client)
        assert "Good" in md

    def test_boundary_exactly_95(self):
        client = MockClient(hit_row={"table_hit_pct": 95.0, "index_hit_pct": 95.0})
        md, _ = _build_memory_effectiveness(client)
        assert "OK" in md

    def test_boundary_just_below_95(self):
        client = MockClient(hit_row={"table_hit_pct": 94.9, "index_hit_pct": 94.9})
        md, _ = _build_memory_effectiveness(client)
        assert "Investigate" in md


# ---------------------------------------------------------------------------
# Temp file signals
# ---------------------------------------------------------------------------


class TestTempFileSignals:
    def test_zero_spills(self):
        client = MockClient(
            hit_row={"table_hit_pct": 99.0, "index_hit_pct": 99.0},
            temp_row={"temp_files": 0, "temp_bytes": 0, "temp_size_pretty": "0 bytes", "stats_reset": _stats_reset()},
        )
        md, raw = _build_memory_effectiveness(client)
        assert "work_mem adequate" in md
        assert raw["temp_files"] == 0
        assert raw["temp_bytes"] == 0

    def test_nonzero_spills(self):
        client = MockClient(
            hit_row={"table_hit_pct": 99.0, "index_hit_pct": 99.0},
            temp_row={"temp_files": 1243, "temp_bytes": 4_400_000_000, "temp_size_pretty": "4.1 GB", "stats_reset": _stats_reset()},
        )
        md, raw = _build_memory_effectiveness(client)
        assert "spill" in md.lower()
        assert "1,243" in md
        assert raw["temp_files"] == 1243

    def test_stats_reset_included_in_note(self):
        reset_time = _stats_reset(days_ago=14)
        client = MockClient(
            hit_row={"table_hit_pct": 99.0, "index_hit_pct": 99.0},
            temp_row={"temp_files": 0, "temp_bytes": 0, "temp_size_pretty": "0 bytes", "stats_reset": reset_time},
        )
        md, _ = _build_memory_effectiveness(client)
        assert "14d ago" in md or "stats_reset" in md.lower() or "last reset" in md.lower()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_hit_rate_error_does_not_crash(self):
        client = MockClient(
            temp_row={"temp_files": 0, "temp_bytes": 0, "temp_size_pretty": "0 bytes", "stats_reset": None},
            raise_on={"hit"},
        )
        md, raw = _build_memory_effectiveness(client)
        assert "unavailable" in md
        assert "table_hit_pct" not in raw

    def test_temp_stats_error_does_not_crash(self):
        client = MockClient(
            hit_row={"table_hit_pct": 99.0, "index_hit_pct": 99.0},
            raise_on={"temp"},
        )
        md, raw = _build_memory_effectiveness(client)
        assert "unavailable" in md
        assert "temp_files" not in raw

    def test_both_errors_returns_something(self):
        client = MockClient(raise_on={"hit", "temp"})
        md, raw = _build_memory_effectiveness(client)
        assert md != ""

    def test_none_rows_returns_empty(self):
        client = MockClient(hit_row=None, temp_row=None)
        md, raw = _build_memory_effectiveness(client)
        # No rows returned — output may be empty or minimal
        assert isinstance(md, str)
        assert isinstance(raw, dict)


# ---------------------------------------------------------------------------
# Findings engine
# ---------------------------------------------------------------------------


class TestMemoryEffectivenessFindings:
    def _analyze(self, data):
        from dbx.report.findings import _analyze
        return _analyze(data)

    def _data(self, mem):
        return {
            "capabilities": {"pss_ready": True, "auto_explain_ready": True},
            "config": {"settings": {}, "memory_effectiveness": mem},
        }

    def test_low_hit_rate_triggers_risk(self):
        risks, _ = self._analyze(self._data({"table_hit_pct": 88.0, "temp_bytes": 0}))
        titles = [r.title for r in risks]
        assert any("hit rate" in t.lower() for t in titles)

    def test_ok_hit_rate_no_risk(self):
        risks, _ = self._analyze(self._data({"table_hit_pct": 97.5, "temp_bytes": 0}))
        titles = [r.title for r in risks]
        assert not any("hit rate" in t.lower() for t in titles)

    def test_temp_spills_triggers_win(self):
        _, wins = self._analyze(self._data({"table_hit_pct": 99.0, "temp_bytes": 2_000_000_000, "temp_files": 500}))
        titles = [w.title for w in wins]
        assert any("spill" in t.lower() or "work_mem" in t.lower() for t in titles)

    def test_no_spills_no_win(self):
        _, wins = self._analyze(self._data({"table_hit_pct": 99.0, "temp_bytes": 0, "temp_files": 0}))
        titles = [w.title for w in wins]
        assert not any("spill" in t.lower() for t in titles)

    def test_missing_mem_data_no_crash(self):
        risks, wins = self._analyze({"capabilities": {"pss_ready": True}})
        assert isinstance(risks, list)
        assert isinstance(wins, list)

    def test_hit_rate_exactly_at_threshold_no_risk(self):
        risks, _ = self._analyze(self._data({"table_hit_pct": 95.0, "temp_bytes": 0}))
        titles = [r.title for r in risks]
        assert not any("hit rate" in t.lower() for t in titles)
