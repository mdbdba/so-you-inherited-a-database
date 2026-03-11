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
-- Lists all extensions installed in the current database along with the
-- latest version available on this server (from pg_available_extensions).
-- Permissions: any role that can connect
SELECT e.extname, e.extversion AS installed_version, a.default_version AS available_version
FROM pg_extension e
LEFT JOIN pg_available_extensions a ON a.name = e.extname
ORDER BY e.extname;
"""

# SHOW <param> statements are issued via PgClient.show(param).
# The list of parameters we read is defined in inspect.py::SHOW_SETTINGS.

# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

Q_INSTANCE_DATABASES = """
-- All non-template databases in this Postgres instance, ordered by size.
-- pg_database is readable by any role; pg_database_size() requires no
-- special privileges in modern Postgres.
SELECT
    datname                                         AS database_name,
    pg_size_pretty(pg_database_size(datname))       AS size,
    pg_encoding_to_char(encoding)                   AS encoding,
    datcollate                                      AS collation
FROM pg_database
WHERE datistemplate = false
ORDER BY pg_database_size(datname) DESC NULLS LAST;
"""

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
    round((100.0 * total_exec_time /
        nullif(sum(total_exec_time) OVER (), 0))::numeric, 2) AS pct_total,
    left(query, 300)                                AS query_snippet
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat_statements%'
ORDER BY total_exec_time DESC
LIMIT 20;
"""

# ---------------------------------------------------------------------------
# Backup & recovery indicators
# ---------------------------------------------------------------------------

Q_ARCHIVE_STATUS = """
-- WAL archiver statistics: last archived WAL, timing, and failure counts.
-- A stale last_archived_time (or high failed_count) is a backup risk signal.
-- Permissions: pg_monitor or superuser
SELECT
    archived_count,
    last_archived_wal,
    last_archived_time,
    failed_count,
    last_failed_wal,
    last_failed_time,
    stats_reset,
    EXTRACT(EPOCH FROM (now() - last_archived_time))::int   AS seconds_since_last_archive
FROM pg_stat_archiver;
"""

Q_REPLICATION_STANDBYS = """
-- Active streaming replication connections (standbys / read replicas).
-- Presence of standbys means WAL is flowing and a failover target exists.
-- Permissions: pg_monitor or superuser
SELECT
    application_name,
    client_addr::text                                               AS client_addr,
    state,
    sync_state,
    sent_lsn::text                                                  AS sent_lsn,
    replay_lsn::text                                                AS replay_lsn,
    write_lag,
    flush_lag,
    replay_lag,
    EXTRACT(EPOCH FROM (now() - backend_start))::int                AS connected_seconds
FROM pg_stat_replication
ORDER BY application_name;
"""

Q_REPLICATION_SLOTS = """
-- Physical and logical replication slots.
-- Inactive slots can accumulate WAL indefinitely and cause disk pressure.
-- Permissions: pg_monitor or superuser
SELECT
    slot_name,
    slot_type,
    database,
    active,
    active_pid,
    restart_lsn::text                                               AS restart_lsn,
    CASE
        WHEN restart_lsn IS NOT NULL
        THEN pg_size_pretty(
                 pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)::bigint
             )
        ELSE 'unknown'
    END                                                             AS retained_wal_size,
    CASE
        WHEN restart_lsn IS NOT NULL
        THEN pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)::bigint
        ELSE NULL
    END                                                             AS retained_wal_bytes
FROM pg_replication_slots
ORDER BY slot_name;
"""

Q_BACKUP_AGENT_CONNECTIONS = """
-- Connections from known backup and replication management tools.
-- An active connection here means a backup or replication agent is working.
-- Permissions: pg_monitor or superuser
SELECT
    pid,
    application_name,
    client_addr::text   AS client_addr,
    state,
    backend_start
FROM pg_stat_activity
WHERE application_name ILIKE ANY(ARRAY[
    'pg_basebackup', 'barman', 'barman_streaming_backup',
    'pgbackrest', 'wal-g', 'wal_g',
    'repmgr', 'patroni', 'stolon',
    'pg_dump', 'pg_dumpall'
])
ORDER BY application_name, backend_start;
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
-- Full pg_cron job definitions including command text.
-- Used for the definitions section (rendered outside a table for full-width display).
-- Permissions: superuser or cron.job SELECT grant
SELECT
    jobid,
    schedule,
    command,
    database,
    username,
    active
FROM cron.job
ORDER BY jobid;
"""

Q_CRON_JOB_SUMMARY = """
-- Per-job operational summary: run counts, failure counts, and average duration
-- for the last 7 days. Jobs with no run history still appear (via LEFT JOIN).
-- Permissions: superuser or SELECT on cron.job and cron.job_run_details
SELECT
    j.jobid,
    j.schedule,
    j.database,
    j.username,
    j.active,
    count(r.runid)
        FILTER (WHERE r.end_time > now() - interval '7 days')               AS runs_7d,
    count(r.runid)
        FILTER (WHERE r.status = 'succeeded'
                  AND r.end_time > now() - interval '7 days')               AS succeeded_7d,
    count(r.runid)
        FILTER (WHERE r.status = 'failed'
                  AND r.end_time > now() - interval '7 days')               AS failed_7d,
    round(
        avg(EXTRACT(EPOCH FROM (r.end_time - r.start_time)))
        FILTER (WHERE r.status = 'succeeded'
                  AND r.end_time IS NOT NULL
                  AND r.end_time > now() - interval '7 days')::numeric, 1)  AS avg_duration_sec,
    max(r.end_time)                                                          AS last_run
FROM cron.job j
LEFT JOIN cron.job_run_details r ON r.jobid = j.jobid
GROUP BY j.jobid, j.schedule, j.database, j.username, j.active
ORDER BY j.jobid;
"""

Q_CRON_RECENT_FAILURES = """
-- Most recent pg_cron job failures with error messages and duration.
-- command is taken from the run record (captures the command as it ran).
-- Permissions: superuser or SELECT on cron.job_run_details
SELECT
    r.jobid,
    r.start_time,
    round(EXTRACT(EPOCH FROM (r.end_time - r.start_time))::numeric, 1)  AS duration_sec,
    r.command,
    r.return_message
FROM cron.job_run_details r
WHERE r.status = 'failed'
ORDER BY r.start_time DESC
LIMIT 10;
"""

# ---------------------------------------------------------------------------
# Memory effectiveness
# ---------------------------------------------------------------------------

Q_BUFFER_HIT_RATE = """
-- Buffer cache hit rates for table heap blocks and index blocks.
-- Computed from cumulative stats since the last pg_stat_reset().
-- table_hit_pct or index_hit_pct below 95% suggests shared_buffers may be undersized.
-- Permissions: SELECT on pg_statio_user_tables (public by default)
SELECT
    sum(heap_blks_hit)                                                        AS table_hits,
    sum(heap_blks_read)                                                       AS table_reads,
    round(
        sum(heap_blks_hit)::numeric /
        nullif(sum(heap_blks_hit) + sum(heap_blks_read), 0) * 100, 1
    )                                                                         AS table_hit_pct,
    sum(idx_blks_hit)                                                         AS index_hits,
    sum(idx_blks_read)                                                        AS index_reads,
    round(
        sum(idx_blks_hit)::numeric /
        nullif(sum(idx_blks_hit) + sum(idx_blks_read), 0) * 100, 1
    )                                                                         AS index_hit_pct
FROM pg_statio_user_tables;
"""

Q_TEMP_FILE_STATS = """
-- Temp file usage for the current database since last stats reset.
-- temp_files > 0 means some sorts or hash joins spilled to disk.
-- High temp_bytes suggests work_mem is undersized for some queries.
-- Permissions: SELECT on pg_stat_database (public by default)
SELECT
    temp_files,
    temp_bytes,
    pg_size_pretty(temp_bytes)  AS temp_size_pretty,
    stats_reset
FROM pg_stat_database
WHERE datname = current_database();
"""

# ---------------------------------------------------------------------------
# Extension health probes
# ---------------------------------------------------------------------------

Q_PSS_INFO = """
-- pg_stat_statements eviction counter (PG14+).
-- dealloc counts how many times entries were evicted to stay under pg_stat_statements.max.
-- Non-zero dealloc means query history is incomplete.
-- Permissions: pg_read_all_stats or superuser
SELECT dealloc, stats_reset FROM pg_stat_statements_info;
"""

Q_CRON_JOB_STATS = """
-- pg_cron job run statistics for the last 24 hours.
-- Counts total runs and failed runs to detect cron job failures.
-- Permissions: superuser or SELECT on cron.job_run_details
SELECT
    count(*)                                              AS total_runs,
    count(*) FILTER (WHERE status = 'failed')             AS failed_runs
FROM cron.job_run_details
WHERE end_time > now() - interval '24 hours';
"""

Q_POSTGIS_VERSION = """
-- PostGIS version string, confirming the extension is functional.
-- Permissions: any role that can connect
SELECT PostGIS_Version() AS version;
"""

Q_FOREIGN_SERVER_COUNT = """
-- Count of foreign servers defined in pg_foreign_server.
-- Zero servers means postgres_fdw is installed but not yet configured.
-- Permissions: any role that can connect
SELECT count(*) AS server_count FROM pg_foreign_server;
"""

Q_PGVECTOR_PROBE = """
-- Probe to confirm the vector type is functional.
-- Permissions: any role that can connect
SELECT '[1,2,3]'::vector IS NOT NULL AS works;
"""

Q_DBLINK_FUNCTION_EXISTS = """
-- Confirm the dblink function exists in pg_proc.
-- Permissions: any role that can connect
SELECT count(*) AS fn_count FROM pg_proc WHERE proname = 'dblink';
"""
