#!/bin/bash
# ===========================================
# Monitoring Setup for Bluebox Database
# Creates users and databases for observability tools
# ===========================================
# This runs after bluebox init scripts (50-monitoring-setup.sh)
set -e

VECTOR_PG_PASSWORD="${VECTOR_PG_PASSWORD:-vector_password}"

# Create monitoring users and query-telemetry database
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" <<-EOSQL
    -- Create postgres_exporter user for Prometheus metrics collection
    CREATE USER postgres_exporter WITH PASSWORD 'exporter_password';

    -- Create vector user for log pipeline and query telemetry
    CREATE USER vector WITH PASSWORD '${VECTOR_PG_PASSWORD}';

    -- Grant pg_monitor role to postgres_exporter (PostgreSQL 10+)
    -- This provides read-only access to all pg_stat_* views and functions
    GRANT pg_monitor TO postgres_exporter;

    -- Create database for Grafana query telemetry
    CREATE DATABASE "query-telemetry";
    GRANT CONNECT ON DATABASE "query-telemetry" TO vector;

    -- Grant connection to bluebox database for monitoring
    GRANT CONNECT ON DATABASE bluebox TO postgres_exporter;
EOSQL

# Set up schemas and tables in query-telemetry database
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname "query-telemetry" <<-EOSQL
    -- Create schemas for different telemetry sources
    CREATE SCHEMA common AUTHORIZATION vector;
    CREATE SCHEMA loki AUTHORIZATION vector;
    CREATE SCHEMA mimir AUTHORIZATION vector;

    -- Set search path for vector user
    ALTER ROLE vector SET search_path TO common, loki, mimir, public;
EOSQL

# Create grafana_query_audit table as vector user
psql -v ON_ERROR_STOP=1 --username vector --dbname "query-telemetry" <<-EOSQL
    CREATE SEQUENCE common.grafana_query_audit_id_seq;

    CREATE TABLE common.grafana_query_audit (
        id                    BIGINT           NOT NULL DEFAULT nextval('common.grafana_query_audit_id_seq') PRIMARY KEY,
        ts                    TIMESTAMPTZ      NOT NULL,
        uname                 TEXT             NOT NULL DEFAULT '',
        query_text            TEXT             NOT NULL DEFAULT '',
        query_type            TEXT             NOT NULL DEFAULT '',
        direction             TEXT             NOT NULL DEFAULT '',
        duration_ms           DOUBLE PRECISION NOT NULL DEFAULT 0,
        status_code           INTEGER          NOT NULL DEFAULT 0,
        max_lines             INTEGER          NOT NULL DEFAULT 0,
        query_start           TIMESTAMPTZ,
        query_end             TIMESTAMPTZ,
        step                  TEXT             NOT NULL DEFAULT '',
        ds_name               TEXT             NOT NULL DEFAULT '',
        ds_uid                TEXT             NOT NULL DEFAULT '',
        from_alert            BOOLEAN          NOT NULL DEFAULT false,
        loki_host             TEXT             NOT NULL DEFAULT '',
        loki_path             TEXT             NOT NULL DEFAULT '',
        supporting_query_type TEXT             NOT NULL DEFAULT '',
        status                TEXT             NOT NULL DEFAULT ''
    );

    -- Trigger replaces NULL id with next sequence value (Vector inserts NULL for serial columns)
    CREATE OR REPLACE FUNCTION common.grafana_query_audit_auto_id()
    RETURNS TRIGGER AS \$\$
    BEGIN
        IF NEW.id IS NULL THEN
            NEW.id := nextval('common.grafana_query_audit_id_seq');
        END IF;
        RETURN NEW;
    END;
    \$\$ LANGUAGE plpgsql;

    CREATE TRIGGER grafana_query_audit_auto_id_trigger
        BEFORE INSERT ON common.grafana_query_audit
        FOR EACH ROW EXECUTE FUNCTION common.grafana_query_audit_auto_id();
EOSQL

# Grant bluebox schema permissions to postgres_exporter
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname "bluebox" <<-EOSQL
    -- Grant read access to bluebox schema for application-specific metrics
    GRANT USAGE ON SCHEMA bluebox TO postgres_exporter;
    GRANT SELECT ON ALL TABLES IN SCHEMA bluebox TO postgres_exporter;

    -- Grant default privileges for future tables
    ALTER DEFAULT PRIVILEGES FOR ROLE bluebox_admin IN SCHEMA bluebox
        GRANT SELECT ON TABLES TO postgres_exporter;
EOSQL

echo "=== Monitoring setup complete ==="
