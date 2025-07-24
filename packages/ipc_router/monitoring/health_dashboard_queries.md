# Health Monitoring Dashboard Queries

## Heartbeat Metrics

### Heartbeat Rate by Service
```promql
# Total heartbeats per second by service
rate(ipc_heartbeats_received_total[1m])

# Heartbeat rate by service and instance
sum(rate(ipc_heartbeats_received_total[1m])) by (service_name, instance_id)
```

### Heartbeat Processing Time
```promql
# Average heartbeat processing time by service
histogram_quantile(0.95, sum(rate(ipc_heartbeat_processing_duration_seconds_bucket[5m])) by (service_name, le))

# Heartbeat processing time P50/P95/P99
histogram_quantile(0.5, sum(rate(ipc_heartbeat_processing_duration_seconds_bucket[5m])) by (le))
histogram_quantile(0.95, sum(rate(ipc_heartbeat_processing_duration_seconds_bucket[5m])) by (le))
histogram_quantile(0.99, sum(rate(ipc_heartbeat_processing_duration_seconds_bucket[5m])) by (le))
```

## Instance Health Metrics

### Instance Routing Success Rate
```promql
# Success rate by instance
sum(rate(instance_routing_duration_seconds_count{success="true"}[5m])) by (service_name, instance_id)
/
sum(rate(instance_routing_duration_seconds_count[5m])) by (service_name, instance_id)
```

### Instance Failure Rate
```promql
# Failures by error code
sum(rate(ipc_instance_routing_failures_total[5m])) by (service_name, instance_id, error_code)

# Top failing instances
topk(10, sum(rate(ipc_instance_routing_failures_total[5m])) by (instance_id))
```

### Instance Response Time
```promql
# P95 response time by instance
histogram_quantile(0.95, sum(rate(instance_routing_duration_seconds_bucket[5m])) by (service_name, instance_id, le))

# Average response time comparison
avg(rate(instance_routing_duration_seconds_sum[5m])) by (service_name, instance_id)
/
avg(rate(instance_routing_duration_seconds_count[5m])) by (service_name, instance_id)
```

## Health Status Changes

### Service Status Change Events
```promql
# Count of status changes per service
sum(increase(service_status_changed_total[1h])) by (service_name)

# Alert on frequent status changes (flapping)
sum(increase(service_status_changed_total[5m])) by (service_name, instance_id) > 3
```

## Alert Rules

### Missing Heartbeats Alert
```yaml
groups:
- name: health_alerts
  rules:
  - alert: MissingHeartbeats
    expr: |
      rate(ipc_heartbeats_received_total[2m]) == 0
      and
      up{job="ipc_router"} == 1
    for: 3m
    labels:
      severity: warning
    annotations:
      summary: "No heartbeats received for {{ $labels.service_name }}"
      description: "Service {{ $labels.service_name }} instance {{ $labels.instance_id }} has not sent heartbeats for 3 minutes"

  - alert: HighInstanceFailureRate
    expr: |
      sum(rate(ipc_instance_routing_failures_total[5m])) by (service_name, instance_id)
      /
      sum(rate(instance_routing_duration_seconds_count[5m])) by (service_name, instance_id)
      > 0.1
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "High failure rate for instance {{ $labels.instance_id }}"
      description: "Instance {{ $labels.instance_id }} of service {{ $labels.service_name }} has >10% failure rate"

  - alert: SlowHeartbeatProcessing
    expr: |
      histogram_quantile(0.95, sum(rate(ipc_heartbeat_processing_duration_seconds_bucket[5m])) by (service_name, le)) > 0.1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Slow heartbeat processing for {{ $labels.service_name }}"
      description: "P95 heartbeat processing time for {{ $labels.service_name }} is above 100ms"
```

## Grafana Dashboard JSON Snippets

### Heartbeat Status Panel
```json
{
  "title": "Service Instance Health Status",
  "targets": [
    {
      "expr": "count by (service_name) (up{job=\"service_instances\"} == 1)",
      "legendFormat": "{{ service_name }} - Healthy"
    },
    {
      "expr": "count by (service_name) (up{job=\"service_instances\"} == 0)",
      "legendFormat": "{{ service_name }} - Unhealthy"
    }
  ],
  "type": "stat"
}
```

### Instance Routing Heatmap
```json
{
  "title": "Instance Response Time Heatmap",
  "targets": [
    {
      "expr": "sum(rate(instance_routing_duration_seconds_bucket[5m])) by (le)",
      "format": "heatmap"
    }
  ],
  "type": "heatmap"
}
```
