#!/usr/bin/env python3
"""
verify_output.py — Verify converted service output against canonical snapshots.

Runs a pipeline mode, captures stdout, normalizes non-deterministic content,
and diffs against the expected snapshot. Each mode gets a fresh database.

Usage:
  python3 scripts/verify_output.py --all           # verify all 5 modes
  python3 scripts/verify_output.py --mode pipeline # verify single mode
  python3 scripts/verify_output.py --mode pipeline --snapshot custom.expected

Exit code: 0 if all outputs match, 1 if any mismatch.
"""

import subprocess
import sys
import os
import re
import argparse
import difflib

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
        if re.match(r"^\[\d{4}-\d{2}-\d{2}\s", line):
            continue
        # Normalize date+time combos FIRST (before plain date regex eats the date)
        line = re.sub(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(:\d{2})?", "YYYY-MM-DD HH:MM", line)
        line = re.sub(r"\d{4}-\d{2}-\d{2}", "YYYY-MM-DD", line)
        line = re.sub(r"\d{2}:\d{2}(:\d{2})?", "HH:MM", line)
        line = re.sub(r"batch_id=\d{10}", "batch_id=EPOCH", line)
        line = re.sub(r"\b\d{10}\b", "EPOCH", line)
        cleaned.append(line)

    return "\n".join(cleaned)


def run_equity_mode(mode: str) -> str:
    """Run a specific equity app mode with fresh data, return stdout."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    subprocess.run(
        ["python3", GEN_DATA, "--count", "200", "--output", INPUT_FILE],
        cwd=ROOT, capture_output=True, check=True,
    )

    cmd = [EQUITY_APP, f"--{mode}", "--input", INPUT_FILE, "--schema", SCHEMA_FILE]
    result = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    return result.stdout


def verify(actual: str, expected_path: str) -> tuple:
    """Compare actual output against expected file. Returns (passed, diff_text)."""
    if not os.path.exists(expected_path):
        return False, f"Expected file not found: {expected_path}"

    with open(expected_path) as f:
        expected = f.read()

    actual_norm = normalize(actual).strip()
    expected_norm = expected.strip()

    if actual_norm == expected_norm:
        return True, ""

    diff = difflib.unified_diff(
        expected_norm.splitlines(keepends=True),
        actual_norm.splitlines(keepends=True),
        fromfile=expected_path,
        tofile="actual_output",
        n=3,
    )
    return False, "".join(diff)


def main():
    parser = argparse.ArgumentParser(description="Verify output against snapshots")
    parser.add_argument("--mode", help="Verify a single equity mode")
    parser.add_argument("--snapshot", help="Custom snapshot path (for --mode)")
    parser.add_argument("--all", action="store_true", help="Verify all 5 modes")
    args = parser.parse_args()

    if not args.mode and not args.all:
        parser.print_help()
        sys.exit(1)

    if not os.path.exists(EQUITY_APP):
        print(f"Error: {EQUITY_APP} not found. Run 'make equity' first.")
        sys.exit(1)

    modes = ["pipeline", "portfolio", "analytics", "risk", "all"]
    passed = 0
    failed = 0

    targets = modes if args.all else [args.mode]

    for mode in targets:
        print(f"  [{mode}] ", end="", flush=True)
        try:
            stdout = run_equity_mode(mode)
            snapshot = args.snapshot if args.snapshot else os.path.join(
                SNAPSHOT_DIR, f"{mode}.expected"
            )
            ok, diff = verify(stdout, snapshot)
            if ok:
                print("PASS")
                passed += 1
            else:
                print("FAIL")
                print(diff)
                failed += 1
        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed out of {passed + failed}")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
