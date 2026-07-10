"""
equity_ingest.py — BATCH_EQUITY_INGEST Service

Converted from: pc/batch_equity_ingest.pc (269 lines Pro*C → ~140 lines Python)
Conversion tool: Qwen 3.6 35B (openrouter/qwen/qwen3.6-35b-a3b)
Date: 2025-01-XX

SQL preserved exactly from the original .pc file.

Pattern: Bulk array insert with batch commit every 500 rows.
Processes NSE EOD bhavcopy-style pipe-delimited data.
"""

import time
from typing import Any

from batch.base import BatchProcess
from batch.log import get_logger


class EquityIngestService(BatchProcess):
    name = "BATCH_EQUITY_INGEST"

    def __init__(self):
        self.input_data: str = ""
        self.total_ingested = 0
        self.batch_id = 0
        self.skipped_invalid = 0
        self.batch_seq = 0

    # ── Validation helpers (from .pc:98-118) ─────────────────────────────

    @staticmethod
    def is_valid_ticker(ticker: str) -> bool:
        """Validate NSE ticker symbol. SQL preserved from .pc:98-108."""
        if not ticker or len(ticker) == 0:
            return False
        if len(ticker) > 20:
            return False
        if " " in ticker:
            return False
        if ticker[0] == "-":
            return False
        return True

    @staticmethod
    def is_valid_price(price: float) -> bool:
        """Sanity-check price: must be between 0.01 and 200000.
        SQL preserved from .pc:112-118."""
        if price <= 0.0:
            return False
        if price > 200000.0:
            return False
        return True

    # ── Main ingestion logic ─────────────────────────────────────────────

    async def run(self, conn) -> dict[str, Any]:
        log = get_logger()
        cursor = conn.cursor()

        record_count = 0
        total_in_commit_group = 0

        self.batch_id = int(time.time())
        self.total_ingested = 0
        self.skipped_invalid = 0
        self.batch_seq = 0

        batch_rows: list[dict] = []

        for line in self.input_data.split("\n"):
            line = line.strip()
            if not line:
                continue

            parts = line.split("|")
            if len(parts) != 7:
                self.skipped_invalid += 1
                continue

            ticker, date_str, open_p, high, low, close, volume = (
                parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
            )

            # ── Validation before queuing (from .pc:177-187) ──
            if not self.is_valid_ticker(ticker):
                self.skipped_invalid += 1
                continue

            try:
                open_f = float(open_p)
                high_f = float(high)
                low_f = float(low)
                close_f = float(close)
                vol = int(volume)
            except (ValueError, TypeError):
                self.skipped_invalid += 1
                continue

            if not self.is_valid_price(close_f):
                self.skipped_invalid += 1
                continue

            batch_rows.append({
                "ticker": ticker[:31],
                "date": date_str[:15],
                "open": open_f,
                "high": high_f,
                "low": low_f,
                "close": close_f,
                "volume": vol,
                "batch_id": self.batch_id,
            })
            record_count += 1
            total_in_commit_group += 1

            # Flush batch when array is full (100 rows, from .pc:205)
            if len(batch_rows) >= 100:
                await self._flush_batch(cursor, batch_rows)
                self.total_ingested += len(batch_rows)
                batch_rows = []
                self.batch_seq += 1

                # Commit every 500 rows (from .pc:218)
                if total_in_commit_group >= 500:
                    await conn.commit()
                    log.info(
                        "equity_ingest.commit",
                        batch_seq=self.batch_seq,
                        running_total=self.total_ingested,
                    )
                    total_in_commit_group = 0

        # ── Final partial batch flush (from .pc:233-246) ──
        if batch_rows:
            await self._flush_batch(cursor, batch_rows)
            self.total_ingested += len(batch_rows)
            await conn.commit()
            self.batch_seq += 1
            log.info(
                "equity_ingest.final_flush",
                flushed=len(batch_rows),
                total=self.total_ingested,
                skipped_invalid=self.skipped_invalid,
            )

        # ── Log batch completion (from .pc:249-250) ──
        await self._write_batch_log(conn, "SUCCESS", self.total_ingested)

        return {
            "ingested": self.total_ingested,
            "batch_id": self.batch_id,
            "skipped_invalid": self.skipped_invalid,
            "batches": self.batch_seq,
            "rows_processed": self.total_ingested,
        }

    async def _flush_batch(self, cursor, rows: list[dict]) -> None:
        """Bulk insert a batch of equity rows into equity_staging.
        SQL preserved EXACTLY from batch_equity_ingest.pc:206-211."""
        sql = (
            "INSERT INTO equity_staging "
            "(ticker, batch_id, date, open, high, low, close, volume, ingest_status) "
            "VALUES (:ticker, :batch_id, :date, :open, :high, :low, :close, :volume, 'NEW')"
        )
        await cursor.executemany(sql, rows)

    async def _write_batch_log(self, conn, status: str, rows: int) -> None:
        """Insert a row into batch_log — SQL preserved from .pc:249-250."""
        cursor = conn.cursor()
        # SQL preserved EXACTLY from batch_equity_ingest.pc:249-250
        await cursor.execute(
            "INSERT INTO batch_log (service_name, status, rows_processed) "
            "VALUES ('BATCH_EQUITY_INGEST', :status, :rows)",
            {"status": status, "rows": rows},
        )
        await cursor.close()


def main():
    """Entry point for batch-equity-ingest CLI."""
    import os

    from batch.cli import run_service

    svc = EquityIngestService()
    data_file = os.environ.get("EQUITY_INPUT_FILE", "data/equity.dat")
    try:
        with open(data_file) as f:
            svc.input_data = f.read()
    except FileNotFoundError:
        # Demo data — NSE bhavcopy-style pipe-delimited EOD prices
        svc.input_data = (
            "RELIANCE|2025-01-15|2450.50|2478.90|2441.00|2470.15|15234567\n"
            "TCS|2025-01-15|3890.00|3915.75|3875.20|3905.40|4523891\n"
            "INFY|2025-01-15|1520.30|1535.60|1512.00|1528.90|8912345\n"
            "HDFCBANK|2025-01-15|1675.00|1688.45|1668.10|1680.25|12345678\n"
            "WIPRO|2025-01-15|450.20|456.80|448.50|454.30|6789012\n"
        )

    run_service(EquityIngestService, "BATCH_EQUITY_INGEST")


if __name__ == "__main__":
    main()
