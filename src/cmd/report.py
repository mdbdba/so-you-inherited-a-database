"""Report command orchestration.

This module is the single entry-point for running ``dbx report``. It:
1. Connects to Postgres and detects capabilities.
2. Gathers data for each report section.
3. Queries Grafana (Prometheus + Loki) for telemetry correlation.
4. Runs the findings engine.
5. Assembles everything into a Markdown (and optional JSON) report.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

if TYPE_CHECKING:
    from dbx.config import Settings


def run_report(
    settings: "Settings",
    out_path: Path,
    range_duration: str,
    fmt: str,
    fail_on_telemetry: bool,
    console: Console | None = None,
) -> int:
    """Build and write the report. Returns an exit code (0 = success)."""
    if console is None:
        console = Console(stderr=True)

    # Lazy imports – keep CLI startup fast.
    from dbx.grafana.sections import build_telemetry_section
    from dbx.pg.client import PgClient
    from dbx.pg.inspect import detect_capabilities
    from dbx.pg.sections import (
        build_capabilities,
        build_config_summary,
        build_cron_jobs,
        build_header,
        build_index_health,
        build_inventory,
        build_operational_health,
        build_query_performance,
        build_vacuum_bloat,
    )
    from dbx.report.findings import build_findings_section
    from dbx.report.markdown import ReportBuilder

    exit_code = 0
    raw_data: dict = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:

        # ------------------------------------------------------------------
        # Postgres connection
        # ------------------------------------------------------------------
        task = progress.add_task("Connecting to Postgres…", total=None)
        try:
            pg = PgClient(settings.pg_dsn)
            pg.__enter__()
        except Exception as exc:  # noqa: BLE001
            progress.stop()
            console.print(f"[red]Cannot connect to Postgres:[/red] {exc}")
            console.print(
                f"[yellow]DSN (redacted):[/yellow] {settings.redacted_pg_dsn()}"
            )
            return 1

        progress.update(task, description="Detecting capabilities…")

        try:
            caps = detect_capabilities(pg)
        except Exception as exc:  # noqa: BLE001
            progress.stop()
            console.print(f"[red]Capability detection failed:[/red] {exc}")
            pg.__exit__(None, None, None)
            return 1

        builder = ReportBuilder()

        # ------------------------------------------------------------------
        # Section 1: Header
        # ------------------------------------------------------------------
        # Add server_version to caps.settings via SHOW if possible
        try:
            caps.settings["server_version"] = pg.show("server_version")
        except Exception:  # noqa: BLE001
            pass

        header_md = build_header(settings, range_duration, caps)
        builder.add("Report Details", header_md)

        # ------------------------------------------------------------------
        # Section 2: Capabilities
        # ------------------------------------------------------------------
        progress.update(task, description="Capabilities…")
        try:
            caps_md, caps_data = build_capabilities(caps)
            raw_data["capabilities"] = caps_data
        except Exception as exc:  # noqa: BLE001
            caps_md = f"> **Error building capabilities section:** {exc}"
            raw_data["capabilities"] = {}
        builder.add("Capabilities", caps_md)

        # pg_cron jobs (appended within capabilities)
        if caps.pg_cron_ready:
            try:
                cron_md, cron_data = build_cron_jobs(pg, caps)
                if cron_md:
                    builder.add("pg_cron Jobs", cron_md)
            except Exception:  # noqa: BLE001
                pass

        # ------------------------------------------------------------------
        # Section 3: Configuration
        # ------------------------------------------------------------------
        progress.update(task, description="Configuration…")
        try:
            cfg_md, cfg_data = build_config_summary(caps)
            raw_data["config"] = cfg_data
        except Exception as exc:  # noqa: BLE001
            cfg_md = f"> **Error:** {exc}"
        builder.add("Configuration Summary", cfg_md)

        # ------------------------------------------------------------------
        # Section 4: Inventory
        # ------------------------------------------------------------------
        progress.update(task, description="Inventory…")
        try:
            inv_md, inv_data = build_inventory(pg)
            raw_data["inventory"] = inv_data
        except Exception as exc:  # noqa: BLE001
            inv_md = f"> **Error:** {exc}"
            raw_data["inventory"] = {}
        builder.add("Inventory", inv_md)

        # ------------------------------------------------------------------
        # Section 5: Operational health
        # ------------------------------------------------------------------
        progress.update(task, description="Operational health…")
        try:
            health_md, health_data = build_operational_health(pg)
            raw_data["health"] = health_data
        except Exception as exc:  # noqa: BLE001
            health_md = f"> **Error:** {exc}"
            raw_data["health"] = {}
        builder.add("Operational Health", health_md)

        # ------------------------------------------------------------------
        # Section 6: Vacuum / bloat
        # ------------------------------------------------------------------
        progress.update(task, description="Vacuum / bloat…")
        try:
            vac_md, vac_data = build_vacuum_bloat(pg)
            raw_data["vacuum"] = vac_data
        except Exception as exc:  # noqa: BLE001
            vac_md = f"> **Error:** {exc}"
            raw_data["vacuum"] = {}
        builder.add("Vacuum & Bloat Indicators", vac_md)

        # ------------------------------------------------------------------
        # Section 7: Index health
        # ------------------------------------------------------------------
        progress.update(task, description="Index health…")
        try:
            idx_md, idx_data = build_index_health(pg)
            raw_data["index"] = idx_data
        except Exception as exc:  # noqa: BLE001
            idx_md = f"> **Error:** {exc}"
            raw_data["index"] = {}
        builder.add("Index Health", idx_md)

        # ------------------------------------------------------------------
        # Section 8: Query performance
        # ------------------------------------------------------------------
        progress.update(task, description="Query performance…")
        try:
            qp_md, qp_data = build_query_performance(pg, caps)
            raw_data["perf"] = qp_data
        except Exception as exc:  # noqa: BLE001
            qp_md = f"> **Error:** {exc}"
            raw_data["perf"] = {}
        builder.add("Query Performance (pg_stat_statements)", qp_md)

        # Close Postgres connection before making Grafana requests.
        pg.__exit__(None, None, None)

        # ------------------------------------------------------------------
        # Section 9: Telemetry (Grafana)
        # ------------------------------------------------------------------
        progress.update(task, description="Telemetry (Grafana)…")
        try:
            tel_md, tel_fail = build_telemetry_section(
                grafana_url=settings.grafana_url,
                grafana_token=settings.grafana_token,
                missing_vars=settings.grafana_missing_vars,
                prom_ds_name=settings.grafana_prom_ds_name,
                loki_ds_name=settings.grafana_loki_ds_name,
                range_duration=range_duration,
                fail_on_telemetry=fail_on_telemetry,
            )
            if tel_fail:
                exit_code = 1
        except Exception as exc:  # noqa: BLE001
            tel_md = f"> **Telemetry error:** {exc}"
            if fail_on_telemetry:
                exit_code = 1
        builder.add("Telemetry Correlation (Grafana)", tel_md)

        # ------------------------------------------------------------------
        # Section 10: Findings
        # ------------------------------------------------------------------
        progress.update(task, description="Findings…")
        try:
            findings_md, _ = build_findings_section(raw_data)
        except Exception as exc:  # noqa: BLE001
            findings_md = f"> **Error building findings:** {exc}"
        builder.add("Findings & Next Actions", findings_md)

        progress.update(task, description="Writing report…")

    # ------------------------------------------------------------------
    # Write output
    # ------------------------------------------------------------------
    report_md = builder.build()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt in ("md", "md+json"):
        out_path.write_text(report_md, encoding="utf-8")
        console.print(f"[green]Report written:[/green] {out_path}")

    if fmt in ("json", "md+json"):
        json_path = out_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(
                {
                    "report_md": report_md,
                    "data": _make_serialisable(raw_data),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        console.print(f"[green]JSON written:[/green]  {json_path}")

    return exit_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_serialisable(obj: object) -> object:
    """Recursively convert non-JSON-serialisable values to strings."""
    if isinstance(obj, dict):
        return {k: _make_serialisable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serialisable(v) for v in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)
