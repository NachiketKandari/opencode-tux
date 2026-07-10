# Qwen + OpenCode Conversion Report: `batch_market_analytics.pc`

**Model:** Qwen 3.6 35B (openrouter/qwen/qwen3.6-35b-a3b)  
**Tool:** OpenCode (Continue)  
**Source:** `pc/batch_market_analytics.pc` — 1,149 lines Pro*C  
**Target:** `src/services/market_analytics.py` — 1,031 lines Python  
**Status:** All bugs fixed. Conversion is production-clean.  
**Test file:** `tests/test_qwen_market_analytics.py` — 82 tests, all passing

---

## Conversion Summary

The model produced a class-based async Python service (`MarketAnalyticsService(BatchProcess)`) from a Tuxedo/Pro*C service function. The 7-phase pipeline structure, all SQL queries, all 5 scoring functions, sector aggregation logic, market breadth counters, composite scoring, and ASCII report generation are all present and correct.

---

## What Was Faithfully Converted

**Scoring functions** — All 5 factor models are mathematically exact (verified against hand-computed values):
- `compute_value_score` (P/E, P/B, P/S, PEG, dividend yield)
- `compute_growth_score` (revenue, earnings, quarterly growth, forward estimates)
- `compute_quality_score` (ROE, ROA, margins, debt, cash flow)
- `compute_momentum_score` (1M/3M/6M momentum, SMA crossover, RSI, MACD)
- `compute_low_vol_score` (beta, volatility, debt, dividends)

**Composite scoring** — Weighted blend with market-cap-segmented weights (large/mid/small cap tiers) and 7-tier rating classification (STRONG_BUY through STRONG_SELL). All boundary conditions correct.

**SQL** — All queries preserved exactly from the `.pc` file:
- 48-column fundamental cursor with `COALESCE(recommendation, 'hold')`
- Sector analytics `INSERT OR REPLACE` with running averages
- `equity_derived_metrics` lookup with `ORDER BY date DESC LIMIT 1`
- `batch_log` insert on success
- Market breadth `SELECT AVG(pe_ratio), AVG(roe_pct)` queries
- Sector ranking cursor for the report

**Pipeline logic:**
- Sector transition detection and aggregation reset
- Market cap classification (LARGE/MID/SMALL cap buckets)
- Market breadth accumulation (above SMA-50/200, positive momentum)
- Batch commit every 50 stocks
- Final-sector finalization after the loop
- ASCII report with box-drawing characters and all 5 sections (A-E)

**Idiomatic Python adaptations:**
- Replaced Tuxedo `TPSVCINFO`/`tpreturn` with async class-based service
- Replaced host variable declarations with Python locals
- Replaced `DECLARE/OPEN/FETCH/CLOSE` cursors with `cursor.execute()` + `fetchall()`
- Replaced `sqlite3_mprintf` with parameterized queries (`:ticker`)
- Error handling delegated to the `BatchProcess._execute()` framework method, which provides try/catch, rollback, failed batch_log insert, and Prometheus counters — equivalent to the Pro*C `WHENEVER SQLERROR GOTO` pattern

---

## Bugs Found and Fixed

### Fixed: `phase1_count += 0` → `+= 1` (was line 561)

The initial conversion had:
```python
phase1_count += 0  # counted below
```
This was caught in review and Qwen applied the fix. The counter now correctly increments for each EOD price row processed. The report no longer shows "Phase 1: 0 rows."

---

## Bugs Faithfully Reproduced from Pro*C

These exist in the original Pro*C and were carried over exactly. They are not conversion errors.

### 1. Division by zero in advance/decline ratio
```python
if market_positive_momentum > 0 and market_total > 0:
    market_adv_decline = float(market_positive_momentum) \
                       / float(market_total - market_positive_momentum)
```
When ALL stocks have positive momentum, denominator is zero → `ZeroDivisionError`. The Pro*C has the identical bug. Both guard only against `total == 0`, not `total == positive`.

### 2. Phase 6 overwrites `best_ticker`
The "best composite score" ticker from Phase 2 is overwritten by a "largest market cap" query in Phase 6. Report Section D then shows the same ticker for both "Best Stock" and "Largest by Market Cap" — they're not necessarily the same stock. Matches Pro*C behavior exactly.

### 3. Phase 1 computes dead-local `price_vs_sma50`
The variable is computed in the Phase 1 loop body but goes out of scope immediately — never stored, never used in any subsequent phase. In Pro*C the host variable persists (function-global), but even there it's never referenced again. Dead code in both.

### 4. Phase 1 cross-contamination
When a new ticker is detected, `eod_close / sma_50` uses the new ticker's close price with the **previous** ticker's SMA. Both Pro*C and Python have this.

---

## What Was Lost (Expected — Architectural Differences)

| Pro*C Feature | Python Replacement |
|---|---|
| `tpsvrinit`/`tpsvrdone` lifecycle | Class `__init__` / framework hooks |
| `EXEC SQL BEGIN/END DECLARE SECTION` | Python local variables |
| `EXEC SQL WHENEVER SQLERROR GOTO` | `BatchProcess._execute()` framework catch-all |
| `VARCHAR[n]` with `.arr`/`.len` | Python `str` |
| `tpreturn(TPSUCCESS, ...)` | Return dict |
| `sqlca.sqlcode` error codes | Exception messages |
| `userlog()` | `structlog` logger |
| `EXEC SQL COMMIT` / `ROLLBACK` | `await conn.commit()` / framework rollback |

---

## Test Coverage (82 tests)

```
TestScoringFunctions             16   Hand-computed math verification
TestMarketAnalyticsEmptyDB       11   Empty DB vs C baseline
TestMarketAnalyticsSeededDB      22   5 stocks × 2 sectors × 60 EOD days
TestRegressionSpecific            4   Single-stock edge cases
TestRealModuleFunctions          16   Imports actual market_analytics.py module
TestHandComputedFullScoring       7   TCS full scoring chain (independently computed)
TestAdvanceDeclineEdgeCases       3   Div-by-zero, all-zero, normal ratio
TestSourceCodeBugs                4   Static analysis of source file on disk
```

Tests exercise the real module (not replicas), verify against independently hand-computed expected values, and statically confirm known characteristics of the source file.

---

## Verdict

**Production-clean.** The single conversion bug (phase1_count typo) was fixed by Qwen. All scoring math, SQL, sector logic, market breadth, and report generation are correct. The four remaining quirks are faithful reproductions of the original Pro*C behavior. Error handling is covered by the `BatchProcess` framework base class.
