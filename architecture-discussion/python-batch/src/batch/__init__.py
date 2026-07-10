"""Batch processing framework — oracledb + structlog + prometheus_client."""

from batch.base import BatchProcess
from batch.db import init_db_pool, get_connection, release_connection, transactional, Pool
from batch.log import setup_logging, get_logger
from batch.metrics import (
    batch_runs,
    batch_duration,
    batch_rows,
    db_pool_available,
    start_metrics_server,
)

__all__ = [
    "BatchProcess",
    "init_db_pool",
    "get_connection",
    "release_connection",
    "transactional",
    "Pool",
    "setup_logging",
    "get_logger",
    "batch_runs",
    "batch_duration",
    "batch_rows",
    "db_pool_available",
    "start_metrics_server",
]
