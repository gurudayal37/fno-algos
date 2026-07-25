"""
Positional NIFTY strangle backtest — weekly Friday 3pm rebalance.

Strategy:
  - Every Friday at 3pm: sell 10-delta 2nd-month (next calendar month) monthly strangle
  - Next Friday at 3pm: buy back the same strikes, then open fresh strangle
  - No intraweek stop loss
  - Lot size: 65 (NIFTY monthly, current regime)

Pricing priority:
  1. Real market data from DuckDB (option_candles)
  2. Black-Scholes with ATM IV as fallback when real data is missing

Usage:
    python3 run_positional_backtest.py --from-date 2026-06-01 --to-date 2026-07-25
    python3 run_positional_backtest.py --from-date 2026-06-01 --to-date 2026-07-25 --export-web
"""

import argparse
import calendar
import math
from datetime import date, timedelta

import pandas as pd
from tabulate import tabulate

from config import logger, WEB_DATA_DIR
from src.db import DBManager
from src.web_export import export_strategy_result, export_intraday_data

NIFTY_STRIKE_STEP = 50.0
COSTS_PER_LOT     = 40.0   # brokerage + STT + exchange charges per side
_N_INV_90         = 1.2816
RISK_FREE_RATE    = 0.065  # ~India 91-day T-bill

# NIFTY F&O lot size history (approximate, per SEBI revisions)
_LOT_SCHEDULE = [
    (date(2025, 6, 1),  65),
    (date(2024, 11, 20), 75),
    (date(2000, 1, 1),  25),
]

def nifty_lot_size(for_date: date) -> int:
    for cutoff, size in _LOT_SCHEDULE:
        if for_date >= cutoff:
            return size
    return 25


# NIFTY expiry regime: last Thursday until 2025-09-01, last Tuesday thereafter
_NIFTY_TUESDAY_REGIME = date(2025, 9, 1)


# ── math helpers ──────────────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S: float, K: float, T_years: float, iv_pct: float, opt_type: str) -> float:
    """Black-Scholes European option price. opt_type: 'CE' or 'PE'."""
    if T_years <= 0:
        return max(S - K, 0.0) if opt_type == 'CE' else max(K - S, 0.0)
    sigma = iv_pct / 100.0
    r     = RISK_FREE_RATE
    sqT   = math.sqrt(T_years)
    d1    = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T_years) / (sigma * sqT)
    d2    = d1 - sigma * sqT
    if opt_type == 'CE':
        return S * _norm_cdf(d1) - K * math.exp(-r * T_years) * _norm_cdf(d2)
    else:
        return K * math.exp(-r * T_years) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


# ── expiry helpers ────────────────────────────────────────────────────────────

def last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def next_month_expiry(from_dt: date) -> date:
    """
    Last Thursday of next month (pre-2025-09-01) or last Tuesday (post-2025-09-01).
    Always targets the NEXT calendar month's monthly expiry.
    """
    month = from_dt.month + 1
    year  = from_dt.year + (1 if month > 12 else 0)
    month = month if month <= 12 else 1
    weekday = 1 if from_dt >= _NIFTY_TUESDAY_REGIME else 3  # Tue=1, Thu=3
    return last_weekday_of_month(year, month, weekday)


def compute_10delta_strikes(spot: float, iv_pct: float, days_to_expiry: int):
    sigma = iv_pct / 100.0
    T     = max(days_to_expiry, 1) / 365.0
    K_ce  = round(spot * math.exp( _N_INV_90 * sigma * math.sqrt(T)) / NIFTY_STRIKE_STEP) * NIFTY_STRIKE_STEP
    K_pe  = round(spot * math.exp(-_N_INV_90 * sigma * math.sqrt(T)) / NIFTY_STRIKE_STEP) * NIFTY_STRIKE_STEP
    return K_ce, K_pe


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_spot_at_3pm(conn, day: date):
    df = conn.execute("""
        SELECT close FROM spot_candles
        WHERE security_id = '13'
          AND CAST(timestamp AS DATE) = ?
          AND HOUR(timestamp) < 15
        ORDER BY timestamp DESC LIMIT 1
    """, [day]).df()
    return float(df.iloc[0]['close']) if not df.empty else None


def get_iv_at_3pm(conn, day: date):
    """ATM CE IV at 3pm — ignores same-day expiry contracts."""
    df = conn.execute("""
        SELECT iv FROM option_candles
        WHERE underlying = 'NIFTY'
          AND option_type = 'CE'
          AND CAST(timestamp AS DATE) = ?
          AND expiry_date > ?
          AND iv > 0
          AND HOUR(timestamp) < 15
        ORDER BY timestamp DESC LIMIT 1
    """, [day, day]).df()
    return float(df.iloc[0]['iv']) if not df.empty else None


def get_real_price_at_3pm(conn, day: date, expiry_dt: date, strike: float, opt_type: str):
    """Last close before 15:00 for a specific contract. Returns None if no data."""
    df = conn.execute("""
        SELECT close FROM option_candles
        WHERE underlying = 'NIFTY'
          AND expiry_date = ?
          AND strike = ?
          AND option_type = ?
          AND CAST(timestamp AS DATE) = ?
          AND HOUR(timestamp) < 15
        ORDER BY timestamp DESC LIMIT 1
    """, [expiry_dt, float(strike), opt_type, day]).df()
    return float(df.iloc[0]['close']) if not df.empty else None


def price_option(conn, day: date, expiry_dt: date, strike: float, opt_type: str):
    """
    Returns (price, source) where source is 'REAL' or 'BS'.
    Falls back to Black-Scholes when real market data is absent.
    Returns (None, None) if neither real data nor IV is available.
    """
    real = get_real_price_at_3pm(conn, day, expiry_dt, strike, opt_type)
    if real is not None:
        return real, 'REAL'

    spot   = get_spot_at_3pm(conn, day)
    iv_pct = get_iv_at_3pm(conn, day)
    if spot is None or iv_pct is None:
        return None, None

    T_years = max((expiry_dt - day).days, 0) / 365.0
    price   = bs_price(spot, strike, T_years, iv_pct, opt_type)
    return round(price, 2), 'BS'


def all_fridays(from_date: str, to_date: str):
    return [d.date() for d in pd.date_range(from_date, to_date, freq="W-FRI")]


# ── main backtest ─────────────────────────────────────────────────────────────

def run_positional_backtest(db: DBManager, from_date: str, to_date: str):
    conn    = db.connect()
    fridays = all_fridays(from_date, to_date)
    trades  = []
    intraday_data = {}

    for i in range(len(fridays) - 1):
        entry_fri = fridays[i]
        exit_fri  = fridays[i + 1]

        expiry_dt   = next_month_expiry(entry_fri)
        days_to_exp = (expiry_dt - entry_fri).days
        lot_size    = nifty_lot_size(entry_fri)

        # ── Spot + IV at entry ────────────────────────────────────────────────
        spot   = get_spot_at_3pm(conn, entry_fri)
        iv_pct = get_iv_at_3pm(conn, entry_fri)

        if spot is None:
            logger.warning(f"[{entry_fri}] No spot data — skipping.")
            continue
        if iv_pct is None or iv_pct <= 0:
            logger.warning(f"[{entry_fri}] No ATM IV data — skipping.")
            continue

        K_ce, K_pe = compute_10delta_strikes(spot, iv_pct, days_to_exp)
        logger.info(
            f"[{entry_fri}] spot={spot:.0f}  IV={iv_pct:.1f}%  expiry={expiry_dt}  "
            f"10Δ CE={K_ce:.0f}  PE={K_pe:.0f}"
        )

        # ── Entry prices ──────────────────────────────────────────────────────
        ce_entry, ce_entry_src = price_option(conn, entry_fri, expiry_dt, K_ce, 'CE')
        pe_entry, pe_entry_src = price_option(conn, entry_fri, expiry_dt, K_pe, 'PE')

        if ce_entry is None or pe_entry is None:
            logger.warning(f"[{entry_fri}] Cannot price entry CE={ce_entry} PE={pe_entry} — skipping.")
            continue

        # ── Exit prices ───────────────────────────────────────────────────────
        if expiry_dt <= exit_fri:
            ce_exit = pe_exit = 0.0
            ce_exit_src = pe_exit_src = 'EXPIRY'
            exit_reason = "EXPIRY_SETTLEMENT"
        else:
            ce_exit, ce_exit_src = price_option(conn, exit_fri, expiry_dt, K_ce, 'CE')
            pe_exit, pe_exit_src = price_option(conn, exit_fri, expiry_dt, K_pe, 'PE')

            if ce_exit is None or pe_exit is None:
                logger.warning(f"[{entry_fri}→{exit_fri}] Cannot price exit CE={ce_exit} PE={pe_exit} — skipping.")
                continue
            exit_reason = "REBALANCE"

        # ── P&L ──────────────────────────────────────────────────────────────
        net_credit = round(ce_entry + pe_entry, 2)
        net_debit  = round(ce_exit  + pe_exit,  2)
        gross_pnl  = (net_credit - net_debit) * lot_size
        costs      = COSTS_PER_LOT * 2
        net_pnl    = round(gross_pnl - costs, 2)

        entry_src  = f"CE:{ce_entry_src}/PE:{pe_entry_src}"
        exit_src   = f"CE:{ce_exit_src}/PE:{pe_exit_src}"

        logger.info(
            f"[{entry_fri}] credit={net_credit:.2f}({entry_src})  "
            f"debit={net_debit:.2f}({exit_src})  pnl=₹{net_pnl:,.2f}  {exit_reason}"
        )

        trades.append({
            "date":          str(entry_fri),
            "exit_date":     str(exit_fri),
            "expiry_date":   str(expiry_dt),
            "spot_entry":    round(spot, 2),
            "iv_entry":      round(iv_pct, 2),
            "ce_strike":     K_ce,
            "pe_strike":     K_pe,
            "ce_entry":      ce_entry,
            "pe_entry":      pe_entry,
            "ce_exit":       ce_exit,
            "pe_exit":       pe_exit,
            "entry_src":     entry_src,
            "exit_src":      exit_src,
            "net_credit":    net_credit,
            "net_debit":     net_debit,
            "lot_size":      lot_size,
            "exit_reason":   exit_reason,
            "total_net_pnl": net_pnl,
        })

        intraday_data[str(entry_fri)] = [
            {"time": "15:00", "spot": round(spot, 2),
             "ce": round(ce_entry, 2), "pe": round(pe_entry, 2), "pnl": 0.0},
            {"time": "15:00*", "spot": round(spot, 2),
             "ce": round(ce_exit, 2),  "pe": round(pe_exit, 2),
             "pnl": round(net_pnl / lot_size, 2)},
        ]

    df = pd.DataFrame(trades)
    if df.empty:
        return None, df, {}

    # ── Summary ───────────────────────────────────────────────────────────────
    wins       = (df['total_net_pnl'] > 0).sum()
    total      = len(df)
    pnl_cum    = df['total_net_pnl'].cumsum()
    weekly_ret = df['total_net_pnl'] / (df['net_credit'] * df['lot_size'])
    sharpe     = (weekly_ret.mean() / weekly_ret.std() * (52 ** 0.5)) if weekly_ret.std() > 0 else 0
    max_dd     = (pnl_cum - pnl_cum.cummax()).min()

    bs_trades = df[df['entry_src'].str.contains('BS') | df['exit_src'].str.contains('BS')]

    summary = {
        "Total Trades":          total,
        "BS-priced Trades":      len(bs_trades),
        "Win Rate (%)":          f"{wins / total * 100:.2f}%",
        "Total P&L (₹)":        f"₹{df['total_net_pnl'].sum():,.2f}",
        "Avg P&L/Trade (₹)":    f"₹{df['total_net_pnl'].mean():,.2f}",
        "Max Drawdown (₹)":     f"₹{max_dd:,.2f}",
        "Sharpe (weekly, ann.)": f"{sharpe:.2f}",
        "Avg Net Credit":        f"{df['net_credit'].mean():.2f}",
        "Avg CE Strike":         f"{df['ce_strike'].mean():.0f}",
        "Avg PE Strike":         f"{df['pe_strike'].mean():.0f}",
    }

    rows = [[k, v] for k, v in summary.items()]
    print("\n" + tabulate(rows, headers=["Metric", "Value"], tablefmt="fancy_grid"))

    print("\nTrade detail:")
    detail_cols = ["date", "exit_date", "ce_strike", "pe_strike",
                   "ce_entry", "pe_entry", "ce_exit", "pe_exit",
                   "net_credit", "net_debit", "total_net_pnl", "entry_src", "exit_src"]
    print(tabulate(df[detail_cols].values.tolist(), headers=detail_cols, tablefmt="simple", floatfmt=".2f"))

    return summary, df, intraday_data


# ── web export ────────────────────────────────────────────────────────────────

def _export_web(args, df_raw: pd.DataFrame, intraday_data: dict):
    df = df_raw.copy()

    # Fields required by the standard Trade interface / stats functions
    df["underlying"]     = "NIFTY"
    df["strike"]         = 0          # strangle has no single strike
    df["ce_exit_time"]   = "15:00"
    df["pe_exit_time"]   = "15:00"
    df["ce_exit_reason"] = df["exit_reason"]
    df["pe_exit_reason"] = df["exit_reason"]
    df["ce_costs"]       = COSTS_PER_LOT
    df["pe_costs"]       = COSTS_PER_LOT
    df["ce_net_pnl"]     = (df["ce_entry"] - df["ce_exit"]) * df["lot_size"] - COSTS_PER_LOT
    df["pe_net_pnl"]     = (df["pe_entry"] - df["pe_exit"]) * df["lot_size"] - COSTS_PER_LOT
    df["cum_pnl"]        = df["total_net_pnl"].cumsum()
    df["peak"]           = df["cum_pnl"].cummax()
    df["drawdown"]       = df["cum_pnl"] - df["peak"]

    wins       = int((df["total_net_pnl"] > 0).sum())
    total      = len(df)
    weekly_ret = df["total_net_pnl"] / (df["net_credit"] * df["lot_size"])
    sharpe     = float(weekly_ret.mean() / weekly_ret.std() * (52 ** 0.5)) if weekly_ret.std() > 0 else 0.0
    max_dd     = float((df["cum_pnl"] - df["cum_pnl"].cummax()).min())

    export_summary = {
        "underlying":             "NIFTY",
        "total_expiry_days":      total,
        "winning_expiry_days":    wins,
        "win_rate_pct":           round(wins / total * 100, 2) if total else 0.0,
        "total_net_pnl":          float(df["total_net_pnl"].sum()),
        "max_drawdown":           max_dd,
        "sharpe_ratio":           sharpe,
        "avg_net_pnl_per_expiry": float(df["total_net_pnl"].mean()),
    }

    params = {
        "strategy_type": "positional_strangle",
        "underlying":    "NIFTY",
        "delta":         10,
        "expiry":        "2nd_month_monthly",
        "rebalance":     "weekly_friday_3pm",
        "from_date":     args.from_date,
        "to_date":       args.to_date,
    }

    export_strategy_result(
        strategy_id  = args.strategy_id,
        name         = args.strategy_name,
        description  = "Sell 10-delta 2nd-month NIFTY strangle every Friday at 3pm; rebalance weekly. BS pricing used where real data is unavailable.",
        underlying   = "NIFTY",
        params       = params,
        summary      = export_summary,
        df_trades    = df,
        web_data_dir = WEB_DATA_DIR,
    )

    export_intraday_data(
        strategy_id  = args.strategy_id,
        df_trades    = df,
        intraday_data = intraday_data,
        web_data_dir = WEB_DATA_DIR,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-date",     default="2026-06-01")
    parser.add_argument("--to-date",       default="2026-07-25")
    parser.add_argument("--export-web",    action="store_true")
    parser.add_argument("--strategy-id",   default="nifty_positional_strangle")
    parser.add_argument("--strategy-name", default="NIFTY Positional Strangle")
    args = parser.parse_args()

    db = DBManager()
    summary, df, intraday_data = run_positional_backtest(db, args.from_date, args.to_date)

    if summary is None:
        logger.error("No trades generated — check that data is downloaded first.")
        return

    if args.export_web:
        _export_web(args, df, intraday_data)
        logger.info("Web export complete.")


if __name__ == "__main__":
    main()
