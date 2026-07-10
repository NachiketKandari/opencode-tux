"""
batch_validate.py — BATCH_VALIDATE Service

Converts batch_validate.pc (221 lines Pro*C → ~120 lines Python).
SQL preserved exactly from the original .pc file.

Pattern: Cursor-based validation with row-level error tracking.
"""

from typing import Any

from batch.base import BatchProcess
from batch.log import get_logger


class ValidateService(BatchProcess):
    name = "BATCH_VALIDATE"

    def __init__(self):
        self.batch_id: int = 0

    async def run(self, conn) -> dict[str, Any]:
        log = get_logger()
        cursor = conn.cursor()

        # Resolve batch_id — SQL preserved from batch_validate.pc:123-125
        if not self.batch_id:
            await cursor.execute(
                "SELECT MAX(ingest_batch_id) FROM posts_staging"
            )
            row = await cursor.fetchone()
            self.batch_id = row[0] if row[0] else 0

        log.info("batch.validate.start", batch_id=self.batch_id)

        valid_count = 0
        invalid_count = 0
        empty_title_count = 0
        empty_body_count = 0
        short_body_count = 0

        # Cursor SELECT — SQL preserved from batch_validate.pc:45-49
        await cursor.execute(
            "SELECT id, user_id, title, body "
            "FROM posts_staging "
            "WHERE ingest_status = 'NEW' "
            "  AND ingest_batch_id = :h_batch_id",
            {"h_batch_id": self.batch_id},
        )

        # Fetch loop — equivalent to EXEC SQL FETCH c_staging INTO :hv
        rows = await cursor.fetchall()
        for row in rows:
            post_id, user_id, title, body = row[0], row[1], row[2], row[3]

            valid, reason = self._validate(title, body)

            if valid:
                valid_count += 1
                # SQL preserved from batch_validate.pc:167-169
                await cursor.execute(
                    "UPDATE posts_staging "
                    "SET ingest_status = 'VALIDATED' "
                    "WHERE id = :h_post_id",
                    {"h_post_id": post_id},
                )
            else:
                invalid_count += 1
                if "R1" in reason:
                    empty_title_count += 1
                if "R2" in reason:
                    empty_body_count += 1
                if "R3" in reason:
                    short_body_count += 1

                # SQL preserved from batch_validate.pc:178-180
                await cursor.execute(
                    "UPDATE posts_staging "
                    "SET ingest_status = 'ERROR' "
                    "WHERE id = :h_post_id",
                    {"h_post_id": post_id},
                )

                log.info("batch.validate.fail", post_id=post_id, reason=reason)

            # Commit every 200 rows — SQL preserved from batch_validate.pc:187-188
            total = valid_count + invalid_count
            if total % 200 == 0:
                await conn.commit()

        await conn.commit()

        total = valid_count + invalid_count

        # SQL preserved from batch_validate.pc:197-198
        await self._write_batch_log(conn, "SUCCESS", total)

        return {
            "total": total,
            "valid": valid_count,
            "invalid": invalid_count,
            "empty_title": empty_title_count,
            "empty_body": empty_body_count,
            "short_body": short_body_count,
            "batch_id": self.batch_id,
            "rows_processed": total,
        }

    @staticmethod
    def _validate(title: str, body: str) -> tuple[bool, str]:
        """Validation rules — identical logic to batch_validate.pc:92-110."""
        if not title or len(title) == 0:
            return False, "R1: empty title"
        if not body or len(body) == 0:
            return False, "R2: empty body"
        if len(body) < 20:
            return False, f"R3: body too short ({len(body)} chars)"
        return True, "OK"

    async def _write_batch_log(self, conn, status: str, rows: int, error: str = None) -> None:
        cursor = conn.cursor()
        # SQL preserved from batch_validate.pc:197-198
        await cursor.execute(
            "INSERT INTO batch_log (service_name, status, rows_processed) "
            "VALUES ('BATCH_VALIDATE', :status, :rows)",
            {"status": status, "rows": rows},
        )
        await cursor.close()


def main():
    import sys
    from batch.cli import run_service

    svc = ValidateService()
    if len(sys.argv) > 1:
        svc.batch_id = int(sys.argv[1])

    run_service(ValidateService, "BATCH_VALIDATE")


if __name__ == "__main__":
    main()
