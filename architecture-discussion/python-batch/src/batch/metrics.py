"""Prometheus metrics — counters, histograms, gauges for batch observability."""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

batch_runs = Counter(
    "batch_runs_total",
    "Batch process executions",
    ["service", "status"],
)

batch_duration = Histogram(
    "batch_duration_seconds",
    "Batch run duration",
    ["service"],
    buckets=[1, 5, 15, 30, 60, 120, 300, 600, 1800],
)

batch_rows = Counter(
    "batch_rows_processed_total",
    "Rows processed by batch service",
    ["service"],
)

db_pool_available = Gauge(
    "db_pool_available",
    "Available connections in the pool",
)


def start_metrics_server(port: int = 9090) -> None:
    """Start the Prometheus HTTP scrape endpoint."""
    start_http_server(port)
