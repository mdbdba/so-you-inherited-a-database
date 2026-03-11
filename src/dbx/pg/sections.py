"""Generate per-section Markdown + structured data from a live Postgres connection.

Each ``build_*`` function returns a tuple of (markdown_string, raw_data_dict).
On failure the markdown contains an explicit error block and raw_data is empty.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dbx.pg.client import PgClient, dsn_for_database
from dbx.pg.inspect import PgCapabilities
from dbx.pg.queries import (
    Q_ARCHIVE_STATUS,
    Q_BACKUP_AGENT_CONNECTIONS,
    Q_BLOCKED_QUERIES,
    Q_BUFFER_HIT_RATE,
    Q_CONNECTION_STATS,
    Q_CRON_JOBS,
    Q_CRON_JOB_SUMMARY,
    Q_CRON_RECENT_FAILURES,
    Q_DB_SIZE,
    Q_HIGH_SEQ_SCAN_TABLES,
    Q_INSTANCE_DATABASES,
    Q_LONG_RUNNING_TRANSACTIONS,
    Q_PSS_TOP_QUERIES,
    Q_REPLICATION_SLOTS,
    Q_REPLICATION_STANDBYS,
    Q_SCHEMA_TABLE_COUNTS,
    Q_TEMP_FILE_STATS,
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


def build_capabilities(caps: PgCapabilities, ext_health=None) -> tuple[str, dict]:
    lines: list[str] = []

    # Extensions table
    if caps.extensions:
        rows = []
        for name, installed in sorted(caps.extensions.items()):
            available = caps.extensions_available.get(name, "")
            note = "Update available" if available and available != installed else ""
            rows.append({
                "Extension": name,
                "Installed": installed,
                "Available": available or "—",
                "": note,
            })
        lines.append("### Installed Extensions\n")
        lines.append(md_table(rows, ["Extension", "Installed", "Available", ""]))
        updatable = [
            (name, caps.extensions[name], caps.extensions_available.get(name, ""))
            for name in sorted(caps.extensions)
            if caps.extensions_available.get(name, "") not in ("", caps.extensions[name])
        ]
        if updatable:
            lines.append("\n> **Pending extension updates** — the PostgreSQL package on this server")
            lines.append("> ships newer versions of the following extensions. Run in each affected database:")
            lines.append("> ```sql")
            for name, _installed, _available in updatable:
                lines.append(f"> ALTER EXTENSION {name} UPDATE;")
            lines.append("> ```")
            lines.append("> These update the in-database objects to match the files already on disk.")
    else:
        err = caps.settings_errors.get("extensions", "query failed")
        lines.append("### Installed Extensions\n")
        lines.append(err_block("Could not read pg_extension", err))

    lines.append("")

    # --- Capability status table ---
    # Purpose: tell the reader whether each key capability is usable,
    # and what to do if it isn't. One row per capability; no implementation detail.

    def _pss_row() -> dict:
        if caps.pss_ready:
            track = caps.settings.get("pg_stat_statements.track", "")
            max_s = caps.settings.get("pg_stat_statements.max", "")
            note = f"Tracking `{track}` statements, max {max_s}"
        else:
            reasons: list[str] = []
            if not caps.pss_extension_installed:
                reasons.append("extension not installed — run `CREATE EXTENSION pg_stat_statements`")
            if caps.pss_extension_installed and not caps.pss_view_readable:
                reasons.append(f"view not readable: {caps.pss_view_error}")
            if not reasons:
                reasons.append("add to `shared_preload_libraries` and restart")
            note = "; ".join(reasons)
        return {
            "Capability": "pg_stat_statements",
            "Status": "Ready" if caps.pss_ready else "Not ready",
            "Preloaded": "Yes" if caps.pss_in_shared_preload else "No",
            "Version": caps.extensions.get("pg_stat_statements", "—"),
            "Notes": note,
        }

    def _auto_explain_row() -> dict:
        if caps.auto_explain_in_shared_preload:
            dur = caps.auto_explain_log_min_duration or "not set"
            fmt = caps.auto_explain_log_format or "not set"
            note = f"Logging plans >= {dur} in {fmt} format"
        else:
            note = "Add to `shared_preload_libraries` and restart to enable"
        return {
            "Capability": "auto_explain",
            "Status": "Loaded" if caps.auto_explain_in_shared_preload else "Not loaded",
            "Preloaded": "Yes" if caps.auto_explain_in_shared_preload else "No",
            "Version": "module",
            "Notes": note,
        }

    def _pg_cron_row() -> dict:
        if caps.pg_cron_ready:
            note = "Scheduler is active"
            if caps.pg_cron_database_name:
                note += f"; runs in database `{caps.pg_cron_database_name}`"
        elif caps.pg_cron_runs_elsewhere:
            note = (
                f"Scheduler runs in the `{caps.pg_cron_database_name}` database "
                f"(per `cron.database_name`); jobs are fetched from there"
            )
        else:
            reasons: list[str] = []
            if not caps.pg_cron_extension_installed and not caps.pg_cron_runs_elsewhere:
                reasons.append("extension not installed — run `CREATE EXTENSION pg_cron` in the cron database")
            if caps.pg_cron_extension_installed and not caps.pg_cron_job_readable:
                reasons.append(f"job table not readable: {caps.pg_cron_job_error}")
            if not reasons:
                reasons.append("add to `shared_preload_libraries` and restart")
            note = "; ".join(reasons)
        status = (
            "Ready" if caps.pg_cron_ready
            else "Running in `{}`".format(caps.pg_cron_database_name) if caps.pg_cron_runs_elsewhere
            else "Not ready"
        )
        version = caps.extensions.get("pg_cron", "—")
        return {
            "Capability": "pg_cron",
            "Status": status,
            "Preloaded": "Yes" if caps.pg_cron_in_shared_preload else "No",
            "Version": version,
            "Notes": note,
        }

    lines.append("### Capability Status\n")
    cols = ["Capability", "Status", "Preloaded", "Version", "Notes"]
    lines.append(md_table([_pss_row(), _auto_explain_row(), _pg_cron_row()], cols))

    # Unrecognized shared_preload_libraries entries
    _TRACKED_PRELOAD = {"pg_stat_statements", "auto_explain", "pg_cron"}
    spl_raw = caps.settings.get("shared_preload_libraries", "")
    spl_entries = {lib.strip() for lib in spl_raw.split(",") if lib.strip()}
    unrecognized = sorted(spl_entries - _TRACKED_PRELOAD)
    if unrecognized:
        names = ", ".join(f"`{e}`" for e in unrecognized)
        lines.append(
            f"\n> **Unrecognized `shared_preload_libraries` entries:** {names}  \n"
            "> These modules load at server startup but are not evaluated by this report. "
            "Verify each is intentional and functioning correctly."
        )

    # Extension health subsection
    if ext_health is not None:
        lines.append("\n### Extension Health\n")
        if ext_health:
            health_rows = [
                {
                    "Extension": h.name,
                    "Status": h.status,
                    "Notes": "; ".join(h.notes) if h.notes else "",
                }
                for h in ext_health
            ]
            lines.append(md_table(health_rows, ["Extension", "Status", "Notes"]))
        else:
            lines.append("*No extensions installed.*")

    data = {
        "pss_ready": caps.pss_ready,
        "auto_explain_ready": caps.auto_explain_in_shared_preload,
        "pg_cron_ready": caps.pg_cron_ready,
        "extensions": dict(caps.extensions),
        "extension_health": [h.as_dict() for h in ext_health] if ext_health is not None else [],
    }
    return "\n".join(lines), data


# ---------------------------------------------------------------------------
# 3. Configuration summary
# ---------------------------------------------------------------------------


def _build_memory_effectiveness(client: PgClient) -> tuple[str, dict]:
    """Query buffer hit rates and temp file spills; return (markdown, raw_data)."""
    rows: list[dict] = []
    raw: dict = {}

    def _hit_signal(pct: object) -> str:
        if pct is None:
            return "No data"
        f = float(pct)
        if f >= 99.0:
            return "Good"
        if f >= 95.0:
            return "OK"
        return "Investigate"

    # Buffer hit rates
    try:
        hit = client.fetchone(Q_BUFFER_HIT_RATE)
        if hit:
            tpct = hit.get("table_hit_pct")
            ipct = hit.get("index_hit_pct")
            raw["table_hit_pct"] = float(tpct) if tpct is not None else None
            raw["index_hit_pct"] = float(ipct) if ipct is not None else None
            rows.append({
                "Metric": "Table buffer hit rate",
                "Value": f"{tpct}%" if tpct is not None else "—",
                "Signal": _hit_signal(tpct),
            })
            rows.append({
                "Metric": "Index buffer hit rate",
                "Value": f"{ipct}%" if ipct is not None else "—",
                "Signal": _hit_signal(ipct),
            })
    except Exception as exc:  # noqa: BLE001
        rows.append({"Metric": "Buffer hit rates", "Value": "unavailable", "Signal": str(exc)})

    # Temp file spills
    stats_reset = None
    try:
        tmp = client.fetchone(Q_TEMP_FILE_STATS)
        if tmp:
            temp_files = tmp.get("temp_files") or 0
            temp_bytes = tmp.get("temp_bytes") or 0
            temp_pretty = tmp.get("temp_size_pretty", "0 bytes")
            stats_reset = tmp.get("stats_reset")
            raw["temp_files"] = temp_files
            raw["temp_bytes"] = temp_bytes
            raw["stats_reset"] = stats_reset
            rows.append({
                "Metric": "Temp file spills",
                "Value": "0" if temp_files == 0 else f"{temp_files:,} files / {temp_pretty}",
                "Signal": (
                    "None — work_mem adequate for observed queries"
                    if temp_files == 0
                    else "Some queries spill to disk"
                ),
            })
    except Exception as exc:  # noqa: BLE001
        rows.append({"Metric": "Temp file spills", "Value": "unavailable", "Signal": str(exc)})

    if not rows:
        return "", raw

    lines: list[str] = [md_table(rows, ["Metric", "Value", "Signal"])]

    # Stats reset footnote
    reset_str = ""
    if stats_reset is not None:
        try:
            age_secs = (datetime.now(tz=timezone.utc) - stats_reset).total_seconds()
            if age_secs < 3600:
                age_str = f"{int(age_secs / 60)}m ago"
            elif age_secs < 86400:
                age_str = f"{int(age_secs / 3600)}h ago"
            else:
                age_str = f"{int(age_secs / 86400)}d ago"
            reset_str = f"{stats_reset.strftime('%Y-%m-%d %H:%M UTC')} ({age_str})"
        except Exception:  # noqa: BLE001
            reset_str = str(stats_reset)

    note = (
        "\n> Stats accumulate since the last `pg_stat_reset()`"
        + (f" — last reset: {reset_str}" if reset_str else "")
        + ". A newly started or recently reset instance will show lower hit rates "
        "until the working set is warmed."
    )
    lines.append(note)

    return "\n".join(lines), raw


def build_config_summary(caps: PgCapabilities, client: PgClient | None = None) -> tuple[str, dict]:
    notes_map = {
        "shared_preload_libraries": "Full list loaded at server startup — tracked entries evaluated in Capabilities section",
        "shared_buffers": "Main Postgres buffer pool — see Memory Effectiveness below",
        "effective_cache_size": "Planner hint for OS + Postgres cache; not allocated — set to shared_buffers + expected OS page cache",
        "maintenance_work_mem": "Memory for VACUUM, CREATE INDEX, etc.",
        "work_mem": "Per-sort / per-hash memory (× connections × operations) — see Memory Effectiveness below",
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
        rows.append({
            "Setting": f"`{setting}`",
            "Value": f"`{value}`" if value else f"*(error: {error})*",
            "Note": note,
        })

    parts: list[str] = [md_table(rows, ["Setting", "Value", "Note"])]
    raw: dict = {"settings": dict(caps.settings)}

    if client is not None:
        mem_md, mem_data = _build_memory_effectiveness(client)
        if mem_md:
            parts.append("\n### Memory Effectiveness\n")
            parts.append(mem_md)
        raw["memory_effectiveness"] = mem_data

    return "\n".join(parts), raw


# ---------------------------------------------------------------------------
# 4. Inventory
# ---------------------------------------------------------------------------


def build_inventory(client: PgClient, current_db: str = "") -> tuple[str, dict]:
    lines: list[str] = []
    raw: dict = {}

    # Instance databases
    try:
        db_rows = client.fetchall(Q_INSTANCE_DATABASES)
        raw["instance_databases"] = db_rows
        lines.append("### Databases in This Instance\n")
        lines.append(md_table(db_rows, ["database_name", "size", "encoding", "collation"]))
        lines.append("")
    except Exception as exc:  # noqa: BLE001
        db_name = current_db or "this"
        lines.append(
            f"> This report focuses on the **`{db_name}`** database. "
            "There may be other databases running in this instance; "
            "the current role does not have permission to list them."
        )
        lines.append("")
        raw["instance_databases"] = []

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


def _fmt_duration(seconds: object) -> str:
    """Format a duration in seconds to a compact human-readable string."""
    if seconds is None:
        return "—"
    s = float(seconds)
    if s < 1.0:
        return f"{s * 1000:.0f} ms"
    if s < 60.0:
        return f"{s:.1f} s"
    m = int(s // 60)
    sec = s % 60
    return f"{m}m {sec:.0f}s"


def build_cron_jobs(
    client: PgClient, caps: PgCapabilities, pg_dsn: str | None = None
) -> tuple[str, dict]:
    """Fetch and render pg_cron job information in three parts:

    1. Summary table — schedule, runtime stats, last run (no command column).
    2. Job definitions — one block per job with full command text.
    3. Recent failures — if any, with error messages at full width.

    When pg_cron's scheduler database differs from the current connection
    (``caps.pg_cron_runs_elsewhere``), open a short-lived second connection to
    that database using *pg_dsn* with the database component swapped out.
    Falls back gracefully if that connection also fails.
    """
    if not caps.pg_cron_ready and not caps.pg_cron_runs_elsewhere:
        return "", {}

    def _fetch(c: PgClient) -> tuple[str, dict]:
        lines: list[str] = []
        raw: dict = {}

        # ------------------------------------------------------------------
        # 1. Summary table
        # ------------------------------------------------------------------
        summary_rows = c.fetchall(Q_CRON_JOB_SUMMARY)
        raw["cron_jobs"] = summary_rows

        if not summary_rows:
            return "*No pg_cron jobs configured.*", raw

        display = []
        for r in summary_rows:
            display.append({
                "Job": r["jobid"],
                "Schedule": f"`{r['schedule']}`",
                "Database": r["database"],
                "Active": "Yes" if r["active"] else "**No**",
                "Runs (7d)": r.get("runs_7d") or 0,
                "Failed": r.get("failed_7d") or 0,
                "Avg duration": _fmt_duration(r.get("avg_duration_sec")),
                "Last run": str(r["last_run"]) if r.get("last_run") else "—",
            })
        lines.append(md_table(
            display,
            ["Job", "Schedule", "Database", "Active", "Runs (7d)", "Failed", "Avg duration", "Last run"],
        ))

        # ------------------------------------------------------------------
        # 2. Job definitions (command at full width)
        # ------------------------------------------------------------------
        try:
            job_rows = c.fetchall(Q_CRON_JOBS)
            if job_rows:
                lines.append("\n### Job Definitions\n")
                for job in job_rows:
                    active_str = "active" if job["active"] else "**inactive**"
                    lines.append(
                        f"**Job {job['jobid']}** · `{job['schedule']}` · "
                        f"`{job['database']}` · `{job['username']}` · {active_str}\n"
                    )
                    cmd = (job.get("command") or "").strip()
                    lines.append(f"```sql\n{cmd}\n```\n")
        except Exception as exc:  # noqa: BLE001
            lines.append(err_block("Could not read pg_cron job definitions", str(exc)))

        # ------------------------------------------------------------------
        # 3. Recent failures (only if any exist)
        # ------------------------------------------------------------------
        try:
            failure_rows = c.fetchall(Q_CRON_RECENT_FAILURES)
            raw["cron_failures"] = failure_rows
            if failure_rows:
                lines.append("\n### Recent Failures\n")
                for f in failure_rows:
                    dur_str = _fmt_duration(f.get("duration_sec"))
                    ts = f.get("start_time", "")
                    lines.append(f"**Job {f['jobid']}** · {ts} · {dur_str}\n")
                    msg = (f.get("return_message") or "").strip()
                    if msg:
                        lines.append(f"```\n{msg}\n```\n")
        except Exception as exc:  # noqa: BLE001
            lines.append(err_block("Could not read pg_cron failure history", str(exc)))

        return "\n".join(lines), raw

    if caps.pg_cron_ready:
        try:
            return _fetch(client)
        except Exception as exc:  # noqa: BLE001
            return err_block("pg_cron jobs query failed", str(exc)), {}

    # pg_cron runs in a different database — open a second connection there.
    cron_db = caps.pg_cron_database_name
    if not pg_dsn or not cron_db:
        return err_block(
            "pg_cron jobs unavailable",
            f"Scheduler runs in database `{cron_db}` but no DSN was provided to connect.",
        ), {}

    cron_dsn = dsn_for_database(pg_dsn, cron_db)
    try:
        with PgClient(cron_dsn) as cron_client:
            md, data = _fetch(cron_client)
        note = f"*Jobs fetched from the `{cron_db}` database (pg_cron scheduler database).*\n\n"
        return note + md, data
    except Exception as exc:  # noqa: BLE001
        return err_block(
            f"Could not connect to pg_cron database `{cron_db}`", str(exc)
        ), {}


# ---------------------------------------------------------------------------
# Backup & recovery indicators
# ---------------------------------------------------------------------------

_HOURS_STALE = 25  # flag archive as stale if last success is older than this


def build_backup_section(client: PgClient, caps: PgCapabilities) -> tuple[str, dict]:
    """Probe WAL archiving, replication standbys, slots, and backup agents.

    Reports what Postgres can observe internally. Includes an explicit note
    about what cannot be detected (filesystem snapshots, cloud backups, etc.).
    """
    lines: list[str] = []
    raw: dict = {}

    # ------------------------------------------------------------------
    # 1. WAL archiving configuration + pg_stat_archiver
    # ------------------------------------------------------------------
    archive_mode = caps.settings.get("archive_mode", "")
    wal_level = caps.settings.get("wal_level", "")
    archive_command = caps.settings.get("archive_command", "")
    archive_library = caps.settings.get("archive_library", "")
    archiver_configured = archive_command not in ("", "(disabled)") or archive_library not in ("", "(disabled)")

    lines.append("### WAL Archiving\n")

    cfg_rows = [
        {"Setting": "`archive_mode`",   "Value": f"`{archive_mode}`"   if archive_mode   else "*(unknown)*"},
        {"Setting": "`wal_level`",       "Value": f"`{wal_level}`"       if wal_level       else "*(unknown)*"},
        {"Setting": "`archive_command`", "Value": f"`{archive_command}`" if archive_command else "*(not set)*"},
        {"Setting": "`archive_library`", "Value": f"`{archive_library}`" if archive_library else "*(not set)*"},
    ]
    lines.append(md_table(cfg_rows, ["Setting", "Value"]))
    lines.append("")

    if archive_mode != "on":
        lines.append(
            "> **WAL archiving is not enabled** (`archive_mode` is not `on`). "
            "WAL-based backup tools (pgBackRest, WAL-G, Barman) require archiving. "
            "Without it there is no continuous WAL stream to recover from.\n"
        )
        raw["archive_mode_on"] = False
    elif not archiver_configured:
        lines.append(
            "> **`archive_mode` is `on` but no `archive_command` or `archive_library` is set.** "
            "WAL segments will accumulate in `pg_wal/` and not be shipped anywhere.\n"
        )
        raw["archive_mode_on"] = True
        raw["archiver_configured"] = False
    else:
        raw["archive_mode_on"] = True
        raw["archiver_configured"] = True
        try:
            row = client.fetchone(Q_ARCHIVE_STATUS)
            raw["archive_status"] = dict(row) if row else {}
            if row:
                last_time = row.get("last_archived_time")
                secs = row.get("seconds_since_last_archive")
                failures = row.get("failed_count", 0) or 0
                archived = row.get("archived_count", 0) or 0

                age_str = (
                    f"{secs // 3600}h {(secs % 3600) // 60}m ago"
                    if secs is not None
                    else "never"
                )
                stale = secs is None or secs > _HOURS_STALE * 3600

                status_rows = [
                    {"Metric": "Archived WAL files", "Value": str(archived)},
                    {"Metric": "Last archived WAL", "Value": str(row.get("last_archived_wal") or "none")},
                    {"Metric": "Last archive time", "Value": f"{last_time} ({age_str})" if last_time else "never"},
                    {"Metric": "Failed archives", "Value": str(failures)},
                ]
                if row.get("last_failed_wal"):
                    status_rows.append({"Metric": "Last failed WAL", "Value": str(row["last_failed_wal"])})
                    status_rows.append({"Metric": "Last failure time", "Value": str(row["last_failed_time"])})

                lines.append(md_table(status_rows, ["Metric", "Value"]))
                lines.append("")

                if stale:
                    lines.append(
                        f"> **Archive appears stale** — last successful archive was {age_str}. "
                        "Investigate `archive_command` logs.\n"
                    )
                    raw["archive_stale"] = True
                if failures:
                    lines.append(
                        f"> **{failures} archive failure(s) recorded** since stats were last reset. "
                        "Check the Postgres log for `archive_command` errors.\n"
                    )
                    raw["archive_failures"] = failures
        except Exception as exc:  # noqa: BLE001
            lines.append(err_block("Could not read pg_stat_archiver", str(exc)))

    # ------------------------------------------------------------------
    # 2. Streaming standbys
    # ------------------------------------------------------------------
    lines.append("### Streaming Standbys\n")
    try:
        rows = client.fetchall(Q_REPLICATION_STANDBYS)
        raw["standbys"] = rows
        if rows:
            cols = ["application_name", "client_addr", "state", "sync_state",
                    "write_lag", "flush_lag", "replay_lag"]
            lines.append(md_table(rows, cols))
        else:
            lines.append("*No active streaming standbys connected.*\n")
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Could not read pg_stat_replication", str(exc)))

    # ------------------------------------------------------------------
    # 3. Replication slots
    # ------------------------------------------------------------------
    lines.append("\n### Replication Slots\n")
    try:
        rows = client.fetchall(Q_REPLICATION_SLOTS)
        raw["replication_slots"] = rows
        if rows:
            cols = ["slot_name", "slot_type", "database", "active", "retained_wal_size"]
            lines.append(md_table(rows, cols))
            inactive = [r for r in rows if not r.get("active")]
            if inactive:
                total_bytes = sum(
                    r.get("retained_wal_bytes") or 0 for r in inactive
                )
                lines.append(
                    f"\n> **{len(inactive)} inactive slot(s)** are retaining WAL "
                    f"(~{total_bytes // 1024 // 1024} MB total). "
                    "Inactive slots block WAL removal and can fill the disk. "
                    "Drop unused slots with `SELECT pg_drop_replication_slot('name')`.\n"
                )
        else:
            lines.append("*No replication slots defined.*\n")
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Could not read pg_replication_slots", str(exc)))

    # ------------------------------------------------------------------
    # 4. Active backup agents
    # ------------------------------------------------------------------
    lines.append("\n### Active Backup / Replication Agent Connections\n")
    try:
        rows = client.fetchall(Q_BACKUP_AGENT_CONNECTIONS)
        raw["backup_agents"] = rows
        if rows:
            cols = ["application_name", "client_addr", "state", "backend_start"]
            lines.append(md_table(rows, cols))
        else:
            lines.append(
                "*No known backup or replication agent connections detected "
                "at this moment.*\n"
            )
    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Could not query pg_stat_activity for backup agents", str(exc)))

    # ------------------------------------------------------------------
    # 5. What Postgres cannot tell us
    # ------------------------------------------------------------------
    lines.append("\n### What This Report Cannot Detect\n")
    lines.append(
        "Postgres has no built-in record of the following. "
        "Verify these through your backup tool's own logs or catalog:\n\n"
        "- **Filesystem / volume snapshots** (AWS EBS, ZFS, LVM snapshots)\n"
        "- **Cloud-managed backups** (RDS automated backups, Cloud SQL, Azure Database)\n"
        "- **Completed `pg_basebackup` runs** (no SQL-accessible history)\n"
        "- **pgBackRest / WAL-G / Barman catalog** (stored in their own repositories)\n"
    )

    return "\n".join(lines), raw
