"""
Test script for weekend/holiday skip functionality.

Tests that the _should_skip_day() method correctly identifies
weekends for Forex/Metals and allows weekends for Crypto.
"""
from datetime import datetime
from src.backtesting.engine.data_loader import BacktestDataLoader


def test_weekend_skip():
    """Test weekend skip functionality."""
    loader = BacktestDataLoader(use_cache=False)

    # Test dates
    monday = datetime(2024, 1, 1)      # Monday (New Year's Day, but weekday)
    saturday = datetime(2024, 1, 6)    # Saturday
    sunday = datetime(2024, 1, 7)      # Sunday

    # Test Forex symbols (should skip weekends)
    forex_symbols = ['EURUSD', 'GBPUSD', 'USDJPY']
    for symbol in forex_symbols:
        assert not loader._should_skip_day(symbol, monday), f"{symbol} should NOT skip Monday"
        assert loader._should_skip_day(symbol, saturday), f"{symbol} SHOULD skip Saturday"
        assert loader._should_skip_day(symbol, sunday), f"{symbol} SHOULD skip Sunday"
        print(f"✓ {symbol}: Correctly skips weekends, allows weekdays")

    # Test Metals (should skip weekends)
    metals = ['XAUUSD', 'XAGUSD']
    for symbol in metals:
        assert not loader._should_skip_day(symbol, monday), f"{symbol} should NOT skip Monday"
        assert loader._should_skip_day(symbol, saturday), f"{symbol} SHOULD skip Saturday"
        assert loader._should_skip_day(symbol, sunday), f"{symbol} SHOULD skip Sunday"
        print(f"✓ {symbol}: Correctly skips weekends, allows weekdays")

    # Test Crypto (should NOT skip weekends - 24/7 trading)
    crypto_symbols = ['BTCUSD', 'ETHUSD']
    for symbol in crypto_symbols:
        assert not loader._should_skip_day(symbol, monday), f"{symbol} should NOT skip Monday"
        assert not loader._should_skip_day(symbol, saturday), f"{symbol} should NOT skip Saturday"
        assert not loader._should_skip_day(symbol, sunday), f"{symbol} should NOT skip Sunday"
        print(f"✓ {symbol}: Correctly allows all days (24/7 trading)")

    # Test Indices (should skip weekends)
    indices = ['SPX500', 'US30']
    for symbol in indices:
        assert not loader._should_skip_day(symbol, monday), f"{symbol} should NOT skip Monday"
        assert loader._should_skip_day(symbol, saturday), f"{symbol} SHOULD skip Saturday"
        assert loader._should_skip_day(symbol, sunday), f"{symbol} SHOULD skip Sunday"
        print(f"✓ {symbol}: Correctly skips weekends, allows weekdays")

    print("\n✅ All tests passed!")


if __name__ == '__main__':
    test_weekend_skip()
