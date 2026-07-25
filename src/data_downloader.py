import pandas as pd
from datetime import datetime
from src.dhan_client import DhanClientWrapper
from src.security_master import SecurityMaster
from src.db import DBManager
from config import logger

class DataDownloader:
    def __init__(self, client: DhanClientWrapper, sec_master: SecurityMaster, db: DBManager):
        self.client = client
        self.sec_master = sec_master
        self.db = db

    def parse_candles(self, response):
        """Helper to parse raw API response into a pandas DataFrame."""
        if not response or not isinstance(response, dict):
            logger.error(f"Invalid API response format: {response}")
            return pd.DataFrame()
            
        status = response.get("status")
        error_type = response.get("errorType")
        
        if status == "failure" or error_type:
            logger.error(f"API call failed: {response}")
            return pd.DataFrame()
            
        # Extract candle data. Sometimes the data is wrapped inside a "data" key, sometimes directly at root.
        data_block = response.get("data", response)
        
        if not isinstance(data_block, dict) or "open" not in data_block or not data_block["open"]:
            logger.warning("No candle data found in response.")
            return pd.DataFrame()
            
        try:
            # Build DataFrame
            df = pd.DataFrame({
                'timestamp': pd.to_datetime(data_block['timestamp'], unit='s'),
                'open': data_block['open'],
                'high': data_block['high'],
                'low': data_block['low'],
                'close': data_block['close'],
                'volume': data_block['volume']
            })
            
            if 'open_interest' in data_block:
                df['open_interest'] = data_block['open_interest']
            elif 'oi' in data_block:
                df['open_interest'] = data_block['oi']
            else:
                df['open_interest'] = 0
                
            return df
        except Exception as e:
            logger.error(f"Error parsing candles into DataFrame: {e}")
            return pd.DataFrame()

    def download_spot_data(self, security_id, exchange_segment="IDX_I", instrument_type="INDEX", from_date="2026-01-01", to_date="2026-06-01", interval="D"):
        """
        Downloads historical daily/intraday candles for a spot underlying index using v2 API and stores in DuckDB.
        """
        logger.info(f"Downloading spot data for Index ID={security_id}, From={from_date}, To={to_date}, Interval={interval}")
        
        if interval == "D":
            response = self.client.get_historical_daily(
                security_id=str(security_id),
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                from_date=from_date,
                to_date=to_date
            )
        else:
            response = self.client.get_historical_intraday(
                security_id=str(security_id),
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )
        
        df = self.parse_candles(response)
        if not df.empty:
            df['security_id'] = str(security_id)
            # Filter columns matching schema
            df_to_save = df[['security_id', 'timestamp', 'open', 'high', 'low', 'close', 'volume']]
            self.db.save_spot_candles(df_to_save)
            return df_to_save
        return pd.DataFrame()

    def download_rolling_option_data(self, underlying, expiry_date, strike_offset="ATM", option_type="CALL", from_date="2026-01-01", to_date="2026-06-01", interval="1", expiry_flag="WEEK", expiry_code=1):
        """
        Downloads expired/rolling options candle data using the v2 rollingoption endpoint
        and saves each candle mapped to its actual contract strike price.

        expiry_flag: "WEEK" for weekly options, "MONTH" for monthly options
        expiry_code: 1 = nearest expiry, 2 = 2nd expiry, etc.
        """
        if underlying.upper() == "NIFTY":
            security_id = "13"
            exchange_segment = "NSE_FNO"
            instrument_type = "OPTIDX"
        elif underlying.upper() == "SENSEX":
            security_id = "51"
            exchange_segment = "BSE_FNO"
            instrument_type = "OPTIDX"
        else:
            logger.error(f"Unsupported underlying for rolling options: {underlying}")
            return pd.DataFrame()

        logger.debug(
            f"Downloading rolling option: Underlying={underlying}, Expiry={expiry_date}, "
            f"Offset={strike_offset}, Type={option_type}, {expiry_flag}/code={expiry_code}, Range={from_date}→{to_date}"
        )

        response = self.client.get_rolling_option(
            security_id=security_id,
            exchange_segment=exchange_segment,
            instrument_type=instrument_type,
            expiry_flag=expiry_flag,
            expiry_code=expiry_code,
            strike=strike_offset,
            option_type=option_type.upper(),
            from_date=from_date,
            to_date=to_date,
            interval=interval
        )
        
        if not response or not isinstance(response, dict):
            return pd.DataFrame()
            
        status = response.get("status")
        error_type = response.get("errorType")
        if status == "failure" or error_type:
            return pd.DataFrame()
            
        data_block = response.get("data", {})
        if not data_block:
            return pd.DataFrame()
            
        # Resolve option type key (ce/pe)
        key = "ce" if option_type.upper() in ["CALL", "CE"] else "pe"
        opt_data = data_block.get(key)
        
        if not opt_data or "open" not in opt_data or not opt_data["open"]:
            return pd.DataFrame()
            
        try:
            # Ensure each array is present, is a list/array, and has the same length as timestamp
            n = len(opt_data['timestamp'])
            
            def get_clean_array(field, default_val):
                arr = opt_data.get(field)
                if arr is None or not isinstance(arr, list) or len(arr) != n:
                    return [default_val] * n
                return arr

            spot_arr = get_clean_array('spot', 0.0)

            # Resolve strike step (50 for Nifty, 100 for Sensex)
            if underlying.upper() == "NIFTY":
                strike_step = 50.0
            elif underlying.upper() == "SENSEX":
                strike_step = 100.0
            else:
                strike_step = 50.0

            # Parse offset number from strike_offset (e.g. ATM, ATM+1, ATM-1)
            try:
                offset_str = str(strike_offset).upper().strip()
                if offset_str == "ATM":
                    offset_num = 0
                elif "+" in offset_str:
                    offset_num = int(offset_str.split("+")[1])
                elif "-" in offset_str:
                    offset_num = -int(offset_str.split("-")[1])
                else:
                    offset_num = 0
            except Exception as e:
                logger.warning(f"Error parsing strike offset '{strike_offset}': {e}. Defaulting to 0.")
                offset_num = 0

            # Calculate strike price array from spot prices dynamically since Dhan API returns empty list for strike
            strike_price_arr = []
            for s in spot_arr:
                if pd.isna(s) or s <= 0:
                    strike_price_arr.append(0.0)
                else:
                    atm = round(s / strike_step) * strike_step
                    strike_price_arr.append(float(atm + offset_num * strike_step))

            # Build DataFrame
            df = pd.DataFrame({
                'timestamp': pd.to_datetime(opt_data['timestamp'], unit='s'),
                'open': get_clean_array('open', 0.0),
                'high': get_clean_array('high', 0.0),
                'low': get_clean_array('low', 0.0),
                'close': get_clean_array('close', 0.0),
                'volume': get_clean_array('volume', 0),
                'open_interest': get_clean_array('oi', 0),
                'iv': get_clean_array('iv', 0.0),
                'spot': spot_arr,
                'strike_price': strike_price_arr
            })
            
            expiry_str = pd.to_datetime(expiry_date).strftime('%d%b%y').upper()
            type_code = "CE" if option_type.upper() in ["CALL", "CE"] else "PE"
            
            # Group by actual strike price to save separate contracts
            for strike_val, group in df.groupby('strike_price'):
                if pd.isna(strike_val) or strike_val <= 0:
                    continue
                    
                strike_int = int(strike_val)
                trading_symbol = f"{underlying.upper()}{expiry_str}{strike_int}{type_code}"
                security_id_val = trading_symbol
                
                group_to_save = group.copy()
                group_to_save['security_id'] = security_id_val
                group_to_save['trading_symbol'] = trading_symbol
                group_to_save['underlying'] = underlying.upper()
                group_to_save['expiry_date'] = pd.to_datetime(expiry_date)
                group_to_save['strike'] = float(strike_val)
                group_to_save['option_type'] = type_code

                df_to_db = group_to_save[[
                    'security_id', 'trading_symbol', 'underlying', 'expiry_date', 'strike',
                    'option_type', 'timestamp', 'open', 'high', 'low', 'close', 'volume', 'open_interest', 'iv'
                ]]

                self.db.save_option_candles(df_to_db)
                
            return df
            
        except Exception as e:
            logger.error(f"Error parsing rolling option candles: {e}", exc_info=True)
            return pd.DataFrame()

    def download_monthly_option(self, underlying, expiry_date, expiry_code=2, strike_offset="ATM",
                                option_type="CALL", from_date="2026-01-01", to_date="2026-01-02", interval="1"):
        """
        Convenience wrapper for downloading a monthly (MONTH flag) option contract.
        expiry_code=2 → 2nd upcoming monthly expiry from from_date (= next calendar month).
        Returns the raw candle DataFrame (also saves to DuckDB).
        """
        return self.download_rolling_option_data(
            underlying=underlying,
            expiry_date=expiry_date,
            strike_offset=strike_offset,
            option_type=option_type,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
            expiry_flag="MONTH",
            expiry_code=expiry_code,
        )

