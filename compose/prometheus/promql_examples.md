## Example Queries

### SLI Metrics (Pre-computed)

**Availability** (transaction success rate):
```promql
# 5-minute window
sli:postgres_availability:ratio_rate5m * 100

# 30-day rolling average (SLO compliance)
sli:postgres_availability:ratio_rate30d * 100
```
Expected: > 99.9% for SLO compliance

**Latency** (query execution time):
```promql
# Average query latency in seconds
sli:postgres_latency:mean_seconds_rate5m

# Maximum query latency in seconds
sli:postgres_latency:max_seconds_rate5m
```

**Traffic** (throughput):
```promql
# Transactions per second
sli:postgres_traffic:transactions_per_second

# Total operations per second
sli:postgres_traffic:operations_per_second
```

**Saturation** (resource utilization):
```promql
# Connection pool utilization (0-1)
sli:postgres_saturation:connection_utilization_ratio * 100

# Cache hit ratio (0-1)
sli:postgres_saturation:cache_hit_ratio * 100
```
Expected: < 80% connections, > 95% cache hits

### Error Budget

**Budget remaining**:
```promql
error_budget:postgres:remaining_ratio * 100
```
- 100% = Full budget available
- 50% = Half budget consumed
- 0% = Budget exhausted, SLO violated

**Days until budget exhausted**:
```promql
error_budget:postgres:days_remaining
```

### Capacity Forecasting

**Database size in 30 days**:
```promql
capacity:postgres_database:size_bytes_forecast_30d / 1024 / 1024 / 1024
```
Result: Forecasted size in GB

**Connection count in 7 days**:
```promql
capacity:postgres_connections:count_forecast_7d
```

**WAL generation rate**:
```promql
capacity:postgres_wal:bytes_per_second / 1024 / 1024
```
Result: MB per second

### Raw Metrics

**Transaction error rate**:
```promql
rate(pg_transaction_throughput_xact_rollback[5m])
/
(rate(pg_transaction_throughput_xact_commit[5m]) + rate(pg_transaction_throughput_xact_rollback[5m]))
* 100
```
Expected: < 1%

**Active blocking queries**:
```promql
pg_blocking_queries_blocked_count
```
Expected: 0

**Transaction wraparound risk**:
```promql
pg_transaction_wraparound_xid_age
```
Alert: > 1,500,000,000 (1.5 billion)

### Troubleshooting Slow Queries

```promql
# Top 10 slowest queries
topk(10, pg_query_latency_mean_exec_time)

# Queries with high variability
pg_query_latency_stddev_exec_time > 100
```

### Monitoring Availability

```promql
# Current availability (5m window)
sli:postgres_availability:ratio_rate5m * 100

# Has availability violated SLO today?
min_over_time(sli:postgres_availability:ratio_rate5m[24h]) * 100 < 99.9
```

### Capacity Planning

```promql
# Days until disk 85% full
(
  (pg_database_size_bytes * 1.18) - pg_database_size_bytes
)
/
deriv(pg_database_size_bytes[7d])
/ 86400

# Connection pool growth rate (per day)
deriv(pg_connection_utilization_current_connections[7d]) * 86400
```

### Error Rate Tracking

```promql
# Current error rate (%)
(
  rate(pg_transaction_throughput_xact_rollback[5m])
  /
  (rate(pg_transaction_throughput_xact_commit[5m]) + rate(pg_transaction_throughput_xact_rollback[5m]))
) * 100

# Error budget burn rate (multiple of normal)
(1 - sli:postgres_availability:ratio_rate5m) / (1 - 0.999)
```
