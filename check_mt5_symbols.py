"""
Quick script to check MT5 connection and available symbols.
Run this to find the correct symbol names for your broker.
"""
import MetaTrader5 as mt5
from datetime import datetime, timezone

print("=" * 80)
print("MT5 CONNECTION & SYMBOL CHECK")
print("=" * 80)
print()

# Initialize MT5
if not mt5.initialize():
    print("❌ ERROR: Failed to initialize MT5")
    print(f"   Error: {mt5.last_error()}")
    print()
    print("SOLUTIONS:")
    print("  1. Make sure MetaTrader 5 terminal is running")
    print("  2. Check if MT5 is logged in to your broker account")
    print("  3. Try restarting MT5 terminal")
    quit()

print("✅ MT5 initialized successfully")
print()

# Get account info
account_info = mt5.account_info()
if account_info:
    print(f"Account: {account_info.login}")
    print(f"Server: {account_info.server}")
    print(f"Balance: ${account_info.balance:,.2f}")
    print()
else:
    print("⚠️  WARNING: Could not get account info (might not be logged in)")
    print()

# Search for common forex pairs
print("=" * 80)
print("SEARCHING FOR FOREX SYMBOLS")
print("=" * 80)
print()

search_terms = ['EUR', 'GBP', 'USD', 'JPY']
found_symbols = {}

for term in search_terms:
    symbols = mt5.symbols_get(group=f"*{term}*")
    if symbols:
        for s in symbols:
            if s.visible:  # Only show visible symbols
                found_symbols[s.name] = s

print(f"Found {len(found_symbols)} visible symbols")
print()

# Filter for major pairs
major_pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'GBPJPY', 'EURJPY', 'AUDUSD', 'USDCAD', 'NZDUSD']
print("MAJOR FOREX PAIRS:")
print("-" * 80)

found_majors = []
for pair in major_pairs:
    # Try exact match first
    matches = [name for name in found_symbols.keys() if pair in name.upper()]
    if matches:
        for match in matches:
            s = found_symbols[match]
            found_majors.append(match)
            print(f"  ✅ {match:20s} - {s.description}")

if not found_majors:
    print("  ❌ No major pairs found!")
    print()
    print("  Showing ALL available symbols:")
    print("-" * 80)
    for name, s in sorted(found_symbols.items())[:50]:  # Show first 50
        print(f"  {name:20s} - {s.description}")

print()

# Test data availability for found symbols
if found_majors:
    print("=" * 80)
    print("TESTING DATA AVAILABILITY (2025)")
    print("=" * 80)
    print()
    
    test_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    test_end = datetime(2025, 1, 2, tzinfo=timezone.utc)
    
    for symbol in found_majors[:5]:  # Test first 5
        # Try to get M1 data
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, test_start, test_end)
        
        if rates is not None and len(rates) > 0:
            print(f"  ✅ {symbol:20s} - {len(rates):,} M1 bars available (Jan 1, 2025)")
        else:
            error = mt5.last_error()
            print(f"  ❌ {symbol:20s} - No data! Error: {error}")

print()
print("=" * 80)
print("RECOMMENDED CONFIGURATION FOR backtest.py:")
print("=" * 80)
print()

if found_majors:
    # Generate symbol list
    symbol_list = "SYMBOLS: Optional[List[str]] = ["
    symbol_list += ", ".join([f"'{s}'" for s in found_majors[:4]])  # First 4
    symbol_list += "]"
    print(symbol_list)
else:
    print("# No symbols found - check MT5 connection!")

print()

# Cleanup
mt5.shutdown()
print("Done!")

