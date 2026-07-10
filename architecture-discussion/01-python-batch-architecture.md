# Python Batch Processing Architecture — Tuxedo/Pro*C to Python Conversion

## Context

Converting Tuxedo/Pro*C batch processing code to idiomatic Python for ICICI Securities.
Target environment: Oracle SQL database, millions of rows per run, dozens of processes throughout the day.

## Approach Selected: oracledb Direct (no SQLAlchemy)

**Approach B adapted** — `oracledb` native async pooling + `structlog` + `prometheus_client`.

SQLAlchemy was removed per decision that Oracle's long-term driver support favors `oracledb` directly. The `oracledb` package provides native async connection pooling (`create_pool_async`), so we don't need SQLAlchemy for that. All SQL is raw strings (matching Pro*C 1:1), executed via `cursor.execute(sql, params)`.

### Dependencies (~4 runtime)

| Package | Purpose |
|---|---|
| `oracledb>=2.0` | Oracle driver (thin mode) + async connection pool |
| `structlog>=24.0` | Structured JSON logging |
| `prometheus-client>=0.19` | Metrics exposition |
| `typer>=0.12` | CLI entry points |

---

## Directory Layout

```
batch-framework/
├── pyproject.toml              # deps, entry points, build config
├── alembic/                    # schema migrations
│   ├── env.py
│   └── versions/
├── src/
│   ├── batch/                  # the framework itself (~200 lines total)
│   │   ├── __init__.py
│   │   ├── base.py             # BatchProcess base class
│   │   ├── db.py               # connection pool, session, transaction helpers
│   │   ├── log.py              # structlog configuration
│   │   ├── metrics.py          # prometheus_client setup + built-in counters
│   │   └── cli.py              # typer app factory
│   │
│   ├── services/               # one module per batch process
│   │   ├── ingest.py
│   │   ├── validate.py
│   │   ├── transform.py
│   │   └── report.py
│   │
│   └── common/                 # shared business logic, constants
│       ├── __init__.py
│       └── constants.py
│
└── tests/
    ├── test_ingest.py
    └── ...
```

Each `services/*.py` is a single batch process — self-contained, ~100-300 lines, following one consistent template. The `batch/` package changes rarely. New processes only need `services/my_process.py` and a registered entry point.

---

## BatchProcess Base Class

Every batch service follows this template. Mirrors the familiar `tpsvrinit → run → tpsvrdone` lifecycle from Tuxedo, but Pythonic:

```python
class BatchProcess:
    name: str

    async def init_db(self, conn: AsyncConnection) -> None:
        """One-time setup: validate schema, warm caches. Called once at boot."""
        pass

    async def run(self, conn: AsyncConnection) -> dict:
        """The batch logic. Receives an active connection from the pool.
        Returns a result dict (e.g. {"ingested": 5000, "batch_id": 123}).
        MUST be overridden."""
        raise NotImplementedError

    async def done(self, conn: AsyncConnection) -> None:
        """Cleanup: close cursors, log summary. Called once after run()."""
        pass
```

### Framework-provided automation (subclasses don't touch)

- Opens a connection from the pool
- Wraps `run()` in a transaction — any unhandled exception triggers rollback
- Writes a `batch_log` row with service name, status, rows_processed, duration_ms
- Increments Prometheus counters: `batch_runs_total{service, status}`, `batch_duration_seconds`
- Logs start/end with request IDs for traceability

### Error handling

- `run()` raises → transaction rolls back, log row gets `status='FAILED'`, Prometheus gets `status=failed`
- `run()` returns → transaction commits, log row gets `status='SUCCESS'`

### Concrete service example

```python
class IngestService(BatchProcess):
    name = "BATCH_INGEST"

    async def run(self, conn):
        result = await conn.execute(
            text("INSERT INTO posts_staging (...) VALUES (...)"),
            [...]
        )
        return {"ingested": result.rowcount}
```

---

## Database Layer (`batch/db.py`)

```python
import oracledb

_pool: oracledb.AsyncConnectionPool | None = None

async def init_db_pool(
    dsn: str, user: str, password: str,
    min: int = 2, max: int = 10, increment: int = 2,
) -> None:
    global _pool
    _pool = await oracledb.create_pool_async(
        user=user, password=password, dsn=dsn,
        min=min, max=max, increment=increment,
    )

async def get_connection() -> oracledb.AsyncConnection:
    return await _pool.acquire()

async def release_connection(conn: oracledb.AsyncConnection) -> None:
    await _pool.release(conn)
```

### Key decisions

- **Async native** — `oracledb.create_pool_async()` provides connection pooling directly, no middleware needed.
- **Thin mode** — no Oracle Instant Client required. Works over plain TCP.
- **No SQLAlchemy** — Oracle's long-term driver strategy favors `oracledb` directly. Raw SQL via `cursor.execute(sql, params)` maps 1:1 to Pro*C host variables.
- **Pool configuration** — `min=2, max=10, increment=2`. Tune per workload.

### Transaction helper

```python
@asynccontextmanager
async def transactional(conn):
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
```

The base class uses this pattern to wrap `run()`. Services that need multiple transactions inside `run()` can call `conn.commit()` / `conn.rollback()` directly.

---

## Observability

### Logging — `structlog` in JSON format (`batch/log.py`)

```python
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.JSONRenderer(),
    ],
)
structlog.get_logger().bind(service=service_name)
```

Every log line is JSON: `service`, `timestamp`, `level`, `event`, `request_id`. Ships to stdout → Fluentd/Logstash → Grafana Loki or ELK.

### Metrics — `prometheus_client` (`batch/metrics.py`)

```python
batch_runs = Counter(
    "batch_runs_total", "Batch process executions",
    ["service", "status"],
)
batch_duration = Histogram(
    "batch_duration_seconds", "Batch run duration",
    ["service"],
    buckets=[1, 5, 15, 30, 60, 120, 300, 600, 1800],
)
batch_rows = Counter(
    "batch_rows_processed_total", "Rows processed",
    ["service"],
)
db_pool_available = Gauge(
    "db_pool_available", "Available connections in pool",
)
```

The framework increments these automatically in `base.py`. Services can add custom metrics.

### Exposure

Optional HTTP server on port 9090 (starts when `--metrics` flag is passed):

```python
from prometheus_client import start_http_server
start_http_server(9090)
```

This gives Prometheus a scrape target. Grafana dashboards query these metric names directly.

---

## CLI (`batch/cli.py`)

Each service gets a `typer` entry point:

```bash
batch-ingest --input data/input.dat --metrics
batch-validate --batch-id 12345
batch-transform --metrics
batch-report --output-format json
```

`--metrics` starts the Prometheus HTTP server. The framework layer handles argument parsing, logging setup, and pool initialization before delegating to the service.

---

## Pro*C → Python Mapping Reference

| Pro*C Pattern | Python Equivalent |
|---|---|
| `EXEC SQL CONNECT` | `init_db_pool(dsn, user, pwd)` — pool created at startup |
| `EXEC SQL INSERT … VALUES (:hv)` | `await cursor.execute(sql, {"hv": val})` |
| `EXEC SQL FOR :count INSERT` | `await cursor.executemany(sql, params_list)` |
| `EXEC SQL DECLARE c CURSOR / FETCH / CLOSE` | `await cursor.execute(sql); rows = await cursor.fetchall()` |
| `EXEC SQL SELECT … INTO :hv` | `await cursor.execute(sql); row = await cursor.fetchone(); hv = row[0]` |
| `tpforward("SVC", data)` | Call next service directly in orchestrator |
| `EXEC SQL COMMIT / ROLLBACK` | `await conn.commit()` / `await conn.rollback()` |
| `WHENEVER SQLERROR GOTO` | `try/except Exception` (oracledb raises on SQL errors) |
| Host variable arrays | Python dicts/lists passed as bound params |
| `tpsvrinit/tpsvrdone` | `init_db()` / `done()` hooks on BatchProcess |
| `TPSVCINFO` struct | `BatchProcess` class with typed fields |

---

## Scheduling

Not part of this framework — use whatever your team uses:
- **Cron** for simple "every night at 2am"
- **Airflow** if you need DAG-based dependency management between processes
- **Control-M** if that's what ICICI Securities already has

The framework is just a CLI tool; the scheduler calls `batch-<service-name>` with the right flags.

---

## Open Questions

1. **Scheduler**: Which scheduler does ICICI Securities use today for batch jobs?
2. **Oracle connectivity**: Is the Oracle DB accessible via `oracledb` thin mode (TCP), or is there a thick-client/Oracle Client requirement?
3. **Containerization**: Will these run in containers (K8s) or on VMs/bare metal?
4. **Migration strategy**: Parallel run (Python side-by-side with Tuxedo) or hard cutover?
