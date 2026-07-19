#!/usr/bin/env bash
# Called by .github/workflows/update-strategies.yml after every market close.
#
# Flow:
#   1. Download the last 10 days of NIFTY + SENSEX options data into DuckDB.
#   2. Ask DuckDB for the latest expiry date that exists for each underlying.
#   3. Compare against the latest trade date already in the web strategy JSONs.
#   4. If DuckDB has a newer expiry → run all 5 backtests and export web JSON.
#   5. Otherwise → exit 0 silently (non-expiry day, or holiday with no new data).
#
# This approach is holiday-safe: it never hard-codes Tue/Thu.
# DuckDB's spot candles already have gaps on NSE holidays, so the expiry
# derivation in download_data.py naturally rolls back to the prior trading day.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

TODAY=$(date +%Y-%m-%d)
# Last 10 days covers any week with a mid-week holiday
FROM=$(python3 -c "from datetime import date, timedelta; print(date.today() - timedelta(days=10))")

echo "[update_strategies] $TODAY — downloading last 10 days of options data..."

python3 download_data.py --underlying NIFTY  --from-date "$FROM" --to-date "$TODAY"
python3 download_data.py --underlying SENSEX --from-date "$FROM" --to-date "$TODAY"

# ── Check whether a new expiry actually landed for each underlying ────────────
check_new_expiry() {
  local UNDERLYING=$1
  local STRATEGY_JSON=$2   # path to any strategy JSON for that underlying

  LATEST_DUCKDB=$(python3 - <<PYEOF
from src.db import DBManager
db = DBManager()
conn = db.connect()
r = conn.execute(
    "SELECT MAX(expiry_date) FROM option_candles WHERE underlying=?",
    ["$UNDERLYING"]
).fetchone()
print(str(r[0])[:10] if r[0] else "2000-01-01")
PYEOF
)

  LATEST_WEB=$(python3 - <<PYEOF
import json, os
path = "$STRATEGY_JSON"
if not os.path.exists(path):
    print("2000-01-01")
else:
    data = json.load(open(path))
    trades = data.get("trades", [])
    print(max((t["date"][:10] for t in trades), default="2000-01-01"))
PYEOF
)

  echo "[update_strategies] $UNDERLYING — DuckDB latest expiry: $LATEST_DUCKDB | Web latest: $LATEST_WEB"

  if [[ "$LATEST_DUCKDB" > "$LATEST_WEB" ]]; then
    echo "[update_strategies] $UNDERLYING — new expiry found, backtests will run."
    return 0   # new expiry exists
  else
    return 1   # nothing new
  fi
}

NIFTY_NEW=false
SENSEX_NEW=false

check_new_expiry "NIFTY"  "web/data/strategies/nifty_atm_short_straddle.json"  && NIFTY_NEW=true  || true
check_new_expiry "SENSEX" "web/data/strategies/sensex_atm_short_straddle.json" && SENSEX_NEW=true || true

if [ "$NIFTY_NEW" = false ] && [ "$SENSEX_NEW" = false ]; then
  echo "[update_strategies] No new expiries for either underlying. Nothing to do."
  exit 0
fi

# ── Run backtests only for underlyings that have new data ─────────────────────
if [ "$NIFTY_NEW" = true ]; then
  echo "[update_strategies] Running NIFTY ATM Straddle..."
  python3 run_backtest.py \
    --underlying NIFTY --strategy-type straddle \
    --from-date 2020-01-01 --to-date "$TODAY" --export-web

  echo "[update_strategies] Running NIFTY 20-Delta Strangle..."
  python3 run_backtest.py \
    --underlying NIFTY --strategy-type strangle \
    --from-date 2020-01-01 --to-date "$TODAY" --export-web

  echo "[update_strategies] Running NIFTY Iron Condor..."
  python3 run_ic_backtest.py \
    --from-date 2020-08-01 --to-date "$TODAY" \
    --short-pct 1.0 --wing-points 100 \
    --sl-type premium --sl-pct 1.0 \
    --export-web \
    --strategy-id nifty_iron_condor \
    --strategy-name "NIFTY Iron Condor"
fi

if [ "$SENSEX_NEW" = true ]; then
  echo "[update_strategies] Running SENSEX ATM Straddle..."
  python3 run_backtest.py \
    --underlying SENSEX --strategy-type straddle \
    --from-date 2020-01-01 --to-date "$TODAY" --export-web

  echo "[update_strategies] Running SENSEX 20-Delta Strangle..."
  python3 run_backtest.py \
    --underlying SENSEX --strategy-type strangle \
    --from-date 2020-01-01 --to-date "$TODAY" --export-web
fi

echo "[update_strategies] All strategy updates complete."
