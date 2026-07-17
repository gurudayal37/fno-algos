#!/usr/bin/env python3
"""
Iron Condor backtester — NIFTY weekly 0DTE options.

Structure (all same-expiry, sold at 09:20 on expiry day):
  Short OTM Call  @ spot × (1 + short_pct / 100)   → rounded to nearest 50
  Long  OTM Call  @ short_CE + wing_points           → rounded to nearest 50
  Short OTM Put   @ spot × (1 - short_pct / 100)   → rounded to nearest 50
  Long  OTM Put   @ short_PE - wing_points           → rounded to nearest 50

Max profit  = Net credit collected (all four legs expire worthless)
Max loss    = Wing width − Net credit (spot blows past a long strike)

Stop-loss options:
  "none"      : hold until exit time
  "spot"      : exit when spot touches either short strike (spot-based SL)
  "premium"   : exit when net position value reaches sl_pct × net credit collected
"""

import argparse
import sys
from tabulate import tabulate
import pandas as pd
import numpy as np
from datetime import datetime

from config import logger, DATA_DIR, WEB_DATA_DIR
from src.db import DBManager
from src.backtester import LOT_SIZE_REGIMES, _lot_size_for_date
from src.web_export import export_strategy_result, export_intraday_data

IST_OFFSET = pd.Timedelta(hours=5, minutes=30)
STRIKE_STEP = 50  # NIFTY


def round_to_strike(price: float, step: int = 50) -> float:
    return round(price / step) * step


def get_premium(candles_df, time_str):
    """Return the close price at time_str from a time-indexed dataframe."""
    if candles_df.empty or time_str not in candles_df.index:
        return None
    val = candles_df.loc[time_str, "close"]
    if isinstance(val, pd.Series):
        val = val.iloc[0]
    return float(val) if pd.notna(val) else None


def get_high(candles_df, time_str):
    if candles_df.empty or time_str not in candles_df.index:
        return None
    val = candles_df.loc[time_str, "high"]
    if isinstance(val, pd.Series):
        val = val.iloc[0]
    return float(val) if pd.notna(val) else None


def get_open(candles_df, time_str):
    if candles_df.empty or time_str not in candles_df.index:
        return None
    val = candles_df.loc[time_str, "open"]
    if isinstance(val, pd.Series):
        val = val.iloc[0]
    return float(val) if pd.notna(val) else None


def calc_costs(entry: float, exit_: float, qty: int) -> float:
    """Transaction costs per leg (mirrors backtester.py)."""
    sell = entry * qty
    buy  = exit_ * qty
    brokerage   = 40.0
    stt         = 0.0015 * sell
    exch        = 0.0005 * (sell + buy)
    sebi        = 0.000001 * (sell + buy)
    gst         = 0.18 * (brokerage + exch + sebi)
    stamp_duty  = 0.00003 * buy
    return brokerage + stt + exch + sebi + gst + stamp_duty


def run_ic_backtest(
    db: DBManager,
    from_date: str,
    to_date: str,
    short_pct: float = 2.0,
    wing_points: int = 200,
    entry_time: str = "09:20",
    exit_time: str = "15:15",
    sl_type: str = "spot",      # "none" | "spot" | "premium"
    sl_pct: float = 1.0,        # only used when sl_type="premium": SL when net loss = sl_pct × credit
    slippage_pct: float = 0.005,
):

    security_id = "13"   # NIFTY spot
    spot_candles = db.get_spot_candles(security_id, from_date, to_date)
    if spot_candles.empty:
        logger.error("No spot candles found.")
        return None, pd.DataFrame(), {}

    spot_candles["date"] = (spot_candles["timestamp"] + IST_OFFSET).dt.date
    spot_candles["time"] = (spot_candles["timestamp"] + IST_OFFSET).dt.strftime("%H:%M")

    conn = db.connect()
    expiries_df = conn.execute(
        "SELECT DISTINCT expiry_date FROM option_candles WHERE underlying='NIFTY' ORDER BY expiry_date"
    ).df()
    if expiries_df.empty:
        logger.error("No option candles found.")
        return None, pd.DataFrame(), {}

    expiry_dates = sorted(pd.to_datetime(expiries_df["expiry_date"]).dt.date.tolist())

    from_dt = pd.to_datetime(from_date).date()
    to_dt   = pd.to_datetime(to_date).date()
    expiry_dates = [d for d in expiry_dates if from_dt <= d <= to_dt]
    logger.info(f"Iron Condor backtest: {len(expiry_dates)} expiries | short={short_pct}% | wing={wing_points}pts | SL={sl_type}")

    trade_logs = []
    intraday_data = {}   # date_str → list of candle dicts

    for exp_date in expiry_dates:
        lot_size = _lot_size_for_date("NIFTY", exp_date)

        day_spot = spot_candles[(spot_candles["date"] == exp_date) & (spot_candles["time"] == entry_time)]
        if day_spot.empty:
            logger.warning(f"No spot at {entry_time} on {exp_date}. Skipping.")
            continue

        spot_entry = float(day_spot.iloc[0]["close"])

        # Strike selection
        short_ce = round_to_strike(spot_entry * (1 + short_pct / 100))
        short_pe = round_to_strike(spot_entry * (1 - short_pct / 100))
        long_ce  = short_ce + wing_points
        long_pe  = short_pe - wing_points

        logger.info(f"{exp_date} | spot={spot_entry:.0f} | IC: PE{long_pe}/{short_pe} x {short_ce}/{long_ce}CE")

        # Fetch candles for all 4 legs (on expiry day only)
        def load_leg(strike, opt_type):
            df = db.get_option_candles("NIFTY", expiry_date=exp_date, strike=strike, option_type=opt_type)
            if df.empty:
                return pd.DataFrame()
            df = df[df["timestamp"].dt.date == exp_date].copy()
            df["time"] = (df["timestamp"] + IST_OFFSET).dt.strftime("%H:%M")
            return df.set_index("time")

        lk_s_ce = load_leg(short_ce, "CE")
        lk_l_ce = load_leg(long_ce,  "CE")
        lk_s_pe = load_leg(short_pe, "PE")
        lk_l_pe = load_leg(long_pe,  "PE")

        # Must have entry prices for at minimum the two short legs
        s_ce_entry_raw = get_premium(lk_s_ce, entry_time)
        s_pe_entry_raw = get_premium(lk_s_pe, entry_time)
        l_ce_entry_raw = get_premium(lk_l_ce, entry_time)
        l_pe_entry_raw = get_premium(lk_l_pe, entry_time)

        if s_ce_entry_raw is None or s_pe_entry_raw is None:
            logger.warning(f"Missing short leg premium on {exp_date}. Skipping.")
            continue

        # Wing legs: if missing, treat as ₹0 (extremely cheap deep-OTM — conservative)
        l_ce_entry_raw = l_ce_entry_raw or 0.0
        l_pe_entry_raw = l_pe_entry_raw or 0.0

        # Apply slippage: sell short at lower price, buy long at higher price
        s_ce_entry = s_ce_entry_raw * (1 - slippage_pct)
        s_pe_entry = s_pe_entry_raw * (1 - slippage_pct)
        l_ce_entry = l_ce_entry_raw * (1 + slippage_pct)
        l_pe_entry = l_pe_entry_raw * (1 + slippage_pct)

        net_credit = (s_ce_entry + s_pe_entry) - (l_ce_entry + l_pe_entry)
        if net_credit <= 0:
            logger.warning(f"Net credit ≤ 0 on {exp_date} ({net_credit:.2f}). Skipping.")
            continue

        max_loss_per_lot = (wing_points - net_credit) * lot_size

        # Intraday simulation
        day_spot_idx = spot_candles[spot_candles["date"] == exp_date].set_index("time")
        all_times = sorted(set(lk_s_ce.index) | set(lk_s_pe.index))
        sim_times = [t for t in all_times if t > entry_time and t <= exit_time]

        # Entry candle (pnl=0 at open)
        candles = [{
            "time": entry_time,
            "spot": round(spot_entry, 2),
            "ce":   round(s_ce_entry - l_ce_entry, 2),  # net call spread value
            "pe":   round(s_pe_entry - l_pe_entry, 2),  # net put spread value
            "pnl":  0.0,
        }]

        exit_reason = "SQUARE_OFF"
        exit_time_actual = exit_time
        stopped = False

        for t in sim_times:
            s_ce_high = get_high(lk_s_ce, t)
            s_pe_high = get_high(lk_s_pe, t)

            # Spot-based SL: exit if spot touches either short strike
            if sl_type == "spot":
                spot_row = day_spot_idx.loc[t, "close"] if t in day_spot_idx.index else None
                if isinstance(spot_row, pd.Series):
                    spot_row = spot_row.iloc[0]
                if spot_row is not None:
                    if float(spot_row) >= short_ce or float(spot_row) <= short_pe:
                        exit_reason = "SPOT_SL"
                        exit_time_actual = t
                        stopped = True
                        break

            # Premium-based SL: exit when unrealised loss = sl_pct × net_credit
            if sl_type == "premium" and s_ce_high is not None and s_pe_high is not None:
                l_ce_v = get_premium(lk_l_ce, t) or 0.0
                l_pe_v = get_premium(lk_l_pe, t) or 0.0
                current_value = (s_ce_high + s_pe_high) - (l_ce_v + l_pe_v)
                if current_value >= net_credit * (1 + sl_pct):
                    exit_reason = "PREMIUM_SL"
                    exit_time_actual = t
                    stopped = True
                    break

            # Record intraday candle
            s_ce_now = get_premium(lk_s_ce, t) or s_ce_entry
            s_pe_now = get_premium(lk_s_pe, t) or s_pe_entry
            l_ce_now = get_premium(lk_l_ce, t) or l_ce_entry
            l_pe_now = get_premium(lk_l_pe, t) or l_pe_entry
            ce_net_now = round(s_ce_now - l_ce_now, 2)
            pe_net_now = round(s_pe_now - l_pe_now, 2)
            unrealized_pnl = round(
                (s_ce_entry + s_pe_entry - l_ce_entry - l_pe_entry - s_ce_now - s_pe_now + l_ce_now + l_pe_now) * lot_size, 2
            )
            spot_now_val = day_spot_idx.loc[t, "close"] if t in day_spot_idx.index else spot_entry
            if isinstance(spot_now_val, pd.Series):
                spot_now_val = spot_now_val.iloc[0]
            candles.append({
                "time": t,
                "spot": round(float(spot_now_val), 2),
                "ce":   ce_net_now,
                "pe":   pe_net_now,
                "pnl":  unrealized_pnl,
            })

        # Get exit prices
        def exit_price(lk, t_exit, is_short):
            """For shorts we buy-back (pay slippage+); for longs we sell (pay slippage-)."""
            p = get_premium(lk, t_exit)
            if p is None:
                # fallback to last available candle
                if not lk.empty:
                    idx = lk.index[lk.index <= t_exit]
                    if not idx.empty:
                        p = get_premium(lk, idx[-1])
            if p is None:
                p = 0.0
            return p * (1 + slippage_pct) if is_short else p * (1 - slippage_pct)

        s_ce_exit = exit_price(lk_s_ce, exit_time_actual, is_short=True)
        s_pe_exit = exit_price(lk_s_pe, exit_time_actual, is_short=True)
        l_ce_exit = exit_price(lk_l_ce, exit_time_actual, is_short=False)
        l_pe_exit = exit_price(lk_l_pe, exit_time_actual, is_short=False)

        # P&L (short legs: sold high, bought low; long legs: bought low, sold low)
        s_ce_pnl = (s_ce_entry - s_ce_exit) * lot_size
        s_pe_pnl = (s_pe_entry - s_pe_exit) * lot_size
        l_ce_pnl = (l_ce_exit - l_ce_entry) * lot_size
        l_pe_pnl = (l_pe_exit - l_pe_entry) * lot_size

        gross_pnl = s_ce_pnl + s_pe_pnl + l_ce_pnl + l_pe_pnl

        # Costs: 4 legs × 2 executions each
        costs = (
            calc_costs(s_ce_entry, s_ce_exit, lot_size) +
            calc_costs(s_pe_entry, s_pe_exit, lot_size) +
            calc_costs(l_ce_entry, l_ce_exit, lot_size) +
            calc_costs(l_pe_entry, l_pe_exit, lot_size)
        )
        net_pnl = gross_pnl - costs

        # Store final realized candle at exit and save intraday data
        intraday_data[str(exp_date)] = candles

        trade_logs.append({
            "date":          exp_date,
            "spot_entry":    round(spot_entry, 2),
            "lot_size":      lot_size,
            "short_pe":      short_pe,
            "short_ce":      short_ce,
            "long_pe":       long_pe,
            "long_ce":       long_ce,
            "net_credit":    round(net_credit, 2),
            "wing_pts":      wing_points,
            "max_loss_lot":  round(max_loss_per_lot, 0),
            "s_ce_entry":    round(s_ce_entry, 2),
            "s_pe_entry":    round(s_pe_entry, 2),
            "l_ce_entry":    round(l_ce_entry, 2),
            "l_pe_entry":    round(l_pe_entry, 2),
            "s_ce_exit":     round(s_ce_exit, 2),
            "s_pe_exit":     round(s_pe_exit, 2),
            "l_ce_exit":     round(l_ce_exit, 2),
            "l_pe_exit":     round(l_pe_exit, 2),
            "exit_reason":   exit_reason,
            "exit_time":     exit_time_actual,
            "gross_pnl":     round(gross_pnl, 2),
            "costs":         round(costs, 2),
            "net_pnl":       round(net_pnl, 2),
        })

    if not trade_logs:
        logger.error("No trades generated.")
        return None, pd.DataFrame(), {}

    df = pd.DataFrame(trade_logs)

    # Summary
    total_pnl  = df["net_pnl"].sum()
    win_rate   = (df["net_pnl"] > 0).mean() * 100
    df["cum"]  = df["net_pnl"].cumsum()
    df["peak"] = df["cum"].cummax()
    max_dd     = (df["cum"] - df["peak"]).min()
    pnl_std    = df["net_pnl"].std()
    pnl_mean   = df["net_pnl"].mean()
    sharpe     = pnl_mean / pnl_std * np.sqrt(52) if pnl_std > 0 else 0

    exit_counts = df["exit_reason"].value_counts().to_dict()

    summary = {
        "underlying":        "NIFTY",
        "strategy":          f"Iron Condor ±{short_pct}% / {wing_points}pt wing",
        "total_expiries":    len(df),
        "win_rate_pct":      round(win_rate, 1),
        "total_net_pnl":     round(total_pnl, 2),
        "avg_net_pnl":       round(pnl_mean, 2),
        "max_drawdown":      round(max_dd, 2),
        "sharpe_ratio":      round(sharpe, 2),
        "avg_credit":        round(df["net_credit"].mean(), 2),
        "exit_counts":       exit_counts,
    }
    return summary, df, intraday_data


def main():
    parser = argparse.ArgumentParser(description="NIFTY Iron Condor Backtester")
    parser.add_argument("--from-date",    default="2020-08-01")
    parser.add_argument("--to-date",      default="2026-07-11")
    parser.add_argument("--short-pct",    type=float, default=2.0,
                        help="Distance of short strikes from spot as %% (default: 2.0)")
    parser.add_argument("--wing-points",  type=int,   default=200,
                        help="Points from short to long strike (default: 200)")
    parser.add_argument("--entry-time",   default="09:20")
    parser.add_argument("--exit-time",    default="15:15")
    parser.add_argument("--sl-type",      default="spot",
                        choices=["none", "spot", "premium"],
                        help="Stop-loss type: none / spot (default) / premium")
    parser.add_argument("--sl-pct",       type=float, default=1.0,
                        help="For premium SL: exit when loss = sl_pct × credit (default: 1.0 = 100%%)")
    parser.add_argument("--slippage-pct", type=float, default=0.005)
    parser.add_argument("--compare",      action="store_true",
                        help="Run multiple short_pct configs and compare")
    parser.add_argument("--export-web",   action="store_true",
                        help="Export results as JSON for the web app")
    parser.add_argument("--strategy-id",  default="nifty_iron_condor",
                        help="Strategy id for web export")
    parser.add_argument("--strategy-name", default="NIFTY Iron Condor",
                        help="Display name for web export")
    args = parser.parse_args()

    db = DBManager()

    if args.compare:
        # Quick comparison across short_pct values
        configs = [
            (1.0, 100), (1.5, 150), (2.0, 200), (2.5, 200), (3.0, 200)
        ]
        rows = []
        for sp, wp in configs:
            s, df, _ = run_ic_backtest(
                db, args.from_date, args.to_date,
                short_pct=sp, wing_points=wp,
                sl_type=args.sl_type, sl_pct=args.sl_pct,
                slippage_pct=args.slippage_pct,
            )
            if s:
                ec = s["exit_counts"]
                rows.append([
                    f"±{sp}% / {wp}pt",
                    s["total_expiries"],
                    f"{s['win_rate_pct']}%",
                    f"₹{s['total_net_pnl']:,.0f}",
                    f"₹{s['avg_net_pnl']:,.0f}",
                    f"₹{s['max_drawdown']:,.0f}",
                    f"{s['sharpe_ratio']:.2f}",
                    f"₹{s['avg_credit']:.1f}",
                    ec.get("SQUARE_OFF", 0),
                    ec.get("SPOT_SL", 0) + ec.get("PREMIUM_SL", 0),
                ])
        print()
        print(tabulate(rows,
            headers=["Config", "Expiries", "Win%", "Total PnL", "Avg/expiry", "MaxDD", "Sharpe", "Avg credit", "Full profit", "SL exits"],
            tablefmt="fancy_grid"))
        return

    summary, df_trades, intraday_data = run_ic_backtest(
        db,
        from_date=args.from_date,
        to_date=args.to_date,
        short_pct=args.short_pct,
        wing_points=args.wing_points,
        entry_time=args.entry_time,
        exit_time=args.exit_time,
        sl_type=args.sl_type,
        sl_pct=args.sl_pct,
        slippage_pct=args.slippage_pct,
    )

    if summary is None:
        sys.exit(1)

    print()
    print(tabulate([
        ["Strategy",          summary["strategy"]],
        ["Period",            f"{args.from_date} → {args.to_date}"],
        ["Expiry days",       summary["total_expiries"]],
        ["Win rate",          f"{summary['win_rate_pct']}%"],
        ["Total net PnL",     f"₹{summary['total_net_pnl']:,.2f}"],
        ["Avg PnL / expiry",  f"₹{summary['avg_net_pnl']:,.2f}"],
        ["Max drawdown",      f"₹{summary['max_drawdown']:,.2f}"],
        ["Sharpe ratio",      summary["sharpe_ratio"]],
        ["Avg net credit",    f"₹{summary['avg_credit']:.2f} / share"],
        ["Exit breakdown",    str(summary["exit_counts"])],
    ], headers=["Metric", "Value"], tablefmt="fancy_grid"))

    # Trade book preview
    preview = df_trades[[
        "date", "spot_entry", "short_pe", "short_ce",
        "net_credit", "exit_reason", "exit_time", "net_pnl"
    ]].tail(20)
    print()
    print(tabulate(preview, headers="keys", tablefmt="grid", showindex=False))

    # Save CSV
    fname = f"backtest_ic_nifty_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out = DATA_DIR / fname
    df_trades.to_csv(out, index=False)
    logger.info(f"Trade book saved: {out}")

    # Web export
    if args.export_web:
        _export_ic_web(args, summary, df_trades, intraday_data)


def _export_ic_web(args, summary, df_raw, intraday_data):
    """Convert IC trade log to the schema expected by the Next.js web app and export."""
    import numpy as np

    # Build web-compatible trade records
    cum = 0.0
    peak = 0.0
    trades = []
    for _, t in df_raw.iterrows():
        cum  += t["net_pnl"]
        peak  = max(peak, cum)
        dd    = cum - peak

        # Net call spread = value of the call bull spread at that time
        ce_net_entry = round(float(t["s_ce_entry"]) - float(t["l_ce_entry"]), 2)
        ce_net_exit  = round(float(t["s_ce_exit"])  - float(t["l_ce_exit"]),  2)
        pe_net_entry = round(float(t["s_pe_entry"]) - float(t["l_pe_entry"]), 2)
        pe_net_exit  = round(float(t["s_pe_exit"])  - float(t["l_pe_exit"]),  2)

        lot = int(t["lot_size"])
        costs_half = round(float(t["costs"]) / 2, 2)

        trades.append({
            "date":           str(t["date"]),
            "underlying":     "NIFTY",
            "strike":         int(t["short_ce"]),       # proxy (required by schema)
            "ce_strike":      int(t["short_ce"]),
            "pe_strike":      int(t["short_pe"]),
            "long_ce":        int(t["long_ce"]),         # IC-specific
            "long_pe":        int(t["long_pe"]),         # IC-specific
            "lot_size":       lot,
            "spot_entry":     float(t["spot_entry"]),
            # CE side = net call bear spread premium
            "ce_entry":       ce_net_entry,
            "ce_exit":        ce_net_exit,
            "ce_exit_time":   str(t["exit_time"]),
            "ce_exit_reason": str(t["exit_reason"]),
            "ce_net_pnl":     round((ce_net_entry - ce_net_exit) * lot, 2),
            "ce_costs":       costs_half,
            # PE side = net put bear spread premium
            "pe_entry":       pe_net_entry,
            "pe_exit":        pe_net_exit,
            "pe_exit_time":   str(t["exit_time"]),
            "pe_exit_reason": str(t["exit_reason"]),
            "pe_net_pnl":     round((pe_net_entry - pe_net_exit) * lot, 2),
            "pe_costs":       costs_half,
            # IC summary fields
            "net_credit":     float(t["net_credit"]),
            "wing_pts":       int(t["wing_pts"]),
            "total_net_pnl":  float(t["net_pnl"]),
            "cum_pnl":        round(cum, 2),
            "peak":           round(peak, 2),
            "drawdown":       round(dd, 2),
        })

    web_summary = {
        "underlying":            "NIFTY",
        "total_expiry_days":     summary["total_expiries"],
        "winning_expiry_days":   int((df_raw["net_pnl"] > 0).sum()),
        "win_rate_pct":          summary["win_rate_pct"],
        "total_net_pnl":         summary["total_net_pnl"],
        "max_drawdown":          summary["max_drawdown"],
        "sharpe_ratio":          summary["sharpe_ratio"],
        "avg_net_pnl_per_expiry": summary["avg_net_pnl"],
    }

    params = {
        "underlying":    "NIFTY",
        "from_date":     args.from_date,
        "to_date":       args.to_date,
        "entry_time":    args.entry_time,
        "exit_time":     args.exit_time,
        "strategy_type": "iron_condor",
        "short_pct":     args.short_pct,
        "wing_points":   args.wing_points,
        "sl_type":       args.sl_type,
        "sl_pct":        args.sl_pct if args.sl_type == "premium" else None,
        "slippage_pct":  args.slippage_pct,
    }

    import pandas as pd
    df_web = pd.DataFrame(trades)
    export_strategy_result(
        strategy_id=args.strategy_id,
        name=args.strategy_name,
        description=(
            f"Sells a ±{args.short_pct}% OTM call spread and put spread on expiry day. "
            f"Wing width: {args.wing_points} pts. Stop: {args.sl_type}."
        ),
        underlying="NIFTY",
        params=params,
        summary=web_summary,
        df_trades=df_web,
        web_data_dir=WEB_DATA_DIR,
    )
    export_intraday_data(
        strategy_id=args.strategy_id,
        df_trades=df_web,
        intraday_data=intraday_data,
        web_data_dir=WEB_DATA_DIR,
    )
    logger.info(f"Web export complete for strategy '{args.strategy_id}'.")


if __name__ == "__main__":
    main()
