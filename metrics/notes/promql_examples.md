## Example Prometheus Queries

Try these in Prometheus (http://localhost:9090):

### Basic Monitoring
```promql
# Database size in GB
pg_database_size_bytes / 1024 / 1024 / 1024

# Cache hit ratio (should be >0.95)
pg_cache_hit_ratio_cache_hit_ratio

# Active connections by state
pg_connection_states_count

# Queries running longer than 5 minutes
pg_long_running_queries_count

# Tables with most dead tuples
topk(10, pg_table_maintenance_dead_tuples)
```

### Production Monitoring
```promql
# Connection pool utilization (alert if >0.8)
pg_connection_utilization_utilization_ratio

# Transaction wraparound danger (alert if >1.5B)
pg_transaction_wraparound_xid_age

# Oldest open transaction in minutes
pg_oldest_transaction_oldest_xact_seconds / 60

# Blocking query count
sum(pg_blocking_queries_blocked_count) by (blocking_pid)

# WAL generation rate (bytes per second)
rate(pg_wal_stats_wal_bytes[5m])

# Tables with sequential scans on large tables
pg_sequential_scans_seq_scan{table_size_bytes > 10485760}

# Temporary file usage (work_mem tuning indicator)
rate(pg_temp_files_temp_bytes[5m])
```
