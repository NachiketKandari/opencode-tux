# Pro*C Services Reference — Tuxedo Batch Processing POC

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        .pc files (Pro*C)                        │
│  EXEC SQL, cursors, host variables, Tuxedo service signatures   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ scripts/preproc.py
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      .c files (C + SQLite)                      │
│           sqlite3_mprintf, sqlite3_prepare/step/finalize        │
└──────────────────────────┬──────────────────────────────────────┘
                           │ gcc + libsqlite3
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    bin/equity_app  /  bin/batch_app             │
│                   Single executable, all services               │
└─────────────────────────────────────────────────────────────────┘
```

Two independent pipelines exist in this repo:
- **Posts Pipeline** (original, simpler): 4 active services + 2 stubs using JSONPlaceholder data
- **Equity Pipeline** (newer, complex): 7 active services using NSE equity data

Both use the same simulation layer (`atmi.h`, `tuxlib.c`, `sqlca.c`) and the same preprocessor (`scripts/preproc.py`).

---

## Infrastructure Files

### `include/atmi.h` (146 lines)
**Simulated Tuxedo ATMI header.** Defines the entire Tuxedo API surface that .pc files expect.

| Component | Lines | Description |
|---|---|---|
| Return codes + flags | 8 | TPSUCCESS, TPFAIL, TPEXIT, TPNOREPLY, TPNOTRAN, TPTRAN |
| Buffer types | 4 | STRING(0), CARRAY(1), FML(2), VIEW(3) |
| TPSVCINFO struct | 8 | Service request context: name, flags, data ptr, len, cd, appkey |
| SERVICE_TABLE | 5 | Dispatch table entry: svcname → function pointer |
| FML_FIELD struct | 7 | Typed field: fldid, type(STRING/INT/DOUBLE), occ, value union |
| FML_BUF struct | 4 | FML buffer: buftype, field_count, 128 FML_FIELDs |
| Field ID defines | 22 | FLD_CLIENT_CODE(100) through FLD_SECTOR_EXPOSURE_JSON(215) |
| Scenario flags | 9 | SF_BASIC_RISK through SF_DEFAULT for phase gating |
| FML API decls | 7 | Falloc, Ffree, Fadd, Fget, Fchg, Fldid, Fldno |
| ATMI API decls | 20 | tux_init, tux_run, tpcall, tpacall, tpreturn, tpforward, tpalloc, tpfree, tpbegin, tpcommit, tpabort |

### `src/tuxlib.c` (381 lines)
**Tuxedo ATMI simulation runtime.** Implements the service dispatch loop, inter-service communication, FML buffer operations, and transaction stubs.

| Function | Lines | Purpose |
|---|---|---|
| `userlog()` | 12 | Timestamped logging to stderr |
| `Falloc()` | 6 | Allocate FML buffer (calloc + set buftype=FML) |
| `Ffree()` | 4 | Free FML buffer |
| `Fadd()` | 32 | Append typed field to FML buffer (auto-infer type from fldid) |
| `Fget()` | 42 | Retrieve field by ID + occurrence, copy value |
| `Fchg()` | 28 | Change existing field in place |
| `Fldid()` | 22 | Name → field ID lookup (22 entries, case-insensitive) |
| `Fldno()` | 9 | Count occurrences of a field ID |
| `tpalloc()` | 8 | Allocate buffer (STRING or FML) |
| `tpfree()` | 9 | Free buffer (FML-aware) |
| `tpcall()` | 30 | Synchronous service call with return buffer |
| `tpforward()` | 18 | Forward request to another service (fire-and-forget) |
| `tpreturn()` | 20 | Return from service with output data |
| `tux_init/tux_run/tux_done` | 15 | Lifecycle: init registry, run dispatch, shutdown |
| Transaction stubs | 20 | tpbegin, tpcommit, tpabort (log-only) |

### `src/sqlca.c` (33 lines)
**SQL Communication Area simulation.** Mirrors Oracle's `sqlca.h` — tracks sqlcode, error messages, and row counts. Key globals: `sqlca.sqlcode`, `sqlca.sqlerrm`, `sqlca.sqlerrd[2]` (rows affected).

### `scripts/preproc.py` (745 lines)
**Pro*C → C + SQLite preprocessor.** Converts EXEC SQL syntax to SQLite3 C API calls.

| Pattern | Conversion |
|---|---|
| `EXEC SQL CONNECT` | `sqlite3_open("data/batch.db")` |
| `EXEC SQL INSERT … VALUES (:hv)` | `sqlite3_mprintf("%Q", hv)` with auto-quoting |
| `EXEC SQL FOR :count INSERT` | `for(_i=0; _i<count; _i++)` loop with `[_i]` array indexing |
| `EXEC SQL SELECT … INTO :hv` | `sqlite3_prepare / step / column_int_or_text` |
| `EXEC SQL DECLARE c CURSOR / OPEN / FETCH / CLOSE` | `sqlite3_prepare / step / finalize` |
| `EXEC SQL COMMIT / ROLLBACK` | `sqlite3_exec("COMMIT")` / `sqlite3_exec("ROLLBACK")` |
| `VARCHAR name[N]` | `struct { unsigned short len; char arr[N]; } name` |
| `EXEC SQL WHENEVER SQLERROR GOTO/DO/CONTINUE` | `ERR_GOTO(label)` macro / function call / no-op |

---

## Posts Pipeline (Original)

**Orchestrator:** `pc/batch_orchestrator.c` (273 lines) — builds `bin/batch_app`, runs data from `data/input.dat`.
**Schema:** `sql/schema.sql`
**Data source:** JSONPlaceholder API (`scripts/fetch_data.py`)

### Pipeline Flow
```
BATCH_INGEST → BATCH_VALIDATE → BATCH_TRANSFORM → BATCH_REPORT (via tpforward)
```

### BATCH_INGEST — `pc/batch_ingest.pc` (182 lines)
**Complexity: SIMPLE** | Posts ingestion from API data.

| Metric | Count |
|---|---|
| EXEC SQL | 16 |
| if/else branches | 5 |
| Host variables | 15 |
| Cursors | 0 |
| Array bulk inserts (FOR :var) | 2 |
| COMMIT / ROLLBACK | 3 / 2 |

**Patterns used:** Array bulk insert (`FOR :h_batch_size INSERT`), batch commit every 500 rows, `WHENEVER SQLERROR GOTO`, `EXEC SQL CONNECT`, `tpreturn` with status message.

**What it does:** Parses pipe-delimited `user_id|post_id|title|body` lines from `rqst->data`, populates 100-row host arrays, bulk-inserts into `posts_staging` table. Commits every 500 rows to manage transaction log size. Returns count of ingested records.

---

### BATCH_VALIDATE — `pc/batch_validate.pc` (221 lines)
**Complexity: SIMPLE** | Cursor-based validation with tiered error handling.

| Metric | Count |
|---|---|
| EXEC SQL | 21 |
| if/else branches | 12 |
| Host variables | 16 |
| Cursors | 1 |
| SELECT INTO | 1 |
| COMMIT / ROLLBACK | 3 / 1 |

**Patterns used:** Cursor fetch loop (`DECLARE / OPEN / FETCH INTO / CLOSE`), `UPDATE … SET … WHERE` with host variables, multi-condition validation (R1: non-empty title, R2: non-empty body, R3: body ≥ 20 chars), `WHENEVER SQLERROR GOTO`, tiered error categorization.

**What it does:** Opens a cursor over `posts_staging` ordered by id. For each row: runs 3 validation rules, updates `validation_status` to VALID or ERROR with specific rule codes (R1/R2/R3), increments per-rule error counters. Updates the staging table with validation results.

---

### BATCH_TRANSFORM — `pc/batch_transform.pc` (227 lines)
**Complexity: SIMPLE-MEDIUM** | Cursor-based transform with computed metrics and service chaining.

| Metric | Count |
|---|---|
| EXEC SQL | 21 |
| if/else branches | 9 |
| Host variables | 17 |
| Cursors | 1 |
| SELECT INTO | 1 |
| tpforward calls | 3 |
| COMMIT / ROLLBACK | 3 / 1 |

**Patterns used:** Cursor fetch loop, `SELECT … INTO`, computed columns (word counts, derived metrics), `INSERT INTO … SELECT`, `EXEC SQL COMMIT`, `tpforward` service chaining (to BATCH_REPORT), `UPSERT` via INSERT OR REPLACE.

**What it does:** Fetches validated posts via cursor, computes word counts (body word count, title word count), upserts into `posts` table with computed fields, updates `post_stats` per-user aggregates (post count, total words, avg words), calls batch_log insert, then `tpforward`s results to BATCH_REPORT for final output.

---

### BATCH_REPORT — `pc/batch_report.pc` (189 lines)
**Complexity: SIMPLE** | Aggregate queries and formatted report generation.

| Metric | Count |
|---|---|
| EXEC SQL | 15 |
| if/else branches | 5 |
| Host variables | 17 |
| Cursors | 1 |
| SELECT INTO (aggregates) | 0 |
| COMMIT / ROLLBACK | 1 / 0 |

**Patterns used:** `SELECT COUNT(*), SUM(x) INTO :hv` for aggregate queries, `INSERT INTO batch_log`, formatted ASCII report via snprintf, `tpreturn` with report string.

**What it does:** Runs aggregate queries: total posts, total users, total words, top user by post count. Fetches batch log history via cursor. Formats an ASCII report with all metrics, logs completion to batch_log, returns the report string.

---

### BATCH_ANALYTICS — `pc/batch_analytics.pc` (47 lines)
**Complexity: STUB** | Placeholder for future analytics service.

| Metric | Count |
|---|---|
| EXEC SQL | 8 |
| Host variables | 3 |

Has full tpsvrinit/tpsvrdone lifecycle and CONNECT but the service function is a no-op returning `OK|stub=analytics_skipped`.

---

### BATCH_ENRICHMENT — `pc/batch_enrichment.pc` (47 lines)
**Complexity: STUB** | Placeholder for future data enrichment service.

| Metric | Count |
|---|---|
| EXEC SQL | 8 |
| Host variables | 3 |

Identical structure to BATCH_ANALYTICS — full lifecycle, no-op service body returning `OK|stub=enrichment_skipped`.

---

## Equity Pipeline (ICICI Securities NSE)

**Orchestrator:** `pc/batch_equity_orchestrator.c` (381 lines) — builds `bin/equity_app`, supports 5 modes.
**Schema:** `sql/schema_equity.sql` (9 tables, 12 indexes)
**Data source:** Synthetic EOD data (`scripts/gen_eod_data.py`) + optional Turso DB bridge

### Pipeline Flow
```
BATCH_EQUITY_INGEST → BATCH_EQUITY_VALIDATE → BATCH_EQUITY_TRANSFORM
                           ↘ BATCH_EQUITY_REPORT (via tpforward)

Standalone: BATCH_PORTFOLIO_PROCESSOR, BATCH_MARKET_ANALYTICS, BATCH_COMPREHENSIVE_RISK
```

### Run Modes
| Flag | What Runs |
|---|---|
| `--pipeline` (default) | INGEST → VALIDATE → TRANSFORM → REPORT |
| `--portfolio` | BATCH_PORTFOLIO_PROCESSOR only |
| `--analytics` | BATCH_MARKET_ANALYTICS only |
| `--risk` | BATCH_COMPREHENSIVE_RISK only (FML input) |
| `--all` | All 7 services sequentially |

---

### BATCH_EQUITY_INGEST — `pc/batch_equity_ingest.pc` (269 lines)
**Complexity: SIMPLE** | NSE EOD bhavcopy-style bulk ingestion.

| Metric | Count |
|---|---|
| EXEC SQL | 16 |
| if/else branches | 14 |
| Host variables | 24 |
| Cursors | 0 |
| Array bulk inserts (FOR :var) | 2 |
| COMMIT / ROLLBACK | 3 / 2 |

**Patterns used:** Array bulk insert (`FOR :h_batch_size INSERT`), batch commit every 500 rows, ticker validation helper, price sanity checks (0.01–200,000 range), `WHENEVER SQLERROR GOTO`, `tpreturn` with per-batch stats.

**What it does:** Parses pipe-delimited `TICKER|DATE|OPEN|HIGH|LOW|CLOSE|VOLUME` lines. Validates ticker format and price ranges. Populates 100-row host arrays, bulk-inserts into `equity_staging`. Commits every 500 rows. Returns `ingested=X|batch_id=Y|skipped=Z|batches=N`.

---

### BATCH_EQUITY_VALIDATE — `pc/batch_equity_validate.pc` (375 lines)
**Complexity: SIMPLE-MEDIUM** | 6-rule equity data validation with per-rule error tracking.

| Metric | Count |
|---|---|
| EXEC SQL | 19 |
| if/else branches | 25 |
| Host variables | 35 |
| Cursors | 1 |
| SELECT INTO | 0 |
| COMMIT / ROLLBACK | 3 / 2 |

**Patterns used:** Cursor fetch loop, 6 validation rules (R1: valid ticker, R2: price > 0.05, R3: price < 200,000, R4: high ≥ low, R5: close within OHLC, R6: volume ≥ 1), `UPDATE … SET … WHERE`, `WHENEVER SQLERROR GOTO`, per-rule error counters, commit checkpoint every 200 rows.

**What it does:** Fetches from `equity_staging` via cursor. Runs 6 validation rules per row — R4 (high ≥ low), R5 (close within OHLC range), R6 (volume ≥ 1) catch data quality issues. Updates `ingest_status` to VALIDATED or ERROR with specific rule codes in `validation_msg`. Commits every 200 rows.

---

### BATCH_EQUITY_TRANSFORM — `pc/batch_equity_transform.pc` (408 lines)
**Complexity: MEDIUM** | Derived metrics, portfolio MTM, margin calls, tpforward chaining.

| Metric | Count |
|---|---|
| EXEC SQL | 31 |
| if/else branches | 24 |
| Host variables | 54 |
| Cursors | 2 |
| SELECT INTO | 4 |
| tpforward calls | 3 |
| COMMIT / ROLLBACK | 4 / 2 |

**Patterns used:** Two cursors (staging fetch, portfolio position fetch), computed columns (SMA 50/200 approximation, daily return, volatility 30d, volume ratio, RSI 14, price vs 52W high), `INSERT INTO equity_derived_metrics`, `UPDATE equity_staging SET ingest_status='TRANSFORMED'`, portfolio MTM with margin call detection, `tpforward` to BATCH_EQUITY_REPORT.

**What it does:**
1. **Phase 1 — Derived Metrics:** Fetches validated staging records, computes 6 derived metrics per stock, inserts into `equity_derived_metrics`.
2. **Phase 2 — Portfolio MTM:** Fetches user portfolios via cursor, marks positions to market, checks margin adequacy, generates margin calls.
3. **Phase 3 — Forward:** `tpforward`s the results to BATCH_EQUITY_REPORT.

---

### BATCH_EQUITY_REPORT — `pc/batch_equity_report.pc` (365 lines)
**Complexity: MEDIUM** | 12+ aggregate queries, formatted ASCII report, sector breakdown.

| Metric | Count |
|---|---|
| EXEC SQL | 34 |
| if/else branches | 8 |
| Host variables | 46 |
| Cursors | 2 |
| SELECT INTO | 7 |
| COMMIT / ROLLBACK | 2 / 2 |

**Patterns used:** Multiple `SELECT COUNT(*), SUM(x) INTO :hv` aggregate queries, cursors for sector breakdown and batch log history, formatted multi-section ASCII report, `INSERT INTO batch_log`.

**What it does:** Generates a formatted EOD report with 8 sections:
- **Market Overview:** Total records, distinct stocks, advancing/declining/unchanged, total volume
- **Top Movers:** Top gainer, top loser, most active (by % change)
- **Market Fundamentals:** Avg P/E, avg ROE, total market cap
- **Client Portfolio Summary:** Total users, active users, AUM, holdings, pending margin calls
- **Transaction Summary:** Total transactions, total brokerage
- **Sector Breakdown:** Per-sector stats via cursor
- **Batch Execution Log:** Service execution history via cursor

---

### BATCH_PORTFOLIO_PROCESSOR — `pc/batch_portfolio_processor.pc` (629 lines)
**Complexity: MEDIUM** | Risk tier classification, margin engine, concentration checks, 5 action codes.

| Metric | Count |
|---|---|
| EXEC SQL | 26 |
| if/else branches | 65 |
| Host variables | 87 |
| Cursors | 2 |
| SELECT INTO | 2 |
| COMMIT / ROLLBACK | 5 / 2 |

**Patterns used:** Two cursors (user scan, position scan), risk tier classification (AGGRESSIVE/MODERATE/CONSERVATIVE/HIGH_RISK), margin computation engine with leverage adjustments, stock concentration checks (>20% portfolio), sector concentration checks (>40% sector), 5 action codes (MARGIN_CALL, CONCENTRATION_BREACH, ACCOUNT_REVIEW, LIQUIDATION_WARNING, NO_ACTION), per-user position aggregation, formatted ASCII portfolio report.

**What it does:**
1. **Phase 1 — User Scanning:** Fetches all users, classifies by risk profile and account status.
2. **Phase 2 — Position Processing:** Fetches each user's positions, marks to market, computes margin requirements based on risk tier and portfolio type (DELIVERY/MARGIN/INTRADAY), checks concentration limits, generates action codes.

---

### BATCH_MARKET_ANALYTICS — `pc/batch_market_analytics.pc` (1,149 lines)
**Complexity: COMPLEX** | 48-column cursor, 5 factor models, composite scoring, sector ranking, 7-phase processing.

| Metric | Count |
|---|---|
| EXEC SQL | 36 |
| if/else branches | 141 |
| Host variables | 158 |
| Cursors | 3 |
| SELECT INTO | 4 |
| COMMIT / ROLLBACK | 5 / 2 |

**Patterns used:** Wide cursor (48 columns from stock_fundamentals), 5 factor models with per-stock scoring (Value — P/E, P/B, P/S, dividend yield; Growth — revenue growth, earnings growth; Quality — ROE, debt/equity, margins; Momentum — price vs 52W high; Low Volatility — beta), composite score computation, sector ranking by market cap, peer group classification, 7-phase processing pipeline, `INSERT INTO sector_analytics`.

**What it does:** 7-phase market analytics engine:
1. **Phase A — Market Breadth:** Advance/decline statistics, volume trends
2. **Phase B — Sector Rankings:** Sectors ranked by aggregate market cap
3. **Phase C — Multi-Factor Model:** Each stock scored on 5 factors (Value/Growth/Quality/Momentum/LowVol), composite = weighted average
4. **Phase D — Top Composite Scores:** Top stocks by composite score
5. **Phase E — Peer Group Analysis:** Stocks classified into market cap tiers
6. **Phase F — Sector Analytics:** Per-sector aggregates inserted into `sector_analytics`
7. **Phase G — Processing Stats:** Final statistics and batch_log update

---

### BATCH_COMPREHENSIVE_RISK — `pc/batch_comprehensive_risk.pc` (1,464 lines)
**Complexity: COMPLEX (Flagship)** | FML buffer I/O, 10 conditional phases, internal tpcall chaining.

| Metric | Count |
|---|---|
| EXEC SQL | 48 |
| if/else branches | 135 |
| Host variables | 154 |
| Cursors | 5 |
| SELECT INTO | 4 |
| tpforward/tpcall calls | 0 / 2 (BATCH_EQUITY_REPORT, BATCH_PORTFOLIO_PROCESSOR) |
| COMMIT / ROLLBACK | 1 / 1 |

**Input:** FML buffer with 6 fields (CLIENT_CODE, RISK_DATE, SCENARIO_FLAG, CLIENT_SEGMENT, PORTFOLIO_TYPE, REQUEST_ID).
**Output:** FML buffer with 16 fields (VAR_95 through SECTOR_EXPOSURE_JSON).

**10 Phases (gated by scenario flag bitmask 0x01–0x80):**

| # | Phase | Flag Gate | Description |
|---|---|---|---|
| 1 | Parse FML Input | always | Extract 6 input fields from FML buffer; fall back to defaults if no FML |
| 2 | Data Gathering | always | 5 cursors: portfolio+fundamentals JOIN, 252-day price history, user transactions, sector concentration GROUP BY, margin status. 4 SELECT INTO. Computes position weights, weighted beta, mean/std of daily returns. Falls back to 15 synthetic positions if no DB data. |
| 3 | Risk Metrics | SF_BASIC_RISK | Historical VaR (5th/1st percentile of sorted returns), parametric VaR (z-score method), weighted beta, Sharpe ratio (annualized), max drawdown (peak-to-trough). Persists partial results to `risk_assessment_results`. |
| 4 | Stress Testing | SF_STRESS_TEST | 3 scenarios: market crash (-20%, beta-adjusted), rate spike (+200bps, sector-weighted), sector rotation (IT/Banking/O&G hit harder). Computes per-scenario loss %. Updates DB. |
| 5 | Margin & Exposure | SF_MARGIN | Risk-tier margin rate (CONSERVATIVE=40%, MODERATE=30%, AGGRESSIVE=20%) with segment/portfolio/net-worth/beta adjustments. Concentration surcharge. Computes deficit vs available margin (50% of net worth). |
| 6 | Concentration & Liquidity | SF_CONCENTRATION | Stock concentration (single >20% flags), sector concentration (>40% flags), position count penalty. Liquidity: days-to-liquidate via volume, scored 0–100. |
| 7 | Compliance | SF_COMPLIANCE | KYC status check, PMLA enhanced due diligence (>₹1Cr portfolio), SEBI margin rule check. Composite risk score → grade (LOW/MEDIUM/HIGH/CRITICAL). Action codes generated. |
| 8 | Internal tpcall | SF_INTERNAL | tpcall BATCH_EQUITY_REPORT (risk summary), tpcall BATCH_PORTFOLIO_PROCESSOR (margin re-evaluation). |
| 9 | FML Output | always | Allocates output FML_BUF, Fadd 16 computed fields, tpreturn with FML buffer. |
| 10 | Fallback Return | (error path) | STRING buffer fallback if FML allocation fails. |

**Default flags: 0x7F** (all phases except DEBUG).

---

## Aggregate Metrics

### Per-Service Complexity Ranking

| Tier | Service | .pc Lines | Generated C | EXEC SQL | if/else | Cursors | SELECT INTO | Host Vars |
|---|---|---|---|---|---|---|---|---|
| **COMPLEX** | batch_comprehensive_risk | 1,464 | 1,836 | 48 | 135 | 5 | 4 | 154 |
| **COMPLEX** | batch_market_analytics | 1,149 | 1,537 | 36 | 141 | 3 | 4 | 158 |
| **MEDIUM** | batch_portfolio_processor | 629 | 873 | 26 | 65 | 2 | 2 | 87 |
| **MEDIUM** | batch_equity_transform | 408 | 710 | 31 | 24 | 2 | 4 | 54 |
| **MEDIUM** | batch_equity_report | 365 | 812 | 34 | 8 | 2 | 7 | 46 |
| **SIMPLE-MED** | batch_equity_validate | 375 | 517 | 19 | 25 | 1 | 0 | 35 |
| **SIMPLE** | batch_equity_ingest | 269 | 396 | 16 | 14 | 0 | 0 | 24 |
| **SIMPLE-MED** | batch_transform (posts) | 227 | — | 21 | 9 | 1 | 1 | 17 |
| **SIMPLE** | batch_validate (posts) | 221 | — | 21 | 12 | 1 | 1 | 16 |
| **SIMPLE** | batch_report (posts) | 189 | — | 15 | 5 | 1 | 0 | 17 |
| **SIMPLE** | batch_ingest (posts) | 182 | — | 16 | 5 | 0 | 0 | 15 |
| **STUB** | batch_analytics | 47 | — | 8 | 0 | 0 | 0 | 3 |
| **STUB** | batch_enrichment | 47 | — | 8 | 0 | 0 | 0 | 3 |
| **TOTAL** | **13 services** | **5,572** | — | **319** | **443** | **18** | **27** | **629** |

### Pro*C Patterns Used (by frequency across all services)

| Pattern | Occurrences | Used In |
|---|---|---|
| EXEC SQL CONNECT | 13 | Every service's tpsvrinit |
| EXEC SQL COMMIT | 35 | All non-stub services |
| EXEC SQL ROLLBACK | 18 | All non-stub services |
| EXEC SQL INSERT (host vars) | 25 | INGEST, TRANSFORM, RISK, REPORT |
| EXEC SQL FOR :var INSERT (array bulk) | 4 | INGEST (posts + equity) |
| EXEC SQL SELECT … INTO :hv | 27 | TRANSFORM, REPORT, ANALYTICS, RISK |
| DECLARE / OPEN / FETCH / CLOSE CURSOR | 18 cursors | VALIDATE, TRANSFORM, REPORT, PORTFOLIO, ANALYTICS, RISK |
| EXEC SQL UPDATE (host vars) | 12 | VALIDATE, TRANSFORM, RISK |
| WHENEVER SQLERROR GOTO/DO/CONTINUE | 15 | All services |
| tpforward | 7 | TRANSFORM (posts + equity), REPORT |
| tpcall (internal) | 2 | BATCH_COMPREHENSIVE_RISK → REPORT, PORTFOLIO |
| FML buffer I/O | 16 fields | BATCH_COMPREHENSIVE_RISK only |

### Data Flow Map

```
┌──────────────────────────────────────────────────────────────────────┐
│                        EQUITY PIPELINE                               │
│                                                                      │
│  gen_eod_data.py ──→ data/eod_input.dat                              │
│         │                                                            │
│         ▼                                                            │
│  BATCH_EQUITY_INGEST ──→ equity_staging (NEW)                       │
│         │                                                            │
│         ▼                                                            │
│  BATCH_EQUITY_VALIDATE ──→ equity_staging (VALIDATED/ERROR)         │
│         │                                                            │
│         ▼                                                            │
│  BATCH_EQUITY_TRANSFORM ──→ equity_derived_metrics                   │
│         │                    equity_staging (TRANSFORMED)             │
│         │ tpforward                                                  │
│         ▼                                                            │
│  BATCH_EQUITY_REPORT ──→ batch_log (SUCCESS)                        │
│                                                                      │
│  ── Standalone ──                                                    │
│  BATCH_PORTFOLIO_PROCESSOR ──→ user_portfolios (MTM), batch_log     │
│  BATCH_MARKET_ANALYTICS ──→ sector_analytics, batch_log             │
│  BATCH_COMPREHENSIVE_RISK ──→ risk_assessment_results, batch_log    │
│         │ tpcall                                                     │
│         ├──→ BATCH_EQUITY_REPORT                                     │
│         └──→ BATCH_PORTFOLIO_PROCESSOR                               │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                        POSTS PIPELINE                                 │
│                                                                      │
│  fetch_data.py ──→ data/input.dat (JSONPlaceholder API)             │
│         │                                                            │
│         ▼                                                            │
│  BATCH_INGEST ──→ posts_staging                                     │
│         │                                                            │
│         ▼                                                            │
│  BATCH_VALIDATE ──→ posts_staging (R1/R2/R3 validation)             │
│         │                                                            │
│         ▼                                                            │
│  BATCH_TRANSFORM ──→ posts (word counts, derived metrics)            │
│         │            post_stats (per-user aggregates)                 │
│         │ tpforward                                                  │
│         ▼                                                            │
│  BATCH_REPORT ──→ batch_log (aggregate report)                      │
│                                                                      │
│  [BATCH_ANALYTICS] — stub, reserved for future use                   │
│  [BATCH_ENRICHMENT] — stub, reserved for future use                  │
└──────────────────────────────────────────────────────────────────────┘
```


## Snapshot & Verification Infrastructure

### Purpose

The snapshot system captures canonical output from every pipeline mode so converted services (Python, Go, etc.) can be verified automatically. Instead of manually inspecting output, a single command diffs the converted service's output against the known-good baseline.

All output is **deterministic** — random seeds are fixed (`gen_eod_data.py` uses `random.seed(42)`, the risk service uses `srand(42)`), and each run starts with a fresh database. This means snapshots are reproducible and verification is byte-for-byte after normalization.

### Files

| File | Purpose |
|---|---|
| `snapshots/pipeline.expected` (75 lines) | INGEST → VALIDATE → TRANSFORM → REPORT output |
| `snapshots/portfolio.expected` (42 lines) | BATCH_PORTFOLIO_PROCESSOR standalone output |
| `snapshots/analytics.expected` (68 lines) | BATCH_MARKET_ANALYTICS standalone output |
| `snapshots/risk.expected` (26 lines) | BATCH_COMPREHENSIVE_RISK output with FML metrics |
| `snapshots/all.expected` (178 lines) | All 7 services run sequentially |
| `scripts/capture_snapshots.py` | Generates/updates all `.expected` files |
| `scripts/verify_output.py` | Diffs actual output against expected snapshots |

### How It Works

```
make equity              ──→ bin/equity_app (C + SQLite)
    │
    ▼
python3 scripts/capture_snapshots.py
    │
    │  For each mode (pipeline, portfolio, analytics, risk, all):
    │    1. rm data/batch.db          ← fresh database
    │    2. gen_eod_data.py --count 200  ← deterministic input
    │    3. bin/equity_app --{mode}   ← run the pipeline
    │    4. Normalize stdout           ← strip dates/times/epochs
    │    5. Save → snapshots/{mode}.expected
    │
    ▼
snapshots/*.expected     ← canonical baselines (checked in)
```

### Normalization Rules

The verifier normalizes both expected and actual output before comparison:

| Pattern | Example | Normalized To |
|---|---|---|
| ISO dates | `2026-07-07` | `YYYY-MM-DD` |
| Timestamps | `15:12:11` | `HH:MM:SS` |
| Date+time | `2026-07-07 20:41` | `YYYY-MM-DD HH:MM` |
| Epoch batch IDs | `batch_id=1783437136` | `batch_id=EPOCH` |
| Large integers | `15490064949` | `EPOCH` |
| Userlog lines | `[2026-07-07 20:41:17] ...` | (removed) |

This means a converted Python/Go service just needs to produce the same logical output — dates, times, and generated IDs won't cause spurious failures.

### Usage

```bash
# Capture fresh snapshots (after modifying services)
make snapshots

# Verify current build matches snapshots
make verify

# Verify a single mode
python3 scripts/verify_output.py --mode pipeline

# Verify custom command against a snapshot
python3 scripts/verify_output.py --mode pipeline --snapshot my_baseline.expected
```

### Using for AI Conversion Evaluation

When a model converts a `.pc` service to Python/Go/etc.:

1. The converted code must read the same `data/eod_input.dat` and produce formatted output
2. Run `python3 scripts/verify_output.py --mode pipeline` (or relevant mode)
3. The verifier runs the converted service with fresh data, normalizes, and diffs

**Pass criteria:** Exit code 0 (output matches snapshot byte-for-byte after normalization).
**Fail criteria:** Non-zero exit with unified diff showing what diverged.

For a graded eval across tiers:

```bash
for mode in pipeline portfolio analytics risk all; do
    echo "=== $mode ==="
    python3 scripts/verify_output.py --mode "$mode"
done
```

Each mode exercises different levels of complexity — `pipeline` tests basic cursor/bulk-insert/validation, `risk` tests FML buffers and multi-phase conditional execution with internal tpcall chaining. A model that passes `pipeline` and `portfolio` but fails `analytics` and `risk` tells you its ceiling is MEDIUM-tier complexity.
