# Trading Session Checking

## Overview

The Trading Session Checking feature ensures that symbols are only initialized and traded during their active trading hours. This prevents the bot from attempting to trade symbols when their markets are closed, which can lead to failed orders, stale data, and other issues.

**Default Behavior**: The bot checks each symbol's trading session status and **skips inactive symbols immediately** without waiting. This ensures the bot only trades symbols that are currently in their active trading hours.

## How It Works

### 1. Session Status Check

Before initializing each symbol, the system queries MetaTrader 5 to verify:

- **Trading Mode**: Symbol is not disabled for trading
- **Tick Data Availability**: Recent tick data is available (market is active)
- **Tick Freshness**: Tick data is not stale (updated within last 60 seconds)
- **Valid Prices**: Bid and ask prices are valid (non-zero)

### 2. Initialization Logic

The initialization process follows this flow:

```
For each symbol:
  ├─ Is session checking enabled?
  │  ├─ YES: Check if symbol is in active trading session
  │  │  ├─ Active: Initialize immediately
  │  │  └─ Inactive: 
  │  │     ├─ Is waiting enabled?
  │  │     │  ├─ YES: Wait for session to become active (with timeout)
  │  │     │  └─ NO: Skip symbol
  │  └─ NO: Initialize without checking (legacy behavior)
```

### 3. Default Behavior: Skip Inactive Symbols

**By default (`WAIT_FOR_SESSION=false`)**, when a symbol is not in its active trading session:

1. **Log Status**: Record that symbol is outside trading hours
2. **Skip Immediately**: Symbol is skipped without waiting
3. **Continue**: Bot proceeds to check next symbol

### 4. Background Monitoring for Inactive Symbols

**If enabled (`WAIT_FOR_SESSION=true`)**, the bot uses **non-blocking background monitoring**:

1. **Active Symbols**: Initialize and start trading immediately
2. **Inactive Symbols**: Start background monitoring threads (one per symbol)
3. **Background Monitoring**: Each thread independently waits for its symbol's session
4. **Periodic Checks**: Check session status every N seconds (configurable)
5. **Status Updates**: Log progress every 5 checks
6. **Timeout Handling**:
   - If timeout is set (>0): Stop monitoring after timeout expires
   - If timeout is 0: Monitor indefinitely until session becomes active
7. **Auto-Initialization**: When session becomes active, automatically initialize and start trading
8. **No Blocking**: Active symbols trade while inactive symbols are monitored in background

**Key Advantage**: The bot starts trading immediately with active symbols while continuously monitoring inactive symbols in the background. When an inactive symbol's session starts, it's automatically added to the trading pool without any manual intervention.

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# Enable/disable session checking (RECOMMENDED: true)
CHECK_SYMBOL_SESSION=true

# Wait for symbols to enter trading session (RECOMMENDED: false)
# false = Skip inactive symbols immediately
# true = Wait for inactive symbols to become active
WAIT_FOR_SESSION=false

# Maximum wait time per symbol (only used if WAIT_FOR_SESSION=true)
SESSION_WAIT_TIMEOUT_MINUTES=30

# How often to check session status while waiting (only used if WAIT_FOR_SESSION=true)
SESSION_CHECK_INTERVAL_SECONDS=60
```

### Configuration Options

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CHECK_SYMBOL_SESSION` | boolean | `true` | Enable session checking before initialization |
| `WAIT_FOR_SESSION` | boolean | `false` | Wait for inactive symbols (false = skip immediately) |
| `SESSION_WAIT_TIMEOUT_MINUTES` | integer | `30` | Max wait time per symbol (only if waiting enabled) |
| `SESSION_CHECK_INTERVAL_SECONDS` | integer | `60` | Interval between session checks (only if waiting enabled) |

## Use Cases

### Scenario 1: All Symbols Active

```
Symbols: EURUSD, GBPUSD, USDJPY
Status: All in active trading session

Result:
✓ EURUSD: In active trading session
✓ GBPUSD: In active trading session  
✓ USDJPY: In active trading session
→ All symbols initialized immediately
```

### Scenario 2: Some Symbols Inactive (Default Behavior)

```
Symbols: EURUSD, XAUUSD, BTCUSD
Status: EURUSD active, XAUUSD inactive, BTCUSD inactive
Config: WAIT_FOR_SESSION=false (default)

Result:
✓ EURUSD: In active trading session → Initialize immediately
✗ XAUUSD: NOT in active trading session → Skip immediately
✗ BTCUSD: NOT in active trading session → Skip immediately

Bot starts trading with only EURUSD
```

### Scenario 3: Some Symbols Inactive (Background Monitoring Enabled)

```
Symbols: EURUSD, XAUUSD, BTCUSD
Status: EURUSD active, XAUUSD inactive, BTCUSD inactive
Config: WAIT_FOR_SESSION=true

Result:
✓ EURUSD: In active trading session → Initialize immediately and start trading
✗ XAUUSD: NOT in active trading session → Start background monitor
✗ BTCUSD: NOT in active trading session → Start background monitor

Bot starts trading EURUSD immediately (no delay!)

[Background Thread for XAUUSD]
Waiting for XAUUSD to enter active trading session...
[After 5 minutes] Still waiting for XAUUSD trading session...
[After 10 minutes] ✓ XAUUSD is now in active trading session → Initialize and start trading

[Background Thread for BTCUSD]
Waiting for BTCUSD to enter active trading session...
[After 30 minutes] Timeout waiting for BTCUSD trading session → Stop monitoring

Note: Active symbols trade immediately while inactive symbols are monitored in background!
```

### Scenario 4: Session Checking Disabled

```
CHECK_SYMBOL_SESSION=false

Result:
→ All symbols initialized immediately without checking
→ Legacy behavior (may attempt to trade closed markets)
```

## Benefits

1. **Prevents Failed Orders**: Avoids attempting to trade when market is closed
2. **Reduces Errors**: Eliminates errors from stale or missing tick data
3. **Improves Reliability**: Ensures bot only trades when markets are active
4. **Flexible Configuration**: Can be enabled/disabled per deployment
5. **Non-Blocking Background Monitoring**: Active symbols trade immediately while inactive symbols are monitored
6. **Automatic Symbol Addition**: Inactive symbols are automatically added when their sessions start
7. **No Manual Intervention**: Fully automated session monitoring and symbol initialization

## Technical Details

### Session Detection Method

The system uses multiple checks to determine if a symbol is in an active trading session:

1. **Symbol Info Check**: Queries `symbol_info()` to get trading mode
2. **Tick Data Check**: Queries `symbol_info_tick()` to get latest tick
3. **Freshness Check**: Compares tick timestamp with current time
4. **Price Validation**: Verifies bid/ask prices are valid

### Components

- **`TradingStatusChecker`**: Core session checking logic
- **`SymbolSessionMonitor`**: Manages waiting and monitoring
- **`TradingController`**: Orchestrates initialization with session checks
- **`TradingHoursConfig`**: Configuration dataclass

### API Methods

```python
# Check if symbol is in trading session
connector.is_in_trading_session(symbol: str) -> bool

# Wait for symbol to enter trading session
session_monitor.wait_for_trading_session(
    symbol: str, 
    max_wait_minutes: Optional[int]
) -> bool

# Filter symbols by session status
session_monitor.filter_active_symbols(
    symbols: List[str]
) -> tuple[List[str], List[str]]
```

## Troubleshooting

### Symbol Never Enters Trading Session

**Possible Causes:**
- Symbol is genuinely closed (weekend, holiday)
- Symbol is delisted or no longer available
- MT5 connection issues
- Symbol not properly configured in MT5

**Solutions:**
1. Check MT5 Market Watch to verify symbol status
2. Verify symbol is visible and active in MT5
3. Check broker's trading hours for the symbol
4. Reduce `SESSION_WAIT_TIMEOUT_MINUTES` to skip faster

### All Symbols Showing as Inactive

**Possible Causes:**
- MT5 connection lost
- System time incorrect
- All markets genuinely closed (weekend)

**Solutions:**
1. Verify MT5 connection is active
2. Check system time is correct
3. Verify it's not a weekend or holiday
4. Temporarily disable session checking to test

## Best Practices

1. **Use Default Settings**: The default configuration works well for most cases
2. **Set Reasonable Timeouts**: 30-60 minutes is usually sufficient
3. **Monitor Logs**: Check logs to see which symbols are waiting
4. **Test During Market Hours**: Initial testing should be during active market hours
5. **Consider Time Zones**: Be aware of your broker's server time zone

## Migration from Legacy Behavior

If you're upgrading from a version without session checking:

1. **Default Behavior**: Session checking is enabled by default
2. **To Disable**: Set `CHECK_SYMBOL_SESSION=false` in `.env`
3. **Gradual Rollout**: Test with a few symbols first
4. **Monitor Performance**: Check logs for any issues

## Future Enhancements

Potential improvements for future versions:

- Per-symbol timeout configuration
- Session schedule caching
- Predictive session start times
- Integration with broker's trading calendar
- Automatic retry on session close/reopen

