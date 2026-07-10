"""
batch_ingest.py — BATCH_INGEST Service

Converts batch_ingest.pc (182 lines Pro*C → ~100 lines Python).
SQL preserved exactly from the original .pc file.

Pattern: Bulk array insert with batch commit every 500 rows.
"""

import time
from typing import Any

from batch.base import BatchProcess
from batch.log import get_logger


class IngestService(BatchProcess):
    name = "BATCH_INGEST"

    def __init__(self):
        self.input_data: str = ""
        self.total_ingested = 0
        self.batch_id = 0

    async def run(self, conn) -> dict[str, Any]:
        log = get_logger()
        cursor = conn.cursor()

        record_count = 0
        total_in_batch = 0

        self.batch_id = int(time.time())
        self.total_ingested = 0

        batch_rows: list[dict] = []

        for line in self.input_data.split("\n"):
            line = line.strip()
            if not line:
                continue

            parts = line.split("|")
            if len(parts) != 4:
                continue

            uid, pid, title, body = parts[0], parts[1], parts[2], parts[3]

            batch_rows.append({
                "pid": int(pid),
                "uid": int(uid),
                "title": title[:255],
                "body": body[:1023],
                "batch_id": self.batch_id,
            })
            record_count += 1
            total_in_batch += 1

            # Flush when array is full (100 rows)
            if len(batch_rows) >= 100:
                await self._flush_batch(cursor, batch_rows)
                self.total_ingested += len(batch_rows)
                batch_rows = []

                # Commit every 500 records
                if total_in_batch >= 500:
                    await conn.commit()
                    log.info(
                        "batch.ingest.commit",
                        total=self.total_ingested,
                    )
                    total_in_batch = 0

        # Final partial batch flush
        if batch_rows:
            await self._flush_batch(cursor, batch_rows)
            self.total_ingested += len(batch_rows)
            await conn.commit()
            log.info(
                "batch.ingest.final_flush",
                flushed=len(batch_rows),
                total=self.total_ingested,
            )

        await self._write_batch_log(conn, "SUCCESS", self.total_ingested)

        return {
            "ingested": self.total_ingested,
            "batch_id": self.batch_id,
            "rows_processed": self.total_ingested,
        }

    async def _flush_batch(self, cursor, rows: list[dict]) -> None:
        """Bulk insert a batch of rows into posts_staging."""
        # SQL preserved EXACTLY from batch_ingest.pc:133-135
        sql = (
            "INSERT INTO posts_staging (id, user_id, title, body, ingest_batch_id) "
            "VALUES (:h_post_id, :h_user_id, :h_title, :h_body, :h_batch_id)"
        )
        params = [
            {
                "h_post_id": r["pid"],
                "h_user_id": r["uid"],
                "h_title": r["title"],
                "h_body": r["body"],
                "h_batch_id": r["batch_id"],
            }
            for r in rows
        ]
        await cursor.executemany(sql, params)

    async def _write_batch_log(self, conn, status: str, rows: int) -> None:
        """Insert a row into batch_log — SQL preserved from .pc:165-166."""
        cursor = conn.cursor()
        # SQL preserved EXACTLY from batch_ingest.pc:165-166
        await cursor.execute(
            "INSERT INTO batch_log (service_name, status, rows_processed) "
            "VALUES ('BATCH_INGEST', :status, :rows)",
            {"status": status, "rows": rows},
        )
        await cursor.close()


def main():
    """Entry point for batch-ingest CLI."""
    import os

    from batch.cli import run_service

    svc = IngestService()
    data_file = os.environ.get("INPUT_FILE", "data/input.dat")
    try:
        with open(data_file) as f:
            svc.input_data = f.read()
    except FileNotFoundError:
        # Demo data
        svc.input_data = (
            "1|1|sunt aut facere repellat provident occaecati excepturi optio|quia et suscipit\n"
            "1|2|qui est esse rerum tempore vitae|est rerum tempore vitae sequi sint\n"
            "2|3|ea molestias quasi exercitationem repellat|et iusto sed quo iure\n"
        )

    run_service(IngestService, "BATCH_INGEST")


if __name__ == "__main__":
    main()
