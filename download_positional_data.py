"""
Download 2nd-month NIFTY monthly option data for the positional strangle backtest.

For each Friday in the date range:
  1. Download ATM call (MONTH, expiry_code=2) → get IV + spot at 3pm
  2. Compute 10-delta CE and PE strikes via Black-Scholes
  3. Download those specific strike offsets

Usage:
    python3 download_positional_data.py --from-date 2022-01-01 --to-date 2026-07-25
"""

import argparse
import calendar
import math
import time
from datetime import date, timedelta

import pandas as pd

from config import logger, check_config
from src.data_downloader import DataDownloader
from src.db import DBManager
from src.dhan_client import DhanClientWrapper
from src.security_master import SecurityMaster

NIFTY_STRIKE_STEP = 50.0
# N^{-1}(0.90) — used to solve for 10-delta strike via Black-Scholes
_N_INV_90 = 1.2816


# ── helpers ──────────────────────────────────────────────────────────────────

def last_thursday_of_month(year: int, month: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    # weekday(): Mon=0 … Thu=3
    days_back = (d.weekday() - 3) % 7
    return d - timedelta(days=days_back)


def next_month_expiry(from_dt: date) -> date:
    """Last Thursday of the calendar month AFTER from_dt's month."""
    month = from_dt.month + 1
    year  = from_dt.year + (1 if month > 12 else 0)
    month = month if month <= 12 else 1
    return last_thursday_of_month(year, month)


def compute_10delta_strikes(spot: float, iv_pct: float, days_to_expiry: int):
    """
    Black-Scholes 10-delta strike approximation (zero rate, zero dividend).
    Returns (K_ce, K_pe) rounded to nearest NIFTY_STRIKE_STEP.
    """
    sigma = iv_pct / 100.0
    T = max(days_to_expiry, 1) / 365.0
    K_ce = spot * math.exp( _N_INV_90 * sigma * math.sqrt(T))
    K_pe = spot * math.exp(-_N_INV_90 * sigma * math.sqrt(T))
    K_ce = round(K_ce / NIFTY_STRIKE_STEP) * NIFTY_STRIKE_STEP
    K_pe = round(K_pe / NIFTY_STRIKE_STEP) * NIFTY_STRIKE_STEP
    return K_ce, K_pe


def strike_to_offset(strike: float, spot: float) -> str:
    atm = round(spot / NIFTY_STRIKE_STEP) * NIFTY_STRIKE_STEP
    n   = round((strike - atm) / NIFTY_STRIKE_STEP)
    if n == 0:   return "ATM"
    if n > 0:    return f"ATM+{n}"
    return f"ATM{n}"   # e.g. "ATM-8"


def all_fridays(from_date: str, to_date: str):
    return [d.strftime("%Y-%m-%d")
            for d in pd.date_range(from_date, to_date, freq="W-FRI")]


def price_at_3pm(df: pd.DataFrame, day: str):
    """Return (close, iv, spot) of the last candle at/before 15:00 on `day`."""
    if df.empty:
        return None
    mask = df['timestamp'].dt.date == pd.to_datetime(day).date()
    day_df = df[mask]
    if day_df.empty:
        return None
    pm3 = day_df[day_df['timestamp'].dt.hour < 15]
    if pm3.empty:
        pm3 = day_df
    row = pm3.iloc[-1]
    return float(row['close']), float(row.get('iv', 0)), float(row.get('spot', 0))


# ── per-Friday download ───────────────────────────────────────────────────────

def download_friday(downloader: DataDownloader, friday: str) -> bool:
    friday_dt = pd.to_datetime(friday).date()
    next_day  = (pd.to_datetime(friday) + timedelta(days=1)).strftime("%Y-%m-%d")
    expiry_dt = next_month_expiry(friday_dt)
    expiry_str = str(expiry_dt)
    days_to_exp = (expiry_dt - friday_dt).days

    # Phase 1: ATM CE to get IV + spot
    atm_df = downloader.download_monthly_option(
        underlying="NIFTY", expiry_date=expiry_str, expiry_code=2,
        strike_offset="ATM", option_type="CALL",
        from_date=friday, to_date=next_day,
    )
    time.sleep(0.15)

    result = price_at_3pm(atm_df, friday)
    if result is None:
        logger.warning(f"[{friday}] No ATM data — skipping.")
        return False

    _, iv_pct, spot = result
    if iv_pct <= 0 or spot <= 0:
        logger.warning(f"[{friday}] IV={iv_pct} spot={spot} invalid — skipping.")
        return False

    # Phase 2: compute 10Δ strikes
    K_ce, K_pe = compute_10delta_strikes(spot, iv_pct, days_to_exp)
    ce_off = strike_to_offset(K_ce, spot)
    pe_off = strike_to_offset(K_pe, spot)

    logger.info(
        f"[{friday}] spot={spot:.0f}  IV={iv_pct:.1f}%  T={days_to_exp}d  expiry={expiry_str}  "
        f"10Δ CE={K_ce:.0f}({ce_off})  PE={K_pe:.0f}({pe_off})"
    )

    # Phase 3: download 10Δ CE, ATM PE, 10Δ PE
    for offset, opt_type in [(ce_off, "CALL"), ("ATM", "PUT"), (pe_off, "PUT")]:
        if offset == "ATM" and opt_type == "CALL":
            continue   # already downloaded
        downloader.download_monthly_option(
            underlying="NIFTY", expiry_date=expiry_str, expiry_code=2,
            strike_offset=offset, option_type=opt_type,
            from_date=friday, to_date=next_day,
        )
        time.sleep(0.15)

    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-date", default="2022-01-01")
    parser.add_argument("--to-date",   default="2026-07-25")
    args = parser.parse_args()

    errors = check_config()
    if errors:
        for e in errors: logger.error(e)
        raise SystemExit(1)

    client     = DhanClientWrapper()
    sec_master = SecurityMaster(); sec_master.load()
    db         = DBManager()
    downloader = DataDownloader(client, sec_master, db)

    fridays = all_fridays(args.from_date, args.to_date)
    logger.info(f"Downloading 2nd-month NIFTY data for {len(fridays)} Fridays")

    ok = failed = 0
    for i, friday in enumerate(fridays, 1):
        logger.info(f"── {i}/{len(fridays)}: {friday} ──")
        if download_friday(downloader, friday):
            ok += 1
        else:
            failed += 1

    logger.info(f"Done — success={ok}  skipped/failed={failed}")


if __name__ == "__main__":
    main()
