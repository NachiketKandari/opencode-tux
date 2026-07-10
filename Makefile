# Tuxedo Batch Processing POC — Makefile
#
# Two pipelines:
#   make posts  → Original JSONPlaceholder posts pipeline (for reference)
#   make equity → New ICICI Securities NSE equity pipeline (primary)
#
# Build pipeline: .pc → preprocessor → C → gcc → bin/

CC       = gcc
SQL_CF   = $(shell PKG_CONFIG_PATH=/opt/homebrew/lib/pkgconfig:/usr/local/lib/pkgconfig \
                    pkg-config --cflags sqlite3 2>/dev/null || echo "-I/opt/homebrew/include")
SQL_LD   = $(shell PKG_CONFIG_PATH=/opt/homebrew/lib/pkgconfig:/usr/local/lib/pkgconfig \
                    pkg-config --libs sqlite3 2>/dev/null || echo "-L/opt/homebrew/lib -lsqlite3")
CFLAGS   = -Wall -Wextra -g -O2 -Iinclude -Isrc -Ibuild $(SQL_CF)

BUILD_DIR = build
BIN_DIR   = bin

# ─── Posts Pipeline (original) ──────────────────────────────────────────

POSTS_PC_SRC = pc/batch_ingest.pc pc/batch_validate.pc pc/batch_transform.pc pc/batch_report.pc
POSTS_PC_C   = $(patsubst pc/%.pc,$(BUILD_DIR)/%.c,$(POSTS_PC_SRC))
POSTS_PC_OBJ = $(POSTS_PC_C:.c=.o)
POSTS_CORE   = $(BUILD_DIR)/tuxlib.o $(BUILD_DIR)/sqlca.o $(BUILD_DIR)/batch_orchestrator.o
POSTS_TARGET = $(BIN_DIR)/batch_app

# ─── Equity Pipeline (new — ICICI Securities NSE) ───────────────────────

EQUITY_PC_SRC = pc/batch_equity_ingest.pc \
                pc/batch_equity_validate.pc \
                pc/batch_equity_transform.pc \
                pc/batch_equity_report.pc \
                pc/batch_portfolio_processor.pc \
                pc/batch_market_analytics.pc \
                pc/batch_comprehensive_risk.pc

EQUITY_PC_C   = $(patsubst pc/%.pc,$(BUILD_DIR)/%.c,$(EQUITY_PC_SRC))
EQUITY_PC_OBJ = $(EQUITY_PC_C:.c=.o)
EQUITY_CORE   = $(BUILD_DIR)/tuxlib.o $(BUILD_DIR)/sqlca.o $(BUILD_DIR)/batch_equity_orchestrator.o
EQUITY_TARGET = $(BIN_DIR)/equity_app

.PRECIOUS: $(POSTS_PC_C) $(EQUITY_PC_C)

.PHONY: all clean posts equity demo equity-demo data bridge

all: equity

# ═══════════════════════════════════════════════════════════════════════════
# Pattern Rules (shared)
# ═══════════════════════════════════════════════════════════════════════════

# Step 1: Preprocess .pc → .c
$(BUILD_DIR)/%.c: pc/%.pc scripts/preproc.py
	@mkdir -p $(BUILD_DIR)
	python3 scripts/preproc.py $< -o $(BUILD_DIR)

# Step 2: Compile preprocessed .c → .o
$(BUILD_DIR)/%.o: $(BUILD_DIR)/%.c
	$(CC) $(CFLAGS) -c $< -o $@

# ═══════════════════════════════════════════════════════════════════════════
# Supporting sources
# ═══════════════════════════════════════════════════════════════════════════

$(BUILD_DIR)/tuxlib.o: src/tuxlib.c
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/sqlca.o: src/sqlca.c
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/batch_orchestrator.o: pc/batch_orchestrator.c
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/batch_equity_orchestrator.o: pc/batch_equity_orchestrator.c
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

# ═══════════════════════════════════════════════════════════════════════════
# Posts Pipeline Targets
# ═══════════════════════════════════════════════════════════════════════════

posts: $(POSTS_TARGET)

$(POSTS_TARGET): $(POSTS_PC_OBJ) $(POSTS_CORE)
	@mkdir -p $(BIN_DIR)
	$(CC) $(CFLAGS) -o $@ $^ $(SQL_LD)
	@echo "  → $(POSTS_TARGET) (posts pipeline)"

demo: posts
	@mkdir -p data
	@rm -f data/batch.db
	@echo "Running posts pipeline (demo data)..."
	$(POSTS_TARGET) data/input.dat

# ═══════════════════════════════════════════════════════════════════════════
# Equity Pipeline Targets (ICICI Securities NSE)
# ═══════════════════════════════════════════════════════════════════════════

equity: $(EQUITY_TARGET)

$(EQUITY_TARGET): $(EQUITY_PC_OBJ) $(EQUITY_CORE)
	@mkdir -p $(BIN_DIR)
	$(CC) $(CFLAGS) -o $@ $^ $(SQL_LD) -lm
	@echo "  → $(EQUITY_TARGET) (equity pipeline)"

# Generate equity EOD data
data:
	python3 scripts/gen_eod_data.py --count 200 --output data/eod_input.dat

# Populate local DB from Turso (requires network)
bridge:
	python3 scripts/turso_bridge.py --stocks 100 --users 500

# Full equity pipeline: bridge → data → build → run
equity-full: bridge data equity
	$(init_schema)
	python3 scripts/turso_bridge.py --stocks 100 --users 500 --skip-turso
	@echo "Running full equity pipeline..."
	$(EQUITY_TARGET) --pipeline --input data/eod_input.dat --schema sql/schema_equity.sql

# Helper: initialize equity schema in SQLite
define init_schema
	@mkdir -p data
	@rm -f data/batch.db
	@python3 -c 'import sqlite3; c=sqlite3.connect("data/batch.db"); c.executescript(open("sql/schema_equity.sql").read()); c.commit(); c.close(); print("Schema created")'
endef

# Quick equity demo (data already generated, no Turso)
equity-demo: data equity
	$(init_schema)
	@echo "Running equity pipeline..."
	$(EQUITY_TARGET) --pipeline --input data/eod_input.dat --schema sql/schema_equity.sql

# Run portfolio processor standalone
equity-portfolio: data equity
	$(init_schema)
	$(EQUITY_TARGET) --portfolio --input data/eod_input.dat --schema sql/schema_equity.sql

# Run market analytics standalone
equity-analytics: equity
	$(init_schema)
	$(EQUITY_TARGET) --analytics --input data/eod_input.dat --schema sql/schema_equity.sql

# Run ALL services
equity-all: data equity
	$(init_schema)
	$(EQUITY_TARGET) --all --input data/eod_input.dat --schema sql/schema_equity.sql

# Run comprehensive risk assessment
equity-risk: data equity
	$(init_schema)
	$(EQUITY_TARGET) --risk --input data/eod_input.dat --schema sql/schema_equity.sql

# ═══════════════════════════════════════════════════════════════════════════
# Utility
# ═══════════════════════════════════════════════════════════════════════════

clean:
	rm -rf $(BUILD_DIR) $(BIN_DIR)

cleanall: clean
	rm -f data/batch.db data/input.dat data/eod_input.dat

# Show complexity tiers
tiers:
	@echo "Complexity Tiers (Pro*C → C expansion):"
	@echo ""
	@echo "  SIMPLE  (~300-400 lines C):"
	@wc -l pc/batch_equity_ingest.pc
	@echo ""
	@echo "  MEDIUM  (~800-1200 lines C):"
	@wc -l pc/batch_equity_validate.pc pc/batch_equity_transform.pc pc/batch_equity_report.pc pc/batch_portfolio_processor.pc
	@echo ""
	@echo "  COMPLEX (~2000+ lines C):"
	@wc -l pc/batch_market_analytics.pc
	@echo ""
	@echo "  Total .pc source:"
	@wc -l pc/batch_equity_*.pc

# Capture canonical output snapshots (requires equity build first)
snapshots: equity data
	@mkdir -p snapshots
	python3 scripts/capture_snapshots.py

# Verify conversion output against snapshots
verify: equity data
	python3 scripts/verify_output.py --all
