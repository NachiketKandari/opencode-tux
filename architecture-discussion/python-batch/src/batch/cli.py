"""CLI factory — one typer entry point per batch service."""

import asyncio
from typing import Optional

import typer


def run_service(service_class, service_name: str, metrics_port: Optional[int] = None):
    """Shared entry point for all batch services.

    1. Start metrics server if requested
    2. Init DB pool from env vars
    3. Set up logging
    4. Execute the BatchProcess lifecycle
    """
    import os

    from batch.db import init_db_pool, get_connection, release_connection
    from batch.log import setup_logging, get_logger

    setup_logging(service_name)

    if metrics_port:
        from batch.metrics import start_metrics_server

        start_metrics_server(metrics_port)

    async def _run():
        dsn = os.environ.get("ORACLE_DSN", "localhost:1521/XEPDB1")
        user = os.environ.get("ORACLE_USER", "batch_user")
        password = os.environ.get("ORACLE_PWD", "batch_pass")

        await init_db_pool(dsn=dsn, user=user, password=password)

        service = service_class()
        conn = await get_connection()
        log = get_logger()

        try:
            await service.init_db(conn)
            log.info("batch.start", name=service_name)
            result = await service.run(conn)
            await conn.commit()
            log.info("batch.complete", name=service_name, result=result)
        except Exception:
            await conn.rollback()
            log.exception("batch.failed", name=service_name)
            raise
        finally:
            await service.done(conn)
            await release_connection(conn)

    asyncio.run(_run())
