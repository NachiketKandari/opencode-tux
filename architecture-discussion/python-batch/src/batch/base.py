"""BatchProcess base class — the template for every batch service."""

import time
from typing import Any

from batch.log import get_logger
from batch.metrics import batch_duration, batch_rows, batch_runs


class BatchProcess:
    """Base class for all batch services.

    Lifecycle:  init_db() → run() → done()

    The framework handles:
      - Connection acquisition/release
      - Transaction commit/rollback
      - batch_log insert
      - Prometheus counters + histograms
      - Structured logging with request_id
    """

    name: str = ""

    async def init_db(self, conn) -> None:
        """One-time setup before run(). Override if needed."""
        pass

    async def run(self, conn) -> dict[str, Any]:
        """The batch logic. MUST be overridden.

        Receives an active oracledb AsyncConnection.
        Returns a result dict (e.g. {"ingested": 5000, "batch_id": 123}).
        """
        raise NotImplementedError

    async def done(self, conn) -> None:
        """Cleanup after run(). Override if needed."""
        pass

    # ── Internal helpers used by cli.py ──────────────────────────────────

    async def _execute(self, conn) -> dict[str, Any]:
        """Full lifecycle with instrumentation. Called by the CLI layer."""
        log = get_logger()

        try:
            await self.init_db(conn)

            start = time.monotonic()
            log.info("batch.run.start", service=self.name)
            result = await self.run(conn)
            elapsed = time.monotonic() - start

            rows = result.get("rows_processed", 0)
            await self._write_batch_log(conn, "SUCCESS", rows)
            await conn.commit()

            batch_runs.labels(service=self.name, status="success").inc()
            batch_duration.labels(service=self.name).observe(elapsed)
            if rows:
                batch_rows.labels(service=self.name).inc(rows)

            log.info(
                "batch.run.complete",
                service=self.name,
                duration_ms=round(elapsed * 1000),
                **result,
            )
            return result

        except Exception as exc:
            await conn.rollback()
            rows = getattr(self, "_rows_so_far", 0)
            await self._write_batch_log(conn, "FAILED", rows, str(exc))

            batch_runs.labels(service=self.name, status="failed").inc()
            log.exception("batch.run.failed", service=self.name, error=str(exc))
            raise

        finally:
            await self.done(conn)

    async def _write_batch_log(
        self, conn, status: str, rows: int, error: str | None = None
    ) -> None:
        """Insert a row into batch_log."""
        sql = (
            "INSERT INTO batch_log (service_name, status, rows_processed, error_message) "
            "VALUES (:svc, :status, :rows, :error)"
        )
        cursor = conn.cursor()
        await cursor.execute(
            sql,
            {"svc": self.name, "status": status, "rows": rows, "error": error},
        )
        await cursor.close()
