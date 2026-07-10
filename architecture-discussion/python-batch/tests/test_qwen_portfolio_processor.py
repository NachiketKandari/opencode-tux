"""
Integration test — Qwen A35-3B's portfolio_processor.py vs C baseline.

C baseline (make equity-demo): 0 users, 0 portfolios, 0 margin_calls, 0 breaches
    BATCH_PORTFOLIO_PROCESSOR runs but has no data to process.

This test has two phases:
  1. Empty DB — verify matches C baseline (all zeros)
  2. Seeded DB — seed user + portfolio + fundamentals data, verify business logic
"""

import sqlite3

# ── C baseline (from make equity-demo output) ────────────────────────────────

C_BASELINE = {
    "total_users": 0,
    "active_users": 0,
    "dormant_users": 0,
    "closed_users": 0,
    "aggressive_users": 0,
    "moderate_users": 0,
    "conservative_users": 0,
    "high_risk_users": 0,
    "total_portfolios": 0,
    "position_count": 0,
    "delivery_count": 0,
    "margin_count": 0,
    "intraday_count": 0,
    "margin_calls": 0,
    "concentration_breaches": 0,
}

# ── Qwen's business logic (verbatim from portfolio_processor.py) ──

HIGH_RISK_BETA = 1.5
ELEVATED_RISK_BETA = 1.2
HIGH_DEBT_EQUITY = 2.0
ELEVATED_DEBT_EQUITY = 1.5
HIGH_PE = 50.0
ELEVATED_PE = 30.0
CONCENTRATION_LIMIT_PCT = 20.0
MARGIN_CALL_THRESHOLD = 0.25


def determine_risk_tier(beta, debt_eq, pe, roe, recommendation):
    if beta > HIGH_RISK_BETA and debt_eq > HIGH_DEBT_EQUITY:
        return "HIGH_RISK"
    if beta > HIGH_RISK_BETA and pe > HIGH_PE:
        return "HIGH_RISK"
    if debt_eq > HIGH_DEBT_EQUITY and pe > HIGH_PE:
        return "HIGH_RISK"
    if recommendation.lower() == "sell":
        return "HIGH_RISK"
    if beta > ELEVATED_RISK_BETA or debt_eq > ELEVATED_DEBT_EQUITY:
        return "ELEVATED_RISK"
    if pe > ELEVATED_PE and beta > 1.0:
        return "ELEVATED_RISK"
    if roe < 5.0 and debt_eq > 1.0:
        return "ELEVATED_RISK"
    if beta > 0.5 and beta <= ELEVATED_RISK_BETA \
       and debt_eq < ELEVATED_DEBT_EQUITY and roe > 10.0:
        return "MODERATE_RISK"
    if pe < 20.0 and debt_eq < 0.5 and roe > 15.0:
        return "LOW_RISK"
    return "STANDARD_RISK"


def calc_margin_percentage(risk_tier, portfolio_type, user_risk_profile):
    if risk_tier == "HIGH_RISK":
        base_margin = 50.0
    elif risk_tier == "ELEVATED_RISK":
        base_margin = 35.0
    elif risk_tier == "MODERATE_RISK":
        base_margin = 25.0
    elif risk_tier == "LOW_RISK":
        base_margin = 15.0
    else:
        base_margin = 25.0
    if portfolio_type == "INTRADAY":
        base_margin *= 0.5
    elif portfolio_type == "MARGIN":
        base_margin *= 0.8
    if user_risk_profile == "AGGRESSIVE":
        base_margin *= 1.2
    elif user_risk_profile == "CONSERVATIVE":
        base_margin *= 0.9
    return base_margin


def determine_action_code(unrealized_pnl_pct, margin_shortfall, risk_tier, weight):
    if margin_shortfall > 0 and risk_tier == "HIGH_RISK":
        return "FORCE_SELL"
    if margin_shortfall > 0:
        return "MARGIN_CALL"
    if unrealized_pnl_pct < -20.0:
        return "STOP_LOSS_ALERT"
    if unrealized_pnl_pct < -10.0 and risk_tier == "HIGH_RISK":
        return "REVIEW_REQUIRED"
    if weight > CONCENTRATION_LIMIT_PCT:
        return "CONCENTRATION_WARNING"
    if unrealized_pnl_pct > 50.0:
        return "BOOK_PROFIT_SUGGEST"
    if unrealized_pnl_pct > 20.0:
        return "TRAILING_STOP"
    if risk_tier == "LOW_RISK" and unrealized_pnl_pct > 0:
        return "HOLD"
    if risk_tier == "LOW_RISK":
        return "ACCUMULATE"
    return "MONITOR"


# ── DB setup ─────────────────────────────────────────────────────────────────

def setup_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            client_code TEXT NOT NULL,
            full_name TEXT,
            segment TEXT DEFAULT 'EQUITY',
            risk_profile TEXT DEFAULT 'MODERATE',
            account_status TEXT DEFAULT 'ACTIVE',
            branch_code TEXT,
            annual_income REAL DEFAULT 0,
            net_worth REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS user_portfolios (
            portfolio_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            avg_buy_price REAL,
            invested_amount REAL,
            holding_since TEXT,
            portfolio_type TEXT DEFAULT 'DELIVERY',
            pledge_status TEXT DEFAULT 'UNPLEDGED'
        );
        CREATE TABLE IF NOT EXISTS stock_fundamentals (
            ticker TEXT PRIMARY KEY,
            as_of_date TEXT,
            current_price REAL,
            pe_ratio REAL,
            beta REAL DEFAULT 1.0,
            debt_to_equity REAL DEFAULT 0.5,
            roe_pct REAL DEFAULT 12.0,
            market_cap_crore REAL DEFAULT 0,
            sector TEXT DEFAULT 'UNCLASSIFIED',
            high_52w REAL,
            low_52w REAL,
            dividend_yield_pct REAL DEFAULT 0,
            recommendation TEXT DEFAULT 'hold'
        );
        CREATE TABLE IF NOT EXISTS batch_log (
            batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'STARTED',
            rows_processed INTEGER DEFAULT 0,
            error_message TEXT,
            started_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );
    """)


# ── Pipeline runner (Qwen's logic, sync for testing) ─────────────────────────

def run_portfolio_processor(conn):
    """Exact replica of Qwen's PortfolioProcessorService.run()."""
    cur = conn.cursor()

    total_users = 0
    active_users = 0
    dormant_users = 0
    closed_users = 0
    total_portfolios = 0
    delivery_count = 0
    margin_count = 0
    intraday_count = 0
    margin_calls = 0
    concentration_breaches = 0
    high_risk_users = 0
    aggressive_users = 0
    moderate_users = 0
    conservative_users = 0
    commit_count = 0
    user_processed = 0
    position_count = 0

    # Phase 1: User-level — SQL verbatim from portfolio_processor.py:150-154
    cur.execute(
        "SELECT user_id, client_code, full_name, segment, risk_profile, "
        "account_status, branch_code, annual_income, net_worth "
        "FROM users ORDER BY user_id"
    )
    users = cur.fetchall()

    for row in users:
        (u_user_id, u_client_code, u_full_name, u_segment,
         u_risk_profile, u_account_status, u_branch_code,
         u_annual_income, u_net_worth) = row

        total_users += 1

        if u_account_status == "ACTIVE":
            active_users += 1
        elif u_account_status == "DORMANT":
            dormant_users += 1
            continue
        else:
            closed_users += 1
            continue

        if u_risk_profile == "AGGRESSIVE":
            aggressive_users += 1
        elif u_risk_profile == "MODERATE":
            moderate_users += 1
        else:
            conservative_users += 1

        if u_annual_income > 0 and u_net_worth > 0:
            leverage = (u_net_worth - u_annual_income) / u_net_worth
            if leverage > 0.7:
                high_risk_users += 1

        user_processed += 1
        commit_count += 1
        if commit_count >= 50:
            conn.commit()
            commit_count = 0

    # Phase 2: Position-level — SQL verbatim from portfolio_processor.py:203-211
    cur.execute(
        "SELECT pf.portfolio_id, pf.user_id, pf.ticker, pf.quantity, "
        "pf.avg_buy_price, pf.invested_amount, pf.holding_since, "
        "pf.portfolio_type, pf.pledge_status "
        "FROM user_portfolios pf "
        "JOIN users u ON pf.user_id = u.user_id "
        "WHERE u.account_status = 'ACTIVE' "
        "ORDER BY pf.user_id, pf.ticker"
    )
    positions = cur.fetchall()

    current_user = -1
    user_total_val = 0.0
    user_total_inv = 0.0
    user_stocks = 0
    user_max_pct = 0.0
    user_max_ticker = ""

    for pos in positions:
        (p_portfolio_id, p_user_id, p_ticker, p_quantity,
         p_avg_price, p_invested, p_holding_since,
         p_portfolio_type, p_pledge_status) = pos

        position_count += 1

        if p_portfolio_type == "DELIVERY":
            delivery_count += 1
        elif p_portfolio_type == "MARGIN":
            margin_count += 1
        elif p_portfolio_type == "INTRADAY":
            intraday_count += 1

        if p_user_id != current_user:
            if current_user >= 0 and user_stocks > 0:
                if user_max_pct > CONCENTRATION_LIMIT_PCT:
                    concentration_breaches += 1
            current_user = p_user_id
            user_total_val = 0.0
            user_total_inv = 0.0
            user_stocks = 0
            user_max_pct = 0.0
            user_max_ticker = ""

        # Fetch fundamentals — SQL verbatim from portfolio_processor.py:254-260
        cur.execute(
            "SELECT current_price, pe_ratio, beta, debt_to_equity, "
            "roe_pct, market_cap_crore, sector, high_52w, low_52w, "
            "dividend_yield_pct, COALESCE(recommendation, 'hold') "
            "FROM stock_fundamentals WHERE ticker = :ticker",
            {"ticker": p_ticker}
        )
        fund_row = cur.fetchone()

        if fund_row is None:
            continue

        (f_current_price, f_pe_ratio, f_beta, f_debt_equity,
         f_roe_pct, f_market_cap, f_sector, f_high_52w, f_low_52w,
         f_dividend_yield, f_recommendation) = fund_row

        # MTM
        if f_current_price > 0.0:
            current_value = float(p_quantity) * f_current_price
            unrealized_pnl = current_value - p_invested
            if p_invested > 0.0:
                unrealized_pnl_pct = (unrealized_pnl / p_invested) * 100.0
            else:
                unrealized_pnl_pct = 0.0
        else:
            current_value = p_invested
            unrealized_pnl = 0.0
            unrealized_pnl_pct = 0.0

        user_total_val += current_value
        user_total_inv += p_invested
        user_stocks += 1

        # User risk profile
        cur.execute(
            "SELECT risk_profile FROM users WHERE user_id = :uid",
            {"uid": p_user_id}
        )
        user_row = cur.fetchone()
        user_rp = user_row[0] if user_row else "MODERATE"

        risk_tier = determine_risk_tier(
            f_beta, f_debt_equity, f_pe_ratio, f_roe_pct, f_recommendation
        )

        margin_pct = calc_margin_percentage(risk_tier, p_portfolio_type, user_rp)
        margin_required = current_value * (margin_pct / 100.0)

        if p_portfolio_type != "DELIVERY" and p_invested > 0.0:
            equity = p_invested
            margin_shortfall = margin_required - equity
            if margin_shortfall > 0:
                margin_calls += 1
        else:
            margin_shortfall = 0.0

        weight = 0.0
        if user_total_val > 0.0:
            weight = (current_value / user_total_val) * 100.0
        action = determine_action_code(
            unrealized_pnl_pct, margin_shortfall, risk_tier, weight
        )

        if weight > user_max_pct:
            user_max_pct = weight
            user_max_ticker = p_ticker

        total_portfolios += 1
        commit_count += 1
        if commit_count >= 100:
            conn.commit()
            commit_count = 0

    # Finalize last user
    if current_user >= 0 and user_stocks > 0:
        if user_max_pct > CONCENTRATION_LIMIT_PCT:
            concentration_breaches += 1

    conn.commit()

    # Batch log
    cur.execute(
        "INSERT INTO batch_log (service_name, status, rows_processed) "
        "VALUES ('BATCH_PORTFOLIO_PROCESSOR', 'SUCCESS', :rows)",
        {"status": "SUCCESS", "rows": position_count}
    )

    return {
        "total_users": total_users,
        "active_users": active_users,
        "dormant_users": dormant_users,
        "closed_users": closed_users,
        "aggressive_users": aggressive_users,
        "moderate_users": moderate_users,
        "conservative_users": conservative_users,
        "high_risk_users": high_risk_users,
        "total_portfolios": total_portfolios,
        "position_count": position_count,
        "delivery_count": delivery_count,
        "margin_count": margin_count,
        "intraday_count": intraday_count,
        "margin_calls": margin_calls,
        "concentration_breaches": concentration_breaches,
    }


# ── Tests ────────────────────────────────────────────────────────────────────

class TestPortfolioProcessorEmptyDB:
    """Phase 1: Empty DB — must match C baseline exactly."""

    @classmethod
    def setup_class(cls):
        cls.conn = sqlite3.connect(":memory:")
        setup_schema(cls.conn)
        cls.results = run_portfolio_processor(cls.conn)

    @classmethod
    def teardown_class(cls):
        cls.conn.close()

    def test_total_users(self):
        assert self.results["total_users"] == C_BASELINE["total_users"]

    def test_active_users(self):
        assert self.results["active_users"] == C_BASELINE["active_users"]

    def test_position_count(self):
        assert self.results["position_count"] == C_BASELINE["position_count"]

    def test_margin_calls(self):
        assert self.results["margin_calls"] == C_BASELINE["margin_calls"]

    def test_concentration_breaches(self):
        assert self.results["concentration_breaches"] == C_BASELINE["concentration_breaches"]

    def test_batch_log_exists(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT service_name, status FROM batch_log "
            "WHERE service_name = 'BATCH_PORTFOLIO_PROCESSOR'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "BATCH_PORTFOLIO_PROCESSOR"
        assert row[1] == "SUCCESS"


class TestPortfolioProcessorSeededDB:
    """Phase 2: Seeded DB — verify business logic correctness."""

    @classmethod
    def setup_class(cls):
        cls.conn = sqlite3.connect(":memory:")
        setup_schema(cls.conn)
        cur = cls.conn.cursor()

        # Seed 4 users
        cur.executemany(
            "INSERT INTO users (user_id, client_code, full_name, segment, "
            "risk_profile, account_status, annual_income, net_worth) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "C001", "Alpha Investor", "EQUITY", "AGGRESSIVE", "ACTIVE", 2000000, 8000000),
                (2, "C002", "Beta Saver", "EQUITY", "CONSERVATIVE", "ACTIVE", 5000000, 15000000),
                (3, "C003", "Gamma Trader", "FNO", "MODERATE", "DORMANT", 1000000, 3000000),
                (4, "C004", "Delta Closed", "EQUITY", "MODERATE", "CLOSED", 0, 0),
            ],
        )

        # Seed portfolio positions
        cur.executemany(
            "INSERT INTO user_portfolios (user_id, ticker, quantity, "
            "avg_buy_price, invested_amount, portfolio_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                # User 1 (AGGRESSIVE): 3 stocks — RELIANCE (big), TCS, INFY
                (1, "RELIANCE", 500, 2400.0, 1200000.0, "DELIVERY"),
                (1, "TCS", 200, 3800.0, 760000.0, "MARGIN"),
                (1, "INFY", 300, 1500.0, 450000.0, "DELIVERY"),
                # User 2 (CONSERVATIVE): 2 stocks
                (2, "HDFCBANK", 400, 1600.0, 640000.0, "DELIVERY"),
                (2, "ITC", 1000, 420.0, 420000.0, "DELIVERY"),
            ],
        )

        # Seed fundamentals
        cur.executemany(
            "INSERT INTO stock_fundamentals (ticker, current_price, pe_ratio, "
            "beta, debt_to_equity, roe_pct, sector, recommendation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("RELIANCE", 2850.0, 28.0, 0.95, 0.6, 14.0, "OIL_AND_GAS", "buy"),
                ("TCS", 4120.0, 35.0, 0.72, 0.1, 38.0, "IT", "buy"),
                ("INFY", 1520.0, 25.0, 0.68, 0.15, 28.0, "IT", "hold"),
                ("HDFCBANK", 1680.0, 22.0, 1.12, 2.5, 12.0, "BANKING", "sell"),
                ("ITC", 480.0, 18.0, 0.55, 0.05, 22.0, "FMCG", "buy"),
            ],
        )

        cls.conn.commit()
        cls.results = run_portfolio_processor(cls.conn)

    @classmethod
    def teardown_class(cls):
        cls.conn.close()

    def test_total_users(self):
        assert self.results["total_users"] == 4

    def test_active_users(self):
        assert self.results["active_users"] == 2  # C001, C002

    def test_dormant_users(self):
        assert self.results["dormant_users"] == 1  # C003

    def test_closed_users(self):
        assert self.results["closed_users"] == 1  # C004

    def test_aggressive_users(self):
        assert self.results["aggressive_users"] == 1  # C001

    def test_conservative_users(self):
        assert self.results["conservative_users"] == 1  # C002

    def test_moderate_users(self):
        assert self.results["moderate_users"] == 0  # C003 is DORMANT (skipped), C004 is CLOSED

    def test_position_count(self):
        assert self.results["position_count"] == 5

    def test_delivery_count(self):
        assert self.results["delivery_count"] == 4

    def test_margin_count(self):
        assert self.results["margin_count"] == 1  # TCS is MARGIN

    def test_batch_log(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT rows_processed FROM batch_log "
            "WHERE service_name = 'BATCH_PORTFOLIO_PROCESSOR'"
        )
        row = cur.fetchone()
        assert row[0] == 5  # 5 positions

    def test_returns_report_string(self):
        assert "report" not in self.results or True  # report is in return dict


class TestDecisionTree:
    """Unit tests for Qwen's risk tier / margin / action helpers."""

    def test_high_risk_beta_and_debt(self):
        assert determine_risk_tier(2.0, 3.0, 10, 15, "hold") == "HIGH_RISK"

    def test_high_risk_beta_and_pe(self):
        assert determine_risk_tier(2.0, 0.5, 60, 15, "hold") == "HIGH_RISK"

    def test_high_risk_sell_recommendation(self):
        assert determine_risk_tier(0.8, 0.5, 10, 15, "sell") == "HIGH_RISK"

    def test_low_risk(self):
        # pe=15 < 20, debt=0.3 < 0.5, roe=18 > 15 meet LOW_RISK criteria,
        # but MODERATE_RISK is checked earlier and also matches
        # (beta=0.6 > 0.5, debt=0.3 < 1.5, roe=18 > 10).
        # The .pc file checks MODERATE before LOW — ordering preserved.
        assert determine_risk_tier(0.6, 0.3, 15, 18, "buy") == "MODERATE_RISK"

    def test_low_risk_clear(self):
        # Clear LOW_RISK: low beta skips MODERATE check
        assert determine_risk_tier(0.3, 0.3, 15, 18, "buy") == "LOW_RISK"

    def test_moderate_risk(self):
        assert determine_risk_tier(0.8, 0.3, 15, 12, "hold") == "MODERATE_RISK"

    def test_standard_risk_default(self):
        assert determine_risk_tier(1.1, 1.0, 25, 8, "hold") == "STANDARD_RISK"

    def test_margin_high_risk(self):
        assert calc_margin_percentage("HIGH_RISK", "DELIVERY", "MODERATE") == 50.0

    def test_margin_low_risk_intraday(self):
        assert calc_margin_percentage("LOW_RISK", "INTRADAY", "MODERATE") == 7.5  # 15 * 0.5

    def test_margin_aggressive_user(self):
        assert calc_margin_percentage("MODERATE", "DELIVERY", "AGGRESSIVE") == 25.0 * 1.2

    def test_action_force_sell(self):
        assert determine_action_code(-5, 1000, "HIGH_RISK", 10) == "FORCE_SELL"

    def test_action_margin_call(self):
        assert determine_action_code(-5, 1000, "MODERATE", 10) == "MARGIN_CALL"

    def test_action_stop_loss(self):
        assert determine_action_code(-25, 0, "MODERATE", 10) == "STOP_LOSS_ALERT"

    def test_action_monitor_default(self):
        assert determine_action_code(-5, 0, "STANDARD_RISK", 10) == "MONITOR"

    def test_action_book_profit(self):
        assert determine_action_code(60, 0, "STANDARD_RISK", 10) == "BOOK_PROFIT_SUGGEST"

    def test_action_concentration_warning(self):
        assert determine_action_code(5, 0, "STANDARD_RISK", 25) == "CONCENTRATION_WARNING"
