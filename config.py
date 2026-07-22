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


def get_access_token() -> str:
    """
    Return a valid Dhan access token.

    Preferred path (CI-safe): mint a fresh 24h token via TOTP login.
      Requires DHAN_PIN + DHAN_TOTP_SECRET in env.

    Fallback: use the static DHAN_ACCESS_TOKEN from .env.
      This expires after ~24h so it will break unattended runs.
    """
    if DHAN_PIN and DHAN_TOTP_SECRET:
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
            raise RuntimeError(f"Dhan TOTP login failed: {data.get('message', data)}")
        logger.info("Minted fresh Dhan access token via TOTP.")
        return data["accessToken"]

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
