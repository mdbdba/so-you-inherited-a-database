"""dbx CLI – entry-point for the inherited-Postgres inspection toolkit.

Register all sub-commands here. Each command delegates to its implementation
module in src/cmd/.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console


def _load_cmd_report():
    """Load src/cmd/report.py by file path to avoid collision with stdlib 'cmd' module."""
    _path = Path(__file__).parent.parent / "cmd" / "report.py"
    spec = importlib.util.spec_from_file_location("dbx._cmd_report", _path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod

app = typer.Typer(
    name="dbx",
    help="Inherited Postgres inspection toolkit.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console(stderr=True)


@app.callback()
def _main() -> None:
    """Inherited Postgres inspection toolkit."""


@app.command("report")
def report_cmd(
    out: Annotated[
        Path,
        typer.Option("--out", help="Output file path for the Markdown report."),
    ] = Path("./dbx-report.md"),
    range_duration: Annotated[
        str,
        typer.Option("--range", help="Grafana query range window (e.g. 15m, 1h, 2d)."),
    ] = "15m",
    fmt: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format: md | json | md+json",
            metavar="FORMAT",
        ),
    ] = "md",
    fail_on_telemetry: Annotated[
        bool,
        typer.Option(
            "--fail-on-telemetry/--no-fail-on-telemetry",
            help="Exit non-zero if Grafana config is missing or unreachable.",
        ),
    ] = False,
) -> None:
    """Generate a Markdown (and optional JSON) report for an inherited Postgres DB."""
    run_report = _load_cmd_report().run_report
    from dbx.config import Settings
    from pydantic import ValidationError

    if fmt not in ("md", "json", "md+json"):
        console.print(f"[red]Error:[/red] --format must be one of: md, json, md+json (got '{fmt}')")
        raise typer.Exit(code=1)

    try:
        settings = Settings()
    except ValidationError as exc:
        console.print("[red]Configuration error:[/red]")
        for err in exc.errors():
            field = ".".join(str(f) for f in err["loc"])
            console.print(f"  • {field}: {err['msg']}")
        console.print(
            "\n[yellow]Hint:[/yellow] Set [bold]DBX_PG_DSN[/bold] environment variable "
            "to a valid Postgres connection string."
        )
        raise typer.Exit(code=1) from exc

    exit_code = run_report(
        settings=settings,
        out_path=out,
        range_duration=range_duration,
        fmt=fmt,
        fail_on_telemetry=fail_on_telemetry,
        console=console,
    )
    raise typer.Exit(code=exit_code)


if __name__ == "__main__":
    app()
