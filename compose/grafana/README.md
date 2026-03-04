## Grafana Dashboard Setup

1. Log into Grafana at http://localhost:3000 (admin/admin)
2. Both Prometheus (metrics) and Loki (logs) datasources are pre-configured
3. Import PostgreSQL dashboards:
   - Go to Dashboards → Import
   - Use dashboard ID: **9628** (PostgreSQL Database)
   - Or ID: **455** (PostgreSQL Overview)
   - Select the Prometheus datasource
4. Explore logs:
   - Go to Explore (compass icon in sidebar)
   - Select Loki datasource
   - Try queries like `{job="postgres"}` or `{component="monitoring"}`
   - Use the Log Browser to discover available labels
5. Create correlation between metrics and logs:
   - View a metric in Explore with Prometheus datasource
   - Click "Split" to add Loki datasource alongside
   - Query logs from the same time range to correlate events
