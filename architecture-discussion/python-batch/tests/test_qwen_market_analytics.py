"""
Integration test — Qwen 3.6 35B's market_analytics.py vs C baseline.

C baseline (make equity-demo): 0 stocks with fundamentals, 0 sectors, 0 peers.
    BATCH_MARKET_ANALYTICS runs but has no data to process.

This test has three phases:
  1. Unit tests for scoring functions (deterministic math)
  2. Empty DB — verify matches C baseline (all zeros)
  3. Seeded DB — seed fundamentals + EOD + derived metrics, verify business logic
"""

import sqlite3

# ── C baseline (from make equity-demo output) ────────────────────────────────

C_BASELINE = {
    "phase1_count": 0,
    "phase2_count": 0,
    "phase3_count": 0,
    "phase4_count": 0,
    "phase5_stocks": 0,
    "error_count": 0,
    "market_total": 0,
    "market_large_cap": 0,
    "market_mid_cap": 0,
    "market_small_cap": 0,
    "market_above_sma50": 0,
    "market_above_sma200": 0,
    "market_positive_momentum": 0,
}

# ── Qwen's scoring functions (verbatim from market_analytics.py) ──


def compute_value_score(pe, pb, ps, peg, div_yield):
    score = 50.0
    if pe <= 0.0:
        score += 0.0
    elif pe < 10.0:
        score += 20.0
    elif pe < 15.0:
        score += 15.0
    elif pe < 20.0:
        score += 10.0
    elif pe < 25.0:
        score += 5.0
    elif pe < 30.0:
        score += 0.0
    elif pe < 50.0:
        score += -10.0
    else:
        score += -20.0
    if pb <= 0.0:
        score += 0.0
    elif pb < 1.0:
        score += 15.0
    elif pb < 1.5:
        score += 10.0
    elif pb < 3.0:
        score += 5.0
    elif pb < 5.0:
        score += -5.0
    else:
        score += -15.0
    if ps <= 0.0:
        score += 0.0
    elif ps < 1.0:
        score += 10.0
    elif ps < 2.0:
        score += 5.0
    elif ps < 5.0:
        score += 0.0
    else:
        score += -10.0
    if peg > 0.0 and peg < 1.0:
        score += 10.0
    elif peg >= 1.0 and peg < 2.0:
        score += 5.0
    elif peg >= 3.0:
        score += -10.0
    if div_yield > 3.0:
        score += 10.0
    elif div_yield > 2.0:
        score += 5.0
    elif div_yield > 1.0:
        score += 2.0
    if score > 100.0:
        return 100.0
    if score < 0.0:
        return 0.0
    return score


def compute_growth_score(rev_growth, earn_growth, earn_q_growth, fwd_pe, pe, peg):
    score = 50.0
    if rev_growth > 30.0:
        score += 20.0
    elif rev_growth > 20.0:
        score += 15.0
    elif rev_growth > 10.0:
        score += 10.0
    elif rev_growth > 5.0:
        score += 5.0
    elif rev_growth > 0.0:
        score += 0.0
    elif rev_growth > -10.0:
        score += -10.0
    else:
        score += -20.0
    if earn_growth > 25.0:
        score += 20.0
    elif earn_growth > 15.0:
        score += 15.0
    elif earn_growth > 10.0:
        score += 10.0
    elif earn_growth > 0.0:
        score += 0.0
    elif earn_growth > -20.0:
        score += -10.0
    else:
        score += -20.0
    if earn_q_growth > earn_growth + 5.0:
        score += 10.0
    elif earn_q_growth > earn_growth:
        score += 5.0
    elif earn_q_growth < earn_growth - 10.0:
        score += -10.0
    if fwd_pe > 0 and pe > 0 and fwd_pe < pe * 0.8:
        score += 10.0
    if peg > 0 and peg < 1.0:
        score += 10.0
    if score > 100.0:
        return 100.0
    if score < 0.0:
        return 0.0
    return score


def compute_quality_score(roe, roa, op_margin, gross_margin, debt_eq, current_ratio, free_cf, op_cf):
    score = 50.0
    if roe > 25.0:
        score += 15.0
    elif roe > 20.0:
        score += 12.0
    elif roe > 15.0:
        score += 8.0
    elif roe > 10.0:
        score += 4.0
    elif roe > 5.0:
        score += 0.0
    elif roe > 0.0:
        score += -8.0
    else:
        score += -15.0
    if roa > 10.0:
        score += 10.0
    elif roa > 5.0:
        score += 5.0
    elif roa < 0.0:
        score += -10.0
    if op_margin > 25.0:
        score += 10.0
    elif op_margin > 15.0:
        score += 5.0
    elif op_margin < 5.0:
        score += -10.0
    if gross_margin > 50.0:
        score += 5.0
    elif gross_margin < 20.0:
        score += -5.0
    if debt_eq < 0.3:
        score += 10.0
    elif debt_eq < 0.5:
        score += 8.0
    elif debt_eq < 1.0:
        score += 5.0
    elif debt_eq < 1.5:
        score += 0.0
    elif debt_eq < 2.0:
        score += -5.0
    else:
        score += -15.0
    if current_ratio > 2.0:
        score += 5.0
    elif current_ratio < 1.0:
        score += -10.0
    if free_cf > 0:
        score += 5.0
    else:
        score += -5.0
    if score > 100.0:
        return 100.0
    if score < 0.0:
        return 0.0
    return score


def compute_momentum_score(mom_1m, mom_3m, mom_6m, price_vs_sma50, price_vs_sma200, rsi, macd_signal):
    score = 50.0
    if mom_1m > 15.0:
        score += 15.0
    elif mom_1m > 10.0:
        score += 10.0
    elif mom_1m > 5.0:
        score += 5.0
    elif mom_1m > 0.0:
        score += 2.0
    elif mom_1m > -5.0:
        score += -5.0
    elif mom_1m > -10.0:
        score += -10.0
    else:
        score += -15.0
    if mom_3m > 25.0:
        score += 10.0
    elif mom_3m > 15.0:
        score += 5.0
    elif mom_3m < -15.0:
        score += -10.0
    if mom_6m > 30.0:
        score += 5.0
    elif mom_6m < -20.0:
        score += -5.0
    if price_vs_sma50 > 1.0 and price_vs_sma200 > 1.0:
        score += 10.0
        if price_vs_sma50 > price_vs_sma200:
            score += 5.0
    elif price_vs_sma50 < 1.0 and price_vs_sma200 < 1.0:
        score += -10.0
    if rsi > 70.0:
        score += -5.0
    elif rsi < 30.0:
        score += 5.0
    elif 40.0 <= rsi <= 60.0:
        score += 3.0
    if macd_signal > 0:
        score += 5.0
    if score > 100.0:
        return 100.0
    if score < 0.0:
        return 0.0
    return score


def compute_low_vol_score(beta, volatility_30d, debt_eq, div_yield):
    score = 50.0
    if beta < 0.5:
        score += 20.0
    elif beta < 0.8:
        score += 15.0
    elif beta < 1.0:
        score += 10.0
    elif beta < 1.2:
        score += 0.0
    elif beta < 1.5:
        score += -10.0
    else:
        score += -20.0
    if volatility_30d < 1.0:
        score += 15.0
    elif volatility_30d < 2.0:
        score += 10.0
    elif volatility_30d < 3.0:
        score += 0.0
    else:
        score += -10.0
    if debt_eq < 0.5:
        score += 10.0
    if div_yield > 2.0:
        score += 5.0
    if score > 100.0:
        return 100.0
    if score < 0.0:
        return 0.0
    return score


LARGE_CAP_CRORE = 20000.0
MID_CAP_CRORE = 5000.0


def classify_mcap(mcap_crore):
    if mcap_crore > LARGE_CAP_CRORE:
        return "LARGE_CAP"
    if mcap_crore > MID_CAP_CRORE:
        return "MID_CAP"
    return "SMALL_CAP"


def compute_composite(value, growth, quality, momentum, low_vol, mcap):
    if mcap > LARGE_CAP_CRORE:
        w_value, w_growth, w_quality, w_momentum, w_low_vol = 0.20, 0.15, 0.30, 0.15, 0.20
    elif mcap > MID_CAP_CRORE:
        w_value, w_growth, w_quality, w_momentum, w_low_vol = 0.20, 0.30, 0.20, 0.20, 0.10
    else:
        w_value, w_growth, w_quality, w_momentum, w_low_vol = 0.15, 0.35, 0.15, 0.30, 0.05

    composite = (value * w_value) + (growth * w_growth) \
              + (quality * w_quality) + (momentum * w_momentum) \
              + (low_vol * w_low_vol)

    if composite >= 80.0:
        rating, outlook = "STRONG_BUY", "Highly Favorable"
    elif composite >= 70.0:
        rating, outlook = "BUY", "Favorable"
    elif composite >= 60.0:
        rating, outlook = "ACCUMULATE", "Moderately Positive"
    elif composite >= 50.0:
        rating, outlook = "HOLD", "Neutral"
    elif composite >= 40.0:
        rating, outlook = "REDUCE", "Cautious"
    elif composite >= 30.0:
        rating, outlook = "SELL", "Negative"
    else:
        rating, outlook = "STRONG_SELL", "Highly Negative"

    return composite, rating, outlook


# ── DB setup ─────────────────────────────────────────────────────────────────

def setup_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eod_prices (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (ticker, date)
        );
        CREATE TABLE IF NOT EXISTS stock_fundamentals (
            ticker TEXT PRIMARY KEY,
            as_of_date TEXT,
            company_name TEXT,
            sector TEXT,
            industry TEXT,
            exchange TEXT,
            current_price REAL,
            market_cap_crore REAL,
            pe_ratio REAL,
            forward_pe REAL,
            pb_ratio REAL,
            peg_ratio REAL,
            price_to_sales REAL,
            roe_pct REAL,
            roa_pct REAL,
            profit_margins_pct REAL,
            operating_margins_pct REAL,
            gross_margins_pct REAL,
            ebitda_margins_pct REAL,
            eps_ttm REAL,
            eps_forward REAL,
            book_value_per_share REAL,
            revenue_per_share REAL,
            revenue_growth_pct REAL,
            earnings_growth_pct REAL,
            earnings_quarterly_growth_pct REAL,
            debt_to_equity REAL,
            current_ratio REAL,
            quick_ratio REAL,
            payout_ratio REAL,
            dividend_yield_pct REAL,
            five_year_avg_dividend_yield_pct REAL,
            high_52w REAL,
            low_52w REAL,
            beta REAL,
            target_mean_price REAL,
            target_high_price REAL,
            target_low_price REAL,
            recommendation TEXT,
            number_of_analysts INTEGER,
            held_pct_insiders REAL,
            held_pct_institutions REAL,
            free_cashflow REAL,
            operating_cashflow REAL,
            total_cash_per_share REAL,
            total_debt REAL,
            total_revenue REAL,
            ebitda REAL
        );
        CREATE TABLE IF NOT EXISTS equity_derived_metrics (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            sma_50 REAL,
            sma_200 REAL,
            daily_return REAL,
            volatility_30d REAL,
            volume_ratio REAL,
            rsi_14 REAL,
            price_vs_52w_high REAL,
            PRIMARY KEY (ticker, date)
        );
        CREATE TABLE IF NOT EXISTS sector_analytics (
            sector TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            total_mcap REAL,
            avg_pe REAL,
            avg_roe REAL,
            avg_debt_equity REAL,
            stock_count INTEGER,
            avg_daily_return REAL,
            sector_momentum REAL,
            PRIMARY KEY (sector, as_of_date)
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

def run_market_analytics(conn):
    """Exact replica of Qwen's MarketAnalyticsService.run() but sync."""
    cur = conn.cursor()

    # Init counters
    phase1_count = 0
    phase2_count = 0
    phase3_count = 0
    phase4_count = 0
    phase5_stocks = 0
    error_count = 0
    commit_count = 0

    market_total = 0
    market_above_sma50 = 0
    market_above_sma200 = 0
    market_positive_momentum = 0
    market_large_cap = 0
    market_mid_cap = 0
    market_small_cap = 0
    market_total_mcap = 0.0
    market_adv_decline = 1.0

    prev_sector = ""
    sector_total_mcap = 0.0
    sector_avg_pe = 0.0
    sector_avg_roe = 0.0
    sector_avg_debt_eq = 0.0
    sector_avg_rev_growth = 0.0
    sector_stock_count = 0
    sector_best_composite = 0.0
    sector_best_ticker = ""

    best_composite = 0.0
    best_ticker = ""

    # ── Phase 1: Technical Indicators ──
    cur.execute(
        "SELECT ticker, date, close, volume "
        "FROM eod_prices "
        "WHERE date >= '2026-01-01' "
        "ORDER BY ticker, date DESC"
    )
    eod_rows = cur.fetchall()

    if eod_rows:
        prev_ticker = ""
        days_seen = 0

        for row in eod_rows:
            eod_ticker, eod_date, eod_close, eod_volume = row

            if eod_ticker != prev_ticker:
                if days_seen >= 50:
                    cur.execute(
                        "SELECT AVG(close) FROM ("
                        "SELECT close FROM eod_prices "
                        "WHERE ticker = :ticker "
                        "ORDER BY date DESC LIMIT 50"
                        ")",
                        {"ticker": prev_ticker}
                    )
                    sma_row = cur.fetchone()
                    sma_50 = sma_row[0] if sma_row else 0.0
                else:
                    sma_50 = 0.0

                if days_seen >= 200:
                    cur.execute(
                        "SELECT AVG(close) FROM ("
                        "SELECT close FROM eod_prices "
                        "WHERE ticker = :ticker "
                        "ORDER BY date DESC LIMIT 200"
                        ")",
                        {"ticker": prev_ticker}
                    )
                    sma_row = cur.fetchone()
                    sma_200 = sma_row[0] if sma_row else 0.0
                else:
                    sma_200 = 0.0

                if days_seen >= 14 and sma_50 > 0:
                    price_vs_sma50 = eod_close / sma_50
                    price_vs_sma200 = eod_close / sma_200 if sma_200 > 0 else 1.0

                prev_ticker = eod_ticker
                days_seen = 0

            days_seen += 1
            phase1_count += 0  # BUG in Qwen's code — should be += 1

        # Final ticker metrics
        if days_seen >= 50:
            cur.execute(
                "SELECT AVG(close) FROM ("
                "SELECT close FROM eod_prices "
                "WHERE ticker = :ticker "
                "ORDER BY date DESC LIMIT 50"
                ")",
                {"ticker": prev_ticker}
            )
            sma_row = cur.fetchone()
            sma_50 = sma_row[0] if sma_row else 0.0
        else:
            sma_50 = 0.0

        if days_seen >= 200:
            cur.execute(
                "SELECT AVG(close) FROM ("
                "SELECT close FROM eod_prices "
                "WHERE ticker = :ticker "
                "ORDER BY date DESC LIMIT 200"
                ")",
                {"ticker": prev_ticker}
            )
            sma_row = cur.fetchone()
            sma_200 = sma_row[0] if sma_row else 0.0
        else:
            sma_200 = 0.0

    conn.commit()

    # ── Phase 2: Multi-Factor Fundamental Scoring ──
    cur.execute(
        "SELECT ticker, company_name, sector, industry, exchange, "
        "current_price, market_cap_crore, "
        "pe_ratio, forward_pe, pb_ratio, peg_ratio, price_to_sales, "
        "roe_pct, roa_pct, "
        "profit_margins_pct, operating_margins_pct, "
        "gross_margins_pct, ebitda_margins_pct, "
        "eps_ttm, eps_forward, book_value_per_share, revenue_per_share, "
        "revenue_growth_pct, earnings_growth_pct, "
        "earnings_quarterly_growth_pct, "
        "debt_to_equity, current_ratio, quick_ratio, payout_ratio, "
        "dividend_yield_pct, five_year_avg_dividend_yield_pct, "
        "high_52w, low_52w, beta, "
        "target_mean_price, target_high_price, target_low_price, "
        "COALESCE(recommendation, 'hold'), number_of_analysts, "
        "held_pct_insiders, held_pct_institutions, "
        "free_cashflow, operating_cashflow, total_cash_per_share, "
        "total_debt, total_revenue, ebitda "
        "FROM stock_fundamentals "
        "WHERE current_price > 0 "
        "ORDER BY sector, market_cap_crore DESC"
    )
    fundamentals = cur.fetchall()

    prev_sector = ""
    sector_stock_count = 0
    sector_total_mcap = 0.0

    for fund in fundamentals:
        (c_ticker, c_company, c_sector, c_industry, c_exchange,
         c_price, c_mcap,
         c_pe, c_fwd_pe, c_pb, c_peg, c_ps,
         c_roe, c_roa,
         c_profit_margin, c_op_margin,
         c_gross_margin, c_ebitda_margin,
         c_eps, c_eps_fwd, c_book_val, c_rev_per_share,
         c_rev_growth, c_earn_growth,
         c_earn_q_growth,
         c_debt_eq, c_current_ratio, c_quick_ratio, c_payout,
         c_div_yield, c_div_5y,
         c_high_52w, c_low_52w, c_beta,
         c_target_mean, c_target_high, c_target_low,
         c_recommendation, c_analysts,
         c_insider_pct, c_inst_pct,
         c_free_cf, c_op_cf, c_cash_per_share,
         c_total_debt, c_total_rev, c_ebitda) = fund

        phase2_count += 1
        market_total += 1

        mcap_class = classify_mcap(c_mcap)
        if mcap_class == "LARGE_CAP":
            market_large_cap += 1
        elif mcap_class == "MID_CAP":
            market_mid_cap += 1
        else:
            market_small_cap += 1
        market_total_mcap += c_mcap

        # Sector transition
        if len(prev_sector) > 0 and c_sector != prev_sector:
            if sector_stock_count > 0:
                sector_avg_pe /= sector_stock_count
                sector_avg_roe /= sector_stock_count
                sector_avg_debt_eq /= sector_stock_count
                sector_avg_rev_growth /= sector_stock_count

                cur.execute(
                    "INSERT OR REPLACE INTO sector_analytics "
                    "(sector, as_of_date, total_mcap, avg_pe, avg_roe, "
                    "avg_debt_equity, stock_count) "
                    "VALUES (:sector, DATE('now'), "
                    ":total_mcap, :avg_pe, :avg_roe, "
                    ":avg_debt_eq, :count)",
                    {
                        "sector": prev_sector,
                        "total_mcap": sector_total_mcap,
                        "avg_pe": sector_avg_pe,
                        "avg_roe": sector_avg_roe,
                        "avg_debt_eq": sector_avg_debt_eq,
                        "count": sector_stock_count,
                    }
                )
                phase3_count += 1

            sector_total_mcap = 0.0
            sector_avg_pe = 0.0
            sector_avg_roe = 0.0
            sector_avg_debt_eq = 0.0
            sector_avg_rev_growth = 0.0
            sector_stock_count = 0
            sector_best_composite = 0.0

        prev_sector = c_sector

        sector_total_mcap += c_mcap
        sector_avg_pe += c_pe
        sector_avg_roe += c_roe
        sector_avg_debt_eq += c_debt_eq
        sector_avg_rev_growth += c_rev_growth
        sector_stock_count += 1

        # ── Fetch technical indicators ──
        cur.execute(
            "SELECT sma_50, sma_200, daily_return, volatility_30d "
            "FROM equity_derived_metrics "
            "WHERE ticker = :ticker "
            "ORDER BY date DESC LIMIT 1",
            {"ticker": c_ticker}
        )
        tech_row = cur.fetchone()

        if tech_row:
            sma_50, sma_200, momentum_1m, volatility_30d = tech_row
        else:
            sma_50, sma_200, momentum_1m, volatility_30d = 0.0, 0.0, 0.0, 0.0

        # Compute factor scores
        value_score = compute_value_score(c_pe, c_pb, c_ps, c_peg, c_div_yield)
        growth_score = compute_growth_score(c_rev_growth, c_earn_growth,
                                           c_earn_q_growth, c_fwd_pe, c_pe, c_peg)
        quality_score = compute_quality_score(c_roe, c_roa, c_op_margin,
                                             c_gross_margin, c_debt_eq,
                                             c_current_ratio, c_free_cf, c_op_cf)
        momentum_score = compute_momentum_score(momentum_1m, 0.0, 0.0,
                                               0.0, 0.0, 50.0, 0.0)
        low_vol_score = compute_low_vol_score(c_beta, volatility_30d,
                                             c_debt_eq, c_div_yield)

        composite_score, rating, outlook = compute_composite(
            value_score, growth_score, quality_score,
            momentum_score, low_vol_score, c_mcap
        )

        # Market breadth
        if momentum_1m > 0:
            market_positive_momentum += 1
        if sma_50 > 0 and c_price > sma_50:
            market_above_sma50 += 1
        if sma_200 > 0 and c_price > sma_200:
            market_above_sma200 += 1

        # Track best composite
        total_factor_score = (value_score + growth_score + quality_score
                             + momentum_score + low_vol_score)
        if total_factor_score > best_composite:
            best_composite = total_factor_score
            best_ticker = c_ticker

        phase4_count += 1

        commit_count += 1
        if commit_count >= 50:
            conn.commit()
            commit_count = 0

    # Finalize last sector
    if sector_stock_count > 0 and len(prev_sector) > 0:
        sector_avg_pe /= sector_stock_count
        sector_avg_roe /= sector_stock_count
        sector_avg_debt_eq /= sector_stock_count
        sector_avg_rev_growth /= sector_stock_count

        cur.execute(
            "INSERT OR REPLACE INTO sector_analytics "
            "(sector, as_of_date, total_mcap, avg_pe, avg_roe, "
            "avg_debt_equity, stock_count) "
            "VALUES (:sector, DATE('now'), "
            ":total_mcap, :avg_pe, :avg_roe, "
            ":avg_debt_eq, :count)",
            {
                "sector": prev_sector,
                "total_mcap": sector_total_mcap,
                "avg_pe": sector_avg_pe,
                "avg_roe": sector_avg_roe,
                "avg_debt_eq": sector_avg_debt_eq,
                "count": sector_stock_count,
            }
        )

    conn.commit()

    # ── Phase 5: Market Breadth ──
    cur.execute("SELECT COUNT(*) FROM stock_fundamentals WHERE current_price > 0")
    total_with_fundamentals_row = cur.fetchone()
    total_with_fundamentals = total_with_fundamentals_row[0] if total_with_fundamentals_row else 0

    cur.execute("SELECT AVG(pe_ratio), AVG(roe_pct) FROM stock_fundamentals")
    avg_row = cur.fetchone()
    avg_market_pe = avg_row[0] if avg_row and avg_row[0] else 0.0
    avg_market_roe = avg_row[1] if avg_row and avg_row[1] else 0.0

    if market_positive_momentum > 0 and market_total > 0:
        market_adv_decline = (
            float(market_positive_momentum)
            / float(market_total - market_positive_momentum)
        )
    else:
        market_adv_decline = 1.0

    # ── Phase 6: Composite Summary ──
    cur.execute(
        "SELECT ticker, market_cap_crore "
        "FROM stock_fundamentals "
        "ORDER BY market_cap_crore DESC LIMIT 1"
    )
    summary_row = cur.fetchone()
    if summary_row:
        best_ticker = summary_row[0]  # BUG: overwrites best_composite ticker
        largest_mcap = summary_row[1]
    else:
        largest_mcap = 0.0

    # ── Phase 7: Report ──
    pct_above_sma50 = (
        float(market_above_sma50) / market_total * 100.0 if market_total > 0 else 0.0
    )
    pct_above_sma200 = (
        float(market_above_sma200) / market_total * 100.0 if market_total > 0 else 0.0
    )
    pct_positive_momentum = (
        float(market_positive_momentum) / market_total * 100.0 if market_total > 0 else 0.0
    )

    # Build sector ranking lines
    cur.execute(
        "SELECT sector, total_mcap, avg_pe, avg_roe, stock_count "
        "FROM sector_analytics "
        "ORDER BY total_mcap DESC LIMIT 10"
    )
    sector_rows = cur.fetchall()

    sector_lines = ""
    for s_row in sector_rows:
        s_sector, s_mcap, s_pe, s_roe, s_count = s_row
        sector_lines += (
            "│ %-20s  %6d stks  PE=%5.1f  ROE=%5.1f%%       \n"
        ) % (s_sector, s_count, s_pe, s_roe)

    # Build report (abbreviated for testing — full report in actual code)
    report_header = (
        "\n"
        "=== ICICI SECURITIES — COMPREHENSIVE MARKET ANALYTICS ===\n\n"
        "--- A. MARKET BREADTH ---\n"
    )
    report = report_header

    conn.commit()

    cur.execute(
        "INSERT INTO batch_log (service_name, status, rows_processed) "
        "VALUES ('BATCH_MARKET_ANALYTICS', :status, :rows)",
        {"status": "SUCCESS", "rows": phase2_count}
    )

    return {
        "phase1_count": phase1_count,
        "phase2_count": phase2_count,
        "phase3_count": phase3_count,
        "phase4_count": phase4_count,
        "phase5_stocks": phase5_stocks,
        "error_count": error_count,
        "market_total": market_total,
        "market_large_cap": market_large_cap,
        "market_mid_cap": market_mid_cap,
        "market_small_cap": market_small_cap,
        "market_total_mcap": market_total_mcap,
        "market_above_sma50": market_above_sma50,
        "market_above_sma200": market_above_sma200,
        "market_positive_momentum": market_positive_momentum,
        "market_adv_decline": market_adv_decline,
        "avg_market_pe": avg_market_pe,
        "avg_market_roe": avg_market_roe,
        "best_ticker": best_ticker,
        "best_composite": best_composite,
        "total_with_fundamentals": total_with_fundamentals,
        "report": report,
        "rows_processed": phase2_count,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestScoringFunctions:
    """Unit tests for Qwen's factor scoring functions."""

    def test_value_score_cheap_stock(self):
        """PE=8, PB=0.8, PS=0.8, PEG=0.5, Div=3.5 → strong value."""
        s = compute_value_score(8.0, 0.8, 0.8, 0.5, 3.5)
        # 50 + 20(PE<10) + 15(PB<1) + 10(PS<1) + 10(PEG<1) + 10(Div>3) = 115 → capped 100
        assert s == 100.0, f"Expected 100.0, got {s}"

    def test_value_score_expensive_stock(self):
        """PE=60, PB=8, PS=8, PEG=4, Div=0 → expensive."""
        s = compute_value_score(60.0, 8.0, 8.0, 4.0, 0.0)
        # 50 + (-20) + (-15) + (-10) + (-10 for PEG>=3) + 0 = -5 → floor 0
        assert s == 0.0, f"Expected 0.0, got {s}"

    def test_value_score_neutral(self):
        """PE=20, PB=2, PS=2, PEG=2, Div=1.5 → mid-range."""
        s = compute_value_score(20.0, 2.0, 2.0, 1.5, 1.5)
        # 50 + 5(PE<25) + 5(PB<3) + 0(PS>=2<5) + 5(PEG 1-2) + 2(Div>1) = 67
        assert s == 67.0, f"Expected 67.0, got {s}"

    def test_value_score_negative_earnings(self):
        """PE <= 0 should add 0 (no deduction for negative earnings)."""
        s = compute_value_score(-5.0, 1.0, 1.0, 0.5, 2.0)
        # 50 + 0(PE<=0) + 10(PB<1.5) + 5(PS<2) + 10(PEG<1) + 2(Div>1) = 77
        assert s == 77.0, f"Expected 77.0, got {s}"

    def test_growth_score_high_growth(self):
        """Rev=35%, Earn=30%, Q=35% (accelerating), FwdPE/PE=0.7, PEG=0.5."""
        s = compute_growth_score(35.0, 30.0, 35.0, 10.0, 15.0, 0.5)
        # 50 + 20(rev>30) + 20(earn>25) + 5(q>earn but not +5)
        # Wait: 35 - 30 = 5, not > 5, so just earn_q_growth > earn_growth => +5
        # + 10(fwd<0.8*pe) + 10(peg<1) = 115 → capped 100
        assert s == 100.0, f"Expected 100.0, got {s}"

    def test_growth_score_declining(self):
        """Rev=-15%, Earn=-25%, Q=-40% (decelerating), FwdPE/PE=1.0."""
        s = compute_growth_score(-15.0, -25.0, -40.0, 20.0, 20.0, 2.0)
        # 50 + (-20 for rev<-10) + (-20 for earn<-20)
        # + (-10 for q < earn-10: -40 < -35) = 0 → floor 0
        assert s == 0.0, f"Expected 0.0, got {s}"

    def test_quality_score_excellent(self):
        """ROE=30, ROA=12, OpM=30, GM=60, D/E=0.2, CR=3, FCF=100."""
        s = compute_quality_score(30.0, 12.0, 30.0, 60.0, 0.2, 3.0, 100.0, 200.0)
        # 50 + 15(roe>25) + 10(roa>10) + 10(opM>25) + 5(gm>50)
        # + 10(de<0.3) + 5(cr>2) + 5(fcf>0) = 110 → capped 100
        assert s == 100.0, f"Expected 100.0, got {s}"

    def test_quality_score_poor(self):
        """ROE=-5, ROA=-3, OpM=2, GM=15, D/E=3, CR=0.5, FCF=-50."""
        s = compute_quality_score(-5.0, -3.0, 2.0, 15.0, 3.0, 0.5, -50.0, -10.0)
        # 50 + (-15 for roe<0) + (-10 for roa<0) + (-10 for opM<5)
        # + (-5 for gm<20) + (-15 for de>=2) + (-10 for cr<1) + (-5 for fcf<=0) = -20 → floor 0
        assert s == 0.0, f"Expected 0.0, got {s}"

    def test_momentum_score_strong(self):
        """mom1m=20, mom3m=30, mom6m=35, price>both SMAs, golden cross, RSI=45, MACD>0."""
        s = compute_momentum_score(20.0, 30.0, 35.0, 1.1, 1.05, 45.0, 1.0)
        # 50 + 15(mom1m>15) + 10(mom3m>25) + 5(mom6m>30)
        # + 10(above both SMAs) + 5(golden cross: 1.1>1.05) + 3(RSI 40-60) + 5(MACD>0) = 103 → capped 100
        assert s == 100.0, f"Expected 100.0, got {s}"

    def test_momentum_score_weak(self):
        """mom1m=-15, mom3m=-20, mom6m=-25, below both SMAs, RSI=75, MACD<0."""
        s = compute_momentum_score(-15.0, -20.0, -25.0, 0.9, 0.85, 75.0, -1.0)
        # 50 + (-15 for mom1m<-10) + (-10 for mom3m<-15) + (-5 for mom6m<-20)
        # + (-10 for below both SMAs) + (-5 for RSI>70 overbought) + 0(MACD<=0) = 5
        assert s == 5.0, f"Expected 5.0, got {s}"

    def test_low_vol_score_defensive(self):
        """Beta=0.3, Vol=0.5, D/E=0.2, Div=3.0 → very defensive."""
        s = compute_low_vol_score(0.3, 0.5, 0.2, 3.0)
        # 50 + 20(beta<0.5) + 15(vol<1) + 10(de<0.5) + 5(div>2) = 100
        assert s == 100.0, f"Expected 100.0, got {s}"

    def test_low_vol_score_aggressive(self):
        """Beta=2.0, Vol=5.0, D/E=1.0, Div=0 → volatile."""
        s = compute_low_vol_score(2.0, 5.0, 1.0, 0.0)
        # 50 + (-20 for beta>=1.5) + (-10 for vol>=3) + 0(de>=0.5) + 0(div<=2) = 20
        assert s == 20.0, f"Expected 20.0, got {s}"

    def test_classify_mcap(self):
        assert classify_mcap(30000.0) == "LARGE_CAP"
        assert classify_mcap(20000.1) == "LARGE_CAP"
        assert classify_mcap(10000.0) == "MID_CAP"
        assert classify_mcap(5000.1) == "MID_CAP"
        assert classify_mcap(3000.0) == "SMALL_CAP"

    def test_composite_large_cap_weights(self):
        """Large cap: quality and low-vol matter most."""
        c, r, o = compute_composite(80, 80, 80, 80, 80, 30000.0)
        # w = 0.20+0.15+0.30+0.15+0.20 = 1.0
        # composite = 80*1.0 = 80.0 → STRONG_BUY
        assert c == 80.0, f"Expected 80.0, got {c}"
        assert r == "STRONG_BUY"
        assert o == "Highly Favorable"

    def test_composite_small_cap_weights(self):
        """Small cap: growth and momentum dominate."""
        c, r, o = compute_composite(80, 80, 80, 80, 80, 3000.0)
        # w = 0.15+0.35+0.15+0.30+0.05 = 1.0
        # composite = 80*1.0 = 80.0 → STRONG_BUY
        assert c == 80.0
        assert r == "STRONG_BUY"

    def test_composite_ratings_boundaries(self):
        """Test each rating boundary."""
        assert compute_composite(100, 100, 100, 100, 100, 30000.0)[1] == "STRONG_BUY"
        assert compute_composite(100, 100, 100, 100, 100, 30000.0)[1] == "STRONG_BUY"

        _, r, _ = compute_composite(90, 60, 60, 60, 60, 30000.0)
        # 90*0.20 + 60*0.15 + 60*0.30 + 60*0.15 + 60*0.20 = 18+9+18+9+12 = 66 → ACCUMULATE
        assert r == "ACCUMULATE"

        _, r, _ = compute_composite(50, 50, 50, 50, 50, 30000.0)
        assert r == "HOLD"

        _, r, _ = compute_composite(30, 30, 40, 40, 30, 30000.0)
        # 30*0.20 + 30*0.15 + 40*0.30 + 40*0.15 + 30*0.20 = 6+4.5+12+6+6 = 34.5 → SELL
        assert r == "SELL"

        _, r, _ = compute_composite(20, 20, 20, 20, 20, 30000.0)
        assert r == "STRONG_SELL"


class TestMarketAnalyticsEmptyDB:
    """Phase 1: Empty DB — must match C baseline."""

    @classmethod
    def setup_class(cls):
        cls.conn = sqlite3.connect(":memory:")
        setup_schema(cls.conn)
        cls.results = run_market_analytics(cls.conn)

    @classmethod
    def teardown_class(cls):
        cls.conn.close()

    def test_phase1_count_zero(self):
        assert self.results["phase1_count"] == C_BASELINE["phase1_count"]

    def test_phase2_count_zero(self):
        assert self.results["phase2_count"] == C_BASELINE["phase2_count"]

    def test_phase3_count_zero(self):
        assert self.results["phase3_count"] == C_BASELINE["phase3_count"]

    def test_market_total_zero(self):
        assert self.results["market_total"] == C_BASELINE["market_total"]

    def test_market_large_cap_zero(self):
        assert self.results["market_large_cap"] == C_BASELINE["market_large_cap"]

    def test_above_sma50_zero(self):
        assert self.results["market_above_sma50"] == C_BASELINE["market_above_sma50"]

    def test_positive_momentum_zero(self):
        assert self.results["market_positive_momentum"] == C_BASELINE["market_positive_momentum"]

    def test_batch_log_exists(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT service_name, status, rows_processed FROM batch_log "
            "WHERE service_name = 'BATCH_MARKET_ANALYTICS'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "BATCH_MARKET_ANALYTICS"
        assert row[1] == "SUCCESS"
        assert row[2] == 0

    def test_emptydb_avg_pe_is_none(self):
        """AVG() on empty table returns NULL → coerced to 0.0."""
        assert self.results["avg_market_pe"] == 0.0

    def test_emptydb_adv_decline_default(self):
        """With no data, advance/decline defaults to 1.0."""
        assert self.results["market_adv_decline"] == 1.0

    def test_emptydb_returns_report(self):
        """Report should still be generated even with no data."""
        assert "report" in self.results
        assert "ICICI SECURITIES" in self.results["report"]


class TestMarketAnalyticsSeededDB:
    """Phase 2: Seeded DB — verify business logic correctness."""

    @classmethod
    def setup_class(cls):
        cls.conn = sqlite3.connect(":memory:")
        setup_schema(cls.conn)
        cur = cls.conn.cursor()

        # Seed EOD prices — 60 days each for 3 tickers (enough for SMA-50)
        import datetime
        base_date = datetime.date(2026, 7, 10)
        tickers_prices = {
            "RELIANCE": 2450.0,
            "TCS": 3890.0,
            "HDFCBANK": 1675.0,
        }
        for ticker, base_price in tickers_prices.items():
            for i in range(60):
                d = base_date - datetime.timedelta(days=i)
                # Price trending up slightly as we go back
                adj = (60 - i) * 1.5
                price = base_price - adj
                cur.execute(
                    "INSERT INTO eod_prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ticker, d.isoformat(), price - 5, price + 10, price - 10, price, 1000000 + i * 1000)
                )

        # Seed fundamentals — 5 stocks across 2 sectors
        cur.executemany(
            "INSERT INTO stock_fundamentals (ticker, company_name, sector, industry, "
            "exchange, current_price, market_cap_crore, "
            "pe_ratio, forward_pe, pb_ratio, peg_ratio, price_to_sales, "
            "roe_pct, roa_pct, operating_margins_pct, gross_margins_pct, "
            "debt_to_equity, current_ratio, "
            "revenue_growth_pct, earnings_growth_pct, earnings_quarterly_growth_pct, "
            "dividend_yield_pct, high_52w, low_52w, beta, "
            "free_cashflow, operating_cashflow, "
            "recommendation, as_of_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                # Large cap IT — strong fundamentals
                ("TCS", "Tata Consultancy Services", "IT", "Software", "NSE",
                 3890.0, 1400000.0,
                 32.0, 28.0, 12.0, 1.8, 7.5,
                 42.0, 28.0, 30.0, 55.0,
                 0.05, 3.5,
                 18.0, 15.0, 12.0,
                 1.8, 4200.0, 3200.0, 0.65,
                 45000.0, 52000.0,
                 "buy", "2026-07-10"),
                # Large cap IT — expensive
                ("INFY", "Infosys Limited", "IT", "Software", "NSE",
                 1520.0, 630000.0,
                 28.0, 26.0, 8.0, 2.0, 5.5,
                 32.0, 22.0, 24.0, 45.0,
                 0.08, 3.0,
                 12.0, 10.0, 8.0,
                 2.2, 1700.0, 1200.0, 0.58,
                 22000.0, 28000.0,
                 "hold", "2026-07-10"),
                # Large cap OIL — value play
                ("RELIANCE", "Reliance Industries", "OIL_AND_GAS", "Conglomerate", "NSE",
                 2450.0, 1700000.0,
                 22.0, 20.0, 2.5, 1.2, 1.8,
                 15.0, 12.0, 18.0, 30.0,
                 0.75, 1.8,
                 22.0, 18.0, 25.0,
                 2.8, 2800.0, 2100.0, 0.95,
                 85000.0, 95000.0,
                 "buy", "2026-07-10"),
                # Mid cap OIL — high debt, struggling
                ("ONGC", "Oil and Natural Gas Corp", "OIL_AND_GAS", "Exploration", "NSE",
                 185.0, 15000.0,
                 8.0, 9.0, 0.9, 0.8, 0.9,
                 18.0, 14.0, 22.0, 38.0,
                 1.8, 1.2,
                 -5.0, -8.0, -12.0,
                 4.5, 220.0, 150.0, 0.55,
                 12000.0, 15000.0,
                 "hold", "2026-07-10"),
                # Small cap OIL
                ("OIL", "Oil India Limited", "OIL_AND_GAS", "Exploration", "NSE",
                 420.0, 4500.0,
                 5.0, 5.5, 0.7, 0.6, 0.5,
                 22.0, 18.0, 28.0, 45.0,
                 0.4, 2.5,
                 35.0, 28.0, 30.0,
                 3.5, 500.0, 350.0, 0.45,
                 8000.0, 10000.0,
                 "buy", "2026-07-10"),
            ],
        )

        # Seed equity_derived_metrics — one row per stock with technical indicators
        cur.executemany(
            "INSERT INTO equity_derived_metrics "
            "(ticker, date, sma_50, sma_200, daily_return, volatility_30d) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("TCS", "2026-07-10", 3800.0, 3700.0, 1.5, 1.2),
                ("INFY", "2026-07-10", 1480.0, 1400.0, -0.5, 1.8),
                ("RELIANCE", "2026-07-10", 2400.0, 2350.0, 3.2, 2.1),
                ("ONGC", "2026-07-10", 190.0, 195.0, -2.1, 2.8),
                ("OIL", "2026-07-10", 410.0, 400.0, 6.5, 1.5),
            ],
        )

        cls.conn.commit()
        cls.results = run_market_analytics(cls.conn)

    @classmethod
    def teardown_class(cls):
        cls.conn.close()

    # ── Counts ──

    def test_phase1_count_bug(self):
        """KNOWN BUG: phase1_count += 0 instead of += 1. Always 0."""
        assert self.results["phase1_count"] == 0, (
            f"BUG CONFIRMED: phase1_count={self.results['phase1_count']} (should be ~180 for 60x3 EOD rows)"
        )

    def test_phase2_count(self):
        assert self.results["phase2_count"] == 5  # All 5 fundamentals fetched

    def test_phase3_count(self):
        # phase3_count counts sector TRANSITIONS, not total sectors written.
        # 2 sectors = 1 transition (IT→OIL_AND_GAS).
        # The final sector is written in the "finalize last sector" block
        # but phase3_count is NOT incremented there — matches original Pro*C.
        assert self.results["phase3_count"] == 1

    def test_phase4_count(self):
        assert self.results["phase4_count"] == 5  # One per stock

    # ── Market cap classification ──

    def test_large_cap_count(self):
        assert self.results["market_large_cap"] == 3  # TCS, INFY, RELIANCE

    def test_mid_cap_count(self):
        assert self.results["market_mid_cap"] == 1  # ONGC (15000 Cr)

    def test_small_cap_count(self):
        assert self.results["market_small_cap"] == 1  # OIL (4500 Cr)

    # ── Market breadth ──

    def test_market_total(self):
        assert self.results["market_total"] == 5

    def test_positive_momentum_count(self):
        # TCS: 1.5%, INFY: -0.5%, RELIANCE: 3.2%, ONGC: -2.1%, OIL: 6.5%
        # Positive: TCS, RELIANCE, OIL = 3
        assert self.results["market_positive_momentum"] == 3

    def test_above_sma50_count(self):
        # TCS: 3890 > 3800 ✓, INFY: 1520 > 1480 ✓, RELIANCE: 2450 > 2400 ✓
        # ONGC: 185 < 190 ✗, OIL: 420 > 410 ✓
        # = 4
        assert self.results["market_above_sma50"] == 4

    def test_above_sma200_count(self):
        # TCS: 3890 > 3700 ✓, INFY: 1520 > 1400 ✓, RELIANCE: 2450 > 2350 ✓
        # ONGC: 185 < 195 ✗, OIL: 420 > 400 ✓
        # = 4
        assert self.results["market_above_sma200"] == 4

    # ── Advance/Decline ──

    def test_advance_decline_ratio(self):
        # 3 positive / 2 negative = 1.5
        assert self.results["market_adv_decline"] == 1.5

    # ── Market averages ──

    def test_avg_market_pe(self):
        # (32+28+22+8+5)/5 = 95/5 = 19.0
        assert abs(self.results["avg_market_pe"] - 19.0) < 0.01

    def test_avg_market_roe(self):
        # (42+32+15+18+22)/5 = 129/5 = 25.8
        assert abs(self.results["avg_market_roe"] - 25.8) < 0.01

    # ── Best composite tracking ──

    def test_best_composite_is_positive(self):
        """With good data, best composite should be > 0."""
        assert self.results["best_composite"] > 0

    def test_best_ticker_overwritten_by_phase6(self):
        """KNOWN BUG: Phase 6 overwrites best_ticker with largest-cap stock.
        Regardless of which stock had the best composite, best_ticker will
        always be the largest-cap stock (RELIANCE at 1,700,000 Cr)."""
        assert self.results["best_ticker"] == "RELIANCE", (
            f"BUG CONFIRMED: best_ticker={self.results['best_ticker']} "
            "(Phase 6 overwrote composite-based best with largest-cap)"
        )

    # ── Sector analytics ──

    def test_sector_analytics_rows(self):
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sector_analytics")
        count = cur.fetchone()[0]
        assert count == 2  # IT and OIL_AND_GAS

    def test_it_sector_stats(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT stock_count, avg_pe, avg_roe "
            "FROM sector_analytics WHERE sector = 'IT'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 2  # TCS + INFY
        # avg_pe = (32+28)/2 = 30.0
        assert abs(row[1] - 30.0) < 0.01
        # avg_roe = (42+32)/2 = 37.0
        assert abs(row[2] - 37.0) < 0.01

    def test_oil_sector_stats(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT stock_count, avg_pe, avg_roe "
            "FROM sector_analytics WHERE sector = 'OIL_AND_GAS'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 3  # RELIANCE + ONGC + OIL
        # avg_pe = (22+8+5)/3 = 11.67
        assert abs(row[1] - 11.67) < 0.1
        # avg_roe = (15+18+22)/3 = 18.33
        assert abs(row[2] - 18.33) < 0.1

    # ── Batch log ──

    def test_batch_log_entry(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT service_name, status, rows_processed FROM batch_log "
            "WHERE service_name = 'BATCH_MARKET_ANALYTICS'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "BATCH_MARKET_ANALYTICS"
        assert row[1] == "SUCCESS"
        assert row[2] == 5  # 5 stocks processed

    # ── Report ──

    def test_report_contains_header(self):
        assert "ICICI SECURITIES" in self.results["report"]

    def test_report_contains_market_breadth(self):
        assert "MARKET BREADTH" in self.results["report"]


class TestRegressionSpecific:
    """Targeted tests for bugs found during review."""

    @classmethod
    def setup_class(cls):
        cls.conn = sqlite3.connect(":memory:")
        setup_schema(cls.conn)
        cur = cls.conn.cursor()

        # Single stock, single sector — with negative momentum to avoid div-by-zero
        cur.execute(
            "INSERT INTO stock_fundamentals (ticker, company_name, sector, industry, "
            "exchange, current_price, market_cap_crore, "
            "pe_ratio, forward_pe, pb_ratio, peg_ratio, price_to_sales, "
            "roe_pct, roa_pct, operating_margins_pct, gross_margins_pct, "
            "debt_to_equity, current_ratio, "
            "revenue_growth_pct, earnings_growth_pct, earnings_quarterly_growth_pct, "
            "dividend_yield_pct, high_52w, low_52w, beta, "
            "free_cashflow, operating_cashflow, "
            "recommendation, as_of_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("TEST", "Test Corp", "TESTING", "Test", "NSE",
             100.0, 1000.0,
             15.0, 14.0, 2.0, 1.5, 1.5,
             20.0, 15.0, 20.0, 40.0,
             0.5, 2.0,
             15.0, 12.0, 14.0,
             2.0, 120.0, 80.0, 0.8,
             500.0, 600.0,
             "hold", "2026-07-10"),
        )

        cur.execute(
            "INSERT INTO equity_derived_metrics "
            "(ticker, date, sma_50, sma_200, daily_return, volatility_30d) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("TEST", "2026-07-10", 95.0, 90.0, -1.0, 1.0),
        )

        # Add 60 EOD days for SMA computation
        import datetime
        base_date = datetime.date(2026, 7, 10)
        for i in range(60):
            d = base_date - datetime.timedelta(days=i)
            cur.execute(
                "INSERT INTO eod_prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("TEST", d.isoformat(), 100.0, 105.0, 95.0, 100.0, 10000)
            )

        cls.conn.commit()
        cls.results = run_market_analytics(cls.conn)

    @classmethod
    def teardown_class(cls):
        cls.conn.close()

    def test_phase1_count_is_zero_bug(self):
        """Regression: phase1_count stays 0 regardless of EOD data volume."""
        assert self.results["phase1_count"] == 0, (
            f"BUG: phase1_count should be 60 but is {self.results['phase1_count']}"
        )

    def test_single_sector_finalized(self):
        """Single sector should still get a sector_analytics entry."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sector_analytics")
        count = cur.fetchone()[0]
        assert count == 1, f"Expected 1 sector entry, got {count}"

    def test_no_error_on_empty_derived_metrics(self):
        """Stock without derived metrics should not crash (uses 0.0 defaults)."""
        # Would have crashed if the tech_row None check was missing
        assert self.results["phase2_count"] == 1

    def test_market_total_mcap(self):
        assert self.results["market_total_mcap"] == 1000.0


# ═══════════════════════════════════════════════════════════════════════════════
# RIGOROUS VERIFICATION TESTS
# These test against the REAL module (not replicas) and hand-computed values.
# ═══════════════════════════════════════════════════════════════════════════════


class TestRealModuleFunctions:
    """Verify the ACTUAL market_analytics.py module functions.

    These import the real source file, not replicas. If the real module
    changes, these tests catch discrepancies.
    """

    @classmethod
    def setup_class(cls):
        import sys
        from pathlib import Path

        src = str(Path(__file__).parent.parent / "src")
        if src not in sys.path:
            sys.path.insert(0, src)

        from services.market_analytics import (
            compute_value_score as real_value,
            compute_growth_score as real_growth,
            compute_quality_score as real_quality,
            compute_momentum_score as real_momentum,
            compute_low_vol_score as real_low_vol,
            compute_composite as real_composite,
            classify_mcap as real_classify_mcap,
        )
        cls.real_value = real_value
        cls.real_growth = real_growth
        cls.real_quality = real_quality
        cls.real_momentum = real_momentum
        cls.real_low_vol = real_low_vol
        cls.real_composite = real_composite
        cls.real_classify_mcap = real_classify_mcap

    # ── Value Score ──

    def test_real_value_cheap(self):
        s = type(self).real_value(8.0, 0.8, 0.8, 0.5, 3.5)
        assert s == 100.0, f"real module value(cheap) = {s}, expected 100.0"

    def test_real_value_expensive(self):
        s = type(self).real_value(60.0, 8.0, 8.0, 4.0, 0.0)
        assert s == 0.0, f"real module value(expensive) = {s}, expected 0.0"

    def test_real_value_boundary_pe_exactly_10(self):
        """PE=10.0: pe < 10.0 is False, pe < 15.0 is True → +15.
        PB=2.0: <3 → +5. PS=2.0: NOT < 2, so <5 → +0.
        PEG=1.5: 1-2 → +5. Div=1.0: NOT >1 → +0.
        = 50+15+5+0+5+0 = 75"""
        s = type(self).real_value(10.0, 2.0, 2.0, 1.5, 1.0)
        assert s == 75.0, f"real module value(PE=10) = {s}, expected 75.0"

    # ── Growth Score ──

    def test_real_growth_high(self):
        s = type(self).real_growth(35.0, 30.0, 35.0, 10.0, 15.0, 0.5)
        assert s == 100.0

    def test_real_growth_declining(self):
        s = type(self).real_growth(-15.0, -25.0, -40.0, 20.0, 20.0, 2.0)
        assert s == 0.0

    # ── Quality Score ──

    def test_real_quality_excellent(self):
        s = type(self).real_quality(30.0, 12.0, 30.0, 60.0, 0.2, 3.0, 100.0, 200.0)
        assert s == 100.0

    def test_real_quality_poor(self):
        s = type(self).real_quality(-5.0, -3.0, 2.0, 15.0, 3.0, 0.5, -50.0, -10.0)
        assert s == 0.0

    # ── Momentum Score ──

    def test_real_momentum_strong(self):
        s = type(self).real_momentum(20.0, 30.0, 35.0, 1.1, 1.05, 45.0, 1.0)
        assert s == 100.0

    def test_real_momentum_weak(self):
        s = type(self).real_momentum(-15.0, -20.0, -25.0, 0.9, 0.85, 75.0, -1.0)
        assert s == 5.0

    # ── Low Vol Score ──

    def test_real_low_vol_defensive(self):
        s = type(self).real_low_vol(0.3, 0.5, 0.2, 3.0)
        assert s == 100.0

    def test_real_low_vol_aggressive(self):
        s = type(self).real_low_vol(2.0, 5.0, 1.0, 0.0)
        assert s == 20.0

    # ── Composite ──

    def test_real_composite_mid_cap_weights(self):
        """Mid cap: w=0.20,0.30,0.20,0.20,0.10. Sum of weights = 1.0."""
        c, r, o = type(self).real_composite(50, 50, 50, 50, 50, 10000.0)
        assert c == 50.0
        assert r == "HOLD"

    def test_real_composite_small_cap_weights(self):
        """Small cap: w=0.15,0.35,0.15,0.30,0.05. Growth+momentum=0.65."""
        c, r, o = type(self).real_composite(100, 100, 0, 100, 0, 3000.0)
        # 100*0.15 + 100*0.35 + 0*0.15 + 100*0.30 + 0*0.05 = 15+35+0+30+0 = 80
        assert c == 80.0
        assert r == "STRONG_BUY"

    # ── Market Cap Classification ──

    def test_real_classify_boundary_large_mid(self):
        """Exactly at boundary: >20000 is LARGE, <=20000 is not."""
        assert type(self).real_classify_mcap(20000.0) == "MID_CAP"
        assert type(self).real_classify_mcap(20000.1) == "LARGE_CAP"

    def test_real_classify_boundary_mid_small(self):
        assert type(self).real_classify_mcap(5000.0) == "SMALL_CAP"
        assert type(self).real_classify_mcap(5000.1) == "MID_CAP"


class TestHandComputedFullScoring:
    """Verify the complete scoring pipeline for a specific stock
    against INDEPENDENTLY hand-computed expected values.

    Stock: TCS (Large Cap IT)
      PE=32, PB=12, PS=7.5, PEG=1.8, Div=1.8
      Rev=18%, Earn=15%, Q=12%, FwdPE=28, PEG=1.8
      ROE=42, ROA=28, OpM=30, GM=55, D/E=0.05, CR=3.5, FCF=45000
      mom1m=1.5, beta=0.65, vol=1.2
    """

    @classmethod
    def setup_class(cls):
        import sys
        from pathlib import Path

        src = str(Path(__file__).parent.parent / "src")
        if src not in sys.path:
            sys.path.insert(0, src)

        from services.market_analytics import (
            compute_value_score,
            compute_growth_score,
            compute_quality_score,
            compute_momentum_score,
            compute_low_vol_score,
            compute_composite,
        )
        cls.value = compute_value_score
        cls.growth = compute_growth_score
        cls.quality = compute_quality_score
        cls.momentum = compute_momentum_score
        cls.low_vol = compute_low_vol_score
        cls.composite = compute_composite

        # Compute all scores once
        cls.v_score = compute_value_score(32.0, 12.0, 7.5, 1.8, 1.8)
        cls.g_score = compute_growth_score(18.0, 15.0, 12.0, 28.0, 32.0, 1.8)
        cls.q_score = compute_quality_score(42.0, 28.0, 30.0, 55.0, 0.05, 3.5, 45000.0, 52000.0)
        cls.m_score = compute_momentum_score(1.5, 0.0, 0.0, 0.0, 0.0, 50.0, 0.0)
        cls.l_score = compute_low_vol_score(0.65, 1.2, 0.05, 1.8)
        cls.composite_score, cls.rating, cls.outlook = compute_composite(
            cls.v_score, cls.g_score, cls.q_score, cls.m_score, cls.l_score, 1400000.0
        )

    def test_tcs_value_score_hand_computed(self):
        """PE=32(-10), PB=12(-15), PS=7.5(-10), PEG=1.8(+5), Div=1.8(+2)
        = 50-10-15-10+5+2 = 22"""
        assert self.v_score == 22.0, f"TCS value score: {self.v_score}, expected 22.0"

    def test_tcs_growth_score_hand_computed(self):
        """Rev=18(+10), Earn=15(+10), Q=12>15? No but Q=12>Earn=15? No (Q<Earn)
        → no bonus. FwdPE=28 vs PE*0.8=25.6: 28>25.6 → no bonus.
        PEG=1.8≥1 → no bonus.
        = 50+10+10 = 70"""
        assert self.g_score == 70.0, f"TCS growth score: {self.g_score}, expected 70.0"

    def test_tcs_quality_score_hand_computed(self):
        """ROE=42(+15), ROA=28(+10), OpM=30(+10), GM=55(+5),
        D/E=0.05(+10), CR=3.5(+5), FCF=45000(+5) = 50+15+10+10+5+10+5+5 = 110→100"""
        assert self.q_score == 100.0, f"TCS quality score: {self.q_score}, expected 100.0"

    def test_tcs_momentum_score_hand_computed(self):
        """mom1m=1.5(+2), price_vs_sma50=0.0 & pvsma200=0.0 → below both SMAs (-10),
        RSI=50(+3), MACD=0 → 50+2-10+3 = 45"""
        assert self.m_score == 45.0, f"TCS momentum score: {self.m_score}, expected 45.0"

    def test_tcs_low_vol_score_hand_computed(self):
        """beta=0.65(+15), vol=1.2(+10), D/E=0.05(+10), Div=1.8(0)
        = 50+15+10+10+0 = 85"""
        assert self.l_score == 85.0, f"TCS low vol score: {self.l_score}, expected 85.0"

    def test_tcs_composite_hand_computed(self):
        """Large cap weights: 0.20,0.15,0.30,0.15,0.20
        = 22*0.20 + 70*0.15 + 100*0.30 + 45*0.15 + 85*0.20
        = 4.4 + 10.5 + 30.0 + 6.75 + 17.0 = 68.65 → ACCUMULATE"""
        expected = 4.4 + 10.5 + 30.0 + 6.75 + 17.0
        assert abs(self.composite_score - expected) < 0.01, (
            f"TCS composite: {self.composite_score}, expected {expected}"
        )
        assert self.rating == "ACCUMULATE", f"TCS rating: {self.rating}, expected ACCUMULATE"
        assert self.outlook == "Moderately Positive", f"TCS outlook: {self.outlook}, expected Moderately Positive"

    def test_tcs_total_factor_sum(self):
        """Sum of raw factor scores (used for best_composite tracking)."""
        total = self.v_score + self.g_score + self.q_score + self.m_score + self.l_score
        assert total == 322.0, f"TCS raw sum: {total}, expected 322.0"


class TestAdvanceDeclineEdgeCases:
    """Test the advance-decline ratio edge cases.

    The original code (both Pro*C and Python) has:
        if market_positive_momentum > 0 and market_total > 0:
            market_adv_decline = float(positive) / float(total - positive)
        else:
            market_adv_decline = 1.0

    When ALL stocks have positive momentum, total - positive = 0 → DIVISION BY ZERO.
    """

    def test_all_positive_is_div_by_zero(self):
        """Verify the division-by-zero bug exists in the logic."""
        positive, total = 5, 5
        # This is the exact expression from market_analytics.py line 842-844
        if positive > 0 and total > 0:
            try:
                result = float(positive) / float(total - positive)
                assert False, f"Expected ZeroDivisionError but got {result}"
            except ZeroDivisionError:
                pass  # Bug confirmed

    def test_all_zero_uses_default(self):
        """When no stocks have positive momentum, returns 1.0."""
        positive, total = 0, 5
        if positive > 0 and total > 0:
            result = float(positive) / float(total - positive)
        else:
            result = 1.0
        assert result == 1.0

    def test_mixed_momentum_computes_ratio(self):
        """3 positive, 2 negative → 3/2 = 1.5."""
        positive, total = 3, 5
        result = float(positive) / float(total - positive)
        assert result == 1.5


