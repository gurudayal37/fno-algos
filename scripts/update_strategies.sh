#!/usr/bin/env bash
# Runs after every NIFTY/SENSEX expiry:
#   1. Downloads latest options data into DuckDB
#   2. Runs all 5 strategy backtests and exports web JSON
#   3. Called by the GitHub Actions self-hosted workflow
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Activate virtualenv if present (common local setup)
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

TODAY=$(date +%Y-%m-%d)
echo "[update_strategies] Starting run for $TODAY"

# ── 1. Download latest NIFTY + SENSEX expiry data ────────────────────────────
# The from-date covers the last 30 days to catch any recent expiry that may
# have been missed. Already-downloaded dates are skipped by the downloader.
echo "[update_strategies] Downloading NIFTY options data..."
python3 download_data.py \
  --underlying NIFTY \
  --from-date "$(date -v-30d +%Y-%m-%d 2>/dev/null || date -d '30 days ago' +%Y-%m-%d)" \
  --to-date "$TODAY"

echo "[update_strategies] Downloading SENSEX options data..."
python3 download_data.py \
  --underlying SENSEX \
  --from-date "$(date -v-30d +%Y-%m-%d 2>/dev/null || date -d '30 days ago' +%Y-%m-%d)" \
  --to-date "$TODAY"

# ── 2. Run all strategy backtests (full history, export web JSON) ─────────────
echo "[update_strategies] Running NIFTY ATM Straddle..."
python3 run_backtest.py \
  --underlying NIFTY \
  --strategy-type straddle \
  --from-date 2020-01-01 \
  --to-date "$TODAY" \
  --export-web

echo "[update_strategies] Running NIFTY 20-Delta Strangle..."
python3 run_backtest.py \
  --underlying NIFTY \
  --strategy-type strangle \
  --from-date 2020-01-01 \
  --to-date "$TODAY" \
  --export-web

echo "[update_strategies] Running SENSEX ATM Straddle..."
python3 run_backtest.py \
  --underlying SENSEX \
  --strategy-type straddle \
  --from-date 2020-01-01 \
  --to-date "$TODAY" \
  --export-web

echo "[update_strategies] Running SENSEX 20-Delta Strangle..."
python3 run_backtest.py \
  --underlying SENSEX \
  --strategy-type strangle \
  --from-date 2020-01-01 \
  --to-date "$TODAY" \
  --export-web

echo "[update_strategies] Running NIFTY Iron Condor..."
python3 run_ic_backtest.py \
  --from-date 2020-08-01 \
  --to-date "$TODAY" \
  --short-pct 1.0 \
  --wing-points 100 \
  --sl-type premium \
  --sl-pct 1.0 \
  --export-web \
  --strategy-id nifty_iron_condor \
  --strategy-name "NIFTY Iron Condor"

echo "[update_strategies] All strategies updated successfully."
