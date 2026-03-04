#### vector.yaml
Vector pipeline configuration with three stages:

**1. Source - Docker Log Collection**
```yaml
sources:
  docker_logs:
    type: docker_logs
    docker_host: unix:///var/run/docker.sock
```
Collects logs from all Docker containers via the Docker socket, including container metadata (name, image, labels).

**2. Transform - Log Enrichment**
```yaml
transforms:
  parse_logs:    # Parse JSON logs, extract container info
  add_labels:    # Add component and job labels for filtering
```
- Parses JSON-formatted logs from applications
- Extracts container names and images
- Adds semantic labels (component, job, namespace)
- Identifies components: database, monitoring, visualization

**3. Sink - Send to Loki**
```yaml
sinks:
  loki:
    endpoint: http://loki:3100
    labels:
      container: "{{ container_name }}"
      component: "{{ labels.component }}"
      job: "{{ labels.job }}"
```
- Batches logs for efficient transmission
- Applies labels for Loki stream organization
- Includes retry logic and buffering for reliability

**Container-to-Job Mapping**:
- `pod_postgres` → job: postgres, component: database
- `pod_exporter` → job: postgres_exporter, component: monitoring
- `pod_prometheus` → job: prometheus, component: monitoring
- `pod_grafana` → job: grafana, component: visualization
- `pod_loki` → job: loki, component: monitoring
- `pod_vector` → job: vector, component: monitoring

#### Vector Metrics

Vector exposes its own metrics at http://localhost:8686/metrics in Prometheus format:

**Key Metrics**:
- `vector_component_received_events_total` - Events received by component
- `vector_component_sent_events_total` - Events sent successfully
- `vector_component_errors_total` - Processing errors
- `vector_buffer_events` - Current buffer size
- `vector_utilization` - CPU/memory utilization

Add these to Prometheus to monitor Vector's health.

#### Why Vector.dev Instead of Promtail?

This stack uses **Vector** rather than Promtail for several advantages:

1. **Active Development**: Vector is actively maintained; Promtail's development has slowed
2. **Performance**: Rust-based implementation with lower resource usage
3. **Flexibility**: Single tool for logs, metrics, and traces
4. **Transforms**: Powerful VRL (Vector Remap Language) for log processing
5. **Reliability**: Built-in buffering, retries, and delivery guarantees
6. **Observability**: Rich internal metrics for monitoring the pipeline itself

Vector has become the recommended approach for modern log collection pipelines.
