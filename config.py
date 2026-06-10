import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SRC_DIR = BASE_DIR / "src"

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
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "your_client_id_here")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "your_access_token_here")

# DB Configuration
DB_PATH = DATA_DIR / "options_backtest.duckdb"

# Scrip Master URLs & Path
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
SCRIP_MASTER_PATH = DATA_DIR / "api-scrip-master-detailed.csv"

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
        errors.append("DHAN_CLIENT_ID is not configured or has default placeholder value.")
    if not DHAN_ACCESS_TOKEN or DHAN_ACCESS_TOKEN == "your_access_token_here":
        errors.append("DHAN_ACCESS_TOKEN is not configured or has default placeholder value.")
    return errors
