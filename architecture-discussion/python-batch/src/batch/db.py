"""Database layer — oracledb async connection pool, no SQLAlchemy."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

import oracledb


# ── Connection pool ──────────────────────────────────────────────────────────

@dataclass
class Pool:
    """Holds the oracledb async connection pool."""
    pool: oracledb.AsyncConnectionPool


_pool: Optional[Pool] = None


async def init_db_pool(
    dsn: str,
    user: str,
    password: str,
    min: int = 2,
    max: int = 10,
    increment: int = 2,
) -> Pool:
    """Create the async connection pool. Called once at process start."""
    global _pool
    _pool = Pool(
        pool=await oracledb.create_pool_async(
            user=user,
            password=password,
            dsn=dsn,
            min=min,
            max=max,
            increment=increment,
        )
    )
    return _pool


async def get_connection() -> oracledb.AsyncConnection:
    """Acquire a connection from the pool."""
    if _pool is None:
        raise RuntimeError("Pool not initialized. Call init_db_pool() first.")
    return await _pool.pool.acquire()


async def release_connection(conn: oracledb.AsyncConnection) -> None:
    """Release a connection back to the pool."""
    if _pool is not None:
        await _pool.pool.release(conn)


# ── Transaction helper ───────────────────────────────────────────────────────

@asynccontextmanager
async def transactional(conn: oracledb.AsyncConnection):
    """Explicit transaction boundary. Commits on success, rolls back on error."""
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
