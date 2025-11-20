"""
Test script to verify infrastructure fixes work correctly.

Tests:
1. Lot size calculation for expensive instruments (BTCXAU, BTCZAR)
2. Instrument filtering when min lot creates excessive risk
3. Currency conversion still works correctly
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.mt5_connector import MT5Connector
from src.config.trading_config import config
from src.config.configs import RiskConfig
from src.risk.risk_manager import RiskManager
from src.utils.logger import get_logger

def test_lot_size_calculation():
    """Test lot size calculation with new filtering logic."""
    print("="*80)
    print("TESTING LOT SIZE CALCULATION WITH INFRASTRUCTURE FIXES")
    print("="*80)

    # Initialize MT5 using global config
    connector = MT5Connector(config.mt5)
    
    if not connector.connect():
        print("❌ Failed to connect to MT5")
        return False
    
    # Create risk manager with 1% risk
    risk_config = RiskConfig(
        risk_percent_per_trade=1.0,
        max_lot_size=0.0,  # Use symbol's max (MAX in .env)
        min_lot_size=0.0,  # Use symbol's min (MIN in .env)
        max_positions=1000,
        max_portfolio_risk_percent=10.0
    )
    
    logger = get_logger()
    risk_manager = RiskManager(connector, risk_config)
    
    # Test cases: (symbol, entry, sl, balance, expected_behavior)
    test_cases = [
        ("EURUSD", 1.16219, 1.16119, 1000.0, "normal"),  # Should calculate normally
        ("BTCUSD", 95469, 95369, 1000.0, "normal"),      # Should work with correct lot
        ("BTCZAR", 1633177, 1633077, 1000.0, "min_lot_or_filter"),  # May use min lot or filter
        ("BTCXAU", 23.37711, 23.36711, 1000.0, "filter"),  # Should be filtered (too risky)
    ]
    
    results = []
    
    for symbol, entry, sl, balance, expected in test_cases:
        print(f"\n{'='*80}")
        print(f"Testing: {symbol}")
        print(f"Entry: {entry}, SL: {sl}, Balance: ${balance}")
        print(f"Expected: {expected}")
        print(f"{'='*80}")
        
        # Mock balance (in real code, this comes from connector)
        # For testing, we'll just calculate lot size
        lot_size = risk_manager.calculate_lot_size(symbol, entry, sl)
        
        print(f"\nResult: Lot size = {lot_size:.6f}")
        
        if lot_size == 0.0:
            print("✓ Trade filtered (lot size = 0)")
            result = "filtered"
        elif lot_size > 0:
            # Verify risk
            symbol_info = connector.get_symbol_info(symbol)
            if symbol_info:
                point = symbol_info['point']
                tick_value = symbol_info['tick_value']
                sl_distance = abs(entry - sl)
                sl_points = sl_distance / point if point > 0 else sl_distance
                
                # Get account currency and convert tick value if needed
                from src.utils.currency_conversion_service import CurrencyConversionService
                currency_service = CurrencyConversionService(logger)
                account_currency = connector.get_account_currency()
                currency_profit = symbol_info.get('currency_profit', 'USD')
                
                tick_value_converted, _ = currency_service.convert_tick_value(
                    tick_value=tick_value,
                    currency_profit=currency_profit,
                    account_currency=account_currency,
                    symbol=symbol
                )
                
                risk_amount = sl_points * tick_value_converted * lot_size
                risk_percent = (risk_amount / balance) * 100.0
                
                print(f"✓ Trade allowed")
                print(f"  Actual risk: ${risk_amount:.2f} ({risk_percent:.2f}%)")
                
                if risk_percent <= 3.0:  # Within 3x tolerance
                    result = "normal"
                else:
                    result = "excessive_risk"
                    print(f"  ⚠️  WARNING: Risk exceeds 3% threshold!")
            else:
                result = "unknown"
        else:
            result = "error"
        
        results.append((symbol, expected, result))
    
    # Summary
    print(f"\n{'='*80}")
    print("TEST SUMMARY")
    print(f"{'='*80}")
    
    passed = 0
    failed = 0
    
    for symbol, expected, actual in results:
        if expected == "normal" and actual == "normal":
            status = "✓ PASS"
            passed += 1
        elif expected == "filter" and actual == "filtered":
            status = "✓ PASS"
            passed += 1
        elif expected == "min_lot_or_filter" and actual in ["normal", "filtered"]:
            status = "✓ PASS"
            passed += 1
        else:
            status = "✗ FAIL"
            failed += 1
        
        print(f"{symbol:10} | Expected: {expected:20} | Actual: {actual:20} | {status}")
    
    print(f"\nTotal: {passed} passed, {failed} failed")
    
    connector.disconnect()
    
    return failed == 0


if __name__ == "__main__":
    success = test_lot_size_calculation()
    sys.exit(0 if success else 1)

