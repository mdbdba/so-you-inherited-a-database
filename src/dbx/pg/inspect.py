"""Postgres capability detection.

Reads server settings and extension inventory, then determines the readiness
state of pg_stat_statements, auto_explain, and pg_cron.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dbx.pg.client import PgClient
from dbx.pg.queries import (
    Q_CRON_PROBE,
    Q_EXTENSIONS,
    Q_PSS_PROBE,
)

# ---------------------------------------------------------------------------
# Settings we read via SHOW
# ---------------------------------------------------------------------------

SHOW_SETTINGS: list[str] = [
    "shared_preload_libraries",
    "shared_buffers",
    "effective_cache_size",
    "maintenance_work_mem",
    "work_mem",
    "max_parallel_workers_per_gather",
    "auto_explain.log_min_duration",
    "auto_explain.log_format",
    "pg_stat_statements.max",
    "pg_stat_statements.track",
    "cron.database_name",
    # Backup / archiving
    "archive_mode",
    "wal_level",
    "archive_command",
    "archive_library",   # PG15+ alternative to archive_command
]


# ---------------------------------------------------------------------------
# Capability data-class
# ---------------------------------------------------------------------------


@dataclass
class PgCapabilities:
    """Snapshot of detected Postgres capabilities."""

    settings: dict[str, str] = field(default_factory=dict)
    settings_errors: dict[str, str] = field(default_factory=dict)
    extensions: dict[str, str] = field(default_factory=dict)           # name → installed version
    extensions_available: dict[str, str] = field(default_factory=dict)  # name → latest available version

    # pg_stat_statements
    pss_in_shared_preload: bool = False
    pss_extension_installed: bool = False
    pss_view_readable: bool = False
    pss_view_error: str = ""
    pss_ready: bool = False

    # auto_explain (no view to probe – detected via settings only)
    auto_explain_in_shared_preload: bool = False
    auto_explain_log_min_duration: str = ""
    auto_explain_log_format: str = ""

    # pg_cron
    pg_cron_in_shared_preload: bool = False
    pg_cron_extension_installed: bool = False
    pg_cron_job_readable: bool = False
    pg_cron_job_error: str = ""
    pg_cron_database_name: str = ""  # value of cron.database_name setting
    pg_cron_ready: bool = False
    # True when pg_cron is loaded and its scheduler database differs from the
    # current connection database — the canonical "cron lives in postgres,
    # jobs run against bluebox" pattern.
    pg_cron_runs_elsewhere: bool = False

    current_database: str = ""  # result of SELECT current_database()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_capabilities(client: PgClient) -> PgCapabilities:
    """Probe the connected Postgres server and return a :class:`PgCapabilities`."""
    caps = PgCapabilities()

    # 1. Read all SHOW settings.
    for setting in SHOW_SETTINGS:
        try:
            caps.settings[setting] = client.show(setting)
        except Exception as exc:  # noqa: BLE001
            caps.settings_errors[setting] = str(exc)
            caps.settings[setting] = ""

    # 2. Parse shared_preload_libraries.
    spl_raw = caps.settings.get("shared_preload_libraries", "")
    spl = {lib.strip() for lib in spl_raw.split(",") if lib.strip()}

    caps.pss_in_shared_preload = "pg_stat_statements" in spl
    caps.auto_explain_in_shared_preload = "auto_explain" in spl
    caps.pg_cron_in_shared_preload = "pg_cron" in spl

    # 3. auto_explain convenience fields.
    caps.auto_explain_log_min_duration = caps.settings.get(
        "auto_explain.log_min_duration", ""
    )
    caps.auto_explain_log_format = caps.settings.get("auto_explain.log_format", "")
    caps.pg_cron_database_name = caps.settings.get("cron.database_name", "")

    # 4. Installed extensions.
    try:
        rows = client.fetchall(Q_EXTENSIONS)
        caps.extensions = {r["extname"]: r["installed_version"] for r in rows}
        caps.extensions_available = {r["extname"]: r["available_version"] or "" for r in rows}
    except Exception as exc:  # noqa: BLE001
        caps.extensions = {}
        caps.extensions_available = {}
        caps.settings_errors["extensions"] = str(exc)

    caps.pss_extension_installed = "pg_stat_statements" in caps.extensions
    caps.pg_cron_extension_installed = "pg_cron" in caps.extensions

    # 5. pg_stat_statements view probe.
    if caps.pss_extension_installed:
        ok, err = client.probe(Q_PSS_PROBE)
        caps.pss_view_readable = ok
        caps.pss_view_error = err
    caps.pss_ready = (
        caps.pss_in_shared_preload
        and caps.pss_extension_installed
        and caps.pss_view_readable
    )

    # 6. Current database name (needed to detect cross-database cron setup).
    try:
        row = client.fetchone("SELECT current_database() AS db")
        caps.current_database = row["db"] if row else ""
    except Exception:  # noqa: BLE001
        caps.current_database = ""

    # 7. pg_cron job table probe.
    if caps.pg_cron_extension_installed:
        ok, err = client.probe(Q_CRON_PROBE)
        caps.pg_cron_job_readable = ok
        caps.pg_cron_job_error = err
    caps.pg_cron_ready = (
        caps.pg_cron_in_shared_preload
        and caps.pg_cron_extension_installed
        and caps.pg_cron_job_readable
    )

    # 8. Detect the common pattern where pg_cron is loaded server-wide but its
    #    scheduler database (cron.database_name) differs from the current DB.
    #    In this case the extension is intentionally absent here — the jobs are
    #    visible from the cron database, not this one.
    caps.pg_cron_runs_elsewhere = (
        caps.pg_cron_in_shared_preload
        and not caps.pg_cron_extension_installed
        and bool(caps.pg_cron_database_name)
        and caps.pg_cron_database_name != caps.current_database
    )

    return caps
