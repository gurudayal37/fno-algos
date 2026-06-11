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
