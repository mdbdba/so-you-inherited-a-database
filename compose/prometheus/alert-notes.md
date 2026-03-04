## Recommended Alerting Rules

Add these critical alerts to your Prometheus `alerts.yml`:

```yaml
groups:
  - name: postgresql_critical
    rules:
      # Transaction wraparound prevention
      - alert: TransactionWraparoundDanger
        expr: pg_transaction_wraparound_xid_age > 1500000000
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Database {{ $labels.database }} approaching transaction wraparound"
          description: "XID age: {{ $value }}, ~{{ humanize $labels.xids_remaining }} XIDs remaining"

      # Connection pool saturation
      - alert: HighConnectionUsage
        expr: pg_connection_utilization_utilization_ratio > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Connection pool at {{ $value | humanizePercentage }} capacity"

      # Long-running transactions blocking vacuum
      - alert: LongRunningTransaction
        expr: pg_oldest_transaction_oldest_xact_seconds > 3600
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Transaction running for {{ $value | humanizeDuration }}"

      # Query blocking
      - alert: QueryBlocking
        expr: pg_blocking_queries_blocked_count > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "PID {{ $labels.blocking_pid }} blocking {{ $value }} queries"

      # Excessive temporary file usage
      - alert: HighTempFileUsage
        expr: rate(pg_temp_files_temp_bytes[5m]) > 104857600  # 100MB/s
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High temp file usage in {{ $labels.database }}: {{ $value | humanize }}B/s"
          description: "Consider increasing work_mem"
```
