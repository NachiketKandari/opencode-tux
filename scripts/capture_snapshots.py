#!/usr/bin/env python3
"""
capture_snapshots.py — Run all pipeline modes and capture canonical output.

For each mode: regenerates input data, deletes old database, runs the app,
captures stdout, normalizes non-deterministic content, saves to .expected file.

Usage:
  python3 scripts/capture_snapshots.py           # capture all modes
  python3 scripts/capture_snapshots.py --mode pipeline  # single mode only
"""

import subprocess
import sys
import os
import re
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIR = os.path.join(ROOT, "snapshots")
EQUITY_APP = os.path.join(ROOT, "bin", "equity_app")
GEN_DATA = os.path.join(ROOT, "scripts", "gen_eod_data.py")
DB_FILE = os.path.join(ROOT, "data", "batch.db")
INPUT_FILE = os.path.join(ROOT, "data", "eod_input.dat")
SCHEMA_FILE = os.path.join(ROOT, "sql", "schema_equity.sql")


def normalize(output: str) -> str:
    """Strip non-deterministic content from output for stable comparison."""
    lines = output.split("\n")
    cleaned = []

    for line in lines:
        # Skip userlog/timestamped lines
        if re.match(r"^\[\d{4}-\d{2}-\d{2}\s", line):
            continue

        # Normalize date+time combos FIRST (before plain date regex eats the date)
        line = re.sub(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(:\d{2})?", "YYYY-MM-DD HH:MM", line)
        # Normalize ISO dates
        line = re.sub(r"\d{4}-\d{2}-\d{2}", "YYYY-MM-DD", line)
        # Normalize times (with or without seconds)
        line = re.sub(r"\d{2}:\d{2}(:\d{2})?", "HH:MM", line)
        # Normalize epoch timestamps in batch_id
        line = re.sub(r"batch_id=\d{10}", "batch_id=EPOCH", line)
        # Normalize large standalone epoch ints (volume totals, etc.)
        line = re.sub(r"\b\d{10}\b", "EPOCH", line)

        cleaned.append(line)

    return "\n".join(cleaned)


def run_mode(mode: str) -> str:
    """Run a specific mode with fresh data and return normalized stdout."""
    # Delete old database so each run starts clean
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    # Regenerate input data
    subprocess.run(
        ["python3", GEN_DATA, "--count", "200", "--output", INPUT_FILE],
        cwd=ROOT, capture_output=True, check=True,
    )

    # Run the equity app
    cmd = [EQUITY_APP, f"--{mode}", "--input", INPUT_FILE, "--schema", SCHEMA_FILE]
    result = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=30,
    )

    return normalize(result.stdout)


def main():
    parser = argparse.ArgumentParser(description="Capture canonical output snapshots")
    parser.add_argument("--mode", help="Capture a single mode only")
    args = parser.parse_args()

    modes = ["pipeline", "portfolio", "analytics", "risk", "all"]

    if args.mode:
        if args.mode not in modes:
            print(f"Unknown mode: {args.mode}. Valid: {modes}")
            sys.exit(1)
        modes = [args.mode]

    if not os.path.exists(EQUITY_APP):
        print(f"Error: {EQUITY_APP} not found. Run 'make equity' first.")
        sys.exit(1)

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    print(f"Capturing snapshots → {SNAPSHOT_DIR}/\n")

    for mode in modes:
        print(f"  [{mode}] ", end="", flush=True)
        try:
            output = run_mode(mode)
            path = os.path.join(SNAPSHOT_DIR, f"{mode}.expected")
            with open(path, "w") as f:
                f.write(output)
            lines = len(output.split("\n"))
            print(f"OK ({lines} lines → {mode}.expected)")
        except Exception as e:
            print(f"FAILED: {e}")
            sys.exit(1)

    print(f"\nDone. {len(modes)} snapshot(s) captured.")


if __name__ == "__main__":
    main()
