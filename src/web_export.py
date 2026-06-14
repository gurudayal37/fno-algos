import json
import numpy as np
import pandas as pd
from pathlib import Path

from config import logger


def _json_default(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def export_strategy_result(strategy_id, name, description, underlying, params, summary, df_trades, web_data_dir):
    """
    Writes <strategy_id>.json (full detail incl. per-expiry trades) and upserts
    index.json (summary only) inside web_data_dir.
    """
    web_data_dir = Path(web_data_dir)
    web_data_dir.mkdir(parents=True, exist_ok=True)

    # Convert dates/timestamps to ISO strings and NaN to null for clean JSON
    df = df_trades.astype(object).where(pd.notnull(df_trades), None)
    for col in df.columns:
        df[col] = df[col].apply(lambda v: v.isoformat() if hasattr(v, "isoformat") else v)

    trades = df.to_dict(orient="records")

    detail = {
        "id": strategy_id,
        "name": name,
        "description": description,
        "underlying": underlying.upper(),
        "params": params,
        "summary": summary,
        "trades": trades,
    }

    detail_path = web_data_dir / f"{strategy_id}.json"
    with open(detail_path, "w") as f:
        json.dump(detail, f, indent=2, default=_json_default)
    logger.info(f"Exported strategy detail to {detail_path}")

    # Upsert into index.json
    index_path = web_data_dir / "index.json"
    if index_path.exists():
        with open(index_path) as f:
            index = json.load(f)
    else:
        index = []

    index = [s for s in index if s["id"] != strategy_id]
    index.append({
        "id": strategy_id,
        "name": name,
        "description": description,
        "underlying": underlying.upper(),
        "params": params,
        "summary": summary,
    })
    index.sort(key=lambda s: s["id"])

    with open(index_path, "w") as f:
        json.dump(index, f, indent=2, default=_json_default)
    logger.info(f"Updated strategy index at {index_path}")


def export_intraday_data(strategy_id, df_trades, intraday_data, web_data_dir, last_n=10):
    """
    Writes per-expiry intraday timeseries (spot/CE/PE/PnL) for the most recent
    `last_n` expiry dates into <web_data_dir>/<strategy_id>/expiries/<date>.json,
    plus an expiries/index.json listing the available dates.
    """
    if df_trades.empty:
        return

    expiries_dir = Path(web_data_dir) / strategy_id / "expiries"
    expiries_dir.mkdir(parents=True, exist_ok=True)

    recent_trades = df_trades.sort_values("date").tail(last_n)

    available_dates = []
    for _, trade in recent_trades.iterrows():
        date_str = trade["date"].isoformat() if hasattr(trade["date"], "isoformat") else str(trade["date"])
        candles = intraday_data.get(date_str) or intraday_data.get(str(trade["date"]))
        if not candles:
            continue

        detail = {
            "date": date_str,
            "strike": trade["strike"],
            "ce_entry": trade["ce_entry"],
            **({"ce_strike": trade["ce_strike"], "pe_strike": trade["pe_strike"]} if "ce_strike" in trade else {}),
            "ce_exit": trade["ce_exit"],
            "ce_exit_time": trade["ce_exit_time"],
            "ce_exit_reason": trade["ce_exit_reason"],
            "pe_entry": trade["pe_entry"],
            "pe_exit": trade["pe_exit"],
            "pe_exit_time": trade["pe_exit_time"],
            "pe_exit_reason": trade["pe_exit_reason"],
            "total_net_pnl": trade["total_net_pnl"],
            "candles": candles,
        }

        with open(expiries_dir / f"{date_str}.json", "w") as f:
            json.dump(detail, f, indent=2, default=_json_default)

        available_dates.append(date_str)

    available_dates.sort()
    with open(expiries_dir / "index.json", "w") as f:
        json.dump(available_dates, f, indent=2)

    logger.info(f"Exported intraday data for {len(available_dates)} expiry days to {expiries_dir}")
