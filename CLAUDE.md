# Tuxedo Batch Processing POC — Pro*C + SQLite

## Purpose

This repo is a **testbed for AI code conversion experiments**. The goal: determine which AI models/tools can best convert legacy Tuxedo/Pro*C batch processing code to modern languages (Python, Go, Java, Rust, etc.).

The `.pc` files in `pc/` are **authentic Pro*C/Tuxedo code** with `EXEC SQL` embedded SQL, `tpsvrinit`/`tpsvrdone` lifecycle hooks, `TPSVCINFO` service signatures, cursor declarations, array bulk inserts, and `tpforward` service chaining. A custom Python preprocessor converts these to C + SQLite so the system actually compiles and runs.

## Quick Start

```bash
make demo        # Build and run with 10 demo records (no network needed)
make run         # Fetch from JSONPlaceholder API, then build and run
make fetch       # Just fetch data from the API
make clean       # Remove build artifacts
make cleanall    # Remove everything including database
```

## Architecture

```
.pc files (authentic Pro*C)
    │
    ▼ scripts/preproc.py
.c files (C + sqlite3_mprintf calls)
    │
    ▼ gcc + libsqlite3
bin/batch_app (single executable)
```

## Directory Structure

| Path | Purpose |
|---|---|
| `pc/*.pc` | Pro*C source files — **the code AI agents should convert** |
| `pc/batch_orchestrator.c` | Main driver, service dispatch table, pipeline control |
| `scripts/preproc.py` | EXEC SQL → sqlite3_mprintf preprocessor |
| `scripts/fetch_data.py` | Fetch data from JSONPlaceholder API |
| `include/` | Simulated Tuxedo headers (atmi.h, sqlca.h, userlog.h) |
| `src/tuxlib.c` | Tuxedo ATMI simulation (tpcall, tpreturn, tpforward) |
| `src/sqlca.c` | SQL Communication Area simulation |
| `config/ubbconfig.txt` | UBBCONFIG reference (not compiled — topology doc) |
| `sql/schema.sql` | SQLite schema (staging, final tables, batch log) |
| `data/` | Runtime data (input.dat, batch.db) |

## Batch Pipeline

```
BATCH_INGEST → BATCH_VALIDATE → BATCH_TRANSFORM → BATCH_REPORT
```

| Service | File | What It Does |
|---|---|---|
| BATCH_INGEST | pc/batch_ingest.pc | Parses pipe-delimited data, bulk inserts into staging via `FOR :count INSERT` |
| BATCH_VALIDATE | pc/batch_validate.pc | Cursor-based validation (R1: non-empty title, R2: non-empty body, R3: body ≥ 20 chars) |
| BATCH_TRANSFORM | pc/batch_transform.pc | Cursor-based transform: compute word counts, upsert aggregates, tpforward to REPORT |
| BATCH_REPORT | pc/batch_report.pc | Aggregate queries: total posts/users/words, top user, batch log history |

## Pro*C Patterns Used (for AI conversion reference)

1. **Array bulk insert** (`batch_ingest.pc:185-190`): `EXEC SQL FOR :count INSERT INTO table VALUES (:arr1, :arr2, :scalar)`
2. **Cursor fetch loop** (`batch_validate.pc:173-200`): `DECLARE c CURSOR / OPEN / FETCH INTO :hv / CLOSE`
3. **SELECT INTO** (`batch_report.pc:148-155`): `EXEC SQL SELECT COUNT(*), SUM(x) INTO :hv1, :hv2 FROM table`
4. **Service chaining** (`batch_transform.pc:270`): `tpforward("BATCH_REPORT", data, len, 0)`
5. **Error handling** (`batch_ingest.pc:148`): `EXEC SQL WHENEVER SQLERROR GOTO label` / `CONTINUE`
6. **Host variable declaration**: `EXEC SQL BEGIN/END DECLARE SECTION` with arrays, VARCHAR, scalars
7. **Transaction control**: `EXEC SQL COMMIT` / `EXEC SQL ROLLBACK` with batch commit strategy

## Preprocessor Details

`scripts/preproc.py` converts Pro*C to C + SQLite:

- `EXEC SQL CONNECT` → `sqlite3_open("data/batch.db")`
- `EXEC SQL INSERT … VALUES (:hv)` → `sqlite3_mprintf("%Q", hv)` (auto-quotes strings)
- `EXEC SQL FOR :count INSERT` → `for(_i=0; _i<count; _i++)` loop with array `[_i]` indexing
- `EXEC SQL SELECT … INTO :hv` → `sqlite3_prepare / step / column_int_or_text`
- `EXEC SQL DECLARE c CURSOR / OPEN / FETCH / CLOSE` → `sqlite3_prepare / step / finalize`
- `VARCHAR name[N]` → `struct { unsigned short len; char arr[N]; } name`
- Detects array vs scalar vars from DECLARE SECTION for correct codegen

Verbose logging: `python3 scripts/preproc.py -v pc/*.pc -o build/`

## Adding New .pc Files

1. Add `pc/my_service.pc` with standard Tuxedo structure (tpsvrinit, tpsvrdone, service function)
2. Register the service in `pc/batch_orchestrator.c` (extern decl + SERVICE_TABLE entry + svrinit/svrdone decl)
3. Add to Makefile `PC_SRC` list
4. `make demo`

## Schema

- `posts_staging` — raw ingested data with batch tracking
- `posts` — transformed/validated posts with computed word counts
- `post_stats` — per-user aggregates (post count, total words, avg words)
- `batch_log` — service execution history (like Tuxedo tmqueue)

## Limitations (vs. real Oracle Tuxedo)

- No XA two-phase commit (SQLite doesn't support prepared transactions)
- No multi-process servers (all services run in one process)
- No FML/VIEW typed buffers (STRING buffer only)
- No load balancing or MSSQ (single threaded)
- Oracle-specific SQL (DECODE, CONNECT BY, hints) not supported
- VARCHAR .arr field access instead of native Oracle VARCHAR

## Dependencies

- Python 3 (preprocessor, data fetching)
- gcc/clang
- SQLite 3 (libsqlite3-dev or Homebrew: `brew install sqlite`)
- Optional: pkg-config (for automatic sqlite3 detection)

## License

MIT — this is a testbed for AI code conversion research.
