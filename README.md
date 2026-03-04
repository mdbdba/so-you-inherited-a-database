# so-you-inherited-a-database

A demo environment and inspection toolkit for Postgres databases you've just inherited.

Bluebox drives external workload against Postgres. This repo provides `dbx` — a CLI that
generates a Markdown report correlating Postgres internals with Grafana (Prometheus + Loki).

---

## Quick-start: demo environment

```bash
# Start the full stack (Postgres, Grafana, Prometheus, Loki, Vector)
docker compose up -d

# Check services are healthy
docker compose ps
```

Default service URLs:

| Service    | URL                     | Credentials          |
|------------|-------------------------|----------------------|
| Grafana    | http://localhost:3000   | admin / admin        |
| Prometheus | http://localhost:9090   |                      |
| Loki       | http://localhost:3100   |                      |
| Postgres   | localhost:5432          | postgres / postgres  |

---

## `dbx` – Inherited Postgres inspection toolkit

### Installation (uv)

```bash
# Install uv if you don't have it
curl -Lsf https://astral.sh/uv/install.sh | sh

# Install project dependencies
uv sync
```

### Configuration

Set environment variables (or create a `.env` file at the repo root):

```bash
# Required
export DBX_PG_DSN="postgresql://postgres:postgres@localhost:5432/bluebox"

# Grafana telemetry (expected – report degrades gracefully if missing)
export DBX_GRAFANA_URL="http://localhost:3000"
export DBX_GRAFANA_TOKEN="admin:admin"          # or a service-account token

# Optional: override datasource names (defaults to first match by type)
# export DBX_GRAFANA_PROM_DS_NAME="Prometheus"
# export DBX_GRAFANA_LOKI_DS_NAME="Loki"
```

### Generate a report

```bash
# Default: Markdown report at ./dbx-report.md, 15-minute telemetry window
uv run dbx report

# Custom output path and range
uv run dbx report --out /tmp/my-report.md --range 1h

# Markdown + JSON output
uv run dbx report --format md+json --out dbx-report.md

# Fail (exit 1) if Grafana is unreachable or misconfigured
uv run dbx report --fail-on-telemetry
```

### CLI reference

```
Usage: dbx report [OPTIONS]

  Generate a Markdown (and optional JSON) report for an inherited Postgres DB.

Options:
  --out PATH          Output file path  [default: ./dbx-report.md]
  --range DURATION    Grafana query range (e.g. 15m, 1h, 2d)  [default: 15m]
  --format FORMAT     md | json | md+json  [default: md]
  --fail-on-telemetry / --no-fail-on-telemetry
                      Exit non-zero if Grafana config is missing  [default: no-fail-on-telemetry]
  --help              Show this message and exit.
```

### Report sections

1. **Report Details** – timestamp, redacted DSN, report range, Postgres version
2. **Capabilities** – installed extensions table, readiness for pg_stat_statements / auto_explain / pg_cron
3. **Configuration Summary** – key settings with notes (`shared_buffers`, `work_mem`, etc.)
4. **Inventory** – DB size, top 10 tables/indexes by size, schema/table counts
5. **Operational Health** – connection usage, long-running transactions, blocked queries
6. **Vacuum & Bloat** – tables ranked by dead tuple ratio with last vacuum/analyze times
7. **Index Health** – unused indexes, high sequential-scan tables
8. **Query Performance** – top 20 queries by total time from pg_stat_statements (when ready)
9. **Telemetry Correlation** – Prometheus metric summary table + Loki log excerpts
10. **Findings & Next Actions** – top 5 risks and top 5 easy wins from the rules engine

---

## Development

### Run tests

```bash
uv run pytest -v
```

### Project layout

```
src/
  cmd/
    report.py           # report orchestration (entry-point for `dbx report`)
  dbx/
    cli.py              # Typer app, registers commands
    config.py           # pydantic settings (env vars)
    pg/
      client.py         # psycopg v3 connection wrapper
      queries.py        # all SQL constants (documented)
      inspect.py        # capability detection
      sections.py       # per-section data + Markdown generators
    grafana/
      client.py         # Grafana REST API wrapper
      sections.py       # PromQL / LogQL queries + Markdown rendering
    report/
      markdown.py       # ReportBuilder + formatting utilities
      findings.py       # rules engine
tests/
  test_config.py        # env-var parsing
  test_markdown.py      # table + report assembly
  test_capabilities.py  # capability detection + findings logic
```
