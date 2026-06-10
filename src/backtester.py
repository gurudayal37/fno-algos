import pandas as pd
import numpy as np
from src.db import DBManager
from config import logger

class ExpiryBacktester:
    def __init__(self, db: DBManager):
        self.db = db

    def calculate_transaction_costs(self, entry_price, exit_price, qty, underlying):
        """
        Calculates Indian market transaction costs (Brokerage, STT, GST, Exchange charges, SEBI, Stamp Duty)
        for shorting (selling) and squaring off (buying) options contracts.
        
        STT: 0.15% on Sell side premium.
        Brokerage: ₹20 per executed order.
        Exchange charges (NSE): ~0.05% on premium (both sides).
        GST: 18% of (Brokerage + Exchange Charges + SEBI Fees).
        SEBI Turnover Fees: 0.0001% of premium (both sides).
        Stamp Duty: 0.003% of premium on Buy side (exit).
        """
        if qty <= 0:
            return 0.0
            
        sell_premium = entry_price * qty
        buy_premium = exit_price * qty
        
        # 1. Brokerage: ₹20 for sell, ₹20 for buy
        brokerage = 20.0 + 20.0
        
        # 2. STT: 0.15% on Sell side premium (options shorting)
        stt = 0.0015 * sell_premium
        
        # 3. Exchange Transaction Charges: 0.05% of premium (both buy & sell)
        exch_charges = 0.0005 * (sell_premium + buy_premium)
        
        # 4. SEBI Turnover Fees: 0.0001% of premium
        sebi_fees = 0.000001 * (sell_premium + buy_premium)
        
        # 5. GST: 18% of (Brokerage + Exchange charges + SEBI fees)
        gst = 0.18 * (brokerage + exch_charges + sebi_fees)
        
        # 6. Stamp Duty: 0.003% of premium on BUY side (exit)
        stamp_duty = 0.00003 * buy_premium
        
        total_costs = brokerage + stt + exch_charges + sebi_fees + gst + stamp_duty
        return total_costs

    def run_backtest(self, underlying, from_date, to_date, entry_time_str="09:20", exit_time_str="15:15",
                     sl_pct=0.25, combined_sl_pct=None, shift_c2c=False, slippage_pct=0.005, lot_size=None):
        """
        Simulates short straddle on expiry days.
        """
        logger.info(f"Running backtest for {underlying} from {from_date} to {to_date}...")
        logger.info(f"Parameters: Entry={entry_time_str}, Exit={exit_time_str}, Leg SL={sl_pct}, Combined SL={combined_sl_pct}, C2C={shift_c2c}, Slippage={slippage_pct}")

        # Resolve lot sizes if not specified
        if lot_size is None:
            if underlying.upper() == "NIFTY":
                lot_size = 65  # Nifty lot size is 65 in 2026
            elif underlying.upper() == "SENSEX":
                lot_size = 20  # Sensex lot size is 20 in 2026
            else:
                lot_size = 15

        # 1. Fetch spot index data to identify trading days and calculate ATM strikes
        security_id = "13" if underlying.upper() == "NIFTY" else "51"
        spot_candles = self.db.get_spot_candles(security_id, from_date, to_date)
        if spot_candles.empty:
            logger.error("No spot candles found in database. Please download data first.")
            return None, pd.DataFrame()
            
        spot_candles['date'] = spot_candles['timestamp'].dt.date
        spot_candles['time'] = spot_candles['timestamp'].dt.strftime('%H:%M')
        
        # Find unique expiry dates in database from option_candles table
        conn = self.db.connect()
        expiries = conn.execute("""
            SELECT DISTINCT expiry_date 
            FROM option_candles 
            WHERE underlying = ?
            ORDER BY expiry_date
        """, [underlying.upper()]).df()
        
        if expiries.empty:
            logger.error("No option candles found in database. Please download options data first.")
            return None, pd.DataFrame()
            
        expiry_dates = sorted(pd.to_datetime(expiries['expiry_date']).dt.date.tolist())
        logger.info(f"Found {len(expiry_dates)} expiry dates in database.")
        
        trade_logs = []
        
        # 2. Iterate expiry day by expiry day
        for exp_date in expiry_dates:
            logger.info(f"Simulating Expiry Day: {exp_date}")
            
            # Find spot price at entry time on this day
            day_spot = spot_candles[(spot_candles['date'] == exp_date) & (spot_candles['time'] == entry_time_str)]
            if day_spot.empty:
                logger.warning(f"No spot price found for entry time {entry_time_str} on {exp_date}. Skipping.")
                continue
                
            spot_entry_price = day_spot.iloc[0]['close']
            
            # Calculate ATM Strike
            if underlying.upper() == "NIFTY":
                atm_strike = round(spot_entry_price / 50.0) * 50
            else: # SENSEX
                atm_strike = round(spot_entry_price / 100.0) * 100
                
            logger.info(f"Spot at {entry_time_str}: {spot_entry_price:.2f} -> ATM Strike: {atm_strike}")
            
            # Fetch option candles for ATM CE and PE on this expiry day
            ce_candles = self.db.get_option_candles(underlying, expiry_date=exp_date, strike=atm_strike, option_type="CE")
            pe_candles = self.db.get_option_candles(underlying, expiry_date=exp_date, strike=atm_strike, option_type="PE")
            
            if not ce_candles.empty:
                ce_candles = ce_candles[ce_candles['timestamp'].dt.date == exp_date]
            if not pe_candles.empty:
                pe_candles = pe_candles[pe_candles['timestamp'].dt.date == exp_date]
                
            if ce_candles.empty or pe_candles.empty:
                logger.warning(f"Option data missing for ATM Straddle CE/PE on {exp_date}. Skipping.")
                continue
                
            # Set time as index for quick lookup
            ce_candles['time'] = ce_candles['timestamp'].dt.strftime('%H:%M')
            pe_candles['time'] = pe_candles['timestamp'].dt.strftime('%H:%M')
            
            ce_lookup = ce_candles.set_index('time')
            pe_lookup = pe_candles.set_index('time')
            
            # Find entry prices
            if entry_time_str not in ce_lookup.index or entry_time_str not in pe_lookup.index:
                logger.warning(f"No option candle found at entry time {entry_time_str} on {exp_date}. Skipping.")
                continue
                
            # Entry executes at entry candle close (with negative slippage: we sell at a lower premium)
            # If entry_time_str matches multiple indices (should not happen), take the first one
            ce_entry_close = ce_lookup.loc[entry_time_str, 'close']
            pe_entry_close = pe_lookup.loc[entry_time_str, 'close']
            
            # If multiple rows returned (e.g. database duplicate), take the first value
            if isinstance(ce_entry_close, pd.Series):
                ce_entry_close = ce_entry_close.iloc[0]
            if isinstance(pe_entry_close, pd.Series):
                pe_entry_close = pe_entry_close.iloc[0]
                
            ce_entry_price = ce_entry_close * (1.0 - slippage_pct)
            pe_entry_price = pe_entry_close * (1.0 - slippage_pct)
            
            # Initialize positions
            ce_sl = ce_entry_price * (1.0 + sl_pct) if sl_pct else None
            pe_sl = pe_entry_price * (1.0 + sl_pct) if sl_pct else None
            
            combined_entry_premium = ce_entry_price + pe_entry_price
            combined_sl_trigger = combined_entry_premium * (1.0 + combined_sl_pct) if combined_sl_pct else None
            
            ce_status = "OPEN"
            pe_status = "OPEN"
            
            ce_exit_price = None
            pe_exit_price = None
            
            ce_exit_time = None
            pe_exit_time = None
            
            ce_exit_reason = None
            pe_exit_reason = None
            
            # Get intersection of times present in both dataframes
            common_times = sorted(list(set(ce_lookup.index).intersection(set(pe_lookup.index))))
            common_times = [t for t in common_times if t > entry_time_str and t <= exit_time_str]
            
            # 3. Simulate minute-by-minute
            for t in common_times:
                # Retrieve rows
                ce_row = ce_lookup.loc[t]
                pe_row = pe_lookup.loc[t]
                
                # Check if pandas returned Series or DataFrame (for duplicates)
                ce_high = ce_row['high'].iloc[0] if isinstance(ce_row, pd.DataFrame) else ce_row['high']
                pe_high = pe_row['high'].iloc[0] if isinstance(pe_row, pd.DataFrame) else pe_row['high']
                
                ce_open = ce_row['open'].iloc[0] if isinstance(ce_row, pd.DataFrame) else ce_row['open']
                pe_open = pe_row['open'].iloc[0] if isinstance(pe_row, pd.DataFrame) else pe_row['open']
                
                # Check combined premium stop-loss first
                if combined_sl_trigger and ce_status == "OPEN" and pe_status == "OPEN":
                    current_combined_high = ce_high + pe_high
                    if current_combined_high >= combined_sl_trigger:
                        ce_status = "CLOSED"
                        pe_status = "CLOSED"
                        
                        ce_exit_price = ce_high * (1.0 + slippage_pct)
                        pe_exit_price = pe_high * (1.0 + slippage_pct)
                        
                        ce_exit_time = t
                        pe_exit_time = t
                        
                        ce_exit_reason = "COMBINED_SL"
                        pe_exit_reason = "COMBINED_SL"
                        logger.info(f"[{t}] Combined SL hit at premium: {current_combined_high:.2f} (Trigger: {combined_sl_trigger:.2f})")
                        break
                        
                # Check individual leg SL
                # Check Call leg
                if ce_status == "OPEN" and ce_sl:
                    if ce_high >= ce_sl:
                        ce_status = "CLOSED"
                        # Exit is maximum of SL trigger or open price of that minute (if gap-up), plus slippage
                        ce_exit_price = max(ce_sl, ce_open) * (1.0 + slippage_pct)
                        ce_exit_time = t
                        ce_exit_reason = "STOP_LOSS"
                        logger.info(f"[{t}] CE SL hit at price: {ce_exit_price:.2f} (Trigger: {ce_sl:.2f})")
                        
                        # If C2C is enabled, shift Put leg SL to cost (entry price)
                        if shift_c2c and pe_status == "OPEN":
                            pe_sl = pe_entry_price
                            logger.info(f"[{t}] Shifting PE SL to Cost: {pe_sl:.2f}")
                            
                # Check Put leg
                if pe_status == "OPEN" and pe_sl:
                    if pe_high >= pe_sl:
                        pe_status = "CLOSED"
                        pe_exit_price = max(pe_sl, pe_open) * (1.0 + slippage_pct)
                        pe_exit_time = t
                        pe_exit_reason = "STOP_LOSS"
                        logger.info(f"[{t}] PE SL hit at price: {pe_exit_price:.2f} (Trigger: {pe_sl:.2f})")
                        
                        # If C2C is enabled, shift Call leg SL to cost (entry price)
                        if shift_c2c and ce_status == "OPEN":
                            ce_sl = ce_entry_price
                            logger.info(f"[{t}] Shifting CE SL to Cost: {ce_sl:.2f}")
                            
                # Check if both hit SL (or if it's the exit time)
                if ce_status == "CLOSED" and pe_status == "CLOSED":
                    break
                    
                if t == exit_time_str:
                    break
                    
            # 4. Square off remaining open positions at Exit Time
            final_time = common_times[-1] if common_times else exit_time_str
            
            if ce_status == "OPEN":
                ce_status = "CLOSED"
                ce_close_val = ce_lookup.loc[final_time, 'close']
                if isinstance(ce_close_val, pd.Series):
                    ce_close_val = ce_close_val.iloc[0]
                ce_exit_price = ce_close_val * (1.0 + slippage_pct)
                ce_exit_time = final_time
                ce_exit_reason = "SQUARE_OFF"
                
            if pe_status == "OPEN":
                pe_status = "CLOSED"
                pe_close_val = pe_lookup.loc[final_time, 'close']
                if isinstance(pe_close_val, pd.Series):
                    pe_close_val = pe_close_val.iloc[0]
                pe_exit_price = pe_close_val * (1.0 + slippage_pct)
                pe_exit_time = final_time
                pe_exit_reason = "SQUARE_OFF"
                
            # 5. Calculate trade details and costs
            ce_gross_pnl = (ce_entry_price - ce_exit_price) * lot_size
            pe_gross_pnl = (pe_entry_price - pe_exit_price) * lot_size
            
            ce_costs = self.calculate_transaction_costs(ce_entry_price, ce_exit_price, lot_size, underlying)
            pe_costs = self.calculate_transaction_costs(pe_entry_price, pe_exit_price, lot_size, underlying)
            
            ce_net_pnl = ce_gross_pnl - ce_costs
            pe_net_pnl = pe_gross_pnl - pe_costs
            
            total_net_pnl = ce_net_pnl + pe_net_pnl
            
            trade_logs.append({
                'date': exp_date,
                'underlying': underlying.upper(),
                'strike': atm_strike,
                'spot_entry': spot_entry_price,
                
                'ce_entry': ce_entry_price,
                'ce_exit': ce_exit_price,
                'ce_exit_time': ce_exit_time,
                'ce_exit_reason': ce_exit_reason,
                'ce_net_pnl': ce_net_pnl,
                'ce_costs': ce_costs,
                
                'pe_entry': pe_entry_price,
                'pe_exit': pe_exit_price,
                'pe_exit_time': pe_exit_time,
                'pe_exit_reason': pe_exit_reason,
                'pe_net_pnl': pe_net_pnl,
                'pe_costs': pe_costs,
                
                'total_net_pnl': total_net_pnl
            })
            
        # 6. Generate summary statistics
        df_trades = pd.DataFrame(trade_logs)
        if df_trades.empty:
            return None, df_trades
            
        total_pnl = df_trades['total_net_pnl'].sum()
        win_trades = df_trades[df_trades['total_net_pnl'] > 0]
        win_rate = len(win_trades) / len(df_trades) if len(df_trades) > 0 else 0.0
        
        # Calculate max drawdown
        df_trades['cum_pnl'] = df_trades['total_net_pnl'].cumsum()
        df_trades['peak'] = df_trades['cum_pnl'].cummax()
        df_trades['drawdown'] = df_trades['cum_pnl'] - df_trades['peak']
        max_drawdown = df_trades['drawdown'].min()
        
        # Sharpe ratio (ignoring risk free rate)
        pnl_std = df_trades['total_net_pnl'].std()
        pnl_mean = df_trades['total_net_pnl'].mean()
        sharpe = (pnl_mean / pnl_std * np.sqrt(252)) if pnl_std > 0 else 0.0
        
        summary = {
            'underlying': underlying.upper(),
            'total_expiry_days': len(df_trades),
            'winning_expiry_days': len(win_trades),
            'win_rate_pct': win_rate * 100,
            'total_net_pnl': total_pnl,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe,
            'avg_net_pnl_per_expiry': pnl_mean
        }
        
        return summary, df_trades
