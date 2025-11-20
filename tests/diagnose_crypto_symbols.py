"""
Diagnostic script to extract and analyze MT5 symbol information for crypto instruments.

This script will:
1. Connect to MT5
2. Extract detailed symbol info for problematic crypto pairs
3. Show exactly what MT5 is reporting for currency_base, currency_profit, tick_value, etc.
4. Calculate what position size and risk would be for a sample trade
5. Compare to what our backtest is using

Run this to diagnose the root cause of the "9479% risk" calculation error.
"""

import MetaTrader5 as mt5
from datetime import datetime
import sys

# Problematic symbols from backtest analysis
CRYPTO_SYMBOLS = [
    'BTCZAR',
    'BTCCNH',
    'BTCUSD',
    'BTCAUD',
    'BTCJPY',
    'ETHUSD',
    'ETHZAR',
]

# Also check some normal FX pairs for comparison
NORMAL_SYMBOLS = [
    'EURUSD',
    'GBPUSD',
    'USDJPY',
]

def format_value(value, decimals=5):
    """Format numeric value for display."""
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)

def analyze_symbol(symbol: str, account_balance: float = 1000.0, risk_percent: float = 1.0):
    """
    Analyze a symbol and show all relevant MT5 data.
    
    Args:
        symbol: Symbol name
        account_balance: Simulated account balance for risk calculation
        risk_percent: Risk percentage per trade
    """
    print("\n" + "=" * 100)
    print(f"SYMBOL: {symbol}")
    print("=" * 100)
    
    # Get symbol info
    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"❌ Symbol {symbol} not found in MT5")
        return
    
    # Display all relevant fields
    print("\n📊 MT5 SYMBOL INFO:")
    print(f"  Currency Base:        {info.currency_base}")
    print(f"  Currency Profit:      {info.currency_profit}")
    print(f"  Currency Margin:      {info.currency_margin}")
    print(f"  Category:             {info.path}")  # Full category path
    print(f"  Description:          {info.description}")
    
    print(f"\n💰 CONTRACT SPECIFICATIONS:")
    print(f"  Contract Size:        {format_value(info.trade_contract_size, 2)}")
    print(f"  Tick Size:            {format_value(info.trade_tick_size, 8)}")
    print(f"  Tick Value:           {format_value(info.trade_tick_value, 8)}")
    print(f"  Point:                {format_value(info.point, 8)}")
    print(f"  Digits:               {info.digits}")
    
    print(f"\n📏 LOT SPECIFICATIONS:")
    print(f"  Min Lot:              {format_value(info.volume_min, 2)}")
    print(f"  Max Lot:              {format_value(info.volume_max, 2)}")
    print(f"  Lot Step:             {format_value(info.volume_step, 2)}")
    
    print(f"\n🔒 MARGIN REQUIREMENTS:")
    print(f"  Initial Margin:       {format_value(info.margin_initial, 2)}")
    print(f"  Maintenance Margin:   {format_value(info.margin_maintenance, 2)}")
    
    # Get current price
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"\n❌ No tick data available for {symbol}")
        return
    
    print(f"\n💵 CURRENT PRICES:")
    print(f"  Bid:                  {format_value(tick.bid, info.digits)}")
    print(f"  Ask:                  {format_value(tick.ask, info.digits)}")
    print(f"  Spread:               {info.spread} points")
    
    # Simulate a trade calculation
    print(f"\n🧮 SIMULATED TRADE CALCULATION:")
    print(f"  Account Balance:      ${account_balance:.2f}")
    print(f"  Risk Percent:         {risk_percent}%")
    print(f"  Risk Amount:          ${account_balance * (risk_percent / 100.0):.2f}")
    
    # Simulate entry and SL
    entry_price = tick.ask
    sl_distance_points = 100  # Assume 100 point SL for example
    sl_distance_price = sl_distance_points * info.point
    
    if info.currency_base == symbol[:3]:  # e.g., BTC for BTCUSD
        # For crypto base, SL is below entry for BUY
        sl_price = entry_price - sl_distance_price
    else:
        sl_price = entry_price - sl_distance_price
    
    print(f"  Entry Price (Ask):    {format_value(entry_price, info.digits)}")
    print(f"  SL Distance:          {sl_distance_points} points = {format_value(sl_distance_price, info.digits)} price")
    print(f"  Stop Loss Price:      {format_value(sl_price, info.digits)}")
    
    # Calculate lot size using MT5 formula
    # Risk Amount = (SL Distance in Points) * Tick Value * Lot Size
    # Lot Size = Risk Amount / (SL Distance in Points * Tick Value)
    
    risk_amount = account_balance * (risk_percent / 100.0)
    sl_distance_in_points = sl_distance_points
    tick_value = info.trade_tick_value
    
    lot_size_raw = risk_amount / (sl_distance_in_points * tick_value)
    
    # Normalize to lot step
    lot_size = round(lot_size_raw / info.volume_step) * info.volume_step
    lot_size = max(info.volume_min, min(info.volume_max, lot_size))
    
    print(f"\n📐 LOT SIZE CALCULATION:")
    print(f"  Formula: Lot Size = Risk Amount / (SL Points × Tick Value)")
    print(f"  Calculation: {risk_amount:.2f} / ({sl_distance_in_points} × {tick_value:.8f})")
    print(f"  Raw Lot Size:         {format_value(lot_size_raw, 4)}")
    print(f"  Normalized Lot Size:  {format_value(lot_size, 2)}")
    
    # Calculate actual risk with this lot size
    actual_risk = sl_distance_in_points * tick_value * lot_size
    actual_risk_percent = (actual_risk / account_balance) * 100.0
    
    print(f"\n✅ ACTUAL RISK VERIFICATION:")
    print(f"  Actual Risk Amount:   ${actual_risk:.2f}")
    print(f"  Actual Risk Percent:  {actual_risk_percent:.2f}%")
    
    # Check if this matches expected
    if abs(actual_risk_percent - risk_percent) > 0.5:
        print(f"  ⚠️  WARNING: Risk mismatch! Expected {risk_percent}%, got {actual_risk_percent:.2f}%")
    else:
        print(f"  ✓ Risk calculation correct")
    
    # Calculate margin requirement
    margin_required = (lot_size * info.trade_contract_size * entry_price) / 100.0  # Assuming 1:100 leverage
    margin_percent = (margin_required / account_balance) * 100.0
    
    print(f"\n💳 MARGIN REQUIREMENT (1:100 leverage):")
    print(f"  Margin Required:      ${margin_required:.2f}")
    print(f"  Margin Percent:       {margin_percent:.2f}%")

def main():
    """Main diagnostic routine."""
    print("=" * 100)
    print("MT5 CRYPTO SYMBOL DIAGNOSTIC TOOL")
    print("=" * 100)
    
    # Initialize MT5
    if not mt5.initialize():
        print(f"❌ Failed to initialize MT5: {mt5.last_error()}")
        sys.exit(1)
    
    print(f"✓ Connected to MT5")
    
    # Get account info
    account_info = mt5.account_info()
    if account_info:
        print(f"✓ Account: {account_info.login}")
        print(f"  Currency: {account_info.currency}")
        print(f"  Balance: ${account_info.balance:.2f}")
        print(f"  Leverage: 1:{account_info.leverage}")
    
    # Analyze crypto symbols
    print("\n" + "=" * 100)
    print("ANALYZING PROBLEMATIC CRYPTO SYMBOLS")
    print("=" * 100)
    
    for symbol in CRYPTO_SYMBOLS:
        analyze_symbol(symbol)
    
    # Analyze normal symbols for comparison
    print("\n" + "=" * 100)
    print("ANALYZING NORMAL FX SYMBOLS (FOR COMPARISON)")
    print("=" * 100)
    
    for symbol in NORMAL_SYMBOLS:
        analyze_symbol(symbol)
    
    # Shutdown MT5
    mt5.shutdown()
    
    print("\n" + "=" * 100)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 100)
    print("\nNext steps:")
    print("1. Check if currency_base/currency_profit are actually 'BTC'/'ETH' from MT5")
    print("2. Compare tick_value between crypto and FX pairs")
    print("3. Verify if lot size calculations produce reasonable values")
    print("4. Check if margin requirements make sense")

if __name__ == "__main__":
    main()

