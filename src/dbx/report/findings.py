"""Simple rules-based findings engine.

Analyses structured data collected during the report run and emits
"Top issues" (risks) and "Easy wins" recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass

from dbx.report.markdown import md_table


@dataclass
class Finding:
    title: str
    description: str
    priority: int  # lower = more urgent


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _analyze(data: dict) -> tuple[list[Finding], list[Finding]]:
    risks: list[Finding] = []
    wins: list[Finding] = []

    caps = data.get("capabilities", {})
    health = data.get("health", {})
    vacuum = data.get("vacuum", {})
    index = data.get("index", {})
    perf = data.get("perf", {})
    backup = data.get("backup", {})

    # --- pg_stat_statements not ready ---
    if not caps.get("pss_ready", True):
        risks.append(Finding(
            title="pg_stat_statements not ready",
            description=(
                "`pg_stat_statements` is not fully operational. "
                "Without it you cannot identify slow or expensive queries. "
                "Ensure it is in `shared_preload_libraries`, the extension is created, "
                "and the current role has `pg_read_all_stats`."
            ),
            priority=1,
        ))
    else:
        # Check for queries with high mean time
        top_queries = perf.get("top_queries", [])
        slow = [q for q in top_queries if (q.get("mean_time_ms") or 0) > 1000]
        if slow:
            risks.append(Finding(
                title=f"{len(slow)} query(ies) with mean execution time > 1 s",
                description=(
                    f"Found {len(slow)} statement(s) with mean_exec_time > 1000 ms. "
                    "Review these in the Query Performance section and consider "
                    "adding indexes, rewriting queries, or tuning work_mem."
                ),
                priority=3,
            ))

    # --- Long-running transactions ---
    long_xacts = health.get("long_xacts", [])
    if long_xacts:
        max_secs = max((x.get("xact_seconds", 0) or 0) for x in long_xacts)
        risks.append(Finding(
            title=f"{len(long_xacts)} long-running transaction(s) detected (max {max_secs}s)",
            description=(
                "Long-running transactions block VACUUM, cause table bloat, and can "
                "accumulate locks. Investigate `idle in transaction` sessions and set "
                "`idle_in_transaction_session_timeout`."
            ),
            priority=2,
        ))

    # --- Blocked queries ---
    blocked = health.get("blocked", [])
    if blocked:
        risks.append(Finding(
            title=f"{len(blocked)} blocked query(ies) detected",
            description=(
                "Lock contention is present. Check the Operational Health section "
                "for blocker/waiter chains. Consider advisory locks or shorter transactions."
            ),
            priority=2,
        ))

    # --- Backup risks ---
    if backup.get("archive_mode_on") is False:
        risks.append(Finding(
            title="WAL archiving is disabled",
            description=(
                "`archive_mode` is not `on`. WAL-based backup tools (pgBackRest, WAL-G, Barman) "
                "cannot function without it. Point-in-time recovery is not possible. "
                "Enable archiving and configure `archive_command` or `archive_library`."
            ),
            priority=1,
        ))
    elif backup.get("archive_stale"):
        risks.append(Finding(
            title="WAL archive appears stale (no recent successful archive)",
            description=(
                "The last successfully archived WAL segment is older than 25 hours. "
                "This may mean the backup pipeline is broken. "
                "Check `archive_command` logs and your backup tool's status."
            ),
            priority=1,
        ))
    if backup.get("archive_failures"):
        n = backup["archive_failures"]
        risks.append(Finding(
            title=f"{n} WAL archive failure(s) recorded",
            description=(
                f"{n} archive failure(s) are recorded in `pg_stat_archiver`. "
                "Failed archives mean WAL segments were not shipped to the backup destination. "
                "Investigate `archive_command` errors in the Postgres log."
            ),
            priority=2,
        ))
    inactive_slots = [
        s for s in backup.get("replication_slots", []) if not s.get("active")
    ]
    if inactive_slots:
        risks.append(Finding(
            title=f"{len(inactive_slots)} inactive replication slot(s) retaining WAL",
            description=(
                "Inactive replication slots prevent WAL removal and can fill the disk. "
                "Drop unused slots with `SELECT pg_drop_replication_slot('name')` "
                "after confirming they are no longer needed."
            ),
            priority=2,
        ))

    # --- High dead tuples ---
    vacuum_rows = vacuum.get("vacuum_bloat", [])
    bloated = [
        r for r in vacuum_rows
        if (r.get("dead_pct") or 0) > 20 and (r.get("n_dead_tup") or 0) > 10_000
    ]
    if bloated:
        risks.append(Finding(
            title=f"{len(bloated)} table(s) with > 20% dead tuple ratio",
            description=(
                "High bloat wastes I/O and slows queries. "
                "Run `VACUUM ANALYZE <table>` on the affected tables and tune "
                "`autovacuum_vacuum_scale_factor` for large tables."
            ),
            priority=3,
        ))

    # --- Connection saturation ---
    connections = health.get("connections", {})
    conn_pct = health.get("connection_pct", 0)
    if conn_pct and conn_pct > 80:
        risks.append(Finding(
            title=f"Connection usage at {conn_pct:.0f}% of max_connections",
            description=(
                "High connection usage risks connection exhaustion. "
                "Consider connection pooling (PgBouncer) or increasing `max_connections`."
            ),
            priority=2,
        ))

    # --- auto_explain not loaded ---
    if not caps.get("auto_explain_ready", True):
        wins.append(Finding(
            title="Enable auto_explain for slow-query plan capture",
            description=(
                "Add `auto_explain` to `shared_preload_libraries` and set "
                "`auto_explain.log_min_duration = '500ms'` to automatically log "
                "plans for slow queries. Requires a Postgres restart."
            ),
            priority=3,
        ))

    # --- Unused indexes ---
    unused = index.get("unused_indexes", [])
    if unused:
        total_bytes = sum(r.get("index_bytes", 0) or 0 for r in unused)
        size_mb = total_bytes / 1024 / 1024
        wins.append(Finding(
            title=f"Drop {len(unused)} unused index(es) (saving ~{size_mb:.0f} MB)",
            description=(
                "Unused indexes waste disk space and slow down writes. "
                "Review the Index Health section and drop indexes with idx_scan = 0 "
                "after confirming they are not needed."
            ),
            priority=2,
        ))

    # --- Tables never vacuumed ---
    never_vacuumed = [
        r for r in vacuum_rows
        if r.get("last_vacuum") is None and r.get("last_autovacuum") is None
        and (r.get("n_live_tup") or 0) > 1000
    ]
    if never_vacuumed:
        wins.append(Finding(
            title=f"{len(never_vacuumed)} table(s) have never been vacuumed",
            description=(
                "These tables have live rows but no vacuum history. "
                "Run `VACUUM ANALYZE` and ensure `autovacuum` is enabled."
            ),
            priority=3,
        ))

    # --- High seq-scan tables ---
    seq_scan_rows = index.get("high_seq_scan", [])
    high_seq = [
        r for r in seq_scan_rows
        if (r.get("seq_scan_pct") or 0) > 90 and (r.get("n_live_tup") or 0) > 10_000
    ]
    if high_seq:
        wins.append(Finding(
            title=f"{len(high_seq)} large table(s) relying mostly on sequential scans",
            description=(
                "Tables with > 90% sequential scans and > 10k rows may benefit "
                "from additional indexes. Review query patterns and consider "
                "`EXPLAIN ANALYZE` on the most common queries."
            ),
            priority=3,
        ))

    # --- Memory effectiveness ---
    mem = data.get("config", {}).get("memory_effectiveness", {})
    table_hit_pct = mem.get("table_hit_pct")
    if table_hit_pct is not None and float(table_hit_pct) < 95.0:
        risks.append(Finding(
            title=f"Buffer cache hit rate low ({table_hit_pct}%) — shared_buffers may be undersized",
            description=(
                f"Table buffer hit rate is {table_hit_pct}%, below the 95% threshold. "
                "Frequent cache misses mean Postgres is reading blocks from disk rather than "
                "memory. Consider increasing `shared_buffers` if the host has available RAM. "
                "Check the Memory Effectiveness table in Configuration Summary for details."
            ),
            priority=2,
        ))

    temp_bytes = mem.get("temp_bytes", 0) or 0
    temp_files = mem.get("temp_files", 0) or 0
    if temp_bytes > 0:
        wins.append(Finding(
            title=f"Temp file spills detected ({temp_files:,} files) — review work_mem",
            description=(
                f"Postgres spilled {temp_files:,} sort or hash operations to disk. "
                "Increasing `work_mem` may reduce spills, but it applies per-operation and "
                "multiplies across concurrent connections — raise it carefully. "
                "Use `pg_stat_statements.temp_blks_written` to identify the specific queries "
                "driving the most spill activity."
            ),
            priority=3,
        ))

    # --- Extension health findings ---
    ext_health = caps.get("extension_health", [])

    pss_entry = next((h for h in ext_health if h.get("name") == "pg_stat_statements"), None)
    if pss_entry and pss_entry.get("status") == "Warning":
        notes = "; ".join(pss_entry.get("notes", []))
        risks.append(Finding(
            title="pg_stat_statements evicting entries — query history is incomplete",
            description=(
                f"pg_stat_statements has evicted query entries ({notes}). "
                "Increase `pg_stat_statements.max` to retain a fuller query history."
            ),
            priority=2,
        ))

    cron_entry = next((h for h in ext_health if h.get("name") == "pg_cron"), None)
    if cron_entry and cron_entry.get("status") == "Warning":
        notes = "; ".join(cron_entry.get("notes", []))
        risks.append(Finding(
            title="pg_cron job failures detected",
            description=(
                f"pg_cron reported failed job runs ({notes}). "
                "Review `cron.job_run_details` for error messages."
            ),
            priority=2,
        ))

    degraded = [h for h in ext_health if h.get("status") == "Degraded"]
    if degraded:
        names = ", ".join(h["name"] for h in degraded)
        risks.append(Finding(
            title=f"{len(degraded)} extension(s) degraded: {names}",
            description=(
                "One or more extensions are installed but not functioning correctly. "
                "Check the Extension Health table in the Capabilities section for details."
            ),
            priority=2,
        ))

    unknown = [h for h in ext_health if h.get("status") == "Unknown"]
    if unknown:
        names = ", ".join(h["name"] for h in unknown)
        wins.append(Finding(
            title=f"{len(unknown)} unknown extension(s) need manual review: {names}",
            description=(
                "These extensions have no automated health check. "
                "Verify they are intentional and functioning as expected."
            ),
            priority=3,
        ))

    # Sort by priority
    risks.sort(key=lambda f: f.priority)
    wins.sort(key=lambda f: f.priority)

    return risks[:5], wins[:5]


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def build_findings_section(data: dict) -> tuple[str, dict]:
    risks, wins = _analyze(data)

    lines: list[str] = []

    lines.append("### Top Issues (Risk)\n")
    if risks:
        for i, f in enumerate(risks, 1):
            lines.append(f"**{i}. {f.title}**\n\n{f.description}\n")
    else:
        lines.append("*No critical issues detected.*\n")

    lines.append("### Easy Wins\n")
    if wins:
        for i, f in enumerate(wins, 1):
            lines.append(f"**{i}. {f.title}**\n\n{f.description}\n")
    else:
        lines.append("*No easy wins identified – the database looks healthy!*\n")

    return "\n".join(lines), {"risks": len(risks), "wins": len(wins)}
