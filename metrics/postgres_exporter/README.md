
### queries.yaml - 18 Production-Ready Custom Queries

#### Basic Monitoring (Examples 1-7)
Demonstrates fundamental DBA monitoring scenarios:

1. **Database Size** - Track growth trends for capacity planning
2. **Table Bloat** - Monitor table and index sizes to identify bloat
3. **Connection States** - Count connections by state (active, idle, idle in transaction)
4. **Long-Running Queries** - Alert on queries running over 5 minutes
5. **Cache Hit Ratio** - Ensure buffer cache effectiveness (target >95%)
6. **Index Usage** - Track index scans to identify unused indexes
7. **Vacuum/Analyze Stats** - Monitor table maintenance and dead tuple accumulation

#### Production-Critical Monitoring (Examples 8-16)
Advanced queries for production environments:

8. **Transaction Wraparound Risk** - Prevent catastrophic database shutdown (alert when age > 1.5B)
9. **Connection Pool Utilization** - Monitor connection usage to prevent exhaustion
10. **Blocking Queries** - Identify lock contention and blocking transactions
11. **Sequential Scans on Large Tables** - Find missing indexes (tables >10MB)
12. **Temporary File Usage** - Detect queries spilling to disk (work_mem tuning)
13. **WAL Generation Stats** - Monitor write-ahead log activity for backup/replication sizing
14. **Table Activity (DML)** - Track insert/update/delete rates per table
15. **Invalid Indexes** - Detect indexes that failed to build
16. **Oldest Open Transaction** - Prevent vacuum blocking

#### SRE Service Level Indicators (Examples 17-18)
User-facing metrics for SLO monitoring following the Four Golden Signals:

17. **Query Latency Tracking** - P50/P95/P99 query execution times from `pg_stat_statements` for latency SLOs
18. **Transaction Throughput & Errors** - Commit/rollback rates, error ratios, deadlocks, and data corruption detection

**Requirements**: Examples 17-18 require `pg_stat_statements` extension (automatically enabled in this stack).

**Note**: Replication lag metrics are provided by the built-in `--collector.replication` (enabled by default) as `pg_replication_lag_seconds`, `pg_replication_is_replica`, and `pg_replication_last_replay_seconds`.

Each query demonstrates proper metric typing (LABEL, GAUGE, COUNTER) and PostgreSQL system catalog usage.

## Understanding postgres_exporter Configuration

### Connection String (DATA_SOURCE_NAME)
The exporter connects to PostgreSQL using a connection string:
```
postgresql://postgres_exporter:exporter_password@postgres:5432/chinook?sslmode=disable&application_name=postgres_exporter
```

**User Credentials:**
- `postgres_exporter` / `exporter_password` - Monitoring user (read-only access)
- `app` / `app_password` - Application user (CRUD access)
- `dba` / `dba_password` - Administrator (superuser access)

### Environment Variables

Key configuration options in docker-compose.yml:

- `DATA_SOURCE_NAME`: PostgreSQL connection string for postgres_exporter
- `PG_EXPORTER_EXTEND_QUERY_PATH`: Path to custom queries file (deprecated but functional)
- `POSTGRES_DB`: Database name (chinook)
- `POSTGRES_USER`: PostgreSQL superuser
- `POSTGRES_PASSWORD`: PostgreSQL superuser password

### Command-Line Flags

The postgres_exporter is configured with:
- `--no-collector.wal`: Disables WAL directory collector (requires superuser, not needed for monitoring)

### Custom Queries

The `queries.yaml` file defines custom metrics. Each query follows this structure:

```yaml
metric_name:
  query: "SQL query here"
  master: true  # Run on primary only (false for replicas only)
  metrics:
    - column_name:
        usage: "LABEL|GAUGE|COUNTER"
        description: "Metric description"
```

**Metric Types:**
- `LABEL`: Used for grouping/filtering (e.g., database name, table name)
- `GAUGE`: Values that can go up or down (e.g., current connections, cache size)
- `COUNTER`: Values that only increase (e.g., total queries, bytes transferred)

## Default Metrics

postgres_exporter provides many built-in metrics including:

- `pg_up`: PostgreSQL server availability
- `pg_database_size_bytes`: Database sizes
- `pg_stat_database_*`: Database activity statistics
- `pg_stat_bgwriter_*`: Background writer statistics
- `pg_locks_count`: Lock information
- `pg_stat_replication_*`: Replication statistics
- `pg_replication_lag_seconds`: Replication lag behind primary (from `--collector.replication`)
- `pg_replication_is_replica`: Indicates if server is a replica
- `pg_settings_*`: PostgreSQL configuration settings

View all metrics at: http://localhost:9187/metrics

## Compatibility & Fixes

This setup has been tested and validated with:
- **PostgreSQL latest (18+)** - Volume mount configured for new PostgreSQL 18+ requirements
- **Latest postgres_exporter** - Custom queries updated for current PostgreSQL system view schemas
- **Docker Compose v2** - Uses `docker compose` (not `docker-compose`)

### Expected Deprecation Warning

You may see this warning in the postgres_exporter logs:
```
level=WARN msg="The extended queries.yaml config is DEPRECATED"
```

**This is expected and intentional for this educational demo.** The postgres_exporter project has deprecated custom query files in favor of built-in compiled collectors. For production systems, they recommend using [sql_exporter](https://github.com/burningalchemist/sql_exporter) for custom SQL monitoring.

However, this demo specifically teaches how to write custom queries, making the `queries.yaml` approach perfect for learning. The feature remains fully functional despite the deprecation warning.

**For production use:** Migrate to built-in collectors or sql_exporter. **For learning PostgreSQL monitoring concepts:** This setup is ideal.
