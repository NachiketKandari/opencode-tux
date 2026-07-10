# Walkthrough: How Tux Batch Processing Runs Here

## The problem

Oracle Tuxedo + Pro*C can't run on macOS. Oracle Tuxedo requires Linux/Windows Server with an Oracle license. Pro*C requires an Oracle precompiler and database. For AI code conversion experiments, we need authentic `.pc` files that actually compile and run.

## The approach: a two-layer simulation

### Layer 1: Authentic Pro*C source files (`pc/*.pc`)

These are **real Pro*C code** with `EXEC SQL` syntax, `tpsvrinit`/`tpsvrdone` lifecycle hooks, `TPSVCINFO` service signatures, cursor declarations, array bulk inserts, and `tpforward` service chaining. An AI agent sees genuine Tuxedo patterns.

### Layer 2: A Python preprocessor (`scripts/preproc.py`)

A ~600-line preprocessor that converts `EXEC SQL` blocks into `sqlite3_mprintf` C calls. It handles the subset of Pro*C used in batch processing:

| Pro*C pattern | Generated C + SQLite |
|---|---|
| `EXEC SQL CONNECT :uid IDENTIFIED BY :pwd` | `sqlite3_open("data/batch.db")` |
| `EXEC SQL INSERT INTO t VALUES (:hv)` | `sqlite3_mprintf("INSERT INTO t VALUES (%Q)", hv)` |
| `EXEC SQL FOR :count INSERT INTO t VALUES (:arr)` | `for(_i=0; _i<count; _i++)` loop with array `[_i]` indexing |
| `EXEC SQL SELECT ... INTO :hv FROM t` | `sqlite3_prepare_v2 / sqlite3_step / sqlite3_column_int_or_text` |
| `EXEC SQL DECLARE c CURSOR FOR SELECT ...` | `sqlite3_stmt *c_stmt = NULL` (prepared at OPEN, finalized at CLOSE) |
| `EXEC SQL COMMIT WORK RELEASE` | `sqlite3_exec("COMMIT")` then `sqlite3_close()` |
| `EXEC SQL WHENEVER SQLERROR GOTO label` | `if (sqlca.sqlcode < 0) goto label` after each statement |
| `VARCHAR name[30]` | `struct { unsigned short len; char arr[30]; } name` |

The preprocessor auto-detects array vs scalar variables from the `DECLARE SECTION`, tracks C types for correct `%d`/`%Q`/`%f` formatting, strips SQL string literals before scanning for host variables, and escapes `%` characters to prevent format string bugs.

### Layer 2.5: Simulated Tuxedo runtime (`src/tuxlib.c`, `include/`)

A minimal ATMI implementation (~200 lines of C):

- **tpcall** — synchronous service dispatch with failure propagation
- **tpreturn** — copies return data and sets TPSUCCESS/TPFAIL for tpcall to check
- **tpforward** — service chaining (BATCH_TRANSFORM forwards to BATCH_REPORT)
- **userlog** — timestamped logging to stderr
- **sqlca** — SQL Communication Area with sqlcode, error messages, row counts

## Build pipeline

```
.pc files ──[preproc.py]──► .c files ──[gcc + libsqlite3]──► bin/batch_app
```

Three commands: `make demo` (build + run with 10 demo records, no network needed).

## What's real, what's simulated

**Authentic Pro*C** (would run on real Tuxedo with minor dialect changes):
- Service structure: `tpsvrinit` → `BATCH_SVC(TPSVCINFO*)` → `tpsvrdone`
- Embedded SQL: `EXEC SQL INSERT/SELECT/UPDATE/DELETE/FOR/COMMIT/ROLLBACK`
- Cursor lifecycle: `DECLARE → OPEN → FETCH → CLOSE`
- Error handling: `WHENEVER SQLERROR GOTO label / CONTINUE`
- Host variables in `BEGIN/END DECLARE SECTION`
- Service dispatch table (UBBCONFIG equivalent)

**Simulated** (would not exist in real Tuxedo):
- Single process instead of separate server processes
- SQLite instead of Oracle (no XA, no Pro*C precompiler)
- STRING buffer type only (no FML/VIEW typed buffers)
- In-process dispatch instead of bulletin board + IPC

**Oracle → SQLite adaptations** (documented in the `.pc` files):
- `LIMIT` instead of `ROWNUM`/`FETCH FIRST`
- `INSERT OR REPLACE` instead of `MERGE`
- `CAST(... AS REAL)` instead of `CAST(... AS NUMBER)`

## Running it

```bash
make demo        # 10 demo records, no network
make run         # Fetches from JSONPlaceholder API
make cleanall    # Remove everything
```

## Adding a new service

1. Write `pc/my_service.pc` with the standard template:
```c
EXEC SQL INCLUDE SQLCA;
EXEC SQL BEGIN DECLARE SECTION;
    VARCHAR uid[30];
    VARCHAR pwd[30];
    /* your host variables */
EXEC SQL END DECLARE SECTION;

int tpsvrinit(int argc, char *argv[]) {
    EXEC SQL CONNECT :uid IDENTIFIED BY :pwd;
    if (sqlca.sqlcode != 0) return -1;
    return 0;
}
void tpsvrdone(void) {
    EXEC SQL COMMIT WORK RELEASE;
}
void MY_SERVICE(TPSVCINFO *rqst) {
    /* EXEC SQL statements */
    tpreturn(TPSUCCESS, 0, result_data, result_len, 0);
}
```

2. Register in `pc/batch_orchestrator.c` (add extern decl + svrinit/svrdone + service table entry)
3. Add to Makefile `PC_SRC` list
4. `make demo`
