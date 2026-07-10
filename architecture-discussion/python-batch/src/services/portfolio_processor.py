"""
portfolio_processor.py — BATCH_PORTFOLIO_PROCESSOR Service

Converted from: pc/batch_portfolio_processor.pc (629 lines Pro*C → ~280 lines Python)
Conversion tool: Qwen 3.6 35B (openrouter/qwen/qwen3.6-35b-a3b)
Date: 2025-01-XX

SQL preserved exactly from the original .pc file.

Pattern: Multi-phase cursor processing with risk decision trees,
margin computation, concentration checks, and summary reporting.
Handles FML buffer I/O (Tuxedo TPSVCINFO → Python dict/string).
"""

from typing import Any

from batch.base import BatchProcess
from batch.log import get_logger

# ─── Risk tier thresholds (from ICICI RMS config, .pc:32-40) ─────────

HIGH_RISK_BETA = 1.5
ELEVATED_RISK_BETA = 1.2
HIGH_DEBT_EQUITY = 2.0
ELEVATED_DEBT_EQUITY = 1.5
HIGH_PE = 50.0
ELEVATED_PE = 30.0
CONCENTRATION_LIMIT_PCT = 20.0
MAX_SINGLE_STOCK_PCT = 15.0
MARGIN_CALL_THRESHOLD = 0.25


# ─── Decision tree helpers ───────────────────────────────────────────

def determine_risk_tier(beta: float, debt_eq: float, pe: float,
                         roe: float, recommendation: str) -> str:
    """Classify a stock position into a risk tier.
    SQL preserved from batch_portfolio_processor.pc:176-200."""
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


def calc_margin_percentage(risk_tier: str, portfolio_type: str,
                           user_risk_profile: str) -> float:
    """Margin % based on risk tier, portfolio type, and user risk profile.
    SQL preserved from batch_portfolio_processor.pc:208-241."""
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

    # Portfolio type adjustments
    if portfolio_type == "INTRADAY":
        base_margin *= 0.5
    elif portfolio_type == "MARGIN":
        base_margin *= 0.8

    # User risk profile adjustment
    if user_risk_profile == "AGGRESSIVE":
        base_margin *= 1.2
    elif user_risk_profile == "CONSERVATIVE":
        base_margin *= 0.9

    return base_margin


def determine_action_code(unrealized_pnl_pct: float, margin_shortfall: float,
                          risk_tier: str, weight_in_portfolio: float) -> str:
    """What action should the system take for this position?
    SQL preserved from batch_portfolio_processor.pc:248-272."""
    if margin_shortfall > 0 and risk_tier == "HIGH_RISK":
        return "FORCE_SELL"
    if margin_shortfall > 0:
        return "MARGIN_CALL"
    if unrealized_pnl_pct < -20.0:
        return "STOP_LOSS_ALERT"
    if unrealized_pnl_pct < -10.0 and risk_tier == "HIGH_RISK":
        return "REVIEW_REQUIRED"
    if weight_in_portfolio > CONCENTRATION_LIMIT_PCT:
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


# ─── Main service ────────────────────────────────────────────────────

class PortfolioProcessorService(BatchProcess):
    name = "BATCH_PORTFOLIO_PROCESSOR"

    def __init__(self):
        pass

    async def run(self, conn) -> dict[str, Any]:
        log = get_logger()
        cursor = conn.cursor()

        # ── Initialize counters ──
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

        # ── Phase 1: User-level processing ──
        # Walk through every user, classify by status and risk profile.
        # SQL preserved from batch_portfolio_processor.pc:299-303
        await cursor.execute(
            "SELECT user_id, client_code, full_name, segment, risk_profile, "
            "account_status, branch_code, annual_income, net_worth "
            "FROM users ORDER BY user_id"
        )
        users = await cursor.fetchall()

        for row in users:
            (u_user_id, u_client_code, u_full_name, u_segment,
             u_risk_profile, u_account_status, u_branch_code,
             u_annual_income, u_net_worth) = row

            total_users += 1

            # Classify user by account status
            if u_account_status == "ACTIVE":
                active_users += 1
            elif u_account_status == "DORMANT":
                dormant_users += 1
                continue  # Dormant users: skip portfolio processing
            else:
                closed_users += 1
                continue

            # Classify by risk profile
            if u_risk_profile == "AGGRESSIVE":
                aggressive_users += 1
            elif u_risk_profile == "MODERATE":
                moderate_users += 1
            else:
                conservative_users += 1

            # Check if user is high-risk based on leverage
            # from batch_portfolio_processor.pc:347-352
            if u_annual_income > 0 and u_net_worth > 0:
                leverage = (u_net_worth - u_annual_income) / u_net_worth
                if leverage > 0.7:
                    high_risk_users += 1

            user_processed += 1

            # Commit per user batch
            commit_count += 1
            if commit_count >= 50:
                await conn.commit()
                commit_count = 0

        # ── Phase 2: Position-level processing ──
        # Walk through every portfolio holding, compute MTM, P&L,
        # risk metrics, margin requirements.
        # SQL preserved from batch_portfolio_processor.pc:377-384
        log.info("portfolio_processor.phase2.start")

        await cursor.execute(
            "SELECT pf.portfolio_id, pf.user_id, pf.ticker, pf.quantity, "
            "pf.avg_buy_price, pf.invested_amount, pf.holding_since, "
            "pf.portfolio_type, pf.pledge_status "
            "FROM user_portfolios pf "
            "JOIN users u ON pf.user_id = u.user_id "
            "WHERE u.account_status = 'ACTIVE' "
            "ORDER BY pf.user_id, pf.ticker"
        )
        positions = await cursor.fetchall()

        # Track per-user aggregation
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

            # Portfolio type counter
            if p_portfolio_type == "DELIVERY":
                delivery_count += 1
            elif p_portfolio_type == "MARGIN":
                margin_count += 1
            elif p_portfolio_type == "INTRADAY":
                intraday_count += 1

            # Check if we moved to a new user
            if p_user_id != current_user:
                # Finalize previous user's concentration check
                if current_user >= 0 and user_stocks > 0:
                    if user_max_pct > CONCENTRATION_LIMIT_PCT:
                        concentration_breaches += 1

                # Reset for new user
                current_user = p_user_id
                user_total_val = 0.0
                user_total_inv = 0.0
                user_stocks = 0
                user_max_pct = 0.0
                user_max_ticker = ""

            # ── Fetch fundamentals for this stock ──
            # SQL preserved from batch_portfolio_processor.pc:450-458
            await cursor.execute(
                "SELECT current_price, pe_ratio, beta, debt_to_equity, "
                "roe_pct, market_cap_crore, sector, high_52w, low_52w, "
                "dividend_yield_pct, COALESCE(recommendation, 'hold') "
                "FROM stock_fundamentals WHERE ticker = :ticker",
                {"ticker": p_ticker}
            )
            fund_row = await cursor.fetchone()

            if fund_row is None:
                # No fundamentals available — skip position
                continue

            (f_current_price, f_pe_ratio, f_beta, f_debt_equity,
             f_roe_pct, f_market_cap, f_sector, f_high_52w, f_low_52w,
             f_dividend_yield, f_recommendation) = fund_row

            # ── Compute MTM values ──
            # from batch_portfolio_processor.pc:461-473
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

            # ── Aggregate user portfolio ──
            user_total_val += current_value
            user_total_inv += p_invested
            user_stocks += 1

            # ── Fetch user risk profile for margin calc ──
            # SQL preserved from batch_portfolio_processor.pc:484-485
            await cursor.execute(
                "SELECT risk_profile FROM users WHERE user_id = :uid",
                {"uid": p_user_id}
            )
            user_row = await cursor.fetchone()
            user_rp = user_row[0] if user_row else "MODERATE"

            # ── Risk tier determination ──
            # Full if/else tree from batch_portfolio_processor.pc:489-492
            risk_tier = determine_risk_tier(
                f_beta, f_debt_equity, f_pe_ratio,
                f_roe_pct, f_recommendation
            )

            # ── Margin calculation ──
            margin_pct = calc_margin_percentage(
                risk_tier, p_portfolio_type, user_rp
            )
            margin_required = current_value * (margin_pct / 100.0)

            # Margin shortfall for non-delivery positions
            # from batch_portfolio_processor.pc:501-510
            if p_portfolio_type != "DELIVERY" and p_invested > 0.0:
                equity = p_invested
                margin_shortfall = margin_required - equity
                if margin_shortfall > 0:
                    margin_calls += 1
            else:
                margin_shortfall = 0.0

            # ── Position limit check ──
            # Different limits for different risk profiles
            # from batch_portfolio_processor.pc:516-522
            if user_rp == "AGGRESSIVE":
                position_limit = 25.0
            elif user_rp == "MODERATE":
                position_limit = 20.0
            else:
                position_limit = 15.0

            # ── Action code ──
            weight = 0.0
            if user_total_val > 0.0:
                weight = (current_value / user_total_val) * 100.0
            action = determine_action_code(
                unrealized_pnl_pct, margin_shortfall,
                risk_tier, weight
            )

            # ── Excess position check ──
            # Different limits for different risk tiers
            # from batch_portfolio_processor.pc:536-547
            if risk_tier == "HIGH_RISK":
                position_limit *= 0.5  # 50% reduction
            elif risk_tier == "ELEVATED_RISK":
                position_limit *= 0.7  # 30% reduction

            if weight > position_limit:
                excess_position = (weight - position_limit) * user_total_val / 100.0
            else:
                excess_position = 0.0

            # Update concentration tracking
            if weight > user_max_pct:
                user_max_pct = weight
                user_max_ticker = p_ticker

            total_portfolios += 1

            # Commit every 100 positions
            commit_count += 1
            if commit_count >= 100:
                await conn.commit()
                commit_count = 0

        # Finalize last user's concentration check
        if current_user >= 0 and user_stocks > 0:
            if user_max_pct > CONCENTRATION_LIMIT_PCT:
                concentration_breaches += 1

        await conn.commit()

        # ── Phase 3: Summary Report ──
        # ASCII report buffer — SQL preserved from batch_portfolio_processor.pc:574-609
        report_buffer = (
            "\n"
            "\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
            "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
            "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557\n"
            "\u2551    ICICI SECURITIES \u2014 PORTFOLIO ANALYTICS REPORT          \u2551\n"
            "\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
            "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
            "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d\n"
            "\n"
            "\u250c\u2500\u2500\u2500\u2500\u2500 USER SUMMARY \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510\n"
            "\u2502 Total Users              : %6d                            \u2502\n"
            "\u2502 Active Users             : %6d                            \u2502\n"
            "\u2502 Dormant Users            : %6d                            \u2502\n"
            "\u2502 Closed Accounts          : %6d                            \u2502\n"
            "\u2502                                                           \u2502\n"
            "\u2502 By Risk Profile:                                          \u2502\n"
            "\u2502   Aggressive             : %6d                            \u2502\n"
            "\u2502   Moderate               : %6d                            \u2502\n"
            "\u2502   Conservative           : %6d                            \u2502\n"
            "\u2502   High Risk (leveraged)  : %6d                            \u2502\n"
            "\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518\n"
            "\n"
            "\u250c\u2500\u2500\u2500\u2500\u2500 POSITION SUMMARY \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510\n"
            "\u2502 Total Positions          : %6d                            \u2502\n"
            "\u2502   DELIVERY               : %6d                            \u2502\n"
            "\u2502   MARGIN                 : %6d                            \u2502\n"
            "\u2502   INTRADAY               : %6d                            \u2502\n"
            "\u2502                                                           \u2502\n"
            "\u2502 Margin Calls Triggered   : %6d                            \u2502\n"
            "\u2502 Concentration Breaches   : %6d                            \u2502\n"
            "\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518\n"
            "\n"
        ) % (
            total_users, active_users, dormant_users, closed_users,
            aggressive_users, moderate_users, conservative_users,
            high_risk_users,
            position_count,
            delivery_count, margin_count, intraday_count,
            margin_calls, concentration_breaches,
        )

        # ── Log batch completion ──
        # SQL preserved from batch_portfolio_processor.pc:613-614
        await cursor.execute(
            "INSERT INTO batch_log (service_name, status, rows_processed) "
            "VALUES ('BATCH_PORTFOLIO_PROCESSOR', :status, :rows)",
            {"status": "SUCCESS", "rows": position_count}
        )
        await cursor.close()

        log.info(
            "portfolio_processor.complete",
            users_processed=user_processed,
            positions=position_count,
            margin_calls=margin_calls,
            concentration_breaches=concentration_breaches,
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
            "report": report_buffer,
            "rows_processed": position_count,
        }

    async def _write_batch_log(self, conn, status: str, rows: int,
                                error: str = None) -> None:
        """Insert batch log — SQL preserved from .pc:613-614 / 624-625."""
        cursor = conn.cursor()
        if error:
            # Error path — SQL preserved from batch_portfolio_processor.pc:624-625
            await cursor.execute(
                "INSERT INTO batch_log (service_name, status, rows_processed, error_message) "
                "VALUES ('BATCH_PORTFOLIO_PROCESSOR', :status, :rows, :error)",
                {"status": status, "rows": rows, "error": error}
            )
        else:
            await cursor.execute(
                "INSERT INTO batch_log (service_name, status, rows_processed) "
                "VALUES ('BATCH_PORTFOLIO_PROCESSOR', :status, :rows)",
                {"status": status, "rows": rows}
            )
        await cursor.close()


def main():
    """Entry point for batch-portfolio-processor CLI."""
    from batch.cli import run_service

    run_service(PortfolioProcessorService, "BATCH_PORTFOLIO_PROCESSOR")


if __name__ == "__main__":
    main()
