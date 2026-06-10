import argparse
import sys
import os
import time
from tabulate import tabulate
import pandas as pd

from config import logger, check_config
from src.security_master import SecurityMaster
from src.dhan_client import DhanClientWrapper
from src.db import DBManager
from src.data_downloader import DataDownloader

def chunk_date_range(start_date_str, end_date_str, chunk_size_days=30):
    start_date = pd.to_datetime(start_date_str)
    end_date = pd.to_datetime(end_date_str)
    
    current_start = start_date
    while current_start < end_date:
        current_end = current_start + pd.Timedelta(days=chunk_size_days)
        if current_end > end_date:
            current_end = end_date
        yield current_start.strftime('%Y-%m-%d'), current_end.strftime('%Y-%m-%d')
        current_start = current_end

def find_expiry_dates_from_db(db: DBManager, security_id, day_of_week):
    """
    Finds unique dates in the spot_candles table for a given security_id 
    and returns those that are candidate weekly expiries.
    day_of_week: 3 for Thursday (Nifty), 4 for Friday (Sensex)
    """
    conn = db.connect()
    # Check if table exists
    tables = conn.execute("SHOW TABLES").fetchall()
    table_names = [t[0] for t in tables]
    if 'spot_candles' not in table_names:
        logger.error("spot_candles table does not exist. Please download index spot data first.")
        return []

    res = conn.execute("""
        SELECT DISTINCT CAST(timestamp AS DATE) as trade_date 
        FROM spot_candles 
        WHERE security_id = ?
        ORDER BY trade_date
    """, [str(security_id)]).df()
    
    if res.empty:
        return []
        
    res['trade_date'] = pd.to_datetime(res['trade_date'])
    res['dayofweek'] = res['trade_date'].dt.dayofweek
    res['iso_year'] = res['trade_date'].dt.isocalendar().year
    res['iso_week'] = res['trade_date'].dt.isocalendar().week
    
    if int(day_of_week) == 3: # Nifty (Thursday)
        # Filter trade dates <= Thursday
        weeklies = res[res['dayofweek'] <= 3]
        expiry_idx = weeklies.groupby(['iso_year', 'iso_week'])['trade_date'].idxmax()
        adjusted_expiry_dates = res.loc[expiry_idx]['trade_date'].dt.strftime('%Y-%m-%d').tolist()
    elif int(day_of_week) == 4: # Sensex (Friday)
        # Filter trade dates <= Friday
        weeklies = res[res['dayofweek'] <= 4]
        expiry_idx = weeklies.groupby(['iso_year', 'iso_week'])['trade_date'].idxmax()
        adjusted_expiry_dates = res.loc[expiry_idx]['trade_date'].dt.strftime('%Y-%m-%d').tolist()
    else:
        adjusted_expiry_dates = []
        
    return sorted(adjusted_expiry_dates)

def run_verify():
    """Verify loading configuration and downloading/parsing the scrip master."""
    logger.info("Starting verification run...")
    
    # 1. Config Check
    errors = check_config()
    if errors:
        logger.warning("Configuration errors found (this is normal if you haven't filled in .env yet):")
        for err in errors:
            logger.warning(f"  - {err}")
    else:
        logger.info("API Credentials loaded successfully (Client ID is set).")

    # 2. Security Master Download and Load Test
    try:
        sec_master = SecurityMaster()
        logger.info("Checking/Downloading Dhan Security Master...")
        sec_master.check_and_download()
        logger.info("Parsing Security Master CSV...")
        sec_master.load()
        
        # Display some info
        logger.info("--- Security Master Data Check ---")
        total_rows = len(sec_master.df)
        logger.info(f"Total instruments loaded: {total_rows}")
        
        # Check F&O contracts count
        fno_df = sec_master.df[(sec_master.df['EXCH_ID'] == 'NSE') & (sec_master.df['SEGMENT'] == 'D')]
        logger.info(f"Total F&O contracts: {len(fno_df)}")
        
        # Search for a sample Nifty option
        logger.info("Searching for NIFTY options in security master...")
        nifty_opts = sec_master.df[
            (sec_master.df['EXCH_ID'] == 'NSE') &
            (sec_master.df['SEGMENT'] == 'D') &
            (sec_master.df['UNDERLYING_SYMBOL'] == 'NIFTY')
        ]
        
        if not nifty_opts.empty:
            logger.info("Sample NIFTY options found in master:")
            sample = nifty_opts.head(5)[[
                'SECURITY_ID', 'SYMBOL_NAME', 'SM_EXPIRY_DATE', 'LOT_SIZE', 'STRIKE_PRICE', 'OPTION_TYPE'
            ]]
            print(tabulate(sample, headers='keys', tablefmt='grid'))
        else:
            logger.warning("No NIFTY option contracts found in scrip master. Please check columns.")

    except Exception as e:
        logger.error(f"Verification failed: {e}", exc_info=True)
        sys.exit(1)
        
    logger.info("Verification step complete! Code structure and scrip master parsing are functional.")

def main():
    parser = argparse.ArgumentParser(description="Dhan Option Data Downloader CLI")
    parser.add_argument("--verify", action="store_true", help="Verify configuration and download/parse scrip master")
    parser.add_argument("--download-spot", action="store_true", help="Download spot index historical data (requires API keys)")
    parser.add_argument("--download-options", action="store_true", help="Download rolling option contracts for expiry days (requires spot data downloaded first)")
    parser.add_argument("--underlying", type=str, default="NIFTY", choices=["NIFTY", "SENSEX"], help="Underlying symbol to download (NIFTY or SENSEX)")
    parser.add_argument("--from-date", type=str, default="2026-01-01", help="From date (YYYY-MM-DD)")
    parser.add_argument("--to-date", type=str, default="2026-06-10", help="To date (YYYY-MM-DD)")
    parser.add_argument("--interval", type=str, default="1", help="Candle interval (e.g. D or 1, 5, 15, 60)")
    
    args = parser.parse_args()
    
    if args.verify:
        run_verify()
        return

    # If the user wants to download data, they need API credentials
    errors = check_config()
    if errors:
        logger.error("Cannot run download. Credentials are not configured in your .env file:")
        for err in errors:
            logger.error(f"  - {err}")
        logger.error("Please populate .env with your DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN and retry.")
        sys.exit(1)
        
    # Run download process
    try:
        # Initialize components
        client = DhanClientWrapper()
        sec_master = SecurityMaster()
        sec_master.load()
        db = DBManager()
        downloader = DataDownloader(client, sec_master, db)
        
        # Mapping symbol to security id and exchange parameters
        if args.underlying.upper() == "NIFTY":
            security_id = "13"
            exchange_segment = "IDX_I"
            instrument_type = "INDEX"
            day_of_week = 3 # Thursday
        else: # SENSEX
            security_id = "51"
            exchange_segment = "IDX_I"
            instrument_type = "INDEX"
            day_of_week = 4 # Friday
            
        if args.download_spot:
            logger.info(f"Downloading spot data for {args.underlying} (ID: {security_id}) from {args.from_date} to {args.to_date}...")
            # We chunk the downloads into 30-day blocks to stay within Dhan limits
            chunks = list(chunk_date_range(args.from_date, args.to_date, chunk_size_days=30))
            
            total_saved = 0
            for idx, (c_start, c_end) in enumerate(chunks):
                logger.info(f"Downloading Chunk {idx+1}/{len(chunks)}: {c_start} to {c_end}")
                df = downloader.download_spot_data(
                    security_id=security_id,
                    exchange_segment=exchange_segment,
                    instrument_type=instrument_type,
                    from_date=c_start,
                    to_date=c_end,
                    interval=args.interval
                )
                total_saved += len(df)
                
            logger.info(f"Completed downloading spot index data. Saved {total_saved} candles in total.")
            
        if args.download_options:
            logger.info(f"Identifying weekly expiry dates for {args.underlying}...")
            expiry_dates = find_expiry_dates_from_db(db, security_id, day_of_week)
            logger.info(f"Found {len(expiry_dates)} expiry dates: {expiry_dates}")
            
            # Filter dates to be within user range
            start_dt = pd.to_datetime(args.from_date).date()
            end_dt = pd.to_datetime(args.to_date).date()
            target_dates = [d for d in expiry_dates if start_dt <= pd.to_datetime(d).date() <= end_dt]
            
            logger.info(f"Downloading ATM Call & Put options data (offsets ATM-5 to ATM+5) for {len(target_dates)} expiry dates...")
            
            offsets = ["ATM", "ATM+1", "ATM-1", "ATM+2", "ATM-2", "ATM+3", "ATM-3", "ATM+4", "ATM-4", "ATM+5", "ATM-5"]
            
            for idx, exp_date in enumerate(target_dates):
                logger.info(f"Processing expiry {idx+1}/{len(target_dates)}: {exp_date}")
                next_day = (pd.to_datetime(exp_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                
                # Fetch Call & Put for each offset
                for offset in offsets:
                    # Download CALL option
                    downloader.download_rolling_option_data(
                        underlying=args.underlying,
                        expiry_date=exp_date,
                        strike_offset=offset,
                        option_type="CALL",
                        from_date=exp_date,
                        to_date=next_day,
                        interval=args.interval
                    )
                    
                    # Download PUT option
                    downloader.download_rolling_option_data(
                        underlying=args.underlying,
                        expiry_date=exp_date,
                        strike_offset=offset,
                        option_type="PUT",
                        from_date=exp_date,
                        to_date=next_day,
                        interval=args.interval
                    )
                    # Small delay between calls to satisfy rate limits smoothly
                    time.sleep(0.05)
                
            logger.info("Historical options data download process complete.")
                
    except Exception as e:
        logger.error(f"Error during execution: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
