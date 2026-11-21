"""
Local Parquet store for NIFTY / SENSEX weekly option data pulled from Dhan.

Source: Dhan v2 expired-options endpoint (POST /charts/rollingoption).
  - Minute bars only (no daily interval) -> we keep raw 1-min and build daily ourselves.
  - Strikes are ATM-relative: ATM-10 .. ATM+10 (verified for NIFTY and SENSEX weekly).
  - Up to 5 years back. toDate is INCLUSIVE and a call may span at most 2 consecutive dates
    (Dhan returns DH-905 for anything wider), so we fetch Mon-Tue, Wed-Thu, Fri windows.
  - expiryCode=1 is resolved per bar date (verified: a day fetched alone == the same day fetched
    as part of a 2-day window), and on expiry day it is the contract expiring that day.
  - Rate limits: ~5 req/s burst, and ~10k calls per rolling hour (then minutes of HTTP 429).

Layout (all under data/options/):
  raw_1min/<UNDERLYING>/WEEK1/<YYYY-MM>.parquet   one file per month, all offsets x CE/PE
  daily/<UNDERLYING>_WEEK1_daily.parquet           rebuilt from raw on every sync
  manifest.json                                    which months are fully downloaded

Raw columns:
  underlying, expiry_flag, expiry_code, strike_offset (int, -10..10), option_type (CE/PE),
  ts (IST, naive), open, high, low, close, volume, oi, iv, spot, strike (actual strike price)

Daily columns (one row per actual contract per trading day):
  underlying, expiry_date, strike, option_type, trade_date, open, high, low, close, volume,
  oi, iv, spot_close, n_bars, first_bar, last_bar, min_offset, max_offset, is_full_day

  is_full_day = the contract stayed inside that day's ATM window (+-10, or whatever Dhan served
  that day) for the whole session, so its daily OHLC is built from the complete day. When
  spot moves a lot, far strikes drift in/out of the window and only part of their day is
  captured -> is_full_day = False.

expiry_date is derived (Dhan's rolling endpoint does not return it) from the weekly-expiry
weekday regimes below plus the actual trading days in the data (holiday -> prior trading day).
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
import requests

from config import DATA_DIR, logger

IST = ZoneInfo("Asia/Kolkata")
STORE_DIR = Path(os.getenv("OPTIONS_STORE_DIR", "")) if os.getenv("OPTIONS_STORE_DIR") else DATA_DIR / "options"
RAW_DIR = STORE_DIR / "raw_1min"
DAILY_DIR = STORE_DIR / "daily"
MANIFEST_PATH = STORE_DIR / "manifest.json"

BASE_URL = "https://api.dhan.co/v2"
HISTORY_YEARS = 5
MAX_OFFSET = 10
# A month counts as "complete" only if fetched at least this many days after it ended,
# so late-published bars for the last days of the month aren't missed.
COMPLETE_GRACE_DAYS = 3

UNDERLYINGS = {
    "NIFTY":  {"security_id": "13", "segment": "NSE_FNO", "step": 50},
    "SENSEX": {"security_id": "51", "segment": "BSE_FNO", "step": 100},
}

# Weekly expiry weekday regimes (Mon=0 .. Sun=6). A regime applies to expiry dates on/after
# its start date until the next regime starts. Keep in sync with download_data.py.
EXPIRY_DAY_REGIMES = {
    "NIFTY": [("2016-01-01", 3), ("2025-09-01", 1)],                       # Thu -> Tue
    "SENSEX": [("2016-01-01", 4), ("2025-01-01", 1), ("2025-09-01", 3)],    # Fri -> Tue -> Thu
}
# Exchange-announced one-off expiry moves that are NOT simple holiday roll-backs:
# {"NIFTY": {"2024-xx-yy (nominal)": "2024-xx-zz (actual)"}}
EXPIRY_OVERRIDES: dict[str, dict[str, str]] = {"NIFTY": {}, "SENSEX": {}}


class AuthError(RuntimeError):
    pass


class ApiError(RuntimeError):
    pass


# ── HTTP ──────────────────────────────────────────────────────────────────────

class RateLimiter:
    """Shared pacing for all worker threads, adaptive to Dhan throttling.

    Dhan throttles in blocks (minutes of HTTP 429 after sustained load). On a 429 every
    thread pauses together and the rate is cut; successes slowly restore it to `rps`.
    """
    MIN_RPS = 0.5

    def __init__(self, rps: float):
        self.base_interval = 1.0 / rps
        self.interval = self.base_interval
        self.lock = threading.Lock()
        self.next_at = 0.0

    def penalize(self, pause_s: float):
        with self.lock:
            self.next_at = max(self.next_at, time.monotonic() + pause_s)
            self.interval = min(self.interval * 1.5, 1.0 / self.MIN_RPS)

    def reward(self):
        with self.lock:
            self.interval = max(self.base_interval, self.interval * 0.997)

    @property
    def current_rps(self) -> float:
        return 1.0 / self.interval

    def wait(self):
        with self.lock:
            now = time.monotonic()
            sleep_for = self.next_at - now
            self.next_at = max(now, self.next_at) + self.interval
        if sleep_for > 0:
            time.sleep(sleep_for)


class RollingOptionClient:
    def __init__(self, access_token: str, client_id: str, rps: float = 4.0):
        self.headers = {
            "access-token": access_token,
            "client-id": client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.limiter = RateLimiter(rps)
        self.session = requests.Session()
        self.calls = 0
        self.throttled = 0      # HTTP 429 responses
        self.net_errors = 0

    def fetch(self, underlying: str, offset: int, opt_type: str, from_date: date, to_date: date,
              expiry_flag: str = "WEEK", expiry_code: int = 1, interval: str = "1") -> pd.DataFrame:
        """One series (one ATM offset, one side) for [from_date, to_date] (inclusive, <= 2 dates)."""
        meta = UNDERLYINGS[underlying]
        strike = "ATM" if offset == 0 else f"ATM{offset:+d}"
        payload = {
            "exchangeSegment": meta["segment"],
            "interval": interval,
            "securityId": meta["security_id"],
            "instrument": "OPTIDX",
            "expiryFlag": expiry_flag,
            "expiryCode": expiry_code,
            "strike": strike,
            "drvOptionType": "CALL" if opt_type == "CE" else "PUT",
            "requiredData": ["open", "high", "low", "close", "volume", "oi", "iv", "spot", "strike"],
            "fromDate": from_date.isoformat(),
            "toDate": to_date.isoformat(),
        }
        body = self._post("/charts/rollingoption", payload)
        block = (body.get("data") or {}).get("ce" if opt_type == "CE" else "pe") or {}
        ts = block.get("timestamp") or []
        n = len(ts)
        if n == 0:
            return pd.DataFrame()

        def col(name, default):
            arr = block.get(name)
            return arr if isinstance(arr, list) and len(arr) == n else [default] * n

        df = pd.DataFrame({
            "ts": pd.to_datetime(ts, unit="s", utc=True).tz_convert(IST).tz_localize(None),
            "open": col("open", None), "high": col("high", None),
            "low": col("low", None), "close": col("close", None),
            "volume": col("volume", 0), "oi": col("oi", 0),
            "iv": col("iv", None), "spot": col("spot", None),
            "strike": col("strike", None),
        })
        df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
        # Dhan sometimes returns an empty strike array -> derive from spot.
        missing = df["strike"].isna() | (df["strike"] <= 0)
        if missing.any():
            step = meta["step"]
            spot = pd.to_numeric(df["spot"], errors="coerce")
            df.loc[missing, "strike"] = (spot[missing] / step).round() * step + offset * step
        df.insert(0, "option_type", opt_type)
        df.insert(0, "strike_offset", offset)
        df.insert(0, "expiry_code", expiry_code)
        df.insert(0, "expiry_flag", expiry_flag)
        df.insert(0, "underlying", underlying)
        return df

    def _post(self, endpoint: str, payload: dict, max_retries: int = 6, max_throttle_retries: int = 80) -> dict:
        backoff = 1.0
        throttle_hits = 0
        attempt = -1
        while True:
            attempt += 1
            if attempt > max_retries + max_throttle_retries:
                break
            self.limiter.wait()
            self.calls += 1
            try:
                r = self.session.post(BASE_URL + endpoint, json=payload, headers=self.headers, timeout=(10, 30))
            except requests.RequestException as e:
                self.net_errors += 1
                logger.warning(f"Network error ({e.__class__.__name__}), retry {attempt + 1}")
                if attempt == max_retries:
                    raise ApiError(f"network error: {e}") from e
                time.sleep(backoff); backoff *= 2
                continue

            text = r.text[:300]
            if r.status_code == 401 or "DH-901" in text or "DH-906" in text:
                raise AuthError(f"Dhan auth failed (token invalid/expired): {text}")
            if r.status_code == 429 or "DH-904" in text or "Too many" in text:
                self.throttled += 1
                throttle_hits += 1
                if throttle_hits > max_throttle_retries:
                    break
                attempt -= 1                 # 429s don't use up the network/5xx retry budget
                if backoff >= 8:
                    logger.warning(f"Throttled by Dhan (429 x{throttle_hits} on one call, "
                                   f"{self.throttled} total); all workers pausing {backoff:.0f}s, "
                                   f"rate now {self.limiter.current_rps:.1f}/s")
                self.limiter.penalize(backoff)   # pause everyone, not just this thread
                backoff = min(backoff * 2, 30)
                continue
            if r.status_code >= 500:
                if attempt == max_retries:
                    raise ApiError(f"HTTP {r.status_code}: {text}")
                time.sleep(backoff); backoff *= 2
                continue
            try:
                body = r.json()
            except ValueError:
                raise ApiError(f"HTTP {r.status_code} non-JSON: {text}")
            if r.status_code != 200:
                # "No data" style responses are a legitimate empty result, not a failure.
                if "DH-905" in text and "data" in text.lower():
                    return {}
                raise ApiError(f"HTTP {r.status_code}: {text}")
            self.limiter.reward()
            return body if isinstance(body, dict) else {}
        raise ApiError("rate-limit retries exhausted")


# ── manifest ──────────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {}


def save_manifest(m: dict):
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=1, sort_keys=True))
    os.replace(tmp, MANIFEST_PATH)


def month_key(underlying: str, month_start: date, expiry_flag="WEEK", expiry_code=1) -> str:
    return f"{underlying}/{expiry_flag}{expiry_code}/{month_start:%Y-%m}"


def raw_path(underlying: str, month_start: date, expiry_flag="WEEK", expiry_code=1) -> Path:
    return RAW_DIR / underlying / f"{expiry_flag}{expiry_code}" / f"{month_start:%Y-%m}.parquet"


# ── parquet I/O via DuckDB (no pyarrow dependency) ────────────────────────────

def write_parquet(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    con = duckdb.connect()
    con.register("df", df)
    con.execute(f"COPY (SELECT * FROM df) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)")
    con.close()
    os.replace(tmp, path)


# ── download ──────────────────────────────────────────────────────────────────

def today_ist() -> date:
    return datetime.now(IST).date()


def earliest_available(today: date) -> date:
    return today.replace(year=today.year - HISTORY_YEARS) + timedelta(days=1)


def last_fetchable_day() -> date:
    """Today only once the session is over (16:00 IST), so we never store a half day."""
    now = datetime.now(IST)
    return now.date() if now.hour >= 16 else now.date() - timedelta(days=1)


def windows(start: date, end: date):
    """Inclusive 2-date windows covering EVERY calendar day, weekends included.

    Weekends must be covered: exchanges hold special sessions on them (Diwali Muhurat on a
    Sunday, Union Budget on a Saturday/Sunday, DR drills). A window with no ATM data costs only
    the 2-3 probe calls (see download_month), so covering weekends is cheap.
    """
    d = start
    while d <= end:
        w_end = min(d + timedelta(days=1), end)
        yield d, w_end
        d = w_end + timedelta(days=1)


def month_starts(start: date, end: date):
    m = start.replace(day=1)
    while m <= end:
        yield m
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)


@dataclass
class MonthResult:
    key: str
    rows: int
    complete: bool
    error: str | None = None


def download_month(client: RollingOptionClient, underlying: str, month_start: date, today: date,
                   expiry_flag="WEEK", expiry_code=1, workers=4, refetch=False,
                   until: date | None = None) -> MonthResult:
    key = month_key(underlying, month_start, expiry_flag, expiry_code)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    path = raw_path(underlying, month_start, expiry_flag, expiry_code)
    start = max(month_start, earliest_available(today))
    month_end = next_month - timedelta(days=1)
    end = min(month_end, last_fetchable_day(), until or month_end)

    # Resume a partially downloaded month from its last stored day (re-fetching that day).
    complete = (today >= next_month + timedelta(days=COMPLETE_GRACE_DAYS - 1)
                and (until is None or until >= month_end))
    existing = None
    if path.exists() and not refetch:
        existing = duckdb.sql(f"SELECT * FROM read_parquet('{path}')").df()
        if not existing.empty:
            n_existing = len(existing)
            start = max(start, existing["ts"].max().date())
            if start > end:                      # already up to date
                return MonthResult(key, n_existing, complete)
            existing = existing[existing["ts"].dt.date < start]
    if start > end:
        return MonthResult(key, 0, complete)

    all_windows = list(windows(start, end))
    frames, errors, empty_jobs, windows_with_data = [], [], [], set()

    def run(jobs, label):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(client.fetch, underlying, off, side, ws, we,
                                expiry_flag, expiry_code): (off, side, ws, we) for off, side, ws, we in jobs}
            last_beat, done = time.time(), 0
            for f in as_completed(futs):
                done += 1
                if time.time() - last_beat > 60:
                    logger.info(f"[{underlying}] {month_start:%Y-%m} {label}: {done}/{len(jobs)} series-windows")
                    last_beat = time.time()
                try:
                    df = f.result()
                    if df.empty:
                        empty_jobs.append(futs[f])
                    else:
                        frames.append(df)
                        windows_with_data.add(futs[f][2])
                except AuthError:
                    for other in futs:
                        other.cancel()
                    raise
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{futs[f]}: {e}")

    # Phase 1: probe ATM CE/PE per window. ATM always trades if the contract exists, so a
    # window with no ATM data (holiday, pre-listing months like SENSEX before May-2023) is
    # skipped instead of spending 40 more calls on it. Empty probes are re-checked once.
    run([(0, side, ws, we) for ws, we in all_windows for side in ("CE", "PE")], "probe")
    dead = [(ws, we) for ws, we in all_windows if ws not in windows_with_data]
    if dead:
        run([(0, "CE", ws, we) for ws, we in dead], "re-probe")
    live = [(ws, we) for ws, we in all_windows if ws in windows_with_data]

    # Phase 2: every other offset, live windows only.
    series = [(off, side) for off in range(-MAX_OFFSET, MAX_OFFSET + 1) if off != 0 for side in ("CE", "PE")]
    run([(off, side, ws, we) for ws, we in live for off, side in series], "fetch")
    empty_jobs[:] = [j for j in empty_jobs if j[2] in windows_with_data]

    if errors:
        return MonthResult(key, 0, False, f"{len(errors)} series failed, e.g. {errors[0]}")

    # A series that came back empty for a window where other series have data is suspicious
    # (transient empty response) -> retry it once.
    suspects = [j for j in empty_jobs if j[2] in windows_with_data]
    if suspects:
        logger.warning(f"[{underlying}] {month_start:%Y-%m}: retrying {len(suspects)} empty series")
        for off, side, ws, we in suspects:
            df = client.fetch(underlying, off, side, ws, we, expiry_flag, expiry_code)
            if not df.empty:
                frames.append(df)

    if existing is not None and not existing.empty:
        frames.append(existing)
    rows = 0
    if frames:
        df = pd.concat(frames, ignore_index=True)
        df = df.drop_duplicates(["strike_offset", "option_type", "ts"]).sort_values(
            ["ts", "option_type", "strike_offset"]).reset_index(drop=True)
        write_parquet(df, path)
        rows = len(df)
    return MonthResult(key, rows, complete)


def sync(client: RollingOptionClient, underlyings, from_date: date | None, to_date: date | None,
         refetch=False, workers=4, expiry_flag="WEEK", expiry_code=1):
    today = today_ist()
    from_date = max(from_date or earliest_available(today), earliest_available(today).replace(day=1))
    to_date = min(to_date or today, today)
    manifest = load_manifest()
    summary = []
    for und in underlyings:
        months = list(month_starts(from_date, to_date))
        todo = [m for m in months
                if refetch or not manifest.get(month_key(und, m, expiry_flag, expiry_code), {}).get("complete")]
        logger.info(f"[{und}] {len(months)} months in range, {len(todo)} to download")
        for i, m in enumerate(todo, 1):
            t0 = time.time()
            res = download_month(client, und, m, today, expiry_flag, expiry_code, workers, refetch,
                                 until=to_date)
            if res.error:
                logger.error(f"[{und}] {m:%Y-%m} ({i}/{len(todo)}) FAILED: {res.error}")
            else:
                manifest[res.key] = {"complete": res.complete, "rows": res.rows,
                                     "fetched_at": datetime.now(IST).isoformat(timespec="seconds")}
                save_manifest(manifest)
                logger.info(f"[{und}] {m:%Y-%m} ({i}/{len(todo)}) rows={res.rows:,} "
                            f"{'complete' if res.complete else 'partial (will refetch)'} "
                            f"{time.time() - t0:.0f}s, api calls so far={client.calls} "
                            f"(429s={client.throttled}, net errors={client.net_errors})")
            summary.append(res)
    return summary


def fill_days(client: RollingOptionClient, underlying: str, days: list[date],
              expiry_flag="WEEK", expiry_code=1, workers=4) -> int:
    """Fetch specific dates (all 42 series) and merge them into their month files.
    For back-filling sessions a past run missed, without re-downloading whole months."""
    added = 0
    for d in sorted(days):
        series = [(off, side) for off in range(-MAX_OFFSET, MAX_OFFSET + 1) for side in ("CE", "PE")]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            frames = [f.result() for f in [pool.submit(client.fetch, underlying, off, side, d, d,
                                                       expiry_flag, expiry_code) for off, side in series]]
        frames = [f for f in frames if not f.empty]
        if not frames:
            logger.info(f"[{underlying}] {d}: no data at Dhan")
            continue
        new = pd.concat(frames, ignore_index=True)
        path = raw_path(underlying, d.replace(day=1), expiry_flag, expiry_code)
        if path.exists():
            old = duckdb.sql(f"SELECT * FROM read_parquet('{path}')").df()
            old = old[old["ts"].dt.date != d]
            new = pd.concat([old, new], ignore_index=True)
        new = new.drop_duplicates(["strike_offset", "option_type", "ts"]).sort_values(
            ["ts", "option_type", "strike_offset"]).reset_index(drop=True)
        write_parquet(new, path)
        n = sum(len(f) for f in frames)
        added += n
        logger.info(f"[{underlying}] {d}: filled {n:,} bars")
    return added


# ── expiry calendar ───────────────────────────────────────────────────────────

def derive_weekly_expiries(underlying: str, trading_days: list[date], horizon: date) -> dict[date, date]:
    """Map each trading day -> nearest weekly expiry (on/after that day).

    Trading days after the last day in the data are assumed to be all weekdays (unknown
    future holidays), so the current week's expiry is provisional until its data lands.
    """
    regimes = [(date.fromisoformat(s), dow) for s, dow in EXPIRY_DAY_REGIMES[underlying]]
    overrides = {date.fromisoformat(k): date.fromisoformat(v)
                 for k, v in EXPIRY_OVERRIDES.get(underlying, {}).items()}
    tds = sorted(set(trading_days))
    last = tds[-1]
    d = last + timedelta(days=1)
    while d <= horizon:
        if d.weekday() < 5:
            tds.append(d)
        d += timedelta(days=1)
    td_set = set(tds)

    def regime_dow(day: date):
        cur = None
        for start, dow in regimes:
            if day >= start:
                cur = dow
        return cur

    def nominal_expiry(day: date) -> date:
        # First date on/after `day` whose weekday is the expiry weekday of the regime in force
        # on that date (handles regime switches, e.g. SENSEX Tue 26-Aug-25 -> Thu 4-Sep-25).
        for k in range(15):
            cand = day + timedelta(days=k)
            if cand.weekday() == regime_dow(cand):
                return cand
        raise ValueError(f"no expiry found for {underlying} {day}")

    out = {}
    for day in trading_days:
        nom = nominal_expiry(day)
        nom = overrides.get(nom, nom)
        actual = nom
        while actual not in td_set and actual > day:   # holiday -> previous trading day
            actual -= timedelta(days=1)
        out[day] = actual
    return out


# ── daily build ───────────────────────────────────────────────────────────────

def build_daily(underlying: str, expiry_flag="WEEK", expiry_code=1) -> Path | None:
    src = RAW_DIR / underlying / f"{expiry_flag}{expiry_code}"
    files = sorted(src.glob("*.parquet"))
    if not files:
        logger.warning(f"[{underlying}] no raw files, skipping daily build")
        return None
    step = UNDERLYINGS[underlying]["step"]
    con = duckdb.connect()
    con.execute(f"CREATE VIEW raw AS SELECT * FROM read_parquet('{src}/*.parquet')")
    tdays = [r[0] for r in con.execute(
        "SELECT DISTINCT CAST(ts AS DATE) FROM raw ORDER BY 1").fetchall()]
    exp_map = derive_weekly_expiries(underlying, tdays, tdays[-1] + timedelta(days=14))
    con.register("exp_map", pd.DataFrame({"trade_date": list(exp_map.keys()),
                                          "expiry_date": list(exp_map.values())}))
    out = DAILY_DIR / f"{underlying}_{expiry_flag}{expiry_code}_daily.parquet"
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    con.execute(f"""
        COPY (
        WITH b AS (
            SELECT *, CAST(ts AS DATE) AS trade_date,
                   strike - strike_offset * {step} AS atm
            FROM raw
        ),
        day_atm AS (
            SELECT trade_date, MIN(atm) AS min_atm, MAX(atm) AS max_atm,
                   MAX(ABS(strike_offset)) AS win          -- offsets Dhan actually served that day
            FROM b GROUP BY trade_date
        ),
        agg AS (
            SELECT underlying, trade_date, strike, option_type,
                   arg_min(open, ts) AS open, MAX(high) AS high, MIN(low) AS low,
                   arg_max(close, ts) AS close, SUM(volume) AS volume,
                   arg_max(oi, ts) AS oi, arg_max(iv, ts) AS iv, arg_max(spot, ts) AS spot_close,
                   COUNT(*) AS n_bars, MIN(ts) AS first_bar, MAX(ts) AS last_bar,
                   MIN(strike_offset) AS min_offset, MAX(strike_offset) AS max_offset
            FROM b GROUP BY ALL
        )
        SELECT a.underlying, e.expiry_date, a.strike, a.option_type, a.trade_date,
               a.open, a.high, a.low, a.close, a.volume, a.oi, a.iv, a.spot_close,
               a.n_bars, a.first_bar, a.last_bar, a.min_offset, a.max_offset,
               (a.strike - d.max_atm >= -d.win * {step}
                AND a.strike - d.min_atm <= d.win * {step}) AS is_full_day
        FROM agg a
        JOIN day_atm d USING (trade_date)
        JOIN exp_map e USING (trade_date)
        ORDER BY a.trade_date, a.option_type, a.strike
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)
    """)
    con.close()
    os.replace(tmp, out)
    return out


# ── read helpers for strategies ───────────────────────────────────────────────

def load_daily(underlying: str, full_day_only=False, expiry_flag="WEEK", expiry_code=1) -> pd.DataFrame:
    path = DAILY_DIR / f"{underlying}_{expiry_flag}{expiry_code}_daily.parquet"
    where = "WHERE is_full_day" if full_day_only else ""
    return duckdb.sql(f"SELECT * FROM read_parquet('{path}') {where}").df()


def load_raw(underlying: str, from_date: str | None = None, to_date: str | None = None,
             expiry_flag="WEEK", expiry_code=1) -> pd.DataFrame:
    src = RAW_DIR / underlying / f"{expiry_flag}{expiry_code}"
    conds = []
    if from_date:
        conds.append(f"ts >= DATE '{from_date}'")
    if to_date:
        conds.append(f"ts < DATE '{to_date}' + INTERVAL 1 DAY")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    return duckdb.sql(f"SELECT * FROM read_parquet('{src}/*.parquet') {where} ORDER BY ts").df()


def status() -> pd.DataFrame:
    rows = []
    for und in UNDERLYINGS:
        src = RAW_DIR / und / "WEEK1"
        if not any(src.glob("*.parquet")):
            continue
        r = duckdb.sql(f"""SELECT MIN(ts), MAX(ts), COUNT(*), COUNT(DISTINCT CAST(ts AS DATE))
                           FROM read_parquet('{src}/*.parquet')""").fetchone()
        size = sum(p.stat().st_size for p in src.glob("*.parquet")) / 1e6
        rows.append({"underlying": und, "first_bar": r[0], "last_bar": r[1], "rows_1min": r[2],
                     "trading_days": r[3], "raw_MB": round(size, 1)})
    return pd.DataFrame(rows)
