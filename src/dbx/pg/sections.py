"""Generate per-section Markdown + structured data from a live Postgres connection.

Each ``build_*`` function returns a tuple of (markdown_string, raw_data_dict).
On failure the markdown contains an explicit error block and raw_data is empty.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dbx.pg.client import PgClient
from dbx.pg.inspect import PgCapabilities
from dbx.pg.queries import (
    Q_BLOCKED_QUERIES,
    Q_CONNECTION_STATS,
    Q_CRON_JOBS,
    Q_DB_SIZE,
    Q_HIGH_SEQ_SCAN_TABLES,
    Q_LONG_RUNNING_TRANSACTIONS,
    Q_PSS_TOP_QUERIES,
    Q_SCHEMA_TABLE_COUNTS,
    Q_TOP_INDEXES_BY_SIZE,
    Q_TOP_TABLES_BY_SIZE,
    Q_UNUSED_INDEXES,
    Q_VACUUM_BLOAT,
)
from dbx.report.markdown import err_block, md_table


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _safe(client: PgClient, fn: Any) -> tuple[list[dict], str | None]:
    """Call *fn(client)* and return (rows, error_or_None)."""
    try:
        return fn(client), None
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)


# ---------------------------------------------------------------------------
# 1. Header
# ---------------------------------------------------------------------------


def build_header(
    settings: Any,
    range_duration: str,
    caps: PgCapabilities,
) -> str:
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    redacted = settings.redacted_pg_dsn()
    pg_version = caps.settings.get("server_version", "unknown")

    lines = [
        "## Report Details\n",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Generated | `{now}` |",
        f"| Target DSN | `{redacted}` |",
        f"| Report range | `{range_duration}` |",
        f"| Postgres version | `{pg_version}` |",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. Capabilities
# ---------------------------------------------------------------------------


def build_capabilities(caps: PgCapabilities) -> tuple[str, dict]:
    lines: list[str] = []

    # Extensions table
    if caps.extensions:
        rows = [{"Extension": k, "Version": v} for k, v in sorted(caps.extensions.items())]
        lines.append("### Installed Extensions\n")
        lines.append(md_table(rows, ["Extension", "Version"]))
    else:
        err = caps.settings_errors.get("extensions", "query failed")
        lines.append("### Installed Extensions\n")
        lines.append(err_block("Could not read pg_extension", err))

    lines.append("")

    # Readiness table
    def _tick(ok: bool) -> str:
        return "✅" if ok else "❌"

    ready_rows = [
        {
            "Extension": "pg_stat_statements",
            "In shared_preload_libraries": _tick(caps.pss_in_shared_preload),
            "Extension installed": _tick(caps.pss_extension_installed),
            "View readable": _tick(caps.pss_view_readable),
            "Ready": _tick(caps.pss_ready),
        },
        {
            "Extension": "auto_explain",
            "In shared_preload_libraries": _tick(caps.auto_explain_in_shared_preload),
            "Extension installed": "N/A",
            "View readable": "N/A",
            "Ready": _tick(caps.auto_explain_in_shared_preload),
        },
        {
            "Extension": "pg_cron",
            "In shared_preload_libraries": _tick(caps.pg_cron_in_shared_preload),
            "Extension installed": _tick(caps.pg_cron_extension_installed),
            "View readable": _tick(caps.pg_cron_job_readable),
            "Ready": _tick(caps.pg_cron_ready),
        },
    ]

    lines.append("### Capability Readiness\n")
    cols = [
        "Extension",
        "In shared_preload_libraries",
        "Extension installed",
        "View readable",
        "Ready",
    ]
    lines.append(md_table(ready_rows, cols))

    # Error notes
    if caps.pss_view_error:
        lines.append(f"\n> **pg_stat_statements view error:** `{caps.pss_view_error}`")
    if caps.pg_cron_job_error:
        lines.append(f"\n> **pg_cron job error:** `{caps.pg_cron_job_error}`")
    if caps.pg_cron_database_name:
        lines.append(
            f"\n> **pg_cron.database_name** is set to `{caps.pg_cron_database_name}`. "
            "If you are connected to a different database, cron jobs will not be visible."
        )

    data = {
        "pss_ready": caps.pss_ready,
        "auto_explain_ready": caps.auto_explain_in_shared_preload,
        "pg_cron_ready": caps.pg_cron_ready,
        "extensions": dict(caps.extensions),
    }
    return "\n".join(lines), data


# ---------------------------------------------------------------------------
# 3. Configuration summary
# ---------------------------------------------------------------------------


def build_config_summary(caps: PgCapabilities) -> tuple[str, dict]:
    notes_map = {
        "shared_preload_libraries": "Extensions loaded at startup",
        "shared_buffers": "Main memory cache (should be ~25% of RAM)",
        "effective_cache_size": "OS + Postgres cache estimate for planner",
        "maintenance_work_mem": "Memory for VACUUM, CREATE INDEX, etc.",
        "work_mem": "Per-sort / per-hash memory (x connections x operations!)",
        "max_parallel_workers_per_gather": "Parallel query workers per node",
        "auto_explain.log_min_duration": "Log plans for queries ≥ this duration",
        "auto_explain.log_format": "Format of auto_explain plan output",
        "pg_stat_statements.max": "Max distinct statements tracked",
        "pg_stat_statements.track": "Which statements to track (top/all/none)",
        "cron.database_name": "Database where pg_cron scheduler runs",
    }

    rows: list[dict] = []
    for setting, note in notes_map.items():
        value = caps.settings.get(setting, "")
        error = caps.settings_errors.get(setting, "")
        rows.append(
            {
                "Setting": f"`{setting}`",
                "Value": f"`{value}`" if value else f"*(error: {error})*",
                "Note": note,
            }
        )

    md = md_table(rows, ["Setting", "Value", "Note"])
    return md, {"settings": dict(caps.settings)}


# ---------------------------------------------------------------------------
# 4. Inventory
# ---------------------------------------------------------------------------


def build_inventory(client: PgClient) -> tuple[str, dict]:
    lines: list[str] = []
    raw: dict = {}

    # DB size
    try:
        row = client.fetchone(Q_DB_SIZE)
        if row:
            lines.append(f"**Database size:** `{row['db_size_pretty']}`\n")
            raw["db_size_bytes"] = row["db_size_bytes"]
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Database size unavailable", str(exc)))

    # Schema / table counts
    try:
        row = client.fetchone(Q_SCHEMA_TABLE_COUNTS)
        if row:
            lines.append(
                f"**Schemas:** {row['schema_count']} &nbsp;|&nbsp; "
                f"**Tables:** {row['table_count']}\n"
            )
            raw["schema_count"] = row["schema_count"]
            raw["table_count"] = row["table_count"]
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Schema/table counts unavailable", str(exc)))

    # Top tables
    try:
        rows = client.fetchall(Q_TOP_TABLES_BY_SIZE)
        raw["top_tables"] = rows
        if rows:
            lines.append("### Top 10 Largest Tables\n")
            cols = ["schema", "table_name", "total_size", "table_size", "index_size"]
            lines.append(md_table(rows, cols))
        else:
            lines.append("*No user tables found.*")
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Top tables unavailable", str(exc)))

    # Top indexes
    try:
        rows = client.fetchall(Q_TOP_INDEXES_BY_SIZE)
        raw["top_indexes"] = rows
        if rows:
            lines.append("\n### Top 10 Largest Indexes\n")
            cols = ["schema", "table_name", "index_name", "index_type", "index_size"]
            lines.append(md_table(rows, cols))
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Top indexes unavailable", str(exc)))

    return "\n".join(lines), raw


# ---------------------------------------------------------------------------
# 5. Operational health
# ---------------------------------------------------------------------------


def build_operational_health(client: PgClient) -> tuple[str, dict]:
    lines: list[str] = []
    raw: dict = {}

    # Connections
    try:
        row = client.fetchone(Q_CONNECTION_STATS)
        if row:
            pct = round(row["total_connections"] / row["max_connections"] * 100, 1)
            lines.append("### Connection Usage\n")
            lines.append(
                f"| Metric | Value |\n|--------|-------|\n"
                f"| Total connections | {row['total_connections']} / {row['max_connections']} ({pct}%) |\n"
                f"| Active | {row['active']} |\n"
                f"| Idle | {row['idle']} |\n"
                f"| Idle in transaction | {row['idle_in_txn']} |\n"
                f"| Waiting | {row['waiting']} |"
            )
            raw["connections"] = dict(row)
            raw["connection_pct"] = pct
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Connection stats unavailable", str(exc)))

    # Long-running transactions
    try:
        rows = client.fetchall(Q_LONG_RUNNING_TRANSACTIONS)
        raw["long_xacts"] = rows
        lines.append("\n### Long-Running Transactions (>5 s)\n")
        if rows:
            cols = [
                "pid", "username", "state", "xact_seconds",
                "query_seconds", "wait_event", "query_snippet",
            ]
            lines.append(md_table(rows, cols))
        else:
            lines.append("*No long-running transactions detected.*")
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Long-running transaction query unavailable", str(exc)))

    # Blocked queries
    try:
        rows = client.fetchall(Q_BLOCKED_QUERIES)
        raw["blocked"] = rows
        lines.append("\n### Blocked Queries\n")
        if rows:
            cols = [
                "blocked_pid", "blocked_user", "blocked_query",
                "blocking_pid", "blocking_user", "blocking_query",
                "wait_seconds",
            ]
            lines.append(md_table(rows, cols))
        else:
            lines.append("*No blocked queries detected.*")
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Blocked query check unavailable", str(exc)))

    return "\n".join(lines), raw


# ---------------------------------------------------------------------------
# 6. Vacuum / bloat
# ---------------------------------------------------------------------------


def build_vacuum_bloat(client: PgClient) -> tuple[str, dict]:
    try:
        rows = client.fetchall(Q_VACUUM_BLOAT)
        if not rows:
            return "*No user tables found.*", {}

        cols = [
            "schema", "table_name", "n_live_tup", "n_dead_tup", "dead_pct",
            "last_vacuum", "last_autovacuum", "last_analyze", "last_autoanalyze",
        ]
        return md_table(rows, cols), {"vacuum_bloat": rows}
    except Exception as exc:  # noqa: BLE001
        return err_block("Vacuum/bloat data unavailable", str(exc)), {}


# ---------------------------------------------------------------------------
# 7. Index health
# ---------------------------------------------------------------------------


def build_index_health(client: PgClient) -> tuple[str, dict]:
    lines: list[str] = []
    raw: dict = {}

    # Unused indexes
    try:
        rows = client.fetchall(Q_UNUSED_INDEXES)
        raw["unused_indexes"] = rows
        lines.append("### Unused / Rarely-Used Indexes (idx_scan < 10)\n")
        if rows:
            cols = ["schema", "table_name", "index_name", "index_size", "idx_scan"]
            lines.append(md_table(rows, cols))
        else:
            lines.append("*No unused indexes found.*")
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Unused index query unavailable", str(exc)))

    # High seq-scan tables
    try:
        rows = client.fetchall(Q_HIGH_SEQ_SCAN_TABLES)
        raw["high_seq_scan"] = rows
        lines.append("\n### High Sequential Scan Tables\n")
        if rows:
            cols = [
                "schema", "table_name", "seq_scan", "seq_tup_read",
                "idx_scan", "n_live_tup", "seq_scan_pct",
            ]
            lines.append(md_table(rows, cols))
        else:
            lines.append("*No high seq-scan tables detected.*")
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Seq-scan table query unavailable", str(exc)))

    return "\n".join(lines), raw


# ---------------------------------------------------------------------------
# 8. Query performance (pg_stat_statements)
# ---------------------------------------------------------------------------


def build_query_performance(client: PgClient, caps: PgCapabilities) -> tuple[str, dict]:
    if not caps.pss_ready:
        reasons: list[str] = []
        if not caps.pss_in_shared_preload:
            reasons.append("`pg_stat_statements` is not in `shared_preload_libraries`")
        if not caps.pss_extension_installed:
            reasons.append("Extension is not installed in this database")
        if not caps.pss_view_readable:
            reasons.append(f"View not readable: {caps.pss_view_error}")
        reason_str = "; ".join(reasons) or "unknown"
        return (
            f"> **pg_stat_statements is not ready** – {reason_str}.\n"
            "> Run `CREATE EXTENSION pg_stat_statements;` after adding it to "
            "`shared_preload_libraries` and restarting Postgres.",
            {"skipped": True, "reason": reason_str},
        )

    try:
        rows = client.fetchall(Q_PSS_TOP_QUERIES)
        if not rows:
            return "*No statements recorded yet.*", {}
        cols = [
            "queryid", "calls", "total_time_ms", "mean_time_ms",
            "stddev_ms", "rows", "pct_total", "query_snippet",
        ]
        return md_table(rows, cols), {"top_queries": rows}
    except Exception as exc:  # noqa: BLE001
        return err_block("pg_stat_statements query failed", str(exc)), {}


# ---------------------------------------------------------------------------
# pg_cron jobs (appended to capabilities or separate)
# ---------------------------------------------------------------------------


def build_cron_jobs(client: PgClient, caps: PgCapabilities) -> tuple[str, dict]:
    if not caps.pg_cron_ready:
        return "", {}

    try:
        rows = client.fetchall(Q_CRON_JOBS)
        if not rows:
            return "*No pg_cron jobs configured.*", {}
        cols = ["jobid", "schedule", "command", "database", "username", "active"]
        return md_table(rows, cols), {"cron_jobs": rows}
    except Exception as exc:  # noqa: BLE001
        return err_block("pg_cron jobs query failed", str(exc)), {}
