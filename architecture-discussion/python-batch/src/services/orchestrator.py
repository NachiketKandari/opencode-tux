"""
batch_orchestrator.py — Pipeline Orchestrator

Converts batch_orchestrator.c (273 lines C → ~120 lines Python).
Chains services: BATCH_INGEST → BATCH_VALIDATE → BATCH_TRANSFORM → BATCH_REPORT

In a real Tuxedo system, this would be the batch client that calls services
via tpcall(). In idiomatic Python, it's a simple async pipeline.
"""

import asyncio
from typing import Any

from batch.log import get_logger, setup_logging
from batch.db import init_db_pool, get_connection, release_connection

from services.ingest import IngestService
from services.validate import ValidateService
from services.transform import TransformService
from services.report import ReportService


async def run_pipeline(
    input_data: str,
    batch_id: int | None = None,
    dsn: str = "localhost:1521/XEPDB1",
    user: str = "batch_user",
    password: str = "batch_pass",
) -> dict[str, Any]:
    """Execute the full batch pipeline.

    Flow:
      1. Initialize database pool
      2. BATCH_INGEST    — bulk load input data
      3. BATCH_VALIDATE  — validate staged records
      4. BATCH_TRANSFORM — transform & aggregate
      5. BATCH_REPORT    — generate summary report
    """
    setup_logging("BATCH_ORCHESTRATOR")
    log = get_logger()

    await init_db_pool(dsn=dsn, user=user, password=password)

    conn = await get_connection()
    results: dict[str, Any] = {}

    try:
        # ── Phase 1: BATCH_INGEST ──
        log.info("pipeline.phase", phase=1, service="BATCH_INGEST")
        ingest = IngestService()
        ingest.input_data = input_data
        await ingest._execute(conn)
        results["ingest"] = {"status": "OK", "batch_id": ingest.batch_id}
        batch_id = batch_id or ingest.batch_id
        log.info("pipeline.phase.complete", phase=1, **results["ingest"])

        # ── Phase 2: BATCH_VALIDATE ──
        log.info("pipeline.phase", phase=2, service="BATCH_VALIDATE")
        validate = ValidateService()
        validate.batch_id = batch_id
        results["validate"] = await validate._execute(conn)
        log.info("pipeline.phase.complete", phase=2, **results["validate"])

        # ── Phase 3: BATCH_TRANSFORM ──
        log.info("pipeline.phase", phase=3, service="BATCH_TRANSFORM")
        transform = TransformService()
        transform.batch_id = batch_id
        results["transform"] = await transform._execute(conn)
        log.info("pipeline.phase.complete", phase=3, **results["transform"])

        # ── Phase 4: BATCH_REPORT ──
        log.info("pipeline.phase", phase=4, service="BATCH_REPORT")
        report = ReportService()
        results["report"] = await report._execute(conn)
        log.info("pipeline.phase.complete", phase=4, **results["report"])

    except Exception as exc:
        log.exception("pipeline.failed", error=str(exc))
        results["status"] = "FAILED"
        results["error"] = str(exc)
        raise

    finally:
        await release_connection(conn)

    results["status"] = "SUCCESS"
    return results


def main():
    """CLI entry point: batch-orchestrator."""
    import os
    import sys

    data_file = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "INPUT_FILE", "data/input.dat"
    )

    # Load input data
    try:
        with open(data_file) as f:
            input_data = f.read()
    except FileNotFoundError:
        # Demo data — identical to batch_orchestrator.c:141-151
        input_data = (
            "1|1|sunt aut facere repellat provident occaecati excepturi optio|"
            "quia et suscipit suscipit recusandae consequuntur expedita et cum\n"
            "1|2|qui est esse rerum tempore vitae|"
            "est rerum tempore vitae sequi sint nihil reprehenderit\n"
            "2|3|ea molestias quasi exercitationem repellat|"
            "et iusto sed quo iure voluptatem occaecati omnis eligendi aut\n"
            "2|4|eum et est occaecati ullam saepe|"
            "ullam et saepe reiciendis voluptatem adipisci sit amet\n"
            "3|5|nesciunt quas odio dolorem tempora|"
            "repudiandae veniam quaerat sunt sed alias aut fugiat sit\n"
            "3|6|dolorem eum magni eos aperiam quia|"
            "qui ratione voluptatem sequi nesciunt neque porro quisquam est\n"
            "4|7|magnam facilis autem voluptatem|"
            "dolore placeat quibusdam ea quo voluptas nulla veniam nisi\n"
            "4|8|dolorem dolore est ipsam aspernatur|"
            "ut aspernatur corporis harum nihil quis provident sequi\n"
            "5|9|nesciunt iure omnis dolorem|"
            "nam qui vel suscipit distinctio nihil minus explicabo ipsum\n"
            "5|10|optio molestias id quia eos|"
            "voluptatem animi nihil autem numquam et voluptatem nulla et\n"
        )

    # Run the pipeline
    dsn = os.environ.get("ORACLE_DSN", "localhost:1521/XEPDB1")
    user = os.environ.get("ORACLE_USER", "batch_user")
    password = os.environ.get("ORACLE_PWD", "batch_pass")

    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║     BATCH PROCESSING PIPELINE (Python)          ║")
    print("║     oracledb + structlog + prometheus_client    ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    asyncio.run(run_pipeline(input_data, dsn=dsn, user=user, password=password))

    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║     BATCH PROCESSING COMPLETE                   ║")
    print("╚══════════════════════════════════════════════════╝")


if __name__ == "__main__":
    main()
