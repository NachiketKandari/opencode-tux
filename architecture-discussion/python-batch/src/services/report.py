"""
batch_report.py — BATCH_REPORT Service

Converts batch_report.pc (189 lines Pro*C → ~130 lines Python).
SQL preserved exactly from the original .pc file.

Pattern: Read-only reporting with aggregate queries.
"""

from typing import Any

from batch.base import BatchProcess
from batch.log import get_logger


class ReportService(BatchProcess):
    name = "BATCH_REPORT"

    async def run(self, conn) -> dict[str, Any]:
        log = get_logger()
        cursor = conn.cursor()

        # 1. Overall Statistics — SQL preserved from batch_report.pc:102-105
        await cursor.execute(
            "SELECT COUNT(*), COUNT(DISTINCT user_id), "
            "       COALESCE(SUM(word_count), 0) "
            "FROM posts"
        )
        row = await cursor.fetchone()
        total_posts, total_users, total_words = row[0], row[1], row[2]

        avg_words_per_post = 0.0
        avg_posts_per_user = 0.0

        if total_posts > 0:
            # SQL preserved from batch_report.pc:108-110
            await cursor.execute(
                "SELECT CAST(SUM(word_count) AS REAL) / CAST(COUNT(*) AS REAL) "
                "FROM posts"
            )
            avg_words_per_post = (await cursor.fetchone())[0]

            # SQL preserved from batch_report.pc:112-114
            await cursor.execute(
                "SELECT CAST(COUNT(*) AS REAL) / CAST(COUNT(DISTINCT user_id) AS REAL) "
                "FROM posts"
            )
            avg_posts_per_user = (await cursor.fetchone())[0]

        # 2. Top User — SQL preserved from batch_report.pc:122-126
        await cursor.execute(
            "SELECT user_id, post_count, total_words "
            "FROM post_stats "
            "ORDER BY post_count DESC "
            "LIMIT 1"
        )
        top = await cursor.fetchone()
        if top:
            top_user_id, top_user_posts, top_user_words = top[0], top[1], top[2]
        else:
            top_user_id, top_user_posts, top_user_words = 0, 0, 0

        # 3. Build report string
        report = (
            "╔══════════════════════════════════════════════╗\n"
            "║     BATCH PROCESSING REPORT                  ║\n"
            "╠══════════════════════════════════════════════╣\n"
            "║ OVERALL STATISTICS                          ║\n"
            f"║   Total Posts:      {total_posts:>6}                  ║\n"
            f"║   Unique Users:     {total_users:>6}                  ║\n"
            f"║   Total Words:      {total_words:>6}                  ║\n"
            f"║   Avg Words/Post:   {avg_words_per_post:>8.2f}               ║\n"
            f"║   Avg Posts/User:   {avg_posts_per_user:>8.2f}               ║\n"
            "╠══════════════════════════════════════════════╣\n"
            f"║ TOP USER (user_id={top_user_id})                      ║\n"
            f"║   Posts:            {top_user_posts:>6}                  ║\n"
            f"║   Total Words:      {top_user_words:>6}                  ║\n"
            "╠══════════════════════════════════════════════╣\n"
            "║ BATCH LOG (recent runs)                     ║\n"
        )

        # 4. Batch Log — SQL preserved from batch_report.pc:53-58
        await cursor.execute(
            "SELECT service_name, status, rows_processed, "
            "       COALESCE(completed_at, started_at) "
            "FROM batch_log "
            "ORDER BY batch_id DESC "
            "LIMIT 20"
        )
        log_rows = await cursor.fetchall()
        for log_row in log_rows:
            svc, status, rows_, tstamp = log_row
            report += (
                f"║   {svc:<16} {status:<8} {rows_:>5} rows {tstamp or '':20} ║\n"
            )

        report += "╚══════════════════════════════════════════════╝\n"

        # 5. Log this report run — SQL preserved from batch_report.pc:181-182
        await cursor.execute(
            "INSERT INTO batch_log (service_name, status, rows_processed) "
            "VALUES ('BATCH_REPORT', 'SUCCESS', :h_total_posts)",
            {"h_total_posts": total_posts},
        )
        await conn.commit()

        log.info("batch.report.complete", posts=total_posts, users=total_users)

        # Print the report
        print(report)

        return {
            "total_posts": total_posts,
            "total_users": total_users,
            "total_words": total_words,
            "top_user_id": top_user_id,
            "rows_processed": total_posts,
        }


def main():
    from batch.cli import run_service

    run_service(ReportService, "BATCH_REPORT")


if __name__ == "__main__":
    main()
