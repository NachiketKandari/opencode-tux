#!/bin/bash
# run_batch.sh - Full batch processing pipeline
#
# Simulates a Tuxedo batch window:
#   1. Fetch data from external API (JSONPlaceholder)
#   2. Preprocess .pc files (Pro*C → C + SQLite)
#   3. Compile and link
#   4. Initialize database
#   5. Run batch pipeline (INGEST → VALIDATE → TRANSFORM → REPORT)
#
# Usage:
#   ./scripts/run_batch.sh          # Full pipeline
#   ./scripts/run_batch.sh --demo   # With demo data (no API call)
#   ./scripts/run_batch.sh --clean  # Clean start

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "╔══════════════════════════════════════════════════╗"
echo "║     TUXEDO BATCH PROCESSING PIPELINE            ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Clean Start ─────────────────────────────────────────────────────

if [ "$1" = "--clean" ]; then
    echo "=== Cleaning previous build and data ==="
    make cleanall
    echo ""
fi

# ── Step 1: Fetch Data ──────────────────────────────────────────────

if [ "$1" = "--demo" ]; then
    echo "=== Using demo data (10 records) ==="
    mkdir -p data
    cat > data/input.dat << 'DEMODATA'
1|1|sunt aut facere repellat provident|quia et suscipit suscipit recusandae consequuntur expedita et cum reprehenderit molestiae ut ut quas totam nostrum rerum est autem sunt rem eveniet architecto
1|2|qui est esse|est rerum tempore vitae sequi sint nihil reprehenderit dolor beatae ea dolores neque fugiat blanditiis voluptate porro vel nihil molestiae ut reiciendis qui aperiam non debitis
2|3|ea molestias quasi exercitationem|et iusto sed quo iure voluptatem occaecati omnis eligendi aut ad voluptatem doloribus vel accusantium quis pariatur molestiae porro eius odio et labore et velit aut
2|4|eum et est occaecati|ullam et saepe reiciendis voluptatem adipisci sit amet autem assumenda provident rerum culpa quis hic commodi nesciunt rem tenetur doloremque ipsam iure quis sunt voluptatem rerum
3|5|nesciunt quas odio|repudiandae veniam quaerat sunt sed alias aut fugiat sit autem sed est voluptatem omnis possimus esse voluptatibus quis est aut tenetur dolor neque
3|6|dolorem eum magni eos aperiam quia|qui ratione voluptatem sequi nesciunt neque porro quisquam est qui dolorem ipsum quia dolor sit amet consectetur adipisci velit sed quia non numquam eius modi
4|7|magnam facilis autem|dolore placeat quibusdam ea quo voluptas nulla veniam nisi odit ut quas qui voluptatem officiis
4|8|dolorem dolore est ipsam|ut aspernatur corporis harum nihil quis provident sequi mollitia nobis aliquid molestiae perspiciatis et ea nemo ab reprehenderit accusantium quas voluptate dolores
5|9|nesciunt iure omnis dolorem tempora|nam qui vel suscipit distinctio nihil minus explibo ipsum consequatur non
5|10|optio molestias id quia eos|voluptatem animi nihil autem numquam et voluptatem nulla et autem sint dolorum sit ducimus autem reprehenderit
DEMODATA
    echo "  Created data/input.dat with 10 demo records"
else
    echo "=== Step 1: Fetching data from JSONPlaceholder API ==="
    python3 scripts/fetch_data.py -o data/input.dat --count 50
fi
echo ""

# ── Step 2: Build ───────────────────────────────────────────────────

echo "=== Step 2: Building batch application ==="
make all
echo ""

# ── Step 3: Run Batch Pipeline ──────────────────────────────────────

echo "=== Step 3: Running batch pipeline ==="
echo ""
bin/batch_app data/input.dat
EXIT_CODE=$?
echo ""

# ── Step 4: Show Database Summary ───────────────────────────────────

if [ -f data/batch.db ]; then
    echo "=== Database Summary ==="
    echo ""
    echo "Posts (final table):"
    sqlite3 data/batch.db "SELECT COUNT(*) as count FROM posts;"
    echo ""
    echo "Post Stats (aggregates):"
    sqlite3 data/batch.db -header -column \
        "SELECT user_id, post_count, total_words, ROUND(avg_words,1) as avg_words FROM post_stats ORDER BY post_count DESC LIMIT 5;"
    echo ""
    echo "Batch Log:"
    sqlite3 data/batch.db -header -column \
        "SELECT service_name, status, rows_processed, started_at FROM batch_log ORDER BY batch_id;"
    echo ""
fi

if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ Batch pipeline completed successfully"
else
    echo "✗ Batch pipeline failed with exit code $EXIT_CODE"
fi

exit $EXIT_CODE
