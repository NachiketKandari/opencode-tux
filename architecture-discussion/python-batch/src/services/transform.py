"""
batch_transform.py — BATCH_TRANSFORM Service

Converts batch_transform.pc (227 lines Pro*C → ~140 lines Python).
SQL preserved exactly from the original .pc file.

Pattern: Cursor-based Read-Transform-Write with aggregate computation.
"""

from typing import Any

from batch.base import BatchProcess
from batch.log import get_logger


class TransformService(BatchProcess):
    name = "BATCH_TRANSFORM"

    def __init__(self):
        self.batch_id: int = 0
        self.transformed_count = 0
        self.skip_count = 0
        self.error_count = 0

    async def run(self, conn) -> dict[str, Any]:
        log = get_logger()
        cursor = conn.cursor()

        # Resolve batch_id — SQL preserved from batch_transform.pc:124-126
        if not self.batch_id:
            await cursor.execute(
                "SELECT MAX(ingest_batch_id) FROM posts_staging "
                "WHERE ingest_status = 'VALIDATED'"
            )
            row = await cursor.fetchone()
            self.batch_id = row[0] if row[0] else 0

        log.info("batch.transform.start", batch_id=self.batch_id)

        self.transformed_count = 0
        self.skip_count = 0
        self.error_count = 0

        # Cursor SELECT — SQL preserved from batch_transform.pc:55-59
        await cursor.execute(
            "SELECT id, user_id, title, body "
            "FROM posts_staging "
            "WHERE ingest_status = 'VALIDATED' "
            "  AND ingest_batch_id = :h_batch_id",
            {"h_batch_id": self.batch_id},
        )

        rows = await cursor.fetchall()
        for row in rows:
            post_id, user_id, title, body = row[0], row[1], row[2], row[3]

            word_count = self._compute_word_count(body)

            # Skip records with no meaningful content (< 5 words)
            if word_count < 5:
                self.skip_count += 1
                # SQL preserved from batch_transform.pc:161-163
                await cursor.execute(
                    "UPDATE posts_staging "
                    "SET ingest_status = 'TRANSFORMED' "
                    "WHERE id = :h_post_id",
                    {"h_post_id": post_id},
                )
                continue

            # Insert into final posts table — SQL preserved from .pc:168-169
            await cursor.execute(
                "INSERT INTO posts (id, user_id, title, body, word_count) "
                "VALUES (:h_post_id, :h_user_id, :h_title, :h_body, :h_word_count)",
                {
                    "h_post_id": post_id,
                    "h_user_id": user_id,
                    "h_title": title,
                    "h_body": body,
                    "h_word_count": word_count,
                },
            )

            # Aggregate query — SQL preserved from batch_transform.pc:172-175
            await cursor.execute(
                "SELECT COUNT(*), COALESCE(SUM(word_count), 0) "
                "FROM posts "
                "WHERE user_id = :h_user_id",
                {"h_user_id": user_id},
            )
            agg = await cursor.fetchone()
            agg_count, agg_total_words = agg[0], agg[1]

            # Upsert into post_stats — SQL preserved from batch_transform.pc:177-180
            await cursor.execute(
                "INSERT OR REPLACE INTO post_stats "
                "(user_id, post_count, total_words, avg_words) "
                "VALUES (:h_user_id, :h_agg_count, :h_agg_total_words, "
                "CAST(:h_agg_total_words AS REAL) / CAST(:h_agg_count AS REAL))",
                {
                    "h_user_id": user_id,
                    "h_agg_count": agg_count,
                    "h_agg_total_words": agg_total_words,
                },
            )

            # Mark staging record — SQL preserved from batch_transform.pc:183-185
            await cursor.execute(
                "UPDATE posts_staging "
                "SET ingest_status = 'TRANSFORMED' "
                "WHERE id = :h_post_id",
                {"h_post_id": post_id},
            )

            self.transformed_count += 1

            # Commit every 200 records — matches batch_transform.pc:190
            if self.transformed_count % 200 == 0:
                await conn.commit()
                log.info("batch.transform.progress", transformed=self.transformed_count)

        await conn.commit()

        # SQL preserved from batch_transform.pc:201-202
        await self._write_batch_log(conn, "SUCCESS", self.transformed_count)

        log.info(
            "batch.transform.complete",
            transformed=self.transformed_count,
            skipped=self.skip_count,
            errors=self.error_count,
        )

        return {
            "transformed": self.transformed_count,
            "skipped": self.skip_count,
            "errors": self.error_count,
            "batch_id": self.batch_id,
            "rows_processed": self.transformed_count,
        }

    @staticmethod
    def _compute_word_count(text: str) -> int:
        """Count words — identical logic to batch_transform.pc:98-114."""
        if not text:
            return 0
        count = 0
        in_word = False
        for ch in text:
            if ch.isspace():
                in_word = False
            elif not in_word:
                in_word = True
                count += 1
        return count

    async def _write_batch_log(self, conn, status: str, rows: int) -> None:
        cursor = conn.cursor()
        # SQL preserved from batch_transform.pc:201-202
        await cursor.execute(
            "INSERT INTO batch_log (service_name, status, rows_processed) "
            "VALUES ('BATCH_TRANSFORM', :status, :rows)",
            {"status": status, "rows": rows},
        )
        await cursor.close()


def main():
    import sys
    from batch.cli import run_service

    svc = TransformService()
    if len(sys.argv) > 1:
        svc.batch_id = int(sys.argv[1])

    run_service(TransformService, "BATCH_TRANSFORM")


if __name__ == "__main__":
    main()
