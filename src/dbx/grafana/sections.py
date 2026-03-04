"""Grafana telemetry section: Prometheus + Loki queries and Markdown rendering.

Edit the constants at the top of this file to customize which metrics / logs
are included in the telemetry section of the report.
"""

from __future__ import annotations

import textwrap
from datetime import datetime, timedelta, timezone
from typing import Any

from dbx.grafana.client import GrafanaClient
from dbx.report.markdown import err_block, md_table

# ---------------------------------------------------------------------------
# Configurable PromQL queries
# Each entry: (label, promql_expression, description)
# ---------------------------------------------------------------------------

PROM_QUERIES: list[tuple[str, str, str]] = [
    (
        "Postgres up",
        "pg_up",
        "1 = up, 0 = down",
    ),
    (
        "Total connections",
        "sum(pg_stat_activity_count)",
        "All backends including idle",
    ),
    (
        "Active connections",
        'sum(pg_stat_activity_count{state="active"})',
        "Actively executing queries",
    ),
    (
        "Idle-in-txn connections",
        'sum(pg_stat_activity_count{state="idle in transaction"})',
        "Connections holding an open transaction",
    ),
    (
        "DB size (bytes)",
        "sum(pg_database_size_bytes)",
        "Total database size reported by Postgres",
    ),
    (
        "Txn commit rate (TPS)",
        "sum(rate(pg_stat_database_xact_commit_total[5m]))",
        "Transactions committed per second (5m avg)",
    ),
    (
        "Txn rollback rate",
        "sum(rate(pg_stat_database_xact_rollback_total[5m]))",
        "Rollbacks per second (5m avg)",
    ),
    (
        "Cache hit ratio",
        (
            "sum(rate(pg_stat_database_blks_hit_total[5m])) / "
            "(sum(rate(pg_stat_database_blks_hit_total[5m])) + "
            "sum(rate(pg_stat_database_blks_read_total[5m])))"
        ),
        "Buffer cache hit ratio (target > 0.99)",
    ),
    (
        "Lock count",
        "sum(pg_locks_count)",
        "Total number of locks held",
    ),
    (
        "Checkpoint write time (ms/s)",
        "rate(pg_stat_bgwriter_checkpoint_write_time_total[5m]) / 1000",
        "Time spent writing checkpoints (ms per second)",
    ),
]

# ---------------------------------------------------------------------------
# Configurable LogQL queries
# Each entry: (label, logql_expression, description)
# ---------------------------------------------------------------------------

LOKI_QUERIES: list[tuple[str, str, str]] = [
    (
        "PostgreSQL ERRORs",
        '{container=~"pod_postgres.*"} |= "ERROR"',
        "Error-level log lines from the Postgres container",
    ),
    (
        "PostgreSQL FATALs",
        '{container=~"pod_postgres.*"} |= "FATAL"',
        "Fatal-level log lines from the Postgres container",
    ),
    (
        "auto_explain output",
        '{container=~"pod_postgres.*"} |= "auto_explain"',
        "Slow query plans logged by auto_explain",
    ),
    (
        "Checkpoint slowness",
        '{container=~"pod_postgres.*"} |= "checkpoint"',
        "Checkpoint-related log lines",
    ),
    (
        "Lock waits",
        '{container=~"pod_postgres.*"} |= "lock"',
        "Lock-related log lines",
    ),
]


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------


def parse_duration(s: str) -> timedelta:
    """Parse a duration string like '15m', '1h', '2d' into a timedelta."""
    import re

    m = re.match(r"^(\d+)(m|h|d)$", s.strip())
    if not m:
        raise ValueError(
            f"Invalid duration '{s}'. Use formats like: 15m, 1h, 2d"
        )
    val = int(m.group(1))
    unit = m.group(2)
    return timedelta(minutes=val if unit == "m" else 0,
                     hours=val if unit == "h" else 0,
                     days=val if unit == "d" else 0)


# ---------------------------------------------------------------------------
# Prometheus section
# ---------------------------------------------------------------------------


def _extract_prom_last_value(result: dict) -> str:
    """Pull the last scalar value from a query_range result."""
    try:
        data = result.get("data", {})
        results = data.get("result", [])
        if not results:
            return "no data"
        # Take the last value of the first series
        values = results[0].get("values", [])
        if not values:
            return "no data"
        last_val = values[-1][1]
        # Try to format as float
        f = float(last_val)
        if f == int(f):
            return str(int(f))
        return f"{f:.4f}"
    except Exception:  # noqa: BLE001
        return "parse error"


def build_prometheus_section(
    client: GrafanaClient,
    ds_id: int,
    start: float,
    end: float,
    step: str = "60s",
) -> str:
    rows: list[dict] = []
    errors: list[str] = []

    for label, query, description in PROM_QUERIES:
        try:
            result = client.query_prometheus(ds_id, query, start, end, step)
            value = _extract_prom_last_value(result)
        except Exception as exc:  # noqa: BLE001
            value = "error"
            errors.append(f"`{label}`: {exc}")
        rows.append({"Metric": label, "Latest value": value, "Description": description})

    lines: list[str] = [md_table(rows, ["Metric", "Latest value", "Description"])]
    if errors:
        lines.append("\n**Query errors:**")
        for e in errors:
            lines.append(f"- {e}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loki section
# ---------------------------------------------------------------------------


def _extract_loki_lines(result: dict, max_lines: int = 5) -> list[str]:
    """Extract the most recent log lines from a Loki query_range result."""
    try:
        data = result.get("data", {})
        streams = data.get("result", [])
        lines: list[str] = []
        for stream in streams:
            for _ts, line in stream.get("values", []):
                lines.append(line)
                if len(lines) >= max_lines:
                    return lines
        return lines
    except Exception:  # noqa: BLE001
        return []


def build_loki_section(
    client: GrafanaClient,
    ds_id: int,
    start: float,
    end: float,
) -> str:
    sections: list[str] = []

    for label, query, description in LOKI_QUERIES:
        try:
            result = client.query_loki(ds_id, query, start, end, limit=10)
            lines = _extract_loki_lines(result, max_lines=5)
        except Exception as exc:  # noqa: BLE001
            sections.append(
                f"**{label}** – {description}\n"
                + err_block("Loki query failed", str(exc))
            )
            continue

        if not lines:
            sections.append(f"**{label}** – {description}\n\n*No matching log lines in range.*\n")
        else:
            joined = "\n".join(textwrap.shorten(ln, width=200) for ln in lines)
            sections.append(
                f"**{label}** – {description}\n\n"
                f"```\n{joined}\n```\n"
            )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Top-level telemetry section
# ---------------------------------------------------------------------------


def build_telemetry_section(
    grafana_url: str | None,
    grafana_token: str | None,
    missing_vars: list[str],
    prom_ds_name: str | None,
    loki_ds_name: str | None,
    range_duration: str,
    fail_on_telemetry: bool,
) -> tuple[str, bool]:
    """Build the full Telemetry section.

    Returns (markdown, had_error).
    """
    lines: list[str] = []

    # Config-missing case
    if missing_vars:
        msg = (
            "Grafana telemetry is not configured. "
            f"Missing environment variables: {', '.join(f'`{v}`' for v in missing_vars)}.\n\n"
            "Set these variables and re-run `dbx report` to include Prometheus and Loki data."
        )
        lines.append(err_block("Telemetry skipped – missing configuration", msg))
        return "\n".join(lines), fail_on_telemetry

    assert grafana_url and grafana_token  # both present if missing_vars is empty

    # Parse time range
    try:
        delta = parse_duration(range_duration)
    except ValueError as exc:
        return err_block("Invalid range duration", str(exc)), True

    now = datetime.now(tz=timezone.utc)
    start_dt = now - delta
    start_ts = start_dt.timestamp()
    end_ts = now.timestamp()

    # Choose a reasonable step based on the range
    total_minutes = delta.total_seconds() / 60
    if total_minutes <= 30:
        step = "30s"
    elif total_minutes <= 120:
        step = "60s"
    elif total_minutes <= 1440:
        step = "5m"
    else:
        step = "1h"

    try:
        gf = GrafanaClient(grafana_url, grafana_token)

        # Discover datasources
        prom_ds = gf.find_datasource("prometheus", prom_ds_name)
        loki_ds = gf.find_datasource("loki", loki_ds_name)

        had_error = False

        # --- Prometheus ---
        lines.append("### Prometheus Metrics\n")
        if prom_ds is None:
            prom_err = "No Prometheus datasource found in Grafana."
            if prom_ds_name:
                prom_err += f" (Looked for name: `{prom_ds_name}`)"
            lines.append(err_block("Prometheus datasource not found", prom_err))
            had_error = True
        else:
            lines.append(
                f"*Datasource:* `{prom_ds['name']}` (id={prom_ds['id']}) &nbsp;|&nbsp; "
                f"*Range:* `{start_dt.strftime('%Y-%m-%d %H:%M')} → {now.strftime('%H:%M')} UTC`\n"
            )
            prom_md = build_prometheus_section(
                gf, prom_ds["id"], start_ts, end_ts, step
            )
            lines.append(prom_md)

        # --- Loki ---
        lines.append("\n### Loki Log Excerpts\n")
        if loki_ds is None:
            loki_err = "No Loki datasource found in Grafana."
            if loki_ds_name:
                loki_err += f" (Looked for name: `{loki_ds_name}`)"
            lines.append(err_block("Loki datasource not found", loki_err))
            had_error = True
        else:
            lines.append(
                f"*Datasource:* `{loki_ds['name']}` (id={loki_ds['id']}) &nbsp;|&nbsp; "
                f"*Range:* `{start_dt.strftime('%Y-%m-%d %H:%M')} → {now.strftime('%H:%M')} UTC`\n"
            )
            loki_md = build_loki_section(gf, loki_ds["id"], start_ts, end_ts)
            lines.append(loki_md)

        return "\n".join(lines), had_error and fail_on_telemetry

    except Exception as exc:  # noqa: BLE001
        lines.append(err_block("Grafana API error", str(exc)))
        return "\n".join(lines), fail_on_telemetry
