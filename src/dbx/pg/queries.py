"""All SQL used by dbx, as documented module-level constants.

Each constant has a comment block describing:
  - What it measures
  - Minimum required permissions
  - Which extension/setting it depends on (if any)

Keep ALL SQL here; no inline SQL in other modules.
"""

# ---------------------------------------------------------------------------
# Extension / setting discovery
# ---------------------------------------------------------------------------

Q_EXTENSIONS = """
-- Lists all extensions installed in the current database.
-- Permissions: any role that can connect
SELECT extname, extversion
FROM pg_extension
ORDER BY extname;
"""

# SHOW <param> statements are issued via PgClient.show(param).
# The list of parameters we read is defined in inspect.py::SHOW_SETTINGS.

# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

Q_DB_SIZE = """
-- Current database total size on disk.
-- Permissions: any role that can connect
SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size_pretty,
       pg_database_size(current_database())                  AS db_size_bytes;
"""

Q_TOP_TABLES_BY_SIZE = """
-- Top 10 largest tables (by total size including indexes and TOAST).
-- Permissions: SELECT on pg_catalog tables (public by default)
SELECT
    n.nspname                                            AS schema,
    c.relname                                            AS table_name,
    pg_size_pretty(pg_total_relation_size(c.oid))        AS total_size,
    pg_size_pretty(pg_relation_size(c.oid))              AS table_size,
    pg_size_pretty(
        pg_total_relation_size(c.oid) - pg_relation_size(c.oid)
    )                                                    AS index_size,
    pg_total_relation_size(c.oid)                        AS total_bytes
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY total_bytes DESC
LIMIT 10;
"""

Q_TOP_INDEXES_BY_SIZE = """
-- Top 10 largest indexes.
-- Permissions: SELECT on pg_catalog tables (public by default)
SELECT
    n.nspname                                   AS schema,
    t.relname                                   AS table_name,
    i.relname                                   AS index_name,
    am.amname                                   AS index_type,
    pg_size_pretty(pg_relation_size(i.oid))     AS index_size,
    pg_relation_size(i.oid)                     AS index_bytes
FROM pg_index ix
JOIN pg_class i   ON i.oid  = ix.indexrelid
JOIN pg_class t   ON t.oid  = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN pg_am am     ON am.oid  = i.relam
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY index_bytes DESC
LIMIT 10;
"""

Q_SCHEMA_TABLE_COUNTS = """
-- Count of schemas and tables visible to the current user.
-- Permissions: any role that can connect
SELECT
    count(DISTINCT table_schema)           AS schema_count,
    count(*)                               AS table_count
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
  AND table_schema NOT IN ('pg_catalog', 'information_schema');
"""

# ---------------------------------------------------------------------------
# Operational health
# ---------------------------------------------------------------------------

Q_CONNECTION_STATS = """
-- Current connection usage vs max_connections setting.
-- Permissions: pg_monitor (or superuser) for full detail;
--              any role for their own connections.
SELECT
    count(*)                                                      AS total_connections,
    count(*) FILTER (WHERE state = 'active')                      AS active,
    count(*) FILTER (WHERE state = 'idle')                        AS idle,
    count(*) FILTER (WHERE state = 'idle in transaction')         AS idle_in_txn,
    count(*) FILTER (WHERE wait_event_type IS NOT NULL)           AS waiting,
    current_setting('max_connections')::int                       AS max_connections
FROM pg_stat_activity
WHERE pid <> pg_backend_pid();
"""

Q_LONG_RUNNING_TRANSACTIONS = """
-- Transactions that have been running longer than 5 seconds.
-- Shows the query text, state, wait info, and duration.
-- Permissions: pg_monitor or superuser for all backends; own backends otherwise.
SELECT
    pid,
    usename                                                         AS username,
    application_name,
    state,
    wait_event_type,
    wait_event,
    EXTRACT(EPOCH FROM (now() - xact_start))::int                   AS xact_seconds,
    EXTRACT(EPOCH FROM (now() - query_start))::int                  AS query_seconds,
    left(query, 200)                                                AS query_snippet
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
  AND EXTRACT(EPOCH FROM (now() - xact_start)) > 5
  AND pid <> pg_backend_pid()
ORDER BY xact_start
LIMIT 20;
"""

Q_BLOCKED_QUERIES = """
-- Queries that are blocked waiting for locks, along with their blockers.
-- Permissions: pg_monitor or superuser for all backends.
SELECT
    blocked.pid                                                 AS blocked_pid,
    blocked.usename                                             AS blocked_user,
    blocked.application_name                                    AS blocked_app,
    left(blocked.query, 200)                                    AS blocked_query,
    blocking.pid                                                AS blocking_pid,
    blocking.usename                                            AS blocking_user,
    blocking.application_name                                   AS blocking_app,
    left(blocking.query, 200)                                   AS blocking_query,
    EXTRACT(EPOCH FROM (now() - blocked.query_start))::int      AS wait_seconds
FROM pg_stat_activity AS blocked
JOIN pg_stat_activity AS blocking
     ON blocking.pid = ANY(pg_blocking_pids(blocked.pid))
WHERE cardinality(pg_blocking_pids(blocked.pid)) > 0
ORDER BY wait_seconds DESC
LIMIT 20;
"""

# ---------------------------------------------------------------------------
# Vacuum / bloat indicators
# ---------------------------------------------------------------------------

Q_VACUUM_BLOAT = """
-- Tables with the most dead tuples, including vacuum/analyze timestamps.
-- Helps identify tables in need of vacuuming.
-- Permissions: SELECT on pg_stat_user_tables (public by default)
SELECT
    schemaname                                  AS schema,
    relname                                     AS table_name,
    n_live_tup,
    n_dead_tup,
    CASE WHEN n_live_tup > 0
         THEN round(n_dead_tup::numeric / n_live_tup * 100, 1)
         ELSE NULL
    END                                         AS dead_pct,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze,
    n_mod_since_analyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 20;
"""

# ---------------------------------------------------------------------------
# Index health
# ---------------------------------------------------------------------------

Q_UNUSED_INDEXES = """
-- Indexes that have never been scanned (idx_scan = 0) or very rarely used.
-- Excludes primary-key and unique constraint indexes.
-- Permissions: SELECT on pg_stat_user_indexes (public by default)
SELECT
    ui.schemaname                                       AS schema,
    ui.relname                                          AS table_name,
    ui.indexrelname                                     AS index_name,
    pg_size_pretty(pg_relation_size(ui.indexrelid))     AS index_size,
    pg_relation_size(ui.indexrelid)                     AS index_bytes,
    ui.idx_scan,
    ui.idx_tup_read,
    ui.idx_tup_fetch
FROM pg_stat_user_indexes ui
JOIN pg_index i ON i.indexrelid = ui.indexrelid
WHERE NOT i.indisprimary
  AND NOT i.indisunique
  AND ui.idx_scan < 10
ORDER BY index_bytes DESC
LIMIT 20;
"""

Q_HIGH_SEQ_SCAN_TABLES = """
-- Tables with high sequential scan counts, which may indicate missing indexes.
-- Filters to tables with at least one seq scan and > 1000 live rows.
-- Permissions: SELECT on pg_stat_user_tables (public by default)
SELECT
    schemaname          AS schema,
    relname             AS table_name,
    seq_scan,
    seq_tup_read,
    idx_scan,
    n_live_tup,
    CASE WHEN (seq_scan + coalesce(idx_scan, 0)) > 0
         THEN round(seq_scan::numeric / (seq_scan + coalesce(idx_scan, 0)) * 100, 1)
         ELSE NULL
    END                 AS seq_scan_pct
FROM pg_stat_user_tables
WHERE seq_scan > 0
  AND n_live_tup > 1000
ORDER BY seq_scan DESC
LIMIT 20;
"""

# ---------------------------------------------------------------------------
# pg_stat_statements (only queried when extension is confirmed ready)
# ---------------------------------------------------------------------------

Q_PSS_PROBE = """
-- Probe query to confirm pg_stat_statements view is readable.
-- Permissions: pg_read_all_stats or superuser (or track_io_timing=on user)
SELECT 1 FROM pg_stat_statements LIMIT 1;
"""

Q_PSS_TOP_QUERIES = """
-- Top 20 queries by total execution time from pg_stat_statements.
-- Includes call count, mean time, rows returned, and truncated query text.
-- Permissions: pg_read_all_stats or superuser
SELECT
    queryid,
    calls,
    round(total_exec_time::numeric, 2)              AS total_time_ms,
    round(mean_exec_time::numeric,  2)              AS mean_time_ms,
    round(stddev_exec_time::numeric, 2)             AS stddev_ms,
    rows,
    round(100.0 * total_exec_time /
        nullif(sum(total_exec_time) OVER (), 0), 2) AS pct_total,
    left(query, 300)                                AS query_snippet
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat_statements%'
ORDER BY total_exec_time DESC
LIMIT 20;
"""

# ---------------------------------------------------------------------------
# pg_cron probe (only queried when extension is confirmed ready)
# ---------------------------------------------------------------------------

Q_CRON_PROBE = """
-- Probe query to confirm cron.job table is readable.
-- Permissions: superuser or cron.job SELECT grant
SELECT 1 FROM cron.job LIMIT 1;
"""

Q_CRON_JOBS = """
-- List pg_cron jobs with schedule and last run status.
-- Permissions: superuser or cron.job SELECT grant
SELECT
    jobid,
    schedule,
    command,
    nodename,
    nodeport,
    database,
    username,
    active
FROM cron.job
ORDER BY jobid;
"""
