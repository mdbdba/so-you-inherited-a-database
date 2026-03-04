"""Grafana REST API client.

Authenticates with a service-account token (or admin:password basic-auth).
Datasource discovery and proxy-based Prometheus / Loki query support.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx


class GrafanaClient:
    """Thin httpx wrapper for the Grafana HTTP API."""

    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        # Support both "glsa_..." API tokens and "admin:password" basic-auth.
        if ":" in token and not token.startswith("glsa_"):
            encoded = base64.b64encode(token.encode()).decode()
            self._headers = {"Authorization": f"Basic {encoded}"}
        else:
            self._headers = {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # Datasource discovery
    # ------------------------------------------------------------------

    def get_datasources(self) -> list[dict]:
        """Return all datasources from GET /api/datasources."""
        resp = httpx.get(
            f"{self.base_url}/api/datasources",
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def find_datasource(
        self, ds_type: str, name: str | None = None
    ) -> dict | None:
        """Find the first datasource matching *ds_type* (and optionally *name*)."""
        sources = self.get_datasources()
        for ds in sources:
            if ds.get("type", "").lower() != ds_type.lower():
                continue
            if name and ds.get("name", "").lower() != name.lower():
                continue
            return ds
        return None

    # ------------------------------------------------------------------
    # Prometheus proxy queries
    # ------------------------------------------------------------------

    def query_prometheus(
        self,
        ds_id: int,
        query: str,
        start: float,
        end: float,
        step: str = "60s",
    ) -> dict:
        """Run a PromQL range query through the Grafana datasource proxy."""
        url = f"{self.base_url}/api/datasources/proxy/{ds_id}/api/v1/query_range"
        resp = httpx.get(
            url,
            headers=self._headers,
            params={"query": query, "start": start, "end": end, "step": step},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def query_prometheus_instant(
        self,
        ds_id: int,
        query: str,
        ts: float | None = None,
    ) -> dict:
        """Run an instant PromQL query through the Grafana datasource proxy."""
        url = f"{self.base_url}/api/datasources/proxy/{ds_id}/api/v1/query"
        params: dict[str, Any] = {"query": query}
        if ts is not None:
            params["time"] = ts
        resp = httpx.get(
            url,
            headers=self._headers,
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Loki proxy queries
    # ------------------------------------------------------------------

    def query_loki(
        self,
        ds_id: int,
        query: str,
        start: float,
        end: float,
        step: str = "60s",
        limit: int = 50,
    ) -> dict:
        """Run a LogQL range query through the Grafana datasource proxy."""
        url = f"{self.base_url}/api/datasources/proxy/{ds_id}/loki/api/v1/query_range"
        resp = httpx.get(
            url,
            headers=self._headers,
            params={
                "query": query,
                "start": int(start * 1_000_000_000),  # Loki wants nanoseconds
                "end": int(end * 1_000_000_000),
                "step": step,
                "limit": limit,
                "direction": "backward",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
