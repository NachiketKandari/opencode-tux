#!/usr/bin/env python3
"""
Turso → SQLite Data Bridge for Tux Batch Processing POC

Fetches NSE equity data from the Turso database (used by screener-ai)
and populates a local SQLite file for the C batch processor.

Also generates synthetic users, portfolios, and transactions for the
ICICI Securities-style batch processing demo.

Usage:
    python3 scripts/turso_bridge.py                     # full sync
    python3 scripts/turso_bridge.py --stocks 50          # top 50 stocks only
    python3 scripts/turso_bridge.py --users 500           # 500 synthetic users
    python3 scripts/turso_bridge.py --db data/batch.db    # custom output path
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import http.client
import urllib.parse
from pathlib import Path


# ── Turso connection details from screener-ai .env ──────────────────────

TURSO_URL = "libsql://strattest-nachiketsingh.aws-eu-west-1.turso.io"
TURSO_AUTH_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3ODMyMDQ4OTQsImlkIjoiMDE5ZjJmNDQtZjUwMS03ZTVlLWE3ZmEtZmIxNTYzMjcwYTBiIiwia2lkIjoiX1Y2OTZTc25uSWtrTi0xTkdaMFZacjNNc2RGalgwMkR6cE5yQmI1ZEdQWSIsInJpZCI6ImEyOTQxYmE1LTVlNDQtNDhjMC1iMjIyLWUxNzdhNWQ4YjQyYyJ9.qqbSXGHol3mC36Z9oPp3ItVzfpHfNeS3qQI9ovsgG3xriO253NgX9qKyYHAYBV_0V5mwj68khEYw0EBcWrcUAw"

# Top 200 NSE stocks by market cap (for demo purposes)
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


class TursoClient:
    """Thin HTTP client for Turso's pipeline API."""

    def __init__(self, url: str, token: str):
        parsed = urllib.parse.urlparse(url.replace("libsql://", "https://"))
        self._host = parsed.hostname
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def execute(self, sql: str, params: list | None = None) -> list[dict]:
        """Execute SQL and return rows as list of dicts."""
        args = []
        if params:
            for p in params:
                args.append(self._typed_arg(p))

        body = json.dumps({
            "requests": [{
                "type": "execute",
                "stmt": {"sql": sql, "args": args}
            }]
        }).encode("utf-8")

        conn = http.client.HTTPSConnection(self._host, timeout=30)
        try:
            conn.request("POST", "/v2/pipeline", body=body, headers=self._headers)
            resp = conn.getresponse()
            data = json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()

        results = data.get("results", [{}])
        first = results[0] if results else {}

        if first.get("type") != "ok":
            err = first.get("error", {})
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise RuntimeError(f"Turso error: {msg}")

        result = first.get("response", {}).get("result", {})
        cols = [c["name"] for c in result.get("cols", [])]
        rows = []
        for row in result.get("rows", []):
            converted = {}
            for i, cell in enumerate(row):
                col_name = cols[i]
                if cell is None:
                    converted[col_name] = None
                elif isinstance(cell, dict):
                    ctype = cell.get("type", "")
                    val = cell.get("value")
                    if ctype == "integer":
                        converted[col_name] = int(val) if val is not None else None
                    elif ctype in ("real", "float"):
                        converted[col_name] = float(val) if val is not None else None
                    else:
                        converted[col_name] = str(val) if val is not None else None
                else:
                    converted[col_name] = cell
            rows.append(converted)
        return rows

    @staticmethod
    def _typed_arg(value) -> dict:
        if value is None:
            return {"type": "null", "value": None}
        if isinstance(value, bool):
            return {"type": "integer", "value": "1" if value else "0"}
        if isinstance(value, int):
            return {"type": "integer", "value": str(value)}
        if isinstance(value, float):
            return {"type": "real", "value": str(value)}
        return {"type": "text", "value": str(value)}


def create_local_schema(cursor: sqlite3.Cursor) -> None:
    """Create the equity schema in the local SQLite database."""
    schema_path = Path(__file__).parent.parent / "sql" / "schema_equity.sql"
    schema = schema_path.read_text()
    cursor.executescript(schema)


def fetch_eod_prices(client: TursoClient, tickers: list[str], limit: int = 200) -> list[dict]:
    """Fetch most recent EOD price data for the given tickers."""
    print(f"  Fetching EOD prices for {len(tickers)} stocks...")
    # Fetch last 30 days of data for each stock
    placeholders = ",".join(["?" for _ in tickers])
    sql = f"""
        SELECT ticker, date, open, high, low, close, volume
        FROM eod_prices
        WHERE ticker IN ({placeholders})
        AND date >= '2026-05-01'
        ORDER BY ticker, date DESC
    """
    try:
        rows = client.execute(sql, tickers)
        print(f"    Got {len(rows)} price rows")
        return rows
    except Exception as e:
        print(f"    Warning: Could not fetch EOD prices: {e}")
        return []


def fetch_fundamentals(client: TursoClient, tickers: list[str]) -> list[dict]:
    """Fetch latest fundamentals for the given tickers."""
    print(f"  Fetching fundamentals for {len(tickers)} stocks...")
    placeholders = ",".join(["?" for _ in tickers])
    sql = f"""
        SELECT * FROM stock_fundamentals
        WHERE ticker IN ({placeholders})
    """
    try:
        rows = client.execute(sql, tickers)
        print(f"    Got {len(rows)} fundamental records")
        return rows
    except Exception as e:
        print(f"    Warning: Could not fetch fundamentals: {e}")
        return []


def insert_eod_prices(cursor: sqlite3.Cursor, rows: list[dict]) -> int:
    """Insert EOD price rows into local SQLite."""
    count = 0
    for row in rows:
        cursor.execute("""
            INSERT OR REPLACE INTO eod_prices (ticker, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            row.get("ticker"),
            row.get("date"),
            row.get("open"),
            row.get("high"),
            row.get("low"),
            row.get("close"),
            row.get("volume"),
        ))
        count += 1
    return count


def insert_fundamentals(cursor: sqlite3.Cursor, rows: list[dict]) -> int:
    """Insert fundamentals into local SQLite."""
    cols = [
        "ticker", "as_of_date", "company_name", "sector", "industry", "exchange",
        "current_price", "market_cap_crore", "pe_ratio", "forward_pe", "pb_ratio",
        "peg_ratio", "price_to_sales", "roe_pct", "roa_pct", "profit_margins_pct",
        "operating_margins_pct", "gross_margins_pct", "ebitda_margins_pct",
        "eps_ttm", "eps_forward", "book_value_per_share", "revenue_per_share",
        "revenue_growth_pct", "earnings_growth_pct", "earnings_quarterly_growth_pct",
        "debt_to_equity", "current_ratio", "quick_ratio", "payout_ratio",
        "dividend_yield_pct", "five_year_avg_dividend_yield_pct",
        "high_52w", "low_52w", "beta",
        "target_mean_price", "target_high_price", "target_low_price",
        "recommendation", "number_of_analysts",
        "held_pct_insiders", "held_pct_institutions",
        "free_cashflow", "operating_cashflow", "total_cash_per_share",
        "total_debt", "total_revenue", "ebitda",
    ]
    placeholders = ",".join(["?" for _ in cols])
    sql = f"INSERT OR REPLACE INTO stock_fundamentals ({','.join(cols)}) VALUES ({placeholders})"

    count = 0
    for row in rows:
        values = [row.get(c) for c in cols]
        cursor.execute(sql, values)
        count += 1
    return count


# ── Synthetic data generators ──────────────────────────────────────────

INDIAN_FIRST_NAMES = [
    "Aarav", "Aditi", "Amit", "Ananya", "Arjun", "Deepak", "Divya", "Gaurav",
    "Ishaan", "Kavya", "Manish", "Neha", "Pooja", "Pranav", "Priya", "Rahul",
    "Rajesh", "Rohit", "Sanjay", "Shreya", "Siddharth", "Sneha", "Tanvi",
    "Varun", "Vikram", "Vivek", "Yash", "Zara", "Abhishek", "Anjali",
    "Bhavna", "Chirag", "Deeksha", "Esha", "Ganesh", "Harsh", "Ishita",
    "Jatin", "Kriti", "Lakshay", "Megha", "Nikhil", "Omkar", "Palak",
    "Rajat", "Sakshi", "Tushar", "Utkarsh", "Vani", "Yuvraj",
]

INDIAN_LAST_NAMES = [
    "Sharma", "Patel", "Singh", "Kumar", "Verma", "Gupta", "Joshi", "Mehta",
    "Shah", "Reddy", "Nair", "Menon", "Das", "Agarwal", "Jain", "Iyer",
    "Chopra", "Malhotra", "Kapoor", "Bose", "Sen", "Chatterjee", "Banerjee",
    "Mukherjee", "Kulkarni", "Deshmukh", "Patil", "Thakur", "Yadav", "Pandey",
]

BRANCHES = ["MUMBAI-FORT", "DELHI-CP", "BANGALORE-MG", "CHENNAI-TNAGAR",
            "KOLKATA-PARK", "PUNE-JM", "AHMEDABAD-SG", "HYDERABAD-HITECH"]

SECTORS = [
    "Technology", "Banking", "Pharmaceuticals", "Automotive", "Energy",
    "Consumer Goods", "Metals & Mining", "Telecom", "Construction",
    "Financial Services", "Healthcare", "Retail",
]


def generate_users(cursor: sqlite3.Cursor, count: int) -> int:
    """Generate synthetic ICICI Securities-style user accounts."""
    import random
    random.seed(42)

    segments = ["EQUITY"] * 60 + ["FNO"] * 25 + ["COMMODITY"] * 10 + ["CURRENCY"] * 5
    risk_profiles = ["CONSERVATIVE"] * 30 + ["MODERATE"] * 45 + ["AGGRESSIVE"] * 25

    inserted = 0
    for i in range(1, count + 1):
        client_code = f"ICI{i:06d}"
        first = random.choice(INDIAN_FIRST_NAMES)
        last = random.choice(INDIAN_LAST_NAMES)
        full_name = f"{first} {last}"
        segment = random.choice(segments)
        risk = random.choice(risk_profiles)
        branch = random.choice(BRANCHES)
        kyc = random.choice(["VERIFIED"] * 90 + ["PENDING"] * 8 + ["REJECTED"] * 2)
        status = "ACTIVE" if kyc == "VERIFIED" else random.choice(["DORMANT", "ACTIVE"])
        onboard = f"202{random.randint(0,5)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
        income = random.gauss(1500000, 800000)
        networth = income * random.uniform(2, 15)

        cursor.execute("""
            INSERT INTO users (user_id, client_code, full_name, segment, risk_profile,
                account_status, branch_code, kyc_status, onboard_date, annual_income, net_worth)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (i, client_code, full_name, segment, risk, status, branch, kyc, onboard,
              max(0, income), max(0, networth)))
        inserted += 1
    return inserted


def generate_portfolios(cursor: sqlite3.Cursor, num_users: int, tickers: list[str]) -> int:
    """Generate synthetic portfolios — user stock holdings with varied patterns."""
    import random
    random.seed(123)

    inserted = 0
    # Each user holds 1-15 different stocks
    for user_id in range(1, num_users + 1):
        num_holdings = random.choices(
            [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15],
            weights=[5, 8, 12, 15, 18, 12, 10, 6, 3, 2, 1]
        )[0]

        held = random.sample(tickers, min(num_holdings, len(tickers)))
        for ticker in held:
            # Vary quantities: some large holdings, mostly medium/small
            quantity = random.choices(
                [10, 25, 50, 100, 200, 500, 1000, 2000, 5000],
                weights=[10, 12, 15, 20, 15, 10, 5, 2, 1]
            )[0]
            avg_price = random.uniform(50, 5000)
            invested = quantity * avg_price
            portfolio_type = random.choices(
                ["DELIVERY"] * 70 + ["MARGIN"] * 20 + ["INTRADAY"] * 10
            )[0]

            cursor.execute("""
                INSERT INTO user_portfolios (user_id, ticker, quantity, avg_buy_price,
                    invested_amount, holding_since, portfolio_type, pledge_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, ticker, quantity, round(avg_price, 2),
                  round(invested, 2),
                  f"202{random.randint(3,6)}-{random.randint(1,12):02d}-01",
                  portfolio_type,
                  "UNPLEDGED"))
            inserted += 1
    return inserted


def generate_transactions(cursor: sqlite3.Cursor, num_users: int, tickers: list[str]) -> int:
    """Generate synthetic buy/sell transactions."""
    import random
    random.seed(456)

    inserted = 0
    for _ in range(num_users * 8):  # ~8 transactions per user
        user_id = random.randint(1, num_users)
        ticker = random.choice(tickers)
        txn_type = random.choice(["BUY"] * 55 + ["SELL"] * 45)
        quantity = random.choice([10, 25, 50, 100, 200, 500, 1000])
        price = random.uniform(100, 5000)
        brokerage = round(quantity * price * random.uniform(0.0005, 0.002), 2)
        txn_date = f"2026-{random.randint(1,6):02d}-{random.randint(1,28):02d}"

        cursor.execute("""
            INSERT INTO user_transactions (user_id, ticker, txn_type, quantity, price,
                brokerage, txn_date, exchange)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, ticker, txn_type, quantity, round(price, 2), brokerage, txn_date, "NSE"))
        inserted += 1
    return inserted


# ── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Turso → SQLite data bridge")
    parser.add_argument("--stocks", type=int, default=50, help="Number of stocks to fetch (default: 50)")
    parser.add_argument("--users", type=int, default=200, help="Number of synthetic users (default: 200)")
    parser.add_argument("--db", default="data/batch.db", help="Output SQLite DB path (default: data/batch.db)")
    parser.add_argument("--tickers", nargs="*", help="Specific tickers to fetch (overrides --stocks)")
    parser.add_argument("--skip-turso", action="store_true", help="Skip Turso fetch, only generate synthetic data")
    parser.add_argument("--eod-days", type=int, default=30, help="Days of EOD data to fetch (default: 30)")
    args = parser.parse_args()

    # Ensure data directory exists
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing DB for clean start
    if db_path.exists():
        db_path.unlink()
        print(f"Removed existing {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    cursor = conn.cursor()

    # Create schema
    print("Creating equity schema...")
    create_local_schema(cursor)
    conn.commit()

    # Determine tickers
    if args.tickers:
        tickers = args.tickers
    else:
        tickers = DEFAULT_TICKERS[:args.stocks]

    if not args.skip_turso:
        print(f"\nConnecting to Turso ({TURSO_URL})...")
        client = TursoClient(TURSO_URL, TURSO_AUTH_TOKEN)

        # Fetch and insert EOD prices
        price_rows = fetch_eod_prices(client, tickers, args.eod_days)
        if price_rows:
            count = insert_eod_prices(cursor, price_rows)
            conn.commit()
            print(f"  Inserted {count} EOD price rows")

        # Fetch and insert fundamentals
        fund_rows = fetch_fundamentals(client, tickers)
        if fund_rows:
            count = insert_fundamentals(cursor, fund_rows)
            conn.commit()
            print(f"  Inserted {count} fundamental records")

    # Generate synthetic users, portfolios, transactions
    print(f"\nGenerating synthetic data...")
    print(f"  Creating {args.users} users...")
    user_count = generate_users(cursor, args.users)
    conn.commit()
    print(f"    {user_count} users created")

    print(f"  Creating portfolios...")
    pf_count = generate_portfolios(cursor, args.users, tickers)
    conn.commit()
    print(f"    {pf_count} portfolio holdings created")

    print(f"  Creating transactions...")
    txn_count = generate_transactions(cursor, args.users, tickers)
    conn.commit()
    print(f"    {txn_count} transactions created")

    conn.close()

    # Report
    db_size_mb = db_path.stat().st_size / (1024 * 1024)
    print(f"\nDatabase ready: {db_path} ({db_size_mb:.1f} MB)")
    print(f"  Stocks: {len(tickers)}")
    print(f"  Users: {user_count}")
    print(f"  Portfolio holdings: {pf_count}")
    print(f"  Transactions: {txn_count}")


if __name__ == "__main__":
    main()
