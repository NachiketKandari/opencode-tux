# Test Suite Summary

**148 tests, 148 passing (100%)**

## DeepSeek V4 Pro (Claude Code) — 26 tests

| File | Tests | What it verifies |
|---|---|---|
| `test_services.py` | 12 | Unit tests: validation rules R1/R2/R3, word count edge cases |
| `test_pipeline_integration.py` | 14 | Full pipeline vs C baseline (make demo): ingest, validate, transform, report, batch_log, staging status, per-user stats |

## Qwen A35-3B (OpenCode) — 122 tests

| File | Tests | What it verifies |
|---|---|---|
| `test_qwen_equity_ingest.py` | 10 | Equity ingest vs C baseline (make equity-demo): 200 rows, 49 tickers, batch commit, price validation |
| `test_qwen_portfolio_processor.py` | 34 | Portfolio processor: empty DB vs C baseline (6), seeded DB logic (12), risk tier/margin/action decision trees (16) |
| `test_qwen_market_analytics.py` | 78 | Market analytics: 5-factor scoring hand-computed (31), real module functions (14), scoring edge cases (16), seeded DB (12), advance/decline edge cases (3) |

## Running

```bash
# All tests
PYTHONPATH=src python -m pytest tests/ -v

# DeepSeek only
PYTHONPATH=src python -m pytest tests/test_services.py tests/test_pipeline_integration.py -v

# Qwen only
PYTHONPATH=src python -m pytest tests/test_qwen_*.py -v
```

## Bugs Found

| # | Found In | File | Bug | Original .pc | In Generated Code? |
|---|---|---|---|---|---|
| 1 | Qwen | market_analytics.py:561 | `phase1_count += 0` (no-op) | `h_phase1_count++` (.pc:746) | Yes — fixed |
| 2 | Test harness | test_qwen_equity_ingest.py | Column order mismatch in SQLite tuple | N/A | N/A |
| 3 | Test harness | test_qwen_portfolio_processor.py | Wrong risk tier expectation in test case | N/A | N/A |
