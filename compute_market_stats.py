#!/usr/bin/env python3
"""
Compute NIFTY and SENSEX return distribution statistics for the /stats page.
Run after downloading new spot data to regenerate web/data/market_stats.json.

  python3 compute_market_stats.py
"""
import json
import math
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path

IST_OFFSET = pd.Timedelta(hours=5, minutes=30)
WEB_DATA_DIR = Path("web/data")

SECURITY_IDS = {"NIFTY": "13", "SENSEX": "51"}

DAILY_THRESHOLDS   = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
WEEKLY_THRESHOLDS  = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
MONTHLY_THRESHOLDS = [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]


def _norm_pdf(x: float, mu: float, sigma: float) -> float:
    return (1.0 / (sigma * math.sqrt(2 * math.pi))) * math.exp(-0.5 * ((x - mu) / sigma) ** 2)


def _build_histogram(returns, bin_start, bin_end, bin_step, mean, std):
    """Return (histogram list, normal_curve list) with one entry per bin."""
    n = len(returns)

    # Build regular bin edges
    edges = []
    b = bin_start
    while b < bin_end + 1e-9:
        edges.append(round(b, 8))
        b = round(b + bin_step, 8)

    histogram = []
    normal_curve = []

    def _append(bin_label, center, count):
        histogram.append({
            "bin_label": bin_label,
            "center": round(center, 4),
            "count": count,
            "pct": round(count / n * 100, 2),
        })
        normal_curve.append(round(_norm_pdf(center, mean, std) * bin_step * n, 2))

    # Underflow
    under = sum(1 for r in returns if r < bin_start)
    _append(f"<{bin_start:+.1f}%", bin_start - bin_step, under)

    # Regular bins
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        cnt = sum(1 for r in returns if lo <= r < hi)
        _append(f"{lo:+.2f}%", (lo + hi) / 2, cnt)

    # Overflow
    over = sum(1 for r in returns if r >= bin_end)
    _append(f">{bin_end:+.1f}%", bin_end + bin_step, over)

    return histogram, normal_curve


def _compute_stats(returns_list, bin_start, bin_end, bin_step, thresholds):
    returns = [r for r in returns_list if not math.isnan(r)]
    n = len(returns)
    arr = np.array(returns, dtype=float)

    mean = float(arr.mean())
    std  = float(arr.std(ddof=1))
    s    = pd.Series(arr)

    histogram, normal_curve = _build_histogram(returns, bin_start, bin_end, bin_step, mean, std)

    sorted_r = sorted(returns)
    def pct(p):
        idx = p / 100 * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return sorted_r[lo] + (sorted_r[hi] - sorted_r[lo]) * (idx - lo)

    prob_table = []
    for t in thresholds:
        prob_table.append({
            "threshold": t,
            "p_abs":  round(float(np.mean(np.abs(arr) > t) * 100), 1),
            "p_up":   round(float(np.mean(arr > t) * 100), 1),
            "p_down": round(float(np.mean(arr < -t) * 100), 1),
        })

    return {
        "count":        n,
        "mean":         round(mean, 4),
        "std":          round(std, 4),
        "skew":         round(float(s.skew()), 3),
        "kurt":         round(float(s.kurt()), 3),   # excess kurtosis (pandas subtracts 3)
        "positive_pct": round(float(np.mean(arr > 0) * 100), 1),
        "p5":           round(pct(5), 3),
        "p25":          round(pct(25), 3),
        "p50":          round(pct(50), 3),
        "p75":          round(pct(75), 3),
        "p95":          round(pct(95), 3),
        "histogram":    histogram,
        "normal_curve": normal_curve,
        "prob_table":   prob_table,
    }


def _period_returns(period_df):
    """Given a df with open/close per period (sorted), return (cc_returns, oc_returns)."""
    cc = (period_df["close"] / period_df["close"].shift(1) - 1) * 100
    oc = (period_df["close"] / period_df["open"] - 1) * 100
    return cc.dropna().tolist(), oc.dropna().tolist()


def main():
    conn = duckdb.connect("data/options_backtest.duckdb")
    result = {}

    for underlying, sid in SECURITY_IDS.items():
        df = conn.execute(f"""
            SELECT timestamp, open, high, low, close
            FROM spot_candles
            WHERE security_id = '{sid}'
            ORDER BY timestamp
        """).df()

        df["ist"]  = df["timestamp"] + IST_OFFSET
        df["date"] = df["ist"].dt.date

        # Daily OHLC (first open / max high / min low / last close per trading day)
        daily = (df.groupby("date")
                   .agg(open=("open", "first"), high=("high", "max"),
                        low=("low", "min"), close=("close", "last"))
                   .reset_index())
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.sort_values("date").reset_index(drop=True)
        daily_cc, daily_oc = _period_returns(daily)

        # Weekly (open = first trading day's open, close = last trading day's close of ISO week)
        daily["iso_week"] = daily["date"].dt.to_period("W")
        weekly = (daily.groupby("iso_week")
                        .agg(open=("open", "first"), close=("close", "last"))
                        .reset_index())
        weekly_cc, weekly_oc = _period_returns(weekly)

        # Monthly (open = first trading day's open, close = last trading day's close of month)
        daily["month"] = daily["date"].dt.to_period("M")
        monthly = (daily.groupby("month")
                         .agg(open=("open", "first"), close=("close", "last"))
                         .reset_index())
        monthly_cc, monthly_oc = _period_returns(monthly)

        # Date range label for display
        date_from = daily["date"].min().strftime("%b %Y")
        date_to   = daily["date"].max().strftime("%b %Y")

        # Latest trading day snapshot
        last = daily.iloc[-1]
        prev_close = float(daily.iloc[-2]["close"]) if len(daily) > 1 else None
        latest = {
            "date":        last["date"].strftime("%Y-%m-%d"),
            "open":        round(float(last["open"]), 2),
            "high":        round(float(last["high"]), 2),
            "low":         round(float(last["low"]), 2),
            "close":       round(float(last["close"]), 2),
            "prev_close":  round(prev_close, 2) if prev_close is not None else None,
            "cc_return":   round((last["close"] / prev_close - 1) * 100, 3) if prev_close else None,
            "oc_return":   round((last["close"] / last["open"] - 1) * 100, 3),
        }

        result[underlying] = {
            "date_range": f"{date_from} – {date_to}",
            "latest": latest,
            "daily": {
                "cc": _compute_stats(daily_cc,   -4.0, 4.0,   0.25, DAILY_THRESHOLDS),
                "oc": _compute_stats(daily_oc,   -4.0, 4.0,   0.25, DAILY_THRESHOLDS),
            },
            "weekly": {
                "cc": _compute_stats(weekly_cc,  -8.0, 8.0,   0.5,  WEEKLY_THRESHOLDS),
                "oc": _compute_stats(weekly_oc,  -8.0, 8.0,   0.5,  WEEKLY_THRESHOLDS),
            },
            "monthly": {
                "cc": _compute_stats(monthly_cc, -15.0, 15.0, 2.0,  MONTHLY_THRESHOLDS),
                "oc": _compute_stats(monthly_oc, -15.0, 15.0, 2.0,  MONTHLY_THRESHOLDS),
            },
        }
        print(f"{underlying}: daily n={len(daily_cc)}, weekly n={len(weekly_cc)}, monthly n={len(monthly_cc)}, "
              f"latest={latest['date']} oc={latest['oc_return']}%")

    conn.close()

    out_path = WEB_DATA_DIR / "market_stats.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Written → {out_path}")


if __name__ == "__main__":
    main()
