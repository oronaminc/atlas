"""Concrete Atlas metric instruments on the process-wide REGISTRY.

Importing this module registers every metric, so a process's /metrics lists
them even at zero. Counters/gauges are incremented from the hot paths;
DB-derived gauges are set at scrape time by app/api/v1/metrics.py.
"""

from app.core.metrics import REGISTRY

# --- ingest (API) ---
ingest_requests = REGISTRY.counter(
    "atlas_ingest_requests_total", "Ingest requests", ("provider", "status")
)
ingest_events = REGISTRY.counter(
    "atlas_ingest_events_total", "Alert events accepted", ("provider",)
)
ingest_duration = REGISTRY.histogram(
    "atlas_ingest_request_duration_seconds", "Ingest request latency", ("provider",)
)

# --- correlation (worker) ---
correlation_events = REGISTRY.counter(
    "atlas_correlation_events_processed_total", "Alert events correlated"
)
correlation_iterations = REGISTRY.counter(
    "atlas_correlation_iterations_total", "Correlation loop iterations", ("outcome",)
)
correlation_batch_seconds = REGISTRY.histogram(
    "atlas_correlation_batch_seconds", "correlate_pending pass duration"
)

# --- notification (worker) ---
notifications_sent = REGISTRY.counter(
    "atlas_notifications_sent_total", "Notifications sent", ("channel",)
)
notifications_failed = REGISTRY.counter(
    "atlas_notifications_failed_total", "Notification send failures", ("channel",)
)
notifications_deferred = REGISTRY.counter(
    "atlas_notifications_deferred_total", "Notifications deferred", ("reason",)
)
notifications_dead = REGISTRY.counter(
    "atlas_notifications_dead_total", "Notifications dead-lettered", ("channel",)
)
notification_send_seconds = REGISTRY.histogram(
    "atlas_notification_send_seconds", "Channel send latency", ("channel",)
)

# --- maintenance (worker) ---
retention_partitions_dropped = REGISTRY.counter(
    "atlas_retention_partitions_dropped_total", "alert_events partitions dropped"
)
maintenance_last_run = REGISTRY.gauge(
    "atlas_maintenance_last_run_timestamp_seconds", "Unix ts of last maintenance pass"
)

# --- worker health (every process) ---
worker_last_loop = REGISTRY.gauge(
    "atlas_worker_last_loop_timestamp_seconds", "Unix ts of last worker loop", ("worker",)
)
redis_up = REGISTRY.gauge("atlas_redis_up", "Redis reachable from this process (1/0)")

# --- DB-derived (set at scrape on the API) ---
correlation_backlog = REGISTRY.gauge(
    "atlas_correlation_backlog", "Uncorrelated alert_events within claim lookback"
)
correlation_oldest_seconds = REGISTRY.gauge(
    "atlas_correlation_oldest_unprocessed_seconds", "Age of oldest uncorrelated event"
)
notifications_pending = REGISTRY.gauge(
    "atlas_notifications_pending", "Claimable notifications (pending+failed)"
)
notifications_oldest_pending_seconds = REGISTRY.gauge(
    "atlas_notifications_oldest_pending_seconds", "Age of oldest claimable notification"
)
notifications_dead_gauge = REGISTRY.gauge("atlas_notifications_dead", "Dead-lettered notifications")
default_partition_rows = REGISTRY.gauge(
    "atlas_default_partition_rows", "Rows stranded in the DEFAULT partition (should be 0)"
)
rollup_lag_seconds = REGISTRY.gauge(
    "atlas_alert_stats_rollup_lag_seconds", "now - last rolled-up hourly bucket"
)
# breach-ONLY series (cardinality bound): one series per service over the cap
tenant_pending_softcap_breached = REGISTRY.gauge(
    "atlas_tenant_pending_softcap_breached",
    "1 per service whose pending queue exceeds NOTIFY_PENDING_SOFTCAP",
    ("service",),
)

# --- LLM analysis (Feature A) ---
llm_requests = REGISTRY.counter("atlas_llm_requests_total", "LLM analysis requests", ("outcome",))
llm_tokens = REGISTRY.counter("atlas_llm_tokens_total", "LLM tokens consumed")
llm_request_seconds = REGISTRY.histogram("atlas_llm_request_seconds", "LLM analysis run duration")
llm_analysis_pending = REGISTRY.gauge(
    "atlas_llm_analysis_pending", "Claimable incident-analysis jobs (pending+failed)"
)
