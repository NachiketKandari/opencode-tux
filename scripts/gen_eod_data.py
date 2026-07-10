#!/usr/bin/env python3
"""
Generate synthetic EOD (end-of-day) price data for the Tux batch processor.

Creates pipe-delimited input data that BATCH_EQUITY_INGEST reads.
Format: TICKER|DATE|OPEN|HIGH|LOW|CLOSE|VOLUME

If a local SQLite DB with stock data exists (from turso_bridge.py), uses
real ticker names. Otherwise, generates completely synthetic data.

Usage:
    python3 scripts/gen_eod_data.py                          # 100 records
    python3 scripts/gen_eod_data.py --count 500              # 500 records
    python3 scripts/gen_eod_data.py --db data/batch.db       # use DB tickers
    python3 scripts/gen_eod_data.py --date 2026-07-07        # specific date
"""

import argparse
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Default tickers (used if no DB available)
DEFAULT_TICKERS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "BHARTIARTL",
    "SBIN", "HINDUNILVR", "ITC", "KOTAKBANK", "LT", "BAJFINANCE",
    "MARUTI", "SUNPHARMA", "TITAN", "AXISBANK", "HCLTECH", "NTPC",
    "WIPRO", "POWERGRID", "ULTRACEMCO", "TECHM", "ADANIPORTS", "JSWSTEEL",
    "TATAMOTORS", "GRASIM", "NESTLEIND", "ONGC", "TATASTEEL", "COALINDIA",
    "BAJAJFINSV", "DIVISLAB", "ADANIENT", "DRREDDY", "EICHERMOT",
    "HDFCLIFE", "HINDZINC", "SHREECEM", "BHARATFORG", "SIEMENS",
    "PIDILITIND", "ASIANPAINT", "BRITANNIA", "HAVELLS", "GODREJCP",
    "NAUKRI", "MOTHERSON", "VEDL", "MUTHOOTFIN", "MARICO",
]


def get_tickers_from_db(db_path: str) -> list[str]:
    """Extract ticker list from the local SQLite database."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM stock_fundamentals ORDER BY market_cap_crore DESC"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows] if rows else DEFAULT_TICKERS
    except Exception:
        return DEFAULT_TICKERS


def generate_eod_data(tickers: list[str], count: int, date_str: str) -> str:
    """Generate pipe-delimited EOD data lines."""
    random.seed(42)
    lines = []

    for i in range(count):
        ticker = random.choice(tickers)
        date = date_str

        # Generate OHLCV with realistic stock price behavior
        base_price = random.uniform(100, 5000)
        open_price = round(base_price * random.uniform(0.98, 1.02), 2)

        # Intraday movement: typically 0.5% to 3%
        intraday_range = open_price * random.uniform(0.005, 0.03)
        high = round(open_price + intraday_range, 2)
        low = round(open_price - intraday_range * random.uniform(0.3, 1.0), 2)

        # Close: usually near open, sometimes a big move
        if random.random() < 0.7:
            close = round(open_price * random.uniform(0.995, 1.005), 2)
            close = max(low, min(high, close))
        else:
            # Big move day
            close = round(open_price * random.uniform(0.98, 1.05), 2)
            close = max(low - intraday_range, min(high + intraday_range, close))

        volume = int(random.uniform(1000, 50000000))

        # Ensure high >= max(open, close) and low <= min(open, close)
        high = max(high, open_price, close) + random.uniform(0, 0.5)
        low = min(low, open_price, close) - random.uniform(0, 0.5)
        if low < 0.05:
            low = 0.05

        line = f"{ticker}|{date}|{open_price:.2f}|{high:.2f}|{low:.2f}|{close:.2f}|{volume}"
        lines.append(line)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate EOD input data for Tux batch processor")
    parser.add_argument("--count", type=int, default=100, help="Number of records (default: 100)")
    parser.add_argument("--date", help="Date in YYYY-MM-DD (default: today)")
    parser.add_argument("--db", default="data/batch.db", help="SQLite DB for real ticker names")
    parser.add_argument("--output", default="data/eod_input.dat", help="Output file path")
    parser.add_argument("--duplicates", type=int, default=2,
                        help="Duplicate factor: each ticker appears N times (default: 2)")
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    tickers = get_tickers_from_db(args.db) if os.path.exists(args.db) else DEFAULT_TICKERS

    # If we have relatively few stocks but want many records, repeat with slight variations
    effective_tickers = tickers * args.duplicates if len(tickers) < args.count else tickers

    data = generate_eod_data(effective_tickers[:max(args.count, len(effective_tickers))], args.count, date_str)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(data + "\n")

    print(f"Generated {args.count} EOD records → {output_path}")
    print(f"  Date: {date_str}")
    print(f"  Tickers used: {len(tickers)} unique")
    print(f"  Sample: {data.split(chr(10))[0]}")


if __name__ == "__main__":
    main()
