"""Extension health evaluation registry.

For every extension in pg_extension, evaluate health and return status.
Extensions fall into three categories:
  - Active  — do ongoing work, can fail silently → run a health probe
  - Passive — data types, index methods, utility functions → no health check
  - Unknown — not in either set → flag for manual review
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from dbx.pg.client import PgClient
    from dbx.pg.inspect import PgCapabilities

from dbx.pg.queries import (
    Q_CRON_JOB_STATS,
    Q_DBLINK_FUNCTION_EXISTS,
    Q_FOREIGN_SERVER_COUNT,
    Q_PGVECTOR_PROBE,
    Q_POSTGIS_VERSION,
    Q_PSS_INFO,
)


@dataclass
class ExtensionHealth:
    name: str
    status: str  # "Healthy" | "Warning" | "Degraded" | "Passive" | "Unknown"
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "notes": list(self.notes)}


# ---------------------------------------------------------------------------
# Passive extensions — no ongoing health check needed
# ---------------------------------------------------------------------------

PASSIVE_EXTENSIONS: set[str] = {
    "plpgsql", "plpython3u", "plperl", "pltcl", "plv8",
    "citext", "hstore", "ltree", "isn", "cube", "seg",
    "earthdistance", "intarray", "pgcrypto", "uuid-ossp",
    "tablefunc", "fuzzystrmatch", "unaccent", "pg_trgm",
    "dict_int", "dict_xsyn", "btree_gin", "btree_gist",
    "bloom", "rum", "amcheck", "pg_buffercache", "pg_visibility",
    "pageinspect", "pg_freespacemap", "pg_prewarm", "pg_repack",
    "pg_squeeze", "hypopg", "file_fdw",
    "address_standardizer", "address_standardizer_data_us",
}


# ---------------------------------------------------------------------------
# Active extension check functions
# ---------------------------------------------------------------------------


def _pg_major_version(caps: "PgCapabilities") -> int:
    sv = caps.settings.get("server_version", "")
    try:
        return int(sv.split(".")[0])
    except (ValueError, IndexError):
        return 0


def _check_pg_stat_statements(
    client: "PgClient", caps: "PgCapabilities"
) -> ExtensionHealth:
    major = _pg_major_version(caps)
    if major >= 14:
        row = client.fetchone(Q_PSS_INFO)
        dealloc = (row.get("dealloc", 0) or 0) if row else 0
        if dealloc > 0:
            return ExtensionHealth(
                name="pg_stat_statements",
                status="Warning",
                notes=[f"{dealloc:,} evictions; query history is incomplete"],
            )
        return ExtensionHealth(name="pg_stat_statements", status="Healthy")
    # PG13 or unknown — fall back to pss_ready flag
    if caps.pss_ready:
        return ExtensionHealth(name="pg_stat_statements", status="Healthy")
    return ExtensionHealth(
        name="pg_stat_statements",
        status="Warning",
        notes=["pg_stat_statements not fully operational"],
    )


def _check_pg_cron(client: "PgClient", caps: "PgCapabilities") -> ExtensionHealth:
    row = client.fetchone(Q_CRON_JOB_STATS)
    total = (row.get("total_runs", 0) or 0) if row else 0
    failed = (row.get("failed_runs", 0) or 0) if row else 0
    if failed > 0:
        return ExtensionHealth(
            name="pg_cron",
            status="Warning",
            notes=[f"{failed} failed run(s) in the last 24 hours"],
        )
    if total == 0:
        return ExtensionHealth(
            name="pg_cron",
            status="Healthy",
            notes=["No job runs in the last 24 hours"],
        )
    return ExtensionHealth(name="pg_cron", status="Healthy")


def _check_postgres_fdw(client: "PgClient", caps: "PgCapabilities") -> ExtensionHealth:
    row = client.fetchone(Q_FOREIGN_SERVER_COUNT)
    count = (row.get("server_count", 0) or 0) if row else 0
    if count == 0:
        return ExtensionHealth(
            name="postgres_fdw",
            status="Warning",
            notes=["installed but not configured"],
        )
    return ExtensionHealth(name="postgres_fdw", status="Healthy")


def _check_postgis(client: "PgClient", caps: "PgCapabilities") -> ExtensionHealth:
    ok, err = client.probe(Q_POSTGIS_VERSION)
    if not ok:
        return ExtensionHealth(
            name="postgis",
            status="Degraded",
            notes=[f"PostGIS_Version() failed: {err}"],
        )
    row = client.fetchone(Q_POSTGIS_VERSION)
    version = (row.get("version", "") or "") if row else ""
    notes = [f"version: {version}"] if version else []
    return ExtensionHealth(name="postgis", status="Healthy", notes=notes)


def _check_vector(client: "PgClient", caps: "PgCapabilities") -> ExtensionHealth:
    ok, err = client.probe(Q_PGVECTOR_PROBE)
    if not ok:
        return ExtensionHealth(
            name="vector",
            status="Degraded",
            notes=[f"vector type probe failed: {err}"],
        )
    return ExtensionHealth(name="vector", status="Healthy")


def _check_dblink(client: "PgClient", caps: "PgCapabilities") -> ExtensionHealth:
    row = client.fetchone(Q_DBLINK_FUNCTION_EXISTS)
    fn_count = (row.get("fn_count", 0) or 0) if row else 0
    if fn_count == 0:
        return ExtensionHealth(
            name="dblink",
            status="Degraded",
            notes=["dblink function not found"],
        )
    return ExtensionHealth(name="dblink", status="Healthy")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ACTIVE_EXTENSIONS: dict[str, Callable] = {
    "pg_stat_statements": _check_pg_stat_statements,
    "pg_cron": _check_pg_cron,
    "postgres_fdw": _check_postgres_fdw,
    "postgis": _check_postgis,
    "vector": _check_vector,
    "dblink": _check_dblink,
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def check_all_extensions(
    client: "PgClient",
    caps: "PgCapabilities",
) -> list[ExtensionHealth]:
    """Evaluate health of every installed extension.

    Returns results sorted alphabetically by extension name.
    """
    results: list[ExtensionHealth] = []

    for name in sorted(caps.extensions):
        # Special case: pg_cron scheduler lives in another database
        if name == "pg_cron" and caps.pg_cron_runs_elsewhere:
            results.append(ExtensionHealth(
                name=name,
                status="Passive",
                notes=["Scheduler runs in another database"],
            ))
            continue

        if name in ACTIVE_EXTENSIONS:
            try:
                results.append(ACTIVE_EXTENSIONS[name](client, caps))
            except Exception as exc:  # noqa: BLE001
                results.append(ExtensionHealth(
                    name=name,
                    status="Warning",
                    notes=[f"Health check failed: {exc}"],
                ))
        elif name in PASSIVE_EXTENSIONS:
            results.append(ExtensionHealth(
                name=name,
                status="Passive",
                notes=["No ongoing health check needed"],
            ))
        else:
            results.append(ExtensionHealth(
                name=name,
                status="Unknown",
                notes=["No health check available — verify manually"],
            ))

    return results
