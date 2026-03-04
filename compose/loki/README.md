
#### loki-config.yaml
Loki configuration optimized for local development:
- **Storage**: Filesystem-based (1-week retention for demo)
- **Schema**: TSDB with v13 schema for efficient querying
- **Compaction**: Automatic index compaction for performance
- **Retention**: Configurable retention with automatic deletion
- **Integration**: Connected to Alertmanager for log-based alerts

For production, consider migrating to object storage (S3, GCS) and increasing retention periods.

#### Querying Logs in Grafana

Access logs in Grafana's Explore view (http://localhost:3000/explore) with the Loki datasource:

**Basic Queries**:
```logql
# All logs from PostgreSQL
{job="postgres"}

# All monitoring component logs
{component="monitoring"}

# Errors from any container
{namespace="pgs_obs_demo"} |= "error"

# PostgreSQL errors only
{job="postgres"} |~ "(?i)error|fatal|panic"

# Slow query logs
{job="postgres"} |= "duration:" |~ "duration: [0-9]{4,}"
```

**Advanced Queries with Metrics**:
```logql
# Count errors per second
sum(rate({namespace="pgs_obs_demo"} |= "error" [1m])) by (job)

# Top 10 containers by log volume
topk(10, sum(rate({namespace="pgs_obs_demo"}[5m])) by (container))

# Connection errors rate
sum(rate({job="postgres"} |= "connection" |= "error" [5m]))
```

**Useful LogQL Patterns**:
- `{job="postgres"}` - Label filtering (indexed, fast)
- `|= "error"` - Line contains "error" (fast string search)
- `|~ "regex"` - Regular expression matching
- `| json` - Parse JSON logs
- `| logfmt` - Parse key=value format
- `rate()` - Calculate rate over time window
