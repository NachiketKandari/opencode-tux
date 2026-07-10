"""
Integration test — runs the Python batch pipeline against SQLite and compares
results to the C baseline (from `make demo` output).

C baseline (10 demo records):
  - BATCH_INGEST:    ingested=10
  - BATCH_VALIDATE:  total=10, valid=10, invalid=0
  - BATCH_TRANSFORM: transformed=10, skipped=0
  - BATCH_REPORT:    posts=10, users=5, words=238, avg_words=23.80, avg_posts=2.00
                     top_user=1, top_posts=2, top_words=50
"""

import sqlite3
import time

# ── C baseline values (from make demo run) ───────────────────────────────────

BASELINE = {
    "ingest_total": 10,
    "validate_total": 10,
    "validate_valid": 10,
    "validate_invalid": 0,
    "transform_transformed": 10,
    "transform_skipped": 0,
    "report_total_posts": 10,
    "report_total_users": 5,
    "report_total_words": 238,
    "report_top_user_id": 1,
    "report_top_user_posts": 2,
    "report_top_user_words": 50,
}


def setup_schema(db_path=":memory:"):
    """Create tables matching sql/schema.sql."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
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

        CREATE TABLE IF NOT EXISTS posts (
            id          INTEGER PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            title       TEXT    NOT NULL,
            body        TEXT    NOT NULL,
            word_count  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS post_stats (
            user_id         INTEGER PRIMARY KEY,
            post_count      INTEGER NOT NULL DEFAULT 0,
            total_words     INTEGER NOT NULL DEFAULT 0,
            avg_words       REAL    NOT NULL DEFAULT 0.0,
            last_updated    TEXT    DEFAULT (datetime('now'))
        );

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
    """)
    conn.commit()
    return conn


# ── Demo data (identical to batch_orchestrator.c:141-151) ─────────────────────

DEMO_DATA = (
    "1|1|sunt aut facere repellat provident occaecati excepturi optio|"
    "quia et suscipit suscipit recusandae consequuntur expedita et cum reprehenderit molestiae ut ut quas totam nostrum rerum est autem sunt rem eveniet architecto\n"
    "1|2|qui est esse rerum tempore vitae|"
    "est rerum tempore vitae sequi sint nihil reprehenderit dolor beatae ea dolores neque fugiat blanditiis voluptate porro vel nihil molestiae ut reiciendis qui aperiam non debitis possimus\n"
    "2|3|ea molestias quasi exercitationem repellat|"
    "et iusto sed quo iure voluptatem occaecati omnis eligendi aut ad voluptatem doloribus vel accusantium quis pariatur molestiae porro eius odio et labore et velit aut\n"
    "2|4|eum et est occaecati ullam saepe|"
    "ullam et saepe reiciendis voluptatem adipisci sit amet autem assumenda provident rerum culpa quis hic commodi nesciunt rem tenetur doloremque ipsam iure quis sunt voluptatem rerum\n"
    "3|5|nesciunt quas odio dolorem tempora|"
    "repudiandae veniam quaerat sunt sed alias aut fugiat sit autem sed est voluptatem omnis possimus esse voluptatibus quis est aut tenetur dolor neque dolorum\n"
    "3|6|dolorem eum magni eos aperiam quia|"
    "qui ratione voluptatem sequi nesciunt neque porro quisquam est qui dolorem ipsum quia dolor sit amet consectetur adipisci velit sed quia non numquam eius modi tempora\n"
    "4|7|magnam facilis autem voluptatem|"
    "dolore placeat quibusdam ea quo voluptas nulla veniam nisi odit ut quas qui voluptatem officiis harum nihil quis provident mollitia nobis aliquid\n"
    "4|8|dolorem dolore est ipsam aspernatur|"
    "ut aspernatur corporis harum nihil quis provident sequi mollitia nobis aliquid molestiae perspiciatis et ea nemo ab reprehenderit accusantium quas voluptate dolores\n"
    "5|9|nesciunt iure omnis dolorem|"
    "nam qui vel suscipit distinctio nihil minus explicabo ipsum consequatur non quasi voluptatem atque molestiae natus rerum excepturi deleniti voluptas\n"
    "5|10|optio molestias id quia eos|"
    "voluptatem animi nihil autem numquam et voluptatem nulla et autem sint dolorum sit ducimus autem reprehenderit perspiciatis error sit voluptatem accusantium doloremque\n"
)


# ── Phase 1: BATCH_INGEST ────────────────────────────────────────────────────

def phase_ingest(conn, input_data):
    """Exact Python replica of BATCH_INGEST from batch_ingest.pc."""
    cur = conn.cursor()
    batch_id = int(time.time())
    total_ingested = 0
    batch_rows = []

    for line in input_data.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 4:
            continue
        uid, pid, title, body = parts[0], parts[1], parts[2], parts[3]

        batch_rows.append((int(pid), int(uid), title[:255], body[:1023], batch_id))

        if len(batch_rows) >= 100:
            cur.executemany(
                "INSERT INTO posts_staging (id, user_id, title, body, ingest_batch_id) "
                "VALUES (?, ?, ?, ?, ?)",
                batch_rows,
            )
            total_ingested += len(batch_rows)
            batch_rows = []

    # Final flush
    if batch_rows:
        cur.executemany(
            "INSERT INTO posts_staging (id, user_id, title, body, ingest_batch_id) "
            "VALUES (?, ?, ?, ?, ?)",
            batch_rows,
        )
        total_ingested += len(batch_rows)

    conn.commit()

    # batch_log — SQL preserved from batch_ingest.pc:165-166
    cur.execute(
        "INSERT INTO batch_log (service_name, status, rows_processed) "
        "VALUES ('BATCH_INGEST', 'SUCCESS', ?)",
        (total_ingested,),
    )
    conn.commit()
    return {"ingested": total_ingested, "batch_id": batch_id}


# ── Phase 2: BATCH_VALIDATE ──────────────────────────────────────────────────

def _validate(title, body):
    """Validation rules — identical to batch_validate.pc:92-110."""
    if not title or len(title) == 0:
        return False, "R1: empty title"
    if not body or len(body) == 0:
        return False, "R2: empty body"
    if len(body) < 20:
        return False, f"R3: body too short ({len(body)} chars)"
    return True, "OK"


def phase_validate(conn, batch_id):
    """Exact Python replica of BATCH_VALIDATE from batch_validate.pc."""
    cur = conn.cursor()

    # SQL preserved from batch_validate.pc:45-49
    cur.execute(
        "SELECT id, user_id, title, body "
        "FROM posts_staging "
        "WHERE ingest_status = 'NEW' "
        "  AND ingest_batch_id = ?",
        (batch_id,),
    )

    valid_count = 0
    invalid_count = 0
    empty_title_count = 0
    empty_body_count = 0
    short_body_count = 0

    for row in cur.fetchall():
        post_id, user_id, title, body = row[0], row[1], row[2], row[3]
        valid, reason = _validate(title, body)

        if valid:
            valid_count += 1
            # SQL preserved from batch_validate.pc:167-169
            cur.execute(
                "UPDATE posts_staging SET ingest_status = 'VALIDATED' WHERE id = ?",
                (post_id,),
            )
        else:
            invalid_count += 1
            if "R1" in reason:
                empty_title_count += 1
            if "R2" in reason:
                empty_body_count += 1
            if "R3" in reason:
                short_body_count += 1

            # SQL preserved from batch_validate.pc:178-180
            cur.execute(
                "UPDATE posts_staging SET ingest_status = 'ERROR' WHERE id = ?",
                (post_id,),
            )

        total = valid_count + invalid_count
        if total % 200 == 0:
            conn.commit()

    conn.commit()

    total = valid_count + invalid_count

    # SQL preserved from batch_validate.pc:197-198
    cur.execute(
        "INSERT INTO batch_log (service_name, status, rows_processed) "
        "VALUES ('BATCH_VALIDATE', 'SUCCESS', ?)",
        (total,),
    )
    conn.commit()

    return {
        "total": total,
        "valid": valid_count,
        "invalid": invalid_count,
        "empty_title": empty_title_count,
        "empty_body": empty_body_count,
        "short_body": short_body_count,
    }


# ── Phase 3: BATCH_TRANSFORM ─────────────────────────────────────────────────

def _compute_word_count(text):
    """Count words — identical logic to batch_transform.pc:98-114."""
    if not text:
        return 0
    count = 0
    in_word = False
    for ch in text:
        if ch.isspace():
            in_word = False
        elif not in_word:
            in_word = True
            count += 1
    return count


def phase_transform(conn, batch_id):
    """Exact Python replica of BATCH_TRANSFORM from batch_transform.pc."""
    cur = conn.cursor()

    # SQL preserved from batch_transform.pc:55-59
    cur.execute(
        "SELECT id, user_id, title, body "
        "FROM posts_staging "
        "WHERE ingest_status = 'VALIDATED' "
        "  AND ingest_batch_id = ?",
        (batch_id,),
    )

    transformed = 0
    skipped = 0

    for row in cur.fetchall():
        post_id, user_id, title, body = row[0], row[1], row[2], row[3]
        word_count = _compute_word_count(body)

        if word_count < 5:
            skipped += 1
            # SQL preserved from batch_transform.pc:161-163
            cur.execute(
                "UPDATE posts_staging SET ingest_status = 'TRANSFORMED' WHERE id = ?",
                (post_id,),
            )
            continue

        # SQL preserved from batch_transform.pc:168-169
        cur.execute(
            "INSERT INTO posts (id, user_id, title, body, word_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (post_id, user_id, title, body, word_count),
        )

        # SQL preserved from batch_transform.pc:172-175
        cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(word_count), 0) "
            "FROM posts WHERE user_id = ?",
            (user_id,),
        )
        agg_count, agg_total_words = cur.fetchone()

        # SQL preserved from batch_transform.pc:177-180
        avg_words = (float(agg_total_words) / float(agg_count)) if agg_count > 0 else 0.0
        cur.execute(
            "INSERT OR REPLACE INTO post_stats "
            "(user_id, post_count, total_words, avg_words) "
            "VALUES (?, ?, ?, ?)",
            (user_id, agg_count, agg_total_words, avg_words),
        )

        # SQL preserved from batch_transform.pc:183-185
        cur.execute(
            "UPDATE posts_staging SET ingest_status = 'TRANSFORMED' WHERE id = ?",
            (post_id,),
        )

        transformed += 1

        if transformed % 200 == 0:
            conn.commit()

    conn.commit()

    # SQL preserved from batch_transform.pc:201-202
    cur.execute(
        "INSERT INTO batch_log (service_name, status, rows_processed) "
        "VALUES ('BATCH_TRANSFORM', 'SUCCESS', ?)",
        (transformed,),
    )
    conn.commit()

    return {"transformed": transformed, "skipped": skipped}


# ── Phase 4: BATCH_REPORT ────────────────────────────────────────────────────

def phase_report(conn):
    """Exact Python replica of BATCH_REPORT from batch_report.pc."""
    cur = conn.cursor()

    # SQL preserved from batch_report.pc:102-105
    cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT user_id), "
        "       COALESCE(SUM(word_count), 0) "
        "FROM posts"
    )
    total_posts, total_users, total_words = cur.fetchone()

    avg_words_per_post = 0.0
    avg_posts_per_user = 0.0
    if total_posts > 0:
        # SQL preserved from batch_report.pc:108-110
        cur.execute(
            "SELECT CAST(SUM(word_count) AS REAL) / CAST(COUNT(*) AS REAL) "
            "FROM posts"
        )
        avg_words_per_post = cur.fetchone()[0]

        # SQL preserved from batch_report.pc:112-114
        cur.execute(
            "SELECT CAST(COUNT(*) AS REAL) / CAST(COUNT(DISTINCT user_id) AS REAL) "
            "FROM posts"
        )
        avg_posts_per_user = cur.fetchone()[0]

    # SQL preserved from batch_report.pc:122-126
    cur.execute(
        "SELECT user_id, post_count, total_words "
        "FROM post_stats "
        "ORDER BY post_count DESC "
        "LIMIT 1"
    )
    top = cur.fetchone()
    if top:
        top_user_id, top_user_posts, top_user_words = top[0], top[1], top[2]
    else:
        top_user_id, top_user_posts, top_user_words = 0, 0, 0

    # SQL preserved from batch_report.pc:181-182
    cur.execute(
        "INSERT INTO batch_log (service_name, status, rows_processed) "
        "VALUES ('BATCH_REPORT', 'SUCCESS', ?)",
        (total_posts,),
    )
    conn.commit()

    return {
        "total_posts": total_posts,
        "total_users": total_users,
        "total_words": total_words,
        "avg_words_per_post": avg_words_per_post,
        "avg_posts_per_user": avg_posts_per_user,
        "top_user_id": top_user_id,
        "top_user_posts": top_user_posts,
        "top_user_words": top_user_words,
    }


# ── Full Pipeline ─────────────────────────────────────────────────────────────

def run_full_pipeline(conn, input_data):
    """Run all 4 phases in sequence, exactly like batch_orchestrator.c."""
    print("╔══════════════════════════════════════════════════╗")
    print("║     PYTHON BATCH PIPELINE (SQLite test)         ║")
    print("╚══════════════════════════════════════════════════╝\n")

    # Phase 1
    print("─── Phase 1: BATCH_INGEST ───")
    r1 = phase_ingest(conn, input_data)
    print(f"  Result: OK|ingested={r1['ingested']}|batch_id={r1['batch_id']}")
    batch_id = r1["batch_id"]

    # Phase 2
    print("\n─── Phase 2: BATCH_VALIDATE ───")
    r2 = phase_validate(conn, batch_id)
    print(f"  Result: {r2}")

    # Phase 3
    print("\n─── Phase 3: BATCH_TRANSFORM ───")
    r3 = phase_transform(conn, batch_id)
    print(f"  Result: {r3}")

    # Phase 4
    print("\n─── Phase 4: BATCH_REPORT ───")
    r4 = phase_report(conn)
    print(f"  Result: {r4}")

    print("\n╔══════════════════════════════════════════════════╗")
    print("║     BATCH PROCESSING COMPLETE                   ║")
    print("╚══════════════════════════════════════════════════╝")

    return {"ingest": r1, "validate": r2, "transform": r3, "report": r4}


# ── Tests ────────────────────────────────────────────────────────────────────

class TestPipelineAgainstCBaseline:
    """Verify every output matches the C binary (make demo)."""

    @classmethod
    def setup_class(cls):
        cls.conn = setup_schema()
        cls.results = run_full_pipeline(cls.conn, DEMO_DATA)

    @classmethod
    def teardown_class(cls):
        cls.conn.close()

    def test_ingest_match(self):
        assert self.results["ingest"]["ingested"] == BASELINE["ingest_total"]

    def test_validate_total(self):
        assert self.results["validate"]["total"] == BASELINE["validate_total"]

    def test_validate_valid(self):
        assert self.results["validate"]["valid"] == BASELINE["validate_valid"]

    def test_validate_invalid(self):
        assert self.results["validate"]["invalid"] == BASELINE["validate_invalid"]

    def test_transform_count(self):
        assert self.results["transform"]["transformed"] == BASELINE["transform_transformed"]

    def test_transform_skipped(self):
        assert self.results["transform"]["skipped"] == BASELINE["transform_skipped"]

    def test_report_posts(self):
        assert self.results["report"]["total_posts"] == BASELINE["report_total_posts"]

    def test_report_users(self):
        assert self.results["report"]["total_users"] == BASELINE["report_total_users"]

    def test_report_words(self):
        assert self.results["report"]["total_words"] == BASELINE["report_total_words"]

    def test_report_top_user(self):
        assert self.results["report"]["top_user_id"] == BASELINE["report_top_user_id"]
        assert self.results["report"]["top_user_posts"] == BASELINE["report_top_user_posts"]
        assert self.results["report"]["top_user_words"] == BASELINE["report_top_user_words"]

    def test_staging_status(self):
        """All 10 rows should be TRANSFORMED."""
        cur = self.conn.cursor()
        cur.execute("SELECT ingest_status, COUNT(*) FROM posts_staging GROUP BY ingest_status")
        rows = dict(cur.fetchall())
        assert rows.get("TRANSFORMED") == 10, f"Expected 10 TRANSFORMED, got {rows}"

    def test_posts_table(self):
        """10 posts in final table."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM posts")
        assert cur.fetchone()[0] == 10

    def test_post_stats(self):
        """5 users in stats."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM post_stats")
        assert cur.fetchone()[0] == 5

    def test_batch_log(self):
        """4 entries: INGEST, VALIDATE, TRANSFORM, REPORT."""
        cur = self.conn.cursor()
        cur.execute("SELECT service_name, status FROM batch_log ORDER BY batch_id")
        rows = cur.fetchall()
        services = {r[0] for r in rows}
        assert "BATCH_INGEST" in services
        assert "BATCH_VALIDATE" in services
        assert "BATCH_TRANSFORM" in services
        assert "BATCH_REPORT" in services
        assert all(r[1] == "SUCCESS" for r in rows)


if __name__ == "__main__":
    # Run standalone to see output
    conn = setup_schema(":memory:")
    results = run_full_pipeline(conn, DEMO_DATA)

    print("\n─── COMPARISON ───")
    print(f"{'Metric':<30} {'C Baseline':>12} {'Python':>12} {'Match':>8}")
    print("-" * 65)
    checks = [
        ("ingest_total", "ingest", "ingested", BASELINE["ingest_total"]),
        ("validate_total", "validate", "total", BASELINE["validate_total"]),
        ("validate_valid", "validate", "valid", BASELINE["validate_valid"]),
        ("validate_invalid", "validate", "invalid", BASELINE["validate_invalid"]),
        ("transform_transformed", "transform", "transformed", BASELINE["transform_transformed"]),
        ("transform_skipped", "transform", "skipped", BASELINE["transform_skipped"]),
        ("report_total_posts", "report", "total_posts", BASELINE["report_total_posts"]),
        ("report_total_users", "report", "total_users", BASELINE["report_total_users"]),
        ("report_total_words", "report", "total_words", BASELINE["report_total_words"]),
        ("report_top_user", "report", "top_user_id", BASELINE["report_top_user_id"]),
    ]
    all_pass = True
    for name, phase, key, expected in checks:
        actual = results[phase][key]
        match = "✓" if actual == expected else "✗"
        if actual != expected:
            all_pass = False
        print(f"{name:<30} {expected:>12} {actual:>12} {match:>8}")

    print(f"\n{'ALL CHECKS PASSED' if all_pass else 'SOME CHECKS FAILED'}")

    # Also verify exact word counts
    conn.close()

    # Print the DB state for manual inspection
    conn2 = setup_schema()
    results2 = run_full_pipeline(conn2, DEMO_DATA)

    cur = conn2.cursor()
    cur.execute("SELECT user_id, post_count, total_words, avg_words FROM post_stats ORDER BY user_id")
    print("\n─── post_stats ───")
    for row in cur.fetchall():
        print(f"  user={row[0]}: posts={row[1]}, words={row[2]}, avg={row[3]:.2f}")

    cur.execute("""
        SELECT id, user_id, word_count, SUBSTR(title, 1, 30)
        FROM posts ORDER BY user_id, id
    """)
    print("\n─── posts (word counts) ───")
    for row in cur.fetchall():
        print(f"  post={row[0]}, user={row[1]}, words={row[2]:>3}, title='{row[3]}...'")

    conn2.close()
