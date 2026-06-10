import argparse
import sys
from tabulate import tabulate
import pandas as pd
from datetime import datetime

from config import logger, DATA_DIR
from src.db import DBManager
from src.backtester import ExpiryBacktester

def main():
    parser = argparse.ArgumentParser(description="Dhan Option Backtester runner")
    parser.add_argument("--underlying", type=str, default="NIFTY", choices=["NIFTY", "SENSEX"], help="Underlying index (NIFTY or SENSEX)")
    parser.add_argument("--from-date", type=str, default="2026-01-01", help="From date (YYYY-MM-DD)")
    parser.add_argument("--to-date", type=str, default="2026-06-10", help="To date (YYYY-MM-DD)")
    parser.add_argument("--entry-time", type=str, default="09:20", help="Entry time (HH:MM)")
    parser.add_argument("--exit-time", type=str, default="15:15", help="Exit time (HH:MM)")
    parser.add_argument("--sl-pct", type=float, default=0.25, help="Individual leg stop-loss percentage (e.g. 0.25 for 25%). Set to 0 to disable.")
    parser.add_argument("--combined-sl-pct", type=float, default=None, help="Combined premium stop-loss percentage (e.g. 0.30 for 30%). Default None.")
    parser.add_argument("--c2c", action="store_true", help="Shift remaining leg SL to cost once one leg hits SL")
    parser.add_argument("--slippage-pct", type=float, default=0.005, help="Slippage percentage per execution (e.g. 0.005 for 0.5%)")
    parser.add_argument("--lot-size", type=int, default=None, help="Lot size (Nifty default=65, Sensex default=20)")
    
    args = parser.parse_args()
    
    # Setup leg stop-loss if it's set to 0
    sl_pct = args.sl_pct if args.sl_pct > 0 else None
    
    db = DBManager()
    backtester = ExpiryBacktester(db)
    
    summary, df_trades = backtester.run_backtest(
        underlying=args.underlying,
        from_date=args.from_date,
        to_date=args.to_date,
        entry_time_str=args.entry_time,
        exit_time_str=args.exit_time,
        sl_pct=sl_pct,
        combined_sl_pct=args.combined_sl_pct,
        shift_c2c=args.c2c,
        slippage_pct=args.slippage_pct,
        lot_size=args.lot_size
    )
    
    if summary is None or df_trades.empty:
        logger.error("No trades executed or options data missing. Backtest failed.")
        sys.exit(1)
        
    # Print Backtest Summary
    logger.info("==================================================")
    logger.info("               BACKTEST SUMMARY                   ")
    logger.info("==================================================")
    
    summary_data = [
        ["Underlying", summary['underlying']],
        ["Total Expiry Days Tested", summary['total_expiry_days']],
        ["Winning Expiry Days", summary['winning_expiry_days']],
        ["Win Rate (%)", f"{summary['win_rate_pct']:.2f}%"],
        ["Total Net PnL (Taxes Included)", f"Rs. {summary['total_net_pnl']:.2f}"],
        ["Max Drawdown", f"Rs. {summary['max_drawdown']:.2f}"],
        ["Avg Net PnL per Expiry", f"Rs. {summary['avg_net_pnl_per_expiry']:.2f}"],
        ["Sharpe Ratio", f"{summary['sharpe_ratio']:.2f}"]
    ]
    
    print(tabulate(summary_data, headers=["Metric", "Value"], tablefmt="fancy_grid"))
    
    # Save Trade Book to CSV
    filename = f"backtest_trades_{args.underlying.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    results_path = DATA_DIR / filename
    df_trades.to_csv(results_path, index=False)
    logger.info(f"Detailed trade book saved to: {results_path}")
    
    # Display preview of trades
    logger.info("--- Trade Book Preview ---")
    preview_cols = [
        'date', 'strike', 'spot_entry', 
        'ce_entry', 'ce_exit', 'ce_exit_reason',
        'pe_entry', 'pe_exit', 'pe_exit_reason', 
        'total_net_pnl'
    ]
    # format float columns for clean printing
    df_preview = df_trades[preview_cols].copy()
    for col in ['spot_entry', 'ce_entry', 'ce_exit', 'pe_entry', 'pe_exit', 'total_net_pnl']:
        df_preview[col] = df_preview[col].round(2)
        
    print(tabulate(df_preview.head(15), headers='keys', tablefmt='grid'))

if __name__ == "__main__":
    main()
