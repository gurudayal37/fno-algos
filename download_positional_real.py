"""
Download REAL 10-delta 2nd-month NIFTY monthly option prices
using actual security IDs from the scrip master.

Works only for expiries still listed in the current scrip master
(typically the 3 nearest monthly contracts). Covers ~last 2-3 months.

NIFTY switched from Thursday → Tuesday weekly expiry from 2025-09-01.
Monthly = last Tuesday of each calendar month in the current regime.

Usage:
    python3 download_positional_real.py --from-date 2026-05-01 --to-date 2026-07-25
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
_N_INV_90 = 1.2816   # N⁻¹(0.90) for 10-delta


# ── expiry helpers ────────────────────────────────────────────────────────────

def last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Last occurrence of `weekday` (Mon=0…Sun=6) in a given month."""
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def nifty_monthly_expiry(for_date: date) -> date:
    """
    2nd-month NIFTY monthly expiry from for_date's perspective:
    = last Tuesday of the NEXT calendar month.
    (NIFTY switched to Tuesday expiry from 2025-09-01.)
    """
    month = for_date.month + 1
    year  = for_date.year + (1 if month > 12 else 0)
    month = month if month <= 12 else 1
    return last_weekday_of_month(year, month, 1)   # 1 = Tuesday


# ── scrip master helpers ──────────────────────────────────────────────────────

def load_nifty_options(sec_master: SecurityMaster) -> pd.DataFrame:
    df = sec_master.df
    return df[
        (df['UNDERLYING_SYMBOL'] == 'NIFTY') &
        (df['SEGMENT'] == 'D') &
        (df['OPTION_TYPE'].isin(['CE', 'PE']))
    ].copy()


def find_security_id(opts_df: pd.DataFrame, expiry_dt: date, strike: float, opt_type: str):
    """Find security ID and lot size for a specific NIFTY option contract."""
    opts_df = opts_df.copy()
    opts_df['expiry_date'] = pd.to_datetime(opts_df['SM_EXPIRY_DATE']).dt.date

    mask = (
        (opts_df['expiry_date'] == expiry_dt) &
        (opts_df['STRIKE_PRICE'].astype(float) == float(strike)) &
        (opts_df['OPTION_TYPE'] == opt_type.upper())
    )
    match = opts_df[mask]
    if match.empty:
        return None, None
    row = match.iloc[0]
    return str(row['SECURITY_ID']), int(row['LOT_SIZE'])


def nearest_available_strike(opts_df: pd.DataFrame, expiry_dt: date, target: float, opt_type: str) -> float:
    """Round target to the nearest strike that's actually listed for this expiry."""
    opts_df = opts_df.copy()
    opts_df['expiry_date'] = pd.to_datetime(opts_df['SM_EXPIRY_DATE']).dt.date
    avail = opts_df[
        (opts_df['expiry_date'] == expiry_dt) &
        (opts_df['OPTION_TYPE'] == opt_type.upper())
    ]['STRIKE_PRICE'].astype(float)
    if avail.empty:
        return target
    return float(avail.iloc[(avail - target).abs().argsort()].iloc[0])


# ── price helpers ─────────────────────────────────────────────────────────────

def compute_10delta_strikes(spot: float, iv_pct: float, days_to_expiry: int):
    sigma = iv_pct / 100.0
    T     = max(days_to_expiry, 1) / 365.0
    K_ce  = round(spot * math.exp( _N_INV_90 * sigma * math.sqrt(T)) / NIFTY_STRIKE_STEP) * NIFTY_STRIKE_STEP
    K_pe  = round(spot * math.exp(-_N_INV_90 * sigma * math.sqrt(T)) / NIFTY_STRIKE_STEP) * NIFTY_STRIKE_STEP
    return K_ce, K_pe


def get_spot_at_3pm(conn, day: date):
    df = conn.execute("""
        SELECT close FROM spot_candles
        WHERE security_id='13' AND CAST(timestamp AS DATE)=?
          AND HOUR(timestamp) < 15
        ORDER BY timestamp DESC LIMIT 1
    """, [day]).df()
    return float(df.iloc[0]['close']) if not df.empty else None


def get_atm_iv_at_3pm(conn, day: date, expiry_dt: date):
    # Filter expiry_date > day to exclude 0DTE weekly data; don't filter exact expiry
    # because ATM data was downloaded with a Thursday-based expiry label.
    df = conn.execute("""
        SELECT iv FROM option_candles
        WHERE underlying='NIFTY'
          AND option_type='CE'
          AND CAST(timestamp AS DATE) = ?
          AND expiry_date > ?
          AND HOUR(timestamp) < 15
          AND iv > 0
        ORDER BY timestamp DESC LIMIT 1
    """, [day, day]).df()
    if df.empty:
        return None
    return float(df.iloc[0]['iv'])


# ── download and save ─────────────────────────────────────────────────────────

def download_and_save(client: DhanClientWrapper, db: DBManager,
                      sec_id: str, day: date,
                      expiry_dt: date, strike: float, opt_type: str, lot_size: int):
    next_day = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    day_str  = str(day)

    resp = client.get_historical_intraday(
        security_id=sec_id,
        exchange_segment="NSE_FNO",
        instrument_type="OPTIDX",
        from_date=day_str,
        to_date=next_day,
        interval="1",
    )

    data = resp.get("data", resp) if resp else {}
    if not data or "open" not in data or not data["open"]:
        logger.warning(f"  No data for sec_id={sec_id} strike={strike} {opt_type} on {day}")
        return 0

    n = len(data["open"])
    expiry_str = pd.Timestamp(expiry_dt).strftime("%d%b%y").upper()
    trading_symbol = f"NIFTY{expiry_str}{int(strike)}{opt_type}"

    df = pd.DataFrame({
        "security_id":    [sec_id] * n,
        "trading_symbol": [trading_symbol] * n,
        "underlying":     ["NIFTY"] * n,
        "expiry_date":    [pd.Timestamp(expiry_dt)] * n,
        "strike":         [float(strike)] * n,
        "option_type":    [opt_type] * n,
        "timestamp":      pd.to_datetime(data["timestamp"], unit="s"),
        "open":           data["open"],
        "high":           data["high"],
        "low":            data["low"],
        "close":          data["close"],
        "volume":         data.get("volume", [0] * n),
        "open_interest":  data.get("oi", [0] * n),
        "iv":             data.get("iv", [0.0] * n),
    })

    db.save_option_candles(df)
    logger.info(f"  Saved {n} candles for {trading_symbol} on {day}")
    return n


# ── per-Friday ────────────────────────────────────────────────────────────────

def process_friday(client, db, opts_df, friday: date) -> bool:
    conn       = db.connect()
    expiry_dt  = nifty_monthly_expiry(friday)
    days_to_exp = (expiry_dt - friday).days

    # Check expiry is in scrip master
    opts_df_copy = opts_df.copy()
    opts_df_copy['expiry_date'] = pd.to_datetime(opts_df_copy['SM_EXPIRY_DATE']).dt.date
    if expiry_dt not in opts_df_copy['expiry_date'].values:
        logger.warning(f"[{friday}] Expiry {expiry_dt} not in scrip master — skipping.")
        return False

    spot   = get_spot_at_3pm(conn, friday)
    iv_pct = get_atm_iv_at_3pm(conn, friday, expiry_dt)

    if spot is None or iv_pct is None or iv_pct <= 0:
        logger.warning(f"[{friday}] Missing spot={spot} or IV={iv_pct} — skipping.")
        return False

    K_ce_raw, K_pe_raw = compute_10delta_strikes(spot, iv_pct, days_to_exp)
    K_ce = nearest_available_strike(opts_df, expiry_dt, K_ce_raw, 'CE')
    K_pe = nearest_available_strike(opts_df, expiry_dt, K_pe_raw, 'PE')

    sec_ce, lot_ce = find_security_id(opts_df, expiry_dt, K_ce, 'CE')
    sec_pe, lot_pe = find_security_id(opts_df, expiry_dt, K_pe, 'PE')

    if sec_ce is None or sec_pe is None:
        logger.warning(f"[{friday}] Security ID not found CE={K_ce}→{sec_ce}  PE={K_pe}→{sec_pe}")
        return False

    lot_size = lot_ce or lot_pe or 75
    logger.info(
        f"[{friday}] spot={spot:.0f}  IV={iv_pct:.1f}%  expiry={expiry_dt}  "
        f"10Δ CE={K_ce:.0f}(sid={sec_ce})  PE={K_pe:.0f}(sid={sec_pe})  lot={lot_size}"
    )

    n_ce = download_and_save(client, db, sec_ce, friday, expiry_dt, K_ce, 'CE', lot_size)
    time.sleep(0.2)
    n_pe = download_and_save(client, db, sec_pe, friday, expiry_dt, K_pe, 'PE', lot_size)
    time.sleep(0.2)

    return n_ce > 0 and n_pe > 0


# ── exit-price download ───────────────────────────────────────────────────────

def download_exit_prices(client: DhanClientWrapper, db: DBManager, entry_friday: date, exit_friday: date):
    """
    For whatever was downloaded on entry_friday, also fetch prices on exit_friday
    so the backtester can compute weekly P&L (close position = buy back at exit price).
    """
    conn = db.connect()
    rows = conn.execute("""
        SELECT DISTINCT security_id, strike, option_type, expiry_date
        FROM option_candles
        WHERE underlying='NIFTY'
          AND CAST(timestamp AS DATE) = ?
          AND expiry_date > ?
    """, [entry_friday, entry_friday]).df()

    if rows.empty:
        return

    logger.info(f"  Downloading exit prices ({exit_friday}) for {len(rows)} contracts from entry {entry_friday}")
    for _, row in rows.iterrows():
        expiry_dt = pd.Timestamp(row['expiry_date']).date()
        n = download_and_save(
            client, db,
            str(row['security_id']), exit_friday,
            expiry_dt, float(row['strike']), str(row['option_type']), lot_size=65,
        )
        time.sleep(0.15)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-date", default="2026-05-01")
    parser.add_argument("--to-date",   default="2026-07-25")
    args = parser.parse_args()

    errors = check_config()
    if errors:
        for e in errors: logger.error(e)
        raise SystemExit(1)

    client     = DhanClientWrapper()
    sec_master = SecurityMaster(); sec_master.load()
    db         = DBManager()
    opts_df    = load_nifty_options(sec_master)

    fridays = [
        d.date() for d in pd.date_range(args.from_date, args.to_date, freq="W-FRI")
    ]
    logger.info(f"Downloading real 10Δ monthly data for {len(fridays)} Fridays")

    # Pass 1: download entry strike prices for each Friday
    ok = failed = 0
    for i, friday in enumerate(fridays, 1):
        logger.info(f"── {i}/{len(fridays)}: {friday} ──")
        if process_friday(client, db, opts_df, friday):
            ok += 1
        else:
            failed += 1

    # Pass 2: for each consecutive pair, also download the entry strikes on exit date
    logger.info("Pass 2: downloading exit prices (prior week's strikes on next Friday)")
    for i in range(len(fridays) - 1):
        entry_fri = fridays[i]
        exit_fri  = fridays[i + 1]
        download_exit_prices(client, db, entry_fri, exit_fri)

    logger.info(f"Done — entry downloads: success={ok}  skipped={failed}")


if __name__ == "__main__":
    main()
