"""Structured JSON logging via structlog."""

import structlog


def setup_logging(service_name: str, level: str = "INFO") -> None:
    """Configure structlog for JSON output. Call once at process start."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    # Bind service name so every log line carries it.
    structlog.get_logger().bind(service=service_name)


def get_logger(**kwargs) -> structlog.stdlib.BoundLogger:
    """Return a logger with optional extra context."""
    logger = structlog.get_logger()
    if kwargs:
        logger = logger.bind(**kwargs)
    return logger
