import duckdb
import pandas as pd
from config import DB_PATH, logger

class DBManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        """Establish connection to DuckDB."""
        if self.conn is None:
            # Create data directory if not exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = duckdb.connect(str(self.db_path))
            self._init_db()
        return self.conn

    def close(self):
        """Close connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def _init_db(self):
        """Initialize database schemas."""
        logger.info("Initializing DuckDB database schema...")
        
        # Spot candles table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS spot_candles (
                security_id VARCHAR,
                timestamp TIMESTAMP,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                PRIMARY KEY (security_id, timestamp)
            )
        """)
        
        # Option candles table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS option_candles (
                security_id VARCHAR,
                trading_symbol VARCHAR,
                underlying VARCHAR,
                expiry_date DATE,
                strike DOUBLE,
                option_type VARCHAR,
                timestamp TIMESTAMP,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                open_interest BIGINT,
                iv DOUBLE,
                PRIMARY KEY (security_id, timestamp)
            )
        """)
        # Migrate existing tables that were created without the iv column
        try:
            self.conn.execute("ALTER TABLE option_candles ADD COLUMN IF NOT EXISTS iv DOUBLE")
        except Exception:
            pass
        logger.info("DuckDB schemas initialized.")

    def save_spot_candles(self, df):
        """
        Save/Upsert spot candles dataframe.
        df should have columns: ['security_id', 'timestamp', 'open', 'high', 'low', 'close', 'volume']
        """
        if df.empty:
            return
        
        # Connect to db
        conn = self.connect()
        
        # Ensure timestamp is datetime and security_id is string
        df = df.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['security_id'] = df['security_id'].astype(str)
        
        logger.info(f"Saving {len(df)} spot candles to database...")
        conn.register("df_temp", df)
        conn.execute("""
            INSERT OR REPLACE INTO spot_candles 
            SELECT security_id, timestamp, open, high, low, close, volume FROM df_temp
        """)
        conn.unregister("df_temp")
        logger.info("Spot candles saved.")

    def save_option_candles(self, df):
        """
        Save/Upsert option candles dataframe.
        Required columns: security_id, trading_symbol, underlying, expiry_date, strike,
                          option_type, timestamp, open, high, low, close, volume, open_interest
        Optional column:  iv (implied volatility %)
        """
        if df.empty:
            return

        conn = self.connect()

        df = df.copy()
        df['timestamp']   = pd.to_datetime(df['timestamp'])
        df['expiry_date'] = pd.to_datetime(df['expiry_date']).dt.date
        df['security_id'] = df['security_id'].astype(str)
        df['strike']      = df['strike'].astype(float)
        if 'iv' not in df.columns:
            df['iv'] = 0.0

        logger.info(f"Saving {len(df)} option candles to database...")
        conn.register("df_temp", df)
        conn.execute("""
            INSERT OR REPLACE INTO option_candles
            SELECT
                security_id, trading_symbol, underlying, expiry_date, strike, option_type,
                timestamp, open, high, low, close, volume, open_interest, iv
            FROM df_temp
        """)
        conn.unregister("df_temp")
        logger.info("Option candles saved.")

    def get_spot_candles(self, security_id, from_date=None, to_date=None):
        """Query spot candles."""
        conn = self.connect()
        query = "SELECT * FROM spot_candles WHERE security_id = ?"
        params = [str(security_id)]
        
        if from_date:
            query += " AND timestamp >= ?"
            params.append(pd.to_datetime(from_date))
        if to_date:
            to_dt = pd.to_datetime(to_date)
            if to_dt.hour == 0 and to_dt.minute == 0 and to_dt.second == 0:
                to_dt = to_dt.replace(hour=23, minute=59, second=59)
            query += " AND timestamp <= ?"
            params.append(to_dt)
            
        query += " ORDER BY timestamp"
        return conn.execute(query, params).df()

    def get_option_candles(self, underlying, expiry_date=None, strike=None, option_type=None, from_date=None, to_date=None):
        """Query option candles."""
        conn = self.connect()
        query = "SELECT * FROM option_candles WHERE underlying = ?"
        params = [underlying.upper()]
        
        if expiry_date:
            query += " AND expiry_date = ?"
            params.append(pd.to_datetime(expiry_date).date())
        if strike:
            query += " AND strike = ?"
            params.append(float(strike))
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type.upper())
        if from_date:
            query += " AND timestamp >= ?"
            params.append(pd.to_datetime(from_date))
        if to_date:
            to_dt = pd.to_datetime(to_date)
            if to_dt.hour == 0 and to_dt.minute == 0 and to_dt.second == 0:
                to_dt = to_dt.replace(hour=23, minute=59, second=59)
            query += " AND timestamp <= ?"
            params.append(to_dt)
            
        query += " ORDER BY timestamp"
        return conn.execute(query, params).df()
