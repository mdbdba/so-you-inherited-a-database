## Testing Alerts

### View Alert Definitions

**In Prometheus UI**:
1. Go to http://localhost:9090/alerts
2. See all 22 alerts with:
   - Alert name
   - Expression (PromQL query)
   - State (inactive/pending/firing)
   - Labels and annotations

**Via API**:
```bash
curl -s http://localhost:9090/api/v1/rules | python3 -m json.tool
```

### Simulate Alert Firing

**Method 1: Lower Threshold Temporarily**

Edit `alerts.yml` and lower a threshold:
```yaml
# Original
- alert: HighConnectionUsage
  expr: pg_connection_utilization_utilization_ratio > 0.8

# For testing (will fire immediately)
- alert: HighConnectionUsage
  expr: pg_connection_utilization_utilization_ratio > 0.05
```

Then reload Prometheus:
```bash
curl -X POST http://localhost:9090/-/reload
```

**Method 2: Create Artificial Load**

Generate connections to trigger `HighConnectionUsage`:
```bash
# Open multiple psql connections
for i in {1..50}; do
  docker exec -d pod_postgres \
    psql -U postgres -d exampledb -c "SELECT pg_sleep(300);"
done
```

**Method 3: Force Error Budget Burn**

Run failing queries to increase rollback rate:
```bash
docker exec pod_postgres psql -U postgres -d exampledb <<EOF
BEGIN;
SELECT * FROM nonexistent_table;
ROLLBACK;
EOF
```

Repeat 100+ times to trigger `HighTransactionErrorRate`.

### Check Alert in Alertmanager

Once alert fires in Prometheus:
1. Wait ~10-30 seconds (grouping delay)
2. Visit http://localhost:9093
3. See alert in Alertmanager UI
4. Note grouping by severity/component

### Silence an Alert

**In Alertmanager UI**:
1. Click "Silence" button on alert
2. Set duration (e.g., 1 hour)
3. Add comment: "Testing silences"
4. Create silence
5. Alert disappears from active list

**Via API**:
```bash
curl -X POST http://localhost:9093/api/v2/silences \
  -H "Content-Type: application/json" \
  -d '{
    "matchers": [{"name": "alertname", "value": "HighConnectionUsage", "isRegex": false}],
    "startsAt": "2025-11-21T00:00:00Z",
    "endsAt": "2025-11-21T23:59:59Z",
    "comment": "Planned maintenance",
    "createdBy": "admin"
  }'
```
