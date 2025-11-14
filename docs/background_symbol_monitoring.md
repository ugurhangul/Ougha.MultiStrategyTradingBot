# Background Symbol Monitoring

## Overview

The Background Symbol Monitoring feature enables **non-blocking, concurrent monitoring** of inactive symbols. This allows the bot to:

1. **Start trading immediately** with symbols that are in active trading sessions
2. **Monitor inactive symbols in the background** without blocking or delaying active symbols
3. **Automatically initialize and start trading** inactive symbols when their sessions become active
4. **Operate 24/7** with symbols across different time zones and trading hours

## Key Benefits

### 🚀 No Blocking
- Active symbols initialize and start trading **immediately**
- No waiting for inactive symbols to become active
- Bot is operational within seconds, not minutes or hours

### 🔄 Automatic Symbol Addition
- Inactive symbols are monitored in **background threads**
- When a symbol's trading session starts, it's **automatically initialized**
- The symbol **starts trading immediately** without manual intervention

### 🌍 Multi-Timezone Support
- Perfect for trading symbols across different time zones
- Example: Trade EURUSD (active) while monitoring USDJPY (inactive, waiting for Tokyo session)
- Symbols are added to the trading pool as their markets open

### 📊 Full Visibility
- Log messages show which symbols are active vs. pending
- Status updates every 5 check intervals for pending symbols
- Clear indication when a symbol transitions from pending to active

## How It Works

### Architecture

```
TradingController
├── Active Symbols (immediate)
│   ├── Initialize strategy
│   ├── Start trading thread
│   └── Begin trading immediately
│
└── Inactive Symbols (background)
    ├── Add to pending_symbols set
    ├── Start background monitor thread
    └── Background Monitor Thread:
        ├── Check session status periodically
        ├── Log progress updates
        ├── When session becomes active:
        │   ├── Initialize strategy
        │   ├── Start trading thread
        │   ├── Remove from pending_symbols
        │   └── Begin trading
        └── On timeout or shutdown:
            └── Clean up and exit
```

### Thread Model

Each inactive symbol gets its own **dedicated background monitoring thread**:

- **Thread Name**: `SessionMonitor-{SYMBOL}`
- **Daemon Thread**: Yes (automatically cleaned up on shutdown)
- **Check Interval**: Configurable (default: 60 seconds)
- **Timeout**: Configurable (0 = indefinite, >0 = minutes)

### Lifecycle

1. **Initialization Phase**
   - Bot checks all symbols for active trading sessions
   - Active symbols → Initialize immediately
   - Inactive symbols → Start background monitors

2. **Trading Phase**
   - Active symbols trade normally
   - Background monitors check inactive symbols periodically
   - When inactive symbol becomes active → Auto-initialize and start trading

3. **Shutdown Phase**
   - Set `running = False`
   - Wait for all trading threads to stop
   - Wait for all background monitor threads to stop
   - Clean shutdown

## Configuration

### Recommended Settings

```bash
# Enable session checking
CHECK_SYMBOL_SESSION=true

# Enable background monitoring (RECOMMENDED for multi-timezone trading)
WAIT_FOR_SESSION=true

# Monitor indefinitely (0 = no timeout)
SESSION_WAIT_TIMEOUT_MINUTES=0

# Check every 60 seconds
SESSION_CHECK_INTERVAL_SECONDS=60
```

### Alternative: Skip Inactive Symbols

```bash
# Enable session checking
CHECK_SYMBOL_SESSION=true

# Skip inactive symbols immediately (old behavior)
WAIT_FOR_SESSION=false
```

## Example Scenarios

### Scenario 1: Mixed Active/Inactive Symbols

**Setup:**
- Symbols: EURUSD, GBPUSD, USDJPY, AUDUSD
- Time: 14:00 UTC (London session active, Tokyo session closed)
- Active: EURUSD, GBPUSD
- Inactive: USDJPY, AUDUSD

**Behavior:**
```
[14:00:00] Checking trading session status...
[14:00:01] ✓ EURUSD: In active trading session
[14:00:01] ✓ GBPUSD: In active trading session
[14:00:01] ✗ USDJPY: NOT in active trading session
[14:00:01] ✗ AUDUSD: NOT in active trading session
[14:00:02] Starting background monitoring for inactive symbols...
[14:00:02] Started background monitor for USDJPY
[14:00:02] Started background monitor for AUDUSD
[14:00:03] ✓ EURUSD initialized
[14:00:03] ✓ GBPUSD initialized
[14:00:04] Bot starts trading EURUSD and GBPUSD immediately

[Background Thread - USDJPY]
[14:00:02] Background monitor: Waiting for USDJPY trading session...
[14:05:02] Still waiting for USDJPY trading session... (elapsed: 5.0 minutes)
[14:10:02] Still waiting for USDJPY trading session... (elapsed: 10.0 minutes)
...
[23:00:00] ✓ USDJPY trading session is now active (waited 540.0 minutes)
[23:00:01] ✓ USDJPY initialized
[23:00:02] ✓ USDJPY trading thread started - now actively trading
```

### Scenario 2: All Symbols Inactive at Startup

**Setup:**
- Symbols: EURUSD, GBPUSD, USDJPY
- Time: 22:00 UTC (Weekend, all markets closed)

**Behavior:**
```
[22:00:00] Checking trading session status...
[22:00:01] ✗ EURUSD: NOT in active trading session
[22:00:01] ✗ GBPUSD: NOT in active trading session
[22:00:01] ✗ USDJPY: NOT in active trading session
[22:00:02] Starting background monitoring for inactive symbols...
[22:00:02] Started background monitoring for 3 inactive symbols
[22:00:03] Initialized 0/3 symbols
[22:00:04] Bot is running with 0 active symbols (3 pending)

[Sunday 22:00 UTC - Monday 00:00 UTC]
All background monitors waiting...

[Monday 00:00:00] ✓ USDJPY trading session is now active
[Monday 00:00:01] ✓ USDJPY initialized and trading

[Monday 08:00:00] ✓ EURUSD trading session is now active
[Monday 08:00:01] ✓ EURUSD initialized and trading

[Monday 08:00:00] ✓ GBPUSD trading session is now active
[Monday 08:00:01] ✓ GBPUSD initialized and trading
```

## API Reference

### New Methods

#### `_start_background_symbol_monitor(symbol, max_wait_minutes)`
Starts a background monitoring thread for an inactive symbol.

#### `_background_symbol_monitor_worker(symbol, max_wait_minutes)`
Background worker that monitors a symbol and initializes it when active.

### Updated Methods

#### `initialize(symbols)`
- Now starts background monitors for inactive symbols when `WAIT_FOR_SESSION=true`
- Returns immediately after initializing active symbols

#### `stop()`
- Now waits for background monitor threads to stop
- Clean shutdown of all monitoring threads

#### `get_status()`
- Now returns both active and pending symbols
- Includes counts for visibility

## Monitoring and Debugging

### Log Messages

**Initialization:**
```
Starting background monitoring for inactive symbols...
Started background monitor for XAUUSD
```

**Periodic Updates:**
```
Still waiting for XAUUSD trading session... (elapsed: 15.0 minutes)
```

**Success:**
```
✓ XAUUSD trading session is now active (waited 45.0 minutes)
✓ XAUUSD initialized
✓ XAUUSD trading thread started - now actively trading
```

**Timeout:**
```
Timeout waiting for XAUUSD trading session (waited 120.0 minutes)
```

### Status Checking

The `get_status()` method now returns:
```python
{
    'active_symbols': {
        'EURUSD': {...},
        'GBPUSD': {...}
    },
    'pending_symbols': ['USDJPY', 'AUDUSD'],
    'total_active': 2,
    'total_pending': 2
}
```

## Best Practices

1. **Use Indefinite Timeout for 24/7 Operation**
   - Set `SESSION_WAIT_TIMEOUT_MINUTES=0`
   - Monitors will wait indefinitely for sessions to start

2. **Use Reasonable Check Intervals**
   - 60 seconds is a good default
   - Lower values = more responsive but more API calls

3. **Monitor Logs During Initial Deployment**
   - Verify symbols are being monitored correctly
   - Check that symbols are initialized when sessions start

4. **Consider Time Zones**
   - Be aware of your broker's server time
   - Understand when different markets open/close

## Troubleshooting

### Symbol Never Initializes

**Check:**
1. Is the symbol's market actually open?
2. Is the symbol available in MT5?
3. Check MT5 Market Watch for symbol status
4. Review background monitor logs for errors

### Too Many Pending Symbols

**Check:**
1. Are you running during market hours?
2. Is MT5 connected properly?
3. Check `CHECK_SYMBOL_SESSION` setting

### Background Threads Not Starting

**Check:**
1. Is `WAIT_FOR_SESSION=true`?
2. Are there any initialization errors in logs?
3. Check thread creation logs

