import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from config import SCRIP_MASTER_URL, SCRIP_MASTER_PATH, logger

class SecurityMaster:
    def __init__(self, scrip_master_path=SCRIP_MASTER_PATH, scrip_master_url=SCRIP_MASTER_URL):
        self.scrip_master_path = scrip_master_path
        self.scrip_master_url = scrip_master_url
        self.df = None

    def check_and_download(self, force=False):
        """Downloads the scrip master if not present or older than 24 hours."""
        if not force and self.scrip_master_path.exists():
            # Check file age
            file_time = datetime.fromtimestamp(os.path.getmtime(self.scrip_master_path))
            if datetime.now() - file_time < timedelta(hours=24):
                logger.info(f"Using cached security master file: {self.scrip_master_path}")
                return
            
        logger.info(f"Downloading security master from {self.scrip_master_url}...")
        
        # Create data directory if not exists
        self.scrip_master_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Download the file
        response = requests.get(self.scrip_master_url, stream=True)
        response.raise_for_status()
        
        # Write file with chunks to avoid loading entire file in memory
        with open(self.scrip_master_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
        logger.info("Security master downloaded successfully.")

    def load(self):
        """Loads required columns from the scrip master into a Pandas DataFrame."""
        self.check_and_download()
        
        logger.info("Loading security master into memory...")
        # Load only necessary columns to keep memory usage low
        cols = [
            'SECURITY_ID', 
            'EXCH_ID', 
            'SEGMENT', 
            'SYMBOL_NAME', 
            'DISPLAY_NAME', 
            'UNDERLYING_SYMBOL',
            'SM_EXPIRY_DATE', 
            'LOT_SIZE', 
            'INSTRUMENT_TYPE',
            'STRIKE_PRICE',
            'OPTION_TYPE'
        ]
        
        try:
            self.df = pd.read_csv(self.scrip_master_path, usecols=cols)
            
            # Standardize string columns
            for col in ['EXCH_ID', 'SEGMENT', 'SYMBOL_NAME', 'DISPLAY_NAME', 'UNDERLYING_SYMBOL', 'INSTRUMENT_TYPE', 'OPTION_TYPE']:
                if col in self.df.columns:
                    self.df[col] = self.df[col].astype(str).str.strip().str.upper()
            
            # Clean up security ID
            self.df['SECURITY_ID'] = self.df['SECURITY_ID'].astype(str).str.strip()
            
            # Convert expiry date to datetime
            if 'SM_EXPIRY_DATE' in self.df.columns:
                self.df['SM_EXPIRY_DATE'] = pd.to_datetime(self.df['SM_EXPIRY_DATE'], errors='coerce')
                
            # Convert strike price to float
            if 'STRIKE_PRICE' in self.df.columns:
                self.df['STRIKE_PRICE'] = pd.to_numeric(self.df['STRIKE_PRICE'], errors='coerce')
                
            logger.info(f"Loaded {len(self.df)} instruments from security master.")
        except Exception as e:
            logger.error(f"Error loading security master CSV: {e}")
            raise e

    def get_security_id(self, trading_symbol, exchange="NSE"):
        """Gets security ID for a exact trading symbol."""
        if self.df is None:
            self.load()
            
        res = self.df[(self.df['SYMBOL_NAME'] == trading_symbol.upper()) & 
                      (self.df['EXCH_ID'] == exchange.upper())]
        if not res.empty:
            return res.iloc[0]['SECURITY_ID']
        return None

    def search_options(self, underlying, expiry_date=None, strike=None, option_type=None):
        """
        Search option contracts matching parameters.
        underlying: e.g. 'NIFTY' or 'BANKNIFTY'
        expiry_date: date string 'YYYY-MM-DD' or datetime object
        strike: float/int strike price
        option_type: 'CE' or 'PE'
        """
        if self.df is None:
            self.load()
            
        # Segment F&O is NSE_FNO (in this CSV, NSE EXCH_ID and D SEGMENT is derivatives)
        options = self.df[(self.df['EXCH_ID'] == 'NSE') & (self.df['SEGMENT'] == 'D')]
        
        # Filter by underlying symbol
        options = options[options['UNDERLYING_SYMBOL'] == underlying.upper()]
        
        if expiry_date:
            target_date = pd.to_datetime(expiry_date).date()
            options = options[options['SM_EXPIRY_DATE'].dt.date == target_date]
            
        if option_type:
            options = options[options['OPTION_TYPE'] == option_type.upper()]
            
        if strike is not None:
            options = options[options['STRIKE_PRICE'] == float(strike)]
            
        return options

