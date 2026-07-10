-- Tux Batch Processing Demo: SQLite Schema
-- Simulates tables that would exist in Oracle under Tuxedo/Pro*C

-- Staging table for raw ingested data
CREATE TABLE IF NOT EXISTS posts_staging (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    title           TEXT    NOT NULL,
    body            TEXT    NOT NULL,
    ingest_batch_id INTEGER NOT NULL,
    ingest_status   TEXT    DEFAULT 'NEW'
        CHECK (ingest_status IN ('NEW', 'VALIDATED', 'TRANSFORMED', 'ERROR')),
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- Final posts table (post-transformation)
CREATE TABLE IF NOT EXISTS posts (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    word_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    DEFAULT (datetime('now'))
);

-- Aggregated statistics per user
CREATE TABLE IF NOT EXISTS post_stats (
    user_id         INTEGER PRIMARY KEY,
    post_count      INTEGER NOT NULL DEFAULT 0,
    total_words     INTEGER NOT NULL DEFAULT 0,
    avg_words       REAL    NOT NULL DEFAULT 0.0,
    last_updated    TEXT    DEFAULT (datetime('now'))
);

-- Batch processing log (like Tuxedo tmqueue persistent queue)
CREATE TABLE IF NOT EXISTS batch_log (
    batch_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name    TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'STARTED'
        CHECK (status IN ('STARTED', 'RUNNING', 'SUCCESS', 'FAILED')),
    rows_processed  INTEGER DEFAULT 0,
    error_message   TEXT,
    started_at      TEXT    DEFAULT (datetime('now')),
    completed_at    TEXT
);

-- Index for efficient batch status queries
CREATE INDEX IF NOT EXISTS idx_posts_staging_batch ON posts_staging(ingest_batch_id);
CREATE INDEX IF NOT EXISTS idx_posts_user_id ON posts(user_id);
CREATE INDEX IF NOT EXISTS idx_batch_log_service ON batch_log(service_name);
