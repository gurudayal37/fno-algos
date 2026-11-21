import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SRC_DIR = BASE_DIR / "src"
WEB_DATA_DIR = BASE_DIR / "web" / "data" / "strategies"

# Create directories if they do not exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
SRC_DIR.mkdir(parents=True, exist_ok=True)

# Load env variables from .env file
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

# API Configuration
DHAN_CLIENT_ID    = os.getenv("DHAN_CLIENT_ID", "your_client_id_here")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")   # optional: used only when TOTP vars absent
DHAN_PIN          = os.getenv("DHAN_PIN", "")
DHAN_TOTP_SECRET  = os.getenv("DHAN_TOTP_SECRET", "")

DHAN_TOKEN_URL = "https://auth.dhan.co/app/generateAccessToken"


# Same login flow as data-syncer (scripts/generate_dhan_token.py): a cheap retry first for a
# one-off TOTP/clock edge case, then a wait long enough to clear Dhan's ~2min-per-account
# login window (a login from the Dhan app/web or another script rejects ours with "Invalid TOTP").
DHAN_LOGIN_RETRY_DELAYS = [5, 75]


def _request_totp_token() -> str:
    import pyotp, requests as _req
    totp_code = pyotp.TOTP(DHAN_TOTP_SECRET).now()
    resp = _req.post(
        DHAN_TOKEN_URL,
        params={"dhanClientId": DHAN_CLIENT_ID, "pin": DHAN_PIN, "totp": totp_code},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "accessToken" not in data:
        raise RuntimeError(data.get("message", data))
    return data["accessToken"]


def _read_shared_token():
    """Token minted once and shared via a file (DHAN_TOKEN_FILE), as data-syncer's
    workflow does - never pass the raw token through an env var or logs."""
    token_file = os.getenv("DHAN_TOKEN_FILE")
    if not token_file or not os.path.exists(token_file):
        return None
    with open(token_file) as f:
        return f.read().strip() or None


def get_access_token() -> str:
    """
    Return a valid Dhan access token (same method as data-syncer).

      1. DHAN_TOKEN_FILE  - reuse a token already minted for this job.
      2. DHAN_PIN + DHAN_TOTP_SECRET - mint a fresh 24h token via TOTP login, with retries.
      3. DHAN_ACCESS_TOKEN - static fallback (expires ~24h after issue).
    """
    shared = _read_shared_token()
    if shared:
        logger.info("Using shared Dhan access token from DHAN_TOKEN_FILE.")
        return shared

    if DHAN_PIN and DHAN_TOTP_SECRET:
        import time, requests as _req
        last_error = None
        for attempt, delay in enumerate([0] + DHAN_LOGIN_RETRY_DELAYS, start=1):
            if delay:
                logger.warning(f"Dhan login attempt {attempt - 1} failed ({last_error}), retrying in {delay}s...")
                time.sleep(delay)
            try:
                token = _request_totp_token()
                logger.info("Minted fresh Dhan access token via TOTP.")
                return token
            except (RuntimeError, _req.RequestException) as e:
                last_error = e
        raise RuntimeError(
            f"Dhan TOTP login failed after {len(DHAN_LOGIN_RETRY_DELAYS) + 1} attempts: {last_error}")

    if DHAN_ACCESS_TOKEN:
        logger.warning(
            "Using static DHAN_ACCESS_TOKEN — expires ~24h after issue. "
            "Set DHAN_PIN + DHAN_TOTP_SECRET for unattended/CI use."
        )
        return DHAN_ACCESS_TOKEN

    raise RuntimeError("No Dhan credentials found. Set DHAN_PIN+DHAN_TOTP_SECRET or DHAN_ACCESS_TOKEN in .env")

# DB Configuration — DUCKDB_PATH env var lets the CI runner point to the file
# on the host machine (checked-out workspace won't have the 588MB DuckDB file).
_duckdb_env = os.getenv("DUCKDB_PATH", "")
DB_PATH = Path(_duckdb_env) if _duckdb_env else DATA_DIR / "options_backtest.duckdb"

# Scrip Master URLs & Path
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
_scrip_env = os.getenv("SCRIP_MASTER_PATH", "")
SCRIP_MASTER_PATH = Path(_scrip_env) if _scrip_env else DATA_DIR / "api-scrip-master-detailed.csv"

# Logger settings
LOG_LEVEL = logging.INFO
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(DATA_DIR / "backtester.log", mode="a")
    ]
)
logger = logging.getLogger("OptionBacktester")

def check_config():
    """Verify that credentials are set up."""
    errors = []
    if not DHAN_CLIENT_ID or DHAN_CLIENT_ID == "your_client_id_here":
        errors.append("DHAN_CLIENT_ID is not configured.")
    has_totp   = bool(DHAN_PIN and DHAN_TOTP_SECRET)
    has_static = bool(DHAN_ACCESS_TOKEN)
    if not has_totp and not has_static:
        errors.append(
            "No Dhan auth credentials found. "
            "Set DHAN_PIN + DHAN_TOTP_SECRET (preferred) or DHAN_ACCESS_TOKEN."
        )
    return errors
