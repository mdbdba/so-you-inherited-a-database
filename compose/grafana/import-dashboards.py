#!/usr/bin/env python3
"""Download and patch Grafana dashboards from grafana.com for local provisioning.

Downloads each dashboard by ID, rewrites datasource references to match the
datasources configured in this stack, and saves the JSON files to the
provisioning/dashboards/ directory so Grafana picks them up automatically.

Usage:
    python3 compose/grafana/import-dashboards.py

Re-run any time you want to pull updated dashboard versions from grafana.com.
"""

import json
import sys
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Dashboards to import:  (id, filename, human label)
# ---------------------------------------------------------------------------
DASHBOARDS = [
    (14114, "14114-postgres-exporter.json",  "PostgreSQL Exporter Quickstart"),
    (9628,  "9628-postgresql.json",           "PostgreSQL Database"),
    (22056, "22056-postgresql-v2.json",       "PostgreSQL Database Dashboard v2"),
]

# ---------------------------------------------------------------------------
# Datasource name as configured in provisioning/datasources/prometheus.yml.
# All ${DS_PROMETHEUS} template references and stale hardcoded UIDs are
# rewritten to this value so Grafana resolves the datasource by name.
# ---------------------------------------------------------------------------
PROM_DS_NAME = "Prometheus"

# Hardcoded Prometheus UID found in dashboard 22056 — replace with our name.
STALE_PROM_UID = "c820bb24-f91b-401d-84fd-80b996df41c4"

OUT_DIR = Path(__file__).parent / "provisioning" / "dashboards"


def download(dashboard_id: int) -> dict:
    url = f"https://grafana.com/api/dashboards/{dashboard_id}/revisions/latest/download"
    print(f"  Downloading {url} ...", end=" ", flush=True)
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
        data = json.loads(resp.read())
    print("ok")
    return data


def patch(data: dict) -> dict:
    """Rewrite datasource references so they resolve against our local stack."""
    text = json.dumps(data)

    # Replace __inputs template variable references
    text = text.replace("${DS_PROMETHEUS}", PROM_DS_NAME)

    # Replace any stale hardcoded Prometheus UIDs (found in 22056)
    text = text.replace(STALE_PROM_UID, PROM_DS_NAME)

    return json.loads(text)


def save(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Saved → {path.relative_to(Path(__file__).parent.parent.parent)}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    for dash_id, filename, label in DASHBOARDS:
        print(f"\n[{dash_id}] {label}")
        try:
            raw = download(dash_id)
            patched = patch(raw)
            save(patched, OUT_DIR / filename)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}")
            errors.append(f"{dash_id}: {exc}")

    print()
    if errors:
        print(f"Failed to import {len(errors)} dashboard(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("All dashboards imported successfully.")
        print("Restart (or reload) Grafana to pick up changes:")
        print("  docker compose restart grafana")


if __name__ == "__main__":
    main()
