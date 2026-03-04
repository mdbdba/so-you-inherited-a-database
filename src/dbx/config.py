"""dbx configuration via environment variables (and optional .env file).

Required:
  DBX_PG_DSN           Postgres connection string

Expected for telemetry:
  DBX_GRAFANA_URL      Grafana base URL  (e.g. http://localhost:3000)
  DBX_GRAFANA_TOKEN    Grafana API token or "admin:password" basic-auth string

Optional telemetry overrides:
  DBX_GRAFANA_PROM_DS_NAME   Prometheus datasource name (default: first prom ds)
  DBX_GRAFANA_LOKI_DS_NAME   Loki datasource name       (default: first loki ds)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    pg_dsn: str = Field(alias="DBX_PG_DSN")

    grafana_url: str | None = Field(default=None, alias="DBX_GRAFANA_URL")
    grafana_token: str | None = Field(default=None, alias="DBX_GRAFANA_TOKEN")
    grafana_prom_ds_name: str | None = Field(
        default=None, alias="DBX_GRAFANA_PROM_DS_NAME"
    )
    grafana_loki_ds_name: str | None = Field(
        default=None, alias="DBX_GRAFANA_LOKI_DS_NAME"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def grafana_configured(self) -> bool:
        return bool(self.grafana_url and self.grafana_token)

    @property
    def grafana_missing_vars(self) -> list[str]:
        missing: list[str] = []
        if not self.grafana_url:
            missing.append("DBX_GRAFANA_URL")
        if not self.grafana_token:
            missing.append("DBX_GRAFANA_TOKEN")
        return missing

    def redacted_pg_dsn(self) -> str:
        """Return DSN with password replaced by ***."""
        import re

        return re.sub(r"(:)[^:@]+(@)", r"\1***\2", self.pg_dsn)
