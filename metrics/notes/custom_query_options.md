# Custom Query Options for PostgreSQL Monitoring

This document explains the evolution of custom query approaches in PostgreSQL monitoring and provides guidance for migrating from learning environments to production deployments.

## Table of Contents
- [Overview](#overview)
- [Approach 1: queries.yaml (This Demo)](#approach-1-queriesyaml-this-demo)
- [Approach 2: Built-in Collectors](#approach-2-built-in-collectors)
- [Approach 3: sql_exporter](#approach-3-sql_exporter)
- [Production Recommendations](#production-recommendations)
- [Migration Guide](#migration-guide)

---

## Overview

The PostgreSQL monitoring ecosystem has evolved significantly. This demo uses the **deprecated queries.yaml approach** intentionally for educational purposes, but production environments should use modern alternatives.

### Evolution Timeline

1. **Early Days (Pre-2020)**: Custom queries via YAML configuration files
2. **Current (2020-2024)**: Shift to compiled built-in collectors in postgres_exporter
3. **Modern (2024+)**: Hybrid approach using built-in collectors + sql_exporter for custom needs

---

## Approach 1: queries.yaml (This Demo)

### Overview

The original postgres_exporter approach where custom queries are defined in YAML configuration files.

**Status**: ⚠️ **DEPRECATED** (but still functional)

### How It Works

Define custom metrics using SQL queries in a YAML file:

```yaml
# queries.yaml
pg_custom_metric:
  query: "SELECT table_name, row_count FROM my_custom_view"
  master: true
  metrics:
    - table_name:
        usage: "LABEL"
        description: "Name of the table"
    - row_count:
        usage: "GAUGE"
        description: "Number of rows in the table"
```

### Configuration

**Environment Variable Method:**
```yaml
# docker-compose.yml
postgres_exporter:
  environment:
    PG_EXPORTER_EXTEND_QUERY_PATH: "/etc/postgres_exporter/queries.yaml"
  volumes:
    - ./queries.yaml:/etc/postgres_exporter/queries.yaml:ro
```

**Command-line Flag Method:**
```yaml
# docker-compose.yml
postgres_exporter:
  command:
    - "--extend.query-path=/etc/postgres_exporter/queries.yaml"
  volumes:
    - ./queries.yaml:/etc/postgres_exporter/queries.yaml:ro
```

### Example: Custom Business Metric

```yaml
pg_chinook_sales_by_country:
  query: |
    SELECT
      "BillingCountry" as country,
      COUNT(*) as invoice_count,
      SUM("Total") as total_sales
    FROM chinook."Invoice"
    GROUP BY "BillingCountry"
  master: true
  metrics:
    - country:
        usage: "LABEL"
        description: "Billing country"
    - invoice_count:
        usage: "COUNTER"
        description: "Number of invoices"
    - total_sales:
        usage: "COUNTER"
        description: "Total sales amount"
```

### Pros

- ✅ **Easy to learn** - No programming knowledge required
- ✅ **Fast iteration** - Edit YAML and restart, no compilation
- ✅ **Transparent** - See exactly what SQL produces which metrics
- ✅ **Perfect for demos** - Great for teaching monitoring concepts
- ✅ **Low barrier to entry** - Anyone who knows SQL can create metrics

### Cons

- ❌ **Deprecated** - Will eventually be removed from postgres_exporter
- ❌ **Performance overhead** - YAML parsing and dynamic query execution
- ❌ **Limited error handling** - Less robust than compiled code
- ❌ **PostgreSQL-specific** - Can't monitor other databases
- ❌ **Maintenance burden** - Manual query management at scale

### When to Use

- **Learning environments** ✅
- **Demos and tutorials** ✅
- **Rapid prototyping** ✅
- **Production systems** ❌

---

## Approach 2: Built-in Collectors

### Overview

Modern postgres_exporter includes **compiled Go collectors** that provide PostgreSQL metrics without YAML configuration.

**Status**: ✅ **RECOMMENDED** for standard PostgreSQL metrics

### How It Works

Built-in collectors are compiled into the postgres_exporter binary. You enable/disable them via command-line flags.

### Available Built-in Collectors

**Enabled by default:**
- `database` - Core database metrics
- `locks` - Lock contention data
- `replication` - Replication status
- `replication_slot` - Replication slot metrics
- `stat_bgwriter` - Background writer activity
- `stat_database` - Database-level statistics
- `stat_progress_vacuum` - VACUUM operation progress
- `stat_user_tables` - Table-level statistics
- `statio_user_tables` - Table I/O statistics
- `wal` - Write-ahead log metrics

**Disabled by default (require explicit enabling):**
- `database_wraparound` - Transaction ID wraparound monitoring
- `long_running_transactions` - Long-running query detection
- `postmaster` - PostgreSQL postmaster process info
- `process_idle` - Idle process tracking
- `stat_activity_autovacuum` - Autovacuum activity
- `stat_statements` - Query performance from pg_stat_statements
- `stat_wal_receiver` - WAL receiver statistics
- `statio_user_indexes` - Index I/O statistics
- `xlog_location` - Transaction log position

### Configuration

**Enable specific collectors:**
```yaml
# docker-compose.yml
postgres_exporter:
  command:
    - "--collector.database_wraparound"
    - "--collector.long_running_transactions"
    - "--collector.stat_statements"
    - "--collector.statio_user_indexes"
```

**Disable collectors:**
```yaml
postgres_exporter:
  command:
    - "--no-collector.wal"
    - "--no-collector.locks"
```

### Mapping queries.yaml to Built-in Collectors

| Custom Query (queries.yaml) | Built-in Collector | Command Flag |
|-----------------------------|-------------------|--------------|
| `pg_table_bloat` | stat_user_tables + statio_user_tables | `--collector.stat_user_tables` |
| `pg_cache_hit_ratio` | stat_database | Enabled by default |
| `pg_index_usage` | statio_user_indexes | `--collector.statio_user_indexes` |
| `pg_transaction_wraparound` | database_wraparound | `--collector.database_wraparound` |
| `pg_query_latency` | stat_statements | `--collector.stat_statements` |
| `pg_long_running_queries` | long_running_transactions | `--collector.long_running_transactions` |
| `pg_connection_states` | stat_database | Enabled by default |
| `pg_wal_stats` | wal | Enabled by default |

### Example Metrics

Built-in collectors expose standardized metrics:

```promql
# Database statistics
pg_stat_database_blks_hit
pg_stat_database_blks_read
pg_stat_database_xact_commit
pg_stat_database_xact_rollback

# Table statistics
pg_stat_user_tables_n_live_tup
pg_stat_user_tables_n_dead_tup
pg_stat_user_tables_seq_scan
pg_stat_user_tables_idx_scan

# Transaction wraparound
pg_database_wraparound_age

# Query performance (requires pg_stat_statements extension)
pg_stat_statements_calls_total
pg_stat_statements_mean_exec_time_seconds
```

### Pros

- ✅ **High performance** - Compiled Go code, no parsing overhead
- ✅ **Well-tested** - Used by thousands of production deployments
- ✅ **Standardized** - Consistent metric names across organizations
- ✅ **Official support** - Maintained by prometheus-community
- ✅ **Battle-tested** - Years of production hardening
- ✅ **Resource efficient** - Low CPU and memory footprint

### Cons

- ❌ **Limited flexibility** - Can't query application-specific tables
- ❌ **Fixed metrics** - Must wait for new collectors to be added
- ❌ **PostgreSQL-only** - Can't monitor other databases
- ❌ **Requires pg_stat_statements** - Some collectors need extensions

### When to Use

- **Production PostgreSQL monitoring** ✅
- **Standard database metrics** ✅
- **High-scale deployments** ✅
- **Application-specific queries** ❌

---

## Approach 3: sql_exporter

### Overview

A separate, database-agnostic exporter designed specifically for custom SQL queries across multiple database systems.

**Status**: ✅ **RECOMMENDED** for custom application metrics

**Project**: [burningalchemist/sql_exporter](https://github.com/burningalchemist/sql_exporter)

### How It Works

sql_exporter is a dedicated tool that:
- Connects to any SQL database (PostgreSQL, MySQL, Oracle, SQL Server, etc.)
- Executes custom SQL queries defined in YAML configuration
- Exposes results as Prometheus metrics
- Runs independently from database-specific exporters

### Configuration

**Configuration File Structure:**

```yaml
# sql_exporter.yml
jobs:
  - name: "postgres_chinook_metrics"
    interval: '5m'
    connections:
      - 'postgres://app:password@postgres:5432/chinook?sslmode=disable'

    queries:
      - name: "chinook_sales_by_country"
        help: "Total sales amount by billing country"
        labels:
          - "country"
        values:
          - "invoice_count"
          - "total_sales"
        query: |
          SELECT
            "BillingCountry" as country,
            COUNT(*) as invoice_count,
            SUM("Total") as total_sales
          FROM chinook."Invoice"
          GROUP BY "BillingCountry"

      - name: "chinook_top_artists"
        help: "Top selling artists by track count"
        labels:
          - "artist_name"
        values:
          - "track_count"
          - "total_albums"
        query: |
          SELECT
            ar."Name" as artist_name,
            COUNT(DISTINCT t."TrackId") as track_count,
            COUNT(DISTINCT al."AlbumId") as total_albums
          FROM chinook."Artist" ar
          JOIN chinook."Album" al ON ar."ArtistId" = al."ArtistId"
          JOIN chinook."Track" t ON al."AlbumId" = t."AlbumId"
          GROUP BY ar."Name"
          ORDER BY track_count DESC
          LIMIT 10

      - name: "chinook_customer_lifetime_value"
        help: "Customer lifetime value by customer"
        labels:
          - "customer_id"
          - "customer_name"
          - "country"
        values:
          - "total_spent"
          - "invoice_count"
        query: |
          SELECT
            c."CustomerId"::text as customer_id,
            c."FirstName" || ' ' || c."LastName" as customer_name,
            c."Country" as country,
            COALESCE(SUM(i."Total"), 0) as total_spent,
            COUNT(i."InvoiceId") as invoice_count
          FROM chinook."Customer" c
          LEFT JOIN chinook."Invoice" i ON c."CustomerId" = i."CustomerId"
          GROUP BY c."CustomerId", c."FirstName", c."LastName", c."Country"
```

**Docker Compose Setup:**

```yaml
services:
  sql_exporter:
    image: burningalchemist/sql_exporter:latest
    container_name: sql_exporter
    ports:
      - "9399:9399"
    volumes:
      - ./sql_exporter.yml:/etc/sql_exporter/config.yml:ro
    command:
      - "--config.file=/etc/sql_exporter/config.yml"
    networks:
      - monitoring
    restart: unless-stopped
```

### Example: Complete Application Metrics

```yaml
# sql_exporter.yml - Complete example for Chinook database
jobs:
  - name: "chinook_business_metrics"
    interval: '2m'
    connections:
      - 'postgres://app:app_password@postgres:5432/chinook?sslmode=disable'

    queries:
      # Revenue metrics
      - name: "chinook_revenue_by_genre"
        help: "Total revenue by music genre"
        labels:
          - "genre"
        values:
          - "revenue"
        query: |
          SELECT
            g."Name" as genre,
            SUM(il."UnitPrice" * il."Quantity") as revenue
          FROM chinook."Genre" g
          JOIN chinook."Track" t ON g."GenreId" = t."GenreId"
          JOIN chinook."InvoiceLine" il ON t."TrackId" = il."TrackId"
          GROUP BY g."Name"

      # Employee performance
      - name: "chinook_sales_by_employee"
        help: "Sales performance by support representative"
        labels:
          - "employee_id"
          - "employee_name"
        values:
          - "total_sales"
          - "customer_count"
        query: |
          SELECT
            e."EmployeeId"::text as employee_id,
            e."FirstName" || ' ' || e."LastName" as employee_name,
            COALESCE(SUM(i."Total"), 0) as total_sales,
            COUNT(DISTINCT c."CustomerId") as customer_count
          FROM chinook."Employee" e
          LEFT JOIN chinook."Customer" c ON e."EmployeeId" = c."SupportRepId"
          LEFT JOIN chinook."Invoice" i ON c."CustomerId" = i."CustomerId"
          GROUP BY e."EmployeeId", e."FirstName", e."LastName"

      # Inventory metrics
      - name: "chinook_tracks_by_media_type"
        help: "Track count by media type"
        labels:
          - "media_type"
        values:
          - "track_count"
          - "total_milliseconds"
        query: |
          SELECT
            mt."Name" as media_type,
            COUNT(t."TrackId") as track_count,
            SUM(t."Milliseconds") as total_milliseconds
          FROM chinook."MediaType" mt
          JOIN chinook."Track" t ON mt."MediaTypeId" = t."MediaTypeId"
          GROUP BY mt."Name"
```

### Prometheus Configuration

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'postgres-system-metrics'
    static_configs:
      - targets: ['postgres_exporter:9187']
    scrape_interval: 30s

  - job_name: 'postgres-application-metrics'
    static_configs:
      - targets: ['sql_exporter:9399']
    scrape_interval: 2m  # Less frequent for business metrics
```

### Resulting Metrics

```promql
# Revenue by genre
chinook_revenue_by_genre{genre="Rock"} 826.86
chinook_revenue_by_genre{genre="Latin"} 382.14

# Sales by employee
chinook_sales_by_employee{employee_id="3",employee_name="Jane Peacock"} 833.04

# Track inventory
chinook_tracks_by_media_type{media_type="MPEG audio file"} 3034
```

### Pros

- ✅ **Database-agnostic** - Works with PostgreSQL, MySQL, Oracle, SQL Server, etc.
- ✅ **Full SQL flexibility** - Query any tables, join across schemas
- ✅ **Application-specific** - Perfect for business metrics and KPIs
- ✅ **Separate concerns** - Doesn't interfere with system monitoring
- ✅ **Actively maintained** - Regular updates and improvements
- ✅ **Multi-database** - Monitor multiple database systems with one exporter
- ✅ **Better control** - Configure scrape intervals per query

### Cons

- ❌ **Additional component** - Another service to deploy and monitor
- ❌ **Different config format** - Separate from postgres_exporter
- ❌ **No system catalog queries** - Still need postgres_exporter for pg_stat_* views
- ❌ **Learning curve** - Different tool to learn

### When to Use

- **Application-specific metrics** ✅
- **Business KPIs** ✅
- **Custom table queries** ✅
- **Multi-database environments** ✅
- **Standard PostgreSQL metrics** ❌ (use postgres_exporter built-ins)

---

## Production Recommendations

### Best Practice: Hybrid Approach

Use **both exporters together** for comprehensive monitoring:

```yaml
# docker-compose.yml
services:
  # 1. postgres_exporter for standard PostgreSQL system metrics
  postgres_exporter:
    image: prometheuscommunity/postgres-exporter:latest
    container_name: postgres_exporter
    environment:
      DATA_SOURCE_NAME: "postgresql://postgres_exporter:password@postgres:5432/postgres?sslmode=disable"
    command:
      # Enable additional collectors as needed
      - "--collector.database_wraparound"
      - "--collector.stat_statements"
      - "--collector.long_running_transactions"
      - "--collector.statio_user_indexes"
      # Disable collectors that need superuser
      - "--no-collector.wal"
    ports:
      - "9187:9187"
    networks:
      - monitoring
    restart: unless-stopped

  # 2. sql_exporter for custom application-specific queries
  sql_exporter:
    image: burningalchemist/sql_exporter:latest
    container_name: sql_exporter
    volumes:
      - ./sql_exporter.yml:/config.yml:ro
    command:
      - "--config.file=/config.yml"
    ports:
      - "9399:9399"
    networks:
      - monitoring
    restart: unless-stopped

  postgres:
    image: postgres:latest
    # ... postgres configuration ...
    networks:
      - monitoring

networks:
  monitoring:
    driver: bridge
```

### Prometheus Scrape Configuration

```yaml
# prometheus.yml
scrape_configs:
  # System-level PostgreSQL metrics
  - job_name: 'postgres-system'
    static_configs:
      - targets: ['postgres_exporter:9187']
    scrape_interval: 30s
    scrape_timeout: 10s

  # Application-level custom metrics
  - job_name: 'postgres-application'
    static_configs:
      - targets: ['sql_exporter:9399']
    scrape_interval: 2m  # Less frequent for business metrics
    scrape_timeout: 30s
```

### What Each Exporter Monitors

**postgres_exporter (System Metrics):**
- Database size and growth
- Connection pool utilization
- Transaction wraparound risk
- Cache hit ratios
- Index and table statistics
- Replication lag
- Query performance (pg_stat_statements)
- Vacuum and autovacuum activity
- Lock contention
- WAL generation

**sql_exporter (Application Metrics):**
- Business KPIs (revenue, orders, users)
- Application-specific table data
- Custom aggregations and calculations
- Multi-table joins for business logic
- Domain-specific metrics
- SLA compliance metrics
- Feature usage statistics

---

## Migration Guide

### Step 1: Identify Query Types

Review your current `queries.yaml` and categorize each query:

**Category A: Standard PostgreSQL Metrics**
- Can be replaced with postgres_exporter built-in collectors
- Examples: database size, cache hit ratio, table bloat

**Category B: Application-Specific Metrics**
- Need to migrate to sql_exporter
- Examples: business KPIs, custom table queries

### Step 2: Migrate Standard Metrics

For each Category A query, find the equivalent built-in collector:

```yaml
# OLD: queries.yaml
pg_database_size:
  query: "SELECT datname, pg_database_size(datname) FROM pg_database"
  # ...

# NEW: Enable built-in collector (already enabled by default)
# Provides: pg_database_size_bytes{datname="..."}
```

```yaml
# OLD: queries.yaml
pg_transaction_wraparound:
  query: "SELECT datname, age(datfrozenxid) FROM pg_database"
  # ...

# NEW: docker-compose.yml
postgres_exporter:
  command:
    - "--collector.database_wraparound"
# Provides: pg_database_wraparound_age{datname="..."}
```

### Step 3: Migrate Application Metrics

For each Category B query, convert to sql_exporter format:

**Before (queries.yaml):**
```yaml
pg_chinook_sales:
  query: |
    SELECT
      "BillingCountry" as country,
      SUM("Total") as total
    FROM chinook."Invoice"
    GROUP BY "BillingCountry"
  metrics:
    - country:
        usage: "LABEL"
    - total:
        usage: "COUNTER"
```

**After (sql_exporter.yml):**
```yaml
jobs:
  - name: "chinook_metrics"
    connections:
      - 'postgres://app:password@postgres:5432/chinook'
    queries:
      - name: "chinook_sales_by_country"
        help: "Total sales by country"
        labels:
          - "country"
        values:
          - "total"
        query: |
          SELECT
            "BillingCountry" as country,
            SUM("Total") as total
          FROM chinook."Invoice"
          GROUP BY "BillingCountry"
```

### Step 4: Update Prometheus Queries

Update your Prometheus queries and dashboards to use new metric names:

**Before:**
```promql
# Custom query metric
pg_chinook_sales_total{country="USA"}
```

**After:**
```promql
# sql_exporter metric
chinook_sales_by_country_total{country="USA"}
```

### Step 5: Deploy and Test

1. Deploy both exporters alongside existing setup
2. Verify metrics are being collected
3. Update Grafana dashboards
4. Update alert rules
5. Test for 24-48 hours
6. Remove queries.yaml configuration
7. Clean up old metrics from Prometheus

### Step 6: Monitor the Migration

```promql
# Verify postgres_exporter is working
up{job="postgres-system"} == 1

# Verify sql_exporter is working
up{job="postgres-application"} == 1

# Compare old vs new metrics during transition
rate(pg_custom_metric[5m])  # Old
rate(new_custom_metric[5m])  # New
```

---

## Comparison Matrix

| Feature | queries.yaml | Built-in Collectors | sql_exporter |
|---------|--------------|-------------------|--------------|
| **Performance** | Moderate (YAML parsing) | Excellent (compiled) | Good (dedicated tool) |
| **Flexibility** | High (any SQL) | Low (fixed collectors) | Very High (any SQL) |
| **Maintenance** | Manual | Automatic updates | Configuration-driven |
| **Multi-Database** | PostgreSQL only | PostgreSQL only | All SQL databases |
| **Learning Curve** | Low | Very Low | Moderate |
| **Production Ready** | No (deprecated) | Yes | Yes |
| **Application Metrics** | Yes | No | Yes |
| **System Metrics** | Yes | Yes | Limited |
| **Official Support** | Deprecated | Yes | Community |

---

## Why This Demo Uses queries.yaml

Despite being deprecated, this demo intentionally uses `queries.yaml` because:

### Educational Benefits

1. **Transparency**: You see exactly what SQL produces which metrics
2. **Experimentation**: Easy to modify and test new queries
3. **Comprehensive**: Demonstrates all metric types (LABEL, GAUGE, COUNTER)
4. **Self-contained**: Everything in one repository
5. **No dependencies**: No need to deploy multiple exporters

### Learning Path

```
1. Learn with queries.yaml (this demo)
   ↓
2. Understand metric concepts
   ↓
3. Move to production with built-in collectors + sql_exporter
```

### Production Migration

When you're ready for production:
- Keep the SQL query knowledge
- Apply it to sql_exporter for application metrics
- Use built-in collectors for standard PostgreSQL metrics
- Get better performance and maintainability

---

## Additional Resources

### Official Documentation

- [postgres_exporter GitHub](https://github.com/prometheus-community/postgres_exporter)
- [sql_exporter GitHub](https://github.com/burningalchemist/sql_exporter)
- [Prometheus Best Practices](https://prometheus.io/docs/practices/naming/)

### Further Reading

- [PostgreSQL Monitoring Guide](https://www.postgresql.org/docs/current/monitoring.html)
- [Prometheus Exporter Best Practices](https://prometheus.io/docs/instrumenting/writing_exporters/)
- [Database Reliability Engineering](https://www.oreilly.com/library/view/database-reliability-engineering/9781491925935/)

### Community

- [Prometheus Community Forums](https://prometheus.io/community/)
- [PostgreSQL Mailing Lists](https://www.postgresql.org/list/)
- [r/PrometheusMonitoring](https://www.reddit.com/r/PrometheusMonitoring/)

---

## Conclusion

The evolution from queries.yaml to built-in collectors and sql_exporter represents the maturation of the PostgreSQL monitoring ecosystem. While this demo uses the deprecated approach for educational purposes, understanding all three options empowers you to choose the right tool for each production scenario.

**Remember:**
- **Learning**: queries.yaml is perfect
- **Production system metrics**: Use postgres_exporter built-in collectors
- **Production application metrics**: Use sql_exporter
- **Best of both worlds**: Deploy both exporters together

The SQL skills you learn here transfer directly to sql_exporter, making this demo a perfect stepping stone to production monitoring architectures.
