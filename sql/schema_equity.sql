-- Tux Batch Processing: NSE Equity Schema
-- Mirrors screener-ai Turso DB structure + adds ICICI Securities-style
-- user/portfolio tables for realistic batch processing demo

-- =========================================================================
-- Market Data Tables (from screener-ai Turso DB)
-- =========================================================================

CREATE TABLE IF NOT EXISTS eod_prices (
    ticker      TEXT    NOT NULL,
    date        TEXT    NOT NULL,   -- ISO format: '2021-07-02'
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      INTEGER,
    dividends   REAL    DEFAULT 0,
    stock_splits REAL   DEFAULT 0,
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_eod_ticker ON eod_prices(ticker);
CREATE INDEX IF NOT EXISTS idx_eod_date ON eod_prices(date);
CREATE INDEX IF NOT EXISTS idx_eod_date_ticker ON eod_prices(date, ticker);

CREATE TABLE IF NOT EXISTS stock_fundamentals (
    ticker              TEXT PRIMARY KEY,
    as_of_date          TEXT NOT NULL,

    -- Identity
    company_name        TEXT,
    sector              TEXT,
    industry            TEXT,
    exchange            TEXT,

    -- Valuation
    current_price       REAL,
    market_cap_crore    REAL,
    pe_ratio            REAL,
    forward_pe          REAL,
    pb_ratio            REAL,
    peg_ratio           REAL,
    price_to_sales      REAL,

    -- Profitability
    roe_pct             REAL,
    roa_pct             REAL,
    profit_margins_pct  REAL,
    operating_margins_pct REAL,
    gross_margins_pct   REAL,
    ebitda_margins_pct  REAL,

    -- Per-share
    eps_ttm             REAL,
    eps_forward         REAL,
    book_value_per_share REAL,
    revenue_per_share   REAL,

    -- Growth
    revenue_growth_pct  REAL,
    earnings_growth_pct REAL,
    earnings_quarterly_growth_pct REAL,

    -- Financial health
    debt_to_equity      REAL,
    current_ratio       REAL,
    quick_ratio         REAL,
    payout_ratio        REAL,

    -- Returns & yield
    dividend_yield_pct  REAL,
    five_year_avg_dividend_yield_pct REAL,

    -- Price history
    high_52w            REAL,
    low_52w             REAL,
    beta                REAL,

    -- Targets & ratings
    target_mean_price   REAL,
    target_high_price   REAL,
    target_low_price    REAL,
    recommendation      TEXT,
    number_of_analysts  INTEGER,

    -- Ownership
    held_pct_insiders   REAL,
    held_pct_institutions REAL,

    -- Cash flows
    free_cashflow       REAL,
    operating_cashflow  REAL,
    total_cash_per_share REAL,
    total_debt          REAL,
    total_revenue       REAL,
    ebitda              REAL
);

CREATE INDEX IF NOT EXISTS idx_fund_sector ON stock_fundamentals(sector);
CREATE INDEX IF NOT EXISTS idx_fund_pe ON stock_fundamentals(pe_ratio);
CREATE INDEX IF NOT EXISTS idx_fund_roe ON stock_fundamentals(roe_pct);
CREATE INDEX IF NOT EXISTS idx_fund_mcap ON stock_fundamentals(market_cap_crore);

-- =========================================================================
-- ICICI Securities-style User & Portfolio Tables
-- =========================================================================

CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY,
    client_code     TEXT    NOT NULL UNIQUE,  -- e.g. "ICI001234"
    full_name       TEXT    NOT NULL,
    segment         TEXT    DEFAULT 'EQUITY',  -- EQUITY, FNO, COMMODITY
    risk_profile    TEXT    DEFAULT 'MODERATE', -- CONSERVATIVE, MODERATE, AGGRESSIVE
    account_status  TEXT    DEFAULT 'ACTIVE',  -- ACTIVE, DORMANT, CLOSED
    branch_code     TEXT,
    rm_id           INTEGER,
    kyc_status      TEXT    DEFAULT 'VERIFIED',
    onboard_date    TEXT    DEFAULT (datetime('now')),
    annual_income   REAL,
    net_worth       REAL
);

CREATE TABLE IF NOT EXISTS user_portfolios (
    portfolio_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    ticker          TEXT    NOT NULL,
    quantity        INTEGER NOT NULL,
    avg_buy_price   REAL    NOT NULL,
    invested_amount REAL    NOT NULL,
    holding_since   TEXT,
    portfolio_type  TEXT    DEFAULT 'DELIVERY', -- DELIVERY, INTRADAY, MARGIN
    pledge_status   TEXT    DEFAULT 'UNPLEDGED',
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE (user_id, ticker, portfolio_type)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_user ON user_portfolios(user_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_ticker ON user_portfolios(ticker);

CREATE TABLE IF NOT EXISTS user_transactions (
    txn_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    ticker          TEXT    NOT NULL,
    txn_type        TEXT    NOT NULL CHECK (txn_type IN ('BUY', 'SELL')),
    quantity        INTEGER NOT NULL,
    price           REAL    NOT NULL,
    brokerage       REAL    DEFAULT 0,
    txn_date        TEXT    DEFAULT (datetime('now')),
    settlement_id   TEXT,
    order_id        TEXT,
    exchange        TEXT    DEFAULT 'NSE',
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_txn_user ON user_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_txn_date ON user_transactions(txn_date);

-- =========================================================================
-- Staging table for batch ingestion of equity data
-- =========================================================================

CREATE TABLE IF NOT EXISTS equity_staging (
    row_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT    NOT NULL,
    batch_id        INTEGER NOT NULL,
    date            TEXT,
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL,
    volume          INTEGER,
    ingest_status   TEXT    DEFAULT 'NEW'
        CHECK (ingest_status IN ('NEW', 'VALIDATED', 'TRANSFORMED', 'ERROR')),
    validation_msg  TEXT
);

CREATE INDEX IF NOT EXISTS idx_equity_staging_batch ON equity_staging(batch_id);
CREATE INDEX IF NOT EXISTS idx_equity_staging_status ON equity_staging(ingest_status);

-- =========================================================================
-- Derived/analytics tables (populated by batch processing)
-- =========================================================================

CREATE TABLE IF NOT EXISTS equity_derived_metrics (
    ticker          TEXT    NOT NULL,
    date            TEXT    NOT NULL,
    sma_50          REAL,
    sma_200         REAL,
    daily_return    REAL,
    volatility_30d  REAL,
    volume_ratio    REAL,   -- vs 20-day avg
    rsi_14          REAL,
    price_vs_52w_high REAL, -- proximity to 52W high (percent)
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS sector_analytics (
    sector          TEXT    NOT NULL,
    as_of_date      TEXT    NOT NULL,
    total_mcap      REAL,
    avg_pe          REAL,
    avg_roe         REAL,
    avg_debt_equity REAL,
    stock_count     INTEGER,
    avg_daily_return REAL,
    sector_momentum REAL,
    PRIMARY KEY (sector, as_of_date)
);

-- =========================================================================
-- Batch processing log (like Tuxedo tmqueue)
-- =========================================================================

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

CREATE INDEX IF NOT EXISTS idx_batch_log_service ON batch_log(service_name);

-- =========================================================================
-- Risk Assessment Results (populated by BATCH_COMPREHENSIVE_RISK)
-- =========================================================================

CREATE TABLE IF NOT EXISTS risk_assessment_results (
    request_id          TEXT    NOT NULL,
    client_code         TEXT    NOT NULL,
    risk_date           TEXT    NOT NULL,
    var_95              REAL,
    var_99              REAL,
    max_drawdown        REAL,
    sharpe_ratio        REAL,
    beta_weighted       REAL,
    stress_loss_pct     REAL,
    stress_loss_pct_2   REAL,
    stress_loss_pct_3   REAL,
    margin_deficit      REAL,
    concentration_risk  REAL,
    liquidity_score     REAL,
    risk_grade          TEXT,
    action_required     TEXT,
    total_exposure      REAL,
    hedge_effectiveness REAL,
    sector_exposure_json TEXT,
    computed_at         TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (request_id, client_code, risk_date)
);

CREATE INDEX IF NOT EXISTS idx_risk_client ON risk_assessment_results(client_code);
CREATE INDEX IF NOT EXISTS idx_risk_date ON risk_assessment_results(risk_date);
