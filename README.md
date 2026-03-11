# so-you-inherited-a-database

> **Work in progress** – this project is under active development and is not ready for production use.

A demo environment and inspection toolkit for Postgres databases you've just inherited.

Bluebox drives an external workload against Postgres. This repo provides `dbx` — a CLI that
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
2. **Capabilities** – installed extensions with versions and update availability; preload status and readiness for `pg_stat_statements` / `auto_explain` / `pg_cron`; extension health table classifying each extension as Healthy, Warning, Degraded, Passive, or Unknown
3. **pg_cron Jobs** *(when pg_cron is active)* – 7-day run metrics (runs, failures, avg duration) per job; full SQL job definitions; recent failure details
4. **Configuration Summary** – key settings with context notes; Memory Effectiveness subsection with live buffer cache hit rates (table and index) and temp-file spill data since last stats reset
5. **Inventory** – DB size, schema/table counts; top 10 tables with row counts, index overhead, dead tuple ratio, and vacuum age; top 10 indexes with scan counts and callouts for unused large indexes
6. **Backup & Recovery Indicators** – WAL archiving configuration and `pg_stat_archiver` status; active streaming standbys; replication slots with retained WAL size; active backup agent connections
7. **Operational Health** – connection usage with idle-in-transaction duration, available headroom, and wait events breakdown; long-running transactions; blocked queries with blocker/waiter chains
8. **Vacuum & Bloat** – tables ranked by dead tuple ratio with last vacuum/analyze timestamps
9. **Index Health** – unused indexes (`idx_scan < 10`), high sequential-scan tables
10. **Query Performance** – top 15 queries by total execution time from `pg_stat_statements`; callouts for slow individual queries (mean > 1 s), high-variability plans (stddev > 2× mean), and queries spilling to temp files
11. **Telemetry Correlation** – Prometheus metric summary table and Loki log excerpts from Grafana
12. **Findings & Next Actions** – rules engine surfacing up to 5 risks and 5 easy wins from data collected across all sections

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
    report.py             # report orchestration (entry-point for `dbx report`)
  dbx/
    cli.py                # Typer app, registers commands
    config.py             # pydantic settings (env vars)
    pg/
      client.py           # psycopg v3 connection wrapper
      queries.py          # all SQL constants (documented)
      inspect.py          # capability detection
      extension_health.py # per-extension health probes (Active / Passive / Unknown)
      sections.py         # per-section data + Markdown generators
    grafana/
      client.py           # Grafana REST API wrapper
      sections.py         # PromQL / LogQL queries + Markdown rendering
    report/
      markdown.py         # ReportBuilder + formatting utilities
      findings.py         # rules engine (risks + easy wins)
tests/
  conftest.py                   # shared fixtures
  test_config.py                # env-var parsing
  test_markdown.py              # table + report assembly
  test_capabilities.py          # capability detection + findings logic
  test_backup_section.py        # backup section rendering + findings
  test_extension_health.py      # extension health probes + classification
  test_memory_effectiveness.py  # buffer hit rate + temp spill rendering
  test_pg_client.py             # PgClient wrapper
  test_queries.py               # SQL constant structure validation
```
