"""
Test script to validate using SymbolInfoMarginRate() for position sizing.

This approach is superior to manual currency conversion because:
1. MT5 handles all currency conversions internally
2. Works for any instrument type (FX, crypto, metals, indices)
3. No need to load conversion pairs (XAUUSD, BTCUSD, etc.)
4. Accounts for broker-specific margin requirements
"""

import MetaTrader5 as mt5
from typing import Optional

def calculate_lot_size_using_margin_rate(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    account_balance: float,
    risk_percent: float = 1.0
) -> Optional[float]:
    """
    Calculate lot size using SymbolInfoMarginRate() approach.
    
    This method:
    1. Gets margin rate from MT5 (already in account currency)
    2. Calculates tick value in account currency from margin rate
    3. Uses standard position sizing formula
    
    Args:
        symbol: Symbol name
        entry_price: Entry price
        stop_loss: Stop loss price
        account_balance: Account balance
        risk_percent: Risk percentage per trade
        
    Returns:
        Lot size or None if calculation fails
    """
    # Get symbol info
    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"❌ Failed to get symbol info for {symbol}")
        return None
    
    # Get margin rates (in account currency)
    initial_margin_rate = 0.0
    maintenance_margin_rate = 0.0
    
    # Use BUY order type for margin rate (SELL is similar)
    if not mt5.symbol_info_margin_rate(symbol, mt5.ORDER_TYPE_BUY, initial_margin_rate, maintenance_margin_rate):
        print(f"❌ Failed to get margin rate for {symbol}")
        return None
    
    print(f"\n{'='*80}")
    print(f"MARGIN RATE APPROACH FOR {symbol}")
    print(f"{'='*80}")
    print(f"Initial Margin Rate:      {initial_margin_rate:.6f}")
    print(f"Maintenance Margin Rate:  {maintenance_margin_rate:.6f}")
    
    # Calculate margin for 1 lot (in account currency)
    # Margin = initial_margin_rate × contract_size × price
    margin_per_lot = initial_margin_rate * info.trade_contract_size * entry_price
    print(f"Margin per 1 lot:         ${margin_per_lot:.2f}")
    
    # Now we need to calculate tick value in account currency
    # The key insight: tick_value and margin both involve the same currency conversion
    
    # For most instruments, we can use the tick_value directly if currency_profit == account_currency
    # Otherwise, we need to convert it
    
    # Get account currency
    account_info = mt5.account_info()
    if account_info is None:
        print(f"❌ Failed to get account info")
        return None
    
    account_currency = account_info.currency
    print(f"Account Currency:         {account_currency}")
    print(f"Symbol Currency Profit:   {info.currency_profit}")
    print(f"Symbol Currency Base:     {info.currency_base}")
    
    # Calculate tick value in account currency
    tick_value_account_currency = info.trade_tick_value
    
    if info.currency_profit != account_currency:
        # Need to convert tick value
        # Try to get conversion rate
        conversion_pair = f"{info.currency_profit}{account_currency}"
        tick = mt5.symbol_info_tick(conversion_pair)
        
        if tick is not None:
            conversion_rate = tick.bid
            tick_value_account_currency = info.trade_tick_value * conversion_rate
            print(f"Conversion: {conversion_pair} = {conversion_rate:.5f}")
            print(f"Tick Value (original):    {info.trade_tick_value:.8f} {info.currency_profit}")
            print(f"Tick Value (converted):   {tick_value_account_currency:.8f} {account_currency}")
        else:
            # Try inverse pair
            inverse_pair = f"{account_currency}{info.currency_profit}"
            tick = mt5.symbol_info_tick(inverse_pair)
            
            if tick is not None and tick.ask > 0:
                conversion_rate = 1.0 / tick.ask
                tick_value_account_currency = info.trade_tick_value * conversion_rate
                print(f"Conversion (inverse): {inverse_pair} = {tick.ask:.5f}, inverted = {conversion_rate:.5f}")
                print(f"Tick Value (original):    {info.trade_tick_value:.8f} {info.currency_profit}")
                print(f"Tick Value (converted):   {tick_value_account_currency:.8f} {account_currency}")
            else:
                print(f"⚠️  WARNING: Could not convert {info.currency_profit} to {account_currency}")
                print(f"Using original tick value (may be incorrect!)")
    
    # Calculate position size
    risk_amount = account_balance * (risk_percent / 100.0)
    sl_distance = abs(entry_price - stop_loss)
    sl_distance_points = sl_distance / info.point if info.point > 0 else sl_distance
    
    print(f"\nPOSITION SIZING:")
    print(f"Account Balance:          ${account_balance:.2f}")
    print(f"Risk Percent:             {risk_percent}%")
    print(f"Risk Amount:              ${risk_amount:.2f}")
    print(f"Entry Price:              {entry_price:.{info.digits}f}")
    print(f"Stop Loss:                {stop_loss:.{info.digits}f}")
    print(f"SL Distance:              {sl_distance_points:.2f} points")
    
    # Standard formula: lot_size = risk_amount / (sl_points × tick_value)
    if sl_distance_points <= 0 or tick_value_account_currency <= 0:
        print(f"❌ Invalid SL distance or tick value")
        return None
    
    lot_size_raw = risk_amount / (sl_distance_points * tick_value_account_currency)
    
    # Normalize to lot step
    lot_size = round(lot_size_raw / info.volume_step) * info.volume_step
    lot_size = max(info.volume_min, min(info.volume_max, lot_size))
    
    print(f"Lot Size (raw):           {lot_size_raw:.6f}")
    print(f"Lot Size (normalized):    {lot_size:.2f}")
    
    # Verify risk
    actual_risk = sl_distance_points * tick_value_account_currency * lot_size
    actual_risk_percent = (actual_risk / account_balance) * 100.0
    
    print(f"\nVERIFICATION:")
    print(f"Actual Risk:              ${actual_risk:.2f}")
    print(f"Actual Risk Percent:      {actual_risk_percent:.2f}%")
    
    if abs(actual_risk_percent - risk_percent) > 0.5:
        print(f"⚠️  WARNING: Risk mismatch! Expected {risk_percent}%, got {actual_risk_percent:.2f}%")
    else:
        print(f"✓ Risk calculation correct")
    
    return lot_size


def main():
    """Test the margin rate approach on problematic symbols."""
    if not mt5.initialize():
        print(f"❌ Failed to initialize MT5: {mt5.last_error()}")
        return
    
    print("="*80)
    print("TESTING MARGIN RATE APPROACH FOR POSITION SIZING")
    print("="*80)
    
    # Test symbols
    test_cases = [
        ("BTCZAR", 1633177, 1633077, 1000.0, 1.0),  # Crypto cross
        ("BTCUSD", 95469, 95369, 1000.0, 1.0),      # Crypto vs USD
        ("EURUSD", 1.16219, 1.16119, 1000.0, 1.0),  # Normal FX
        ("BTCXAU", 23.37711, 23.36711, 1000.0, 1.0), # BTC vs Gold (problematic)
    ]
    
    for symbol, entry, sl, balance, risk_pct in test_cases:
        result = calculate_lot_size_using_margin_rate(symbol, entry, sl, balance, risk_pct)
        if result is not None:
            print(f"\n✓ {symbol}: Lot size = {result:.2f}")
        else:
            print(f"\n❌ {symbol}: Failed to calculate lot size")
        print()
    
    mt5.shutdown()


if __name__ == "__main__":
    main()

