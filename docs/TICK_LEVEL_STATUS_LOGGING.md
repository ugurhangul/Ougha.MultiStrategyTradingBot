# Tick-Level Backtesting - Enhanced Status Logging

## Overview

Enhanced the tick-level backtesting engine with comprehensive status logging to provide real-time progress updates during tick-by-tick advancement.

## Changes Made

### 1. Configuration (backtest.py)

**Tick data is now ENABLED by default:**
```python
USE_TICK_DATA = True  # Tick-level backtesting enabled
TICK_TYPE = "ALL"     # All ticks (most comprehensive)
```

### 2. Statistics Tracking (simulated_broker.py)

**Added tick-level statistics:**
```python
self.tick_sl_hits: int = 0   # Count of SL hits detected on ticks
self.tick_tp_hits: int = 0   # Count of TP hits detected on ticks
```

### 3. Enhanced Logging

#### Start of Backtest
When tick-by-tick processing begins (first tick), logs:
```
================================================================================
STARTING TICK-BY-TICK BACKTEST
================================================================================
Total ticks: 123,456
First tick: 2025-11-14 00:00:01 (EURUSD)
Last tick: 2025-11-15 23:59:58 (GBPUSD)
Status updates every 1,000 ticks
================================================================================
```

#### Progress Updates
Every 1,000 ticks (changed from 10,000), logs:
```
[TICK 1,000/123,456] Progress: 0.81% | Symbol: EURUSD | Time: 2025-11-14 00:15:23 | Bid: 1.05432 | Ask: 1.05435
[TICK 2,000/123,456] Progress: 1.62% | Symbol: GBPUSD | Time: 2025-11-14 00:30:45 | Bid: 1.26789 | Ask: 1.26792
[TICK 3,000/123,456] Progress: 2.43% | Symbol: EURUSD | Time: 2025-11-14 00:45:12 | Bid: 1.05445 | Ask: 1.05448
...
```

**Log format includes:**
- Current tick number / Total ticks
- Progress percentage (2 decimal places)
- Symbol that owns the current tick
- Current simulated time (formatted)
- Current bid/ask prices

#### SL/TP Hits
When a position hits SL or TP on a tick, logs:
```
[EURUSD] SL hit on tick at 2025-11-14 12:34:56 | Ticket: 12345 | Close price: 1.05321 | Total SL hits: 5
[GBPUSD] TP hit on tick at 2025-11-14 14:22:11 | Ticket: 12346 | Close price: 1.26850 | Total TP hits: 3
```

**Log format includes:**
- Symbol
- Reason (SL or TP)
- Exact timestamp when hit occurred
- Position ticket number
- Close price (5 decimal places)
- Running total of SL or TP hits

#### End of Backtest
When all ticks are processed, logs:
```
================================================================================
TICK-BY-TICK BACKTEST COMPLETE
================================================================================
Total ticks processed: 123,456
Stop-Loss hits detected on ticks: 15
Take-Profit hits detected on ticks: 8
Total SL/TP hits on ticks: 23
================================================================================
```

## Benefits

### 1. Real-Time Progress Monitoring
- See exactly which tick is being processed
- Know which symbol is currently active
- Track progress percentage in real-time
- Estimate time remaining

### 2. Performance Insights
- Monitor ticks/second processing rate
- Identify slow periods or bottlenecks
- Verify tick distribution across symbols

### 3. SL/TP Validation
- See exactly when SL/TP hits occur
- Verify intra-candle execution is working
- Compare tick-level hits vs candle-level hits
- Track total SL/TP hits for analysis

### 4. Debugging Support
- Detailed timestamp information
- Symbol-specific tracking
- Price information at each update
- Running statistics

## Log Frequency

| Event | Frequency | Purpose |
|-------|-----------|---------|
| Start message | Once (first tick) | Initialize backtest info |
| Progress updates | Every 1,000 ticks | Monitor advancement |
| SL/TP hits | Every occurrence | Track position closures |
| End message | Once (last tick) | Summarize results |

**For a 1-week backtest with ~700,000 ticks:**
- Progress updates: ~700 log messages
- SL/TP hits: Variable (depends on strategy)
- Total overhead: Minimal (logging is fast)

## Performance Impact

✅ **Negligible performance impact:**
- Logging only every 1,000 ticks (0.14% of ticks)
- String formatting is fast
- File I/O is buffered
- No impact on tick processing logic

## Usage

Simply run the backtest with tick data enabled:

```bash
python backtest.py
```

The enhanced logging will automatically provide detailed status updates throughout the tick-by-tick processing.

## Example Output

```
================================================================================
STARTING TICK-BY-TICK BACKTEST
================================================================================
Total ticks: 156,789
First tick: 2025-11-14 00:00:01 (EURUSD)
Last tick: 2025-11-15 23:59:59 (USDJPY)
Status updates every 1,000 ticks
================================================================================

[TICK 1,000/156,789] Progress: 0.64% | Symbol: EURUSD | Time: 2025-11-14 00:12:34 | Bid: 1.05432 | Ask: 1.05435
[TICK 2,000/156,789] Progress: 1.28% | Symbol: GBPUSD | Time: 2025-11-14 00:25:11 | Bid: 1.26789 | Ask: 1.26792
[EURUSD] SL hit on tick at 2025-11-14 00:28:45 | Ticket: 10001 | Close price: 1.05321 | Total SL hits: 1
[TICK 3,000/156,789] Progress: 1.91% | Symbol: USDJPY | Time: 2025-11-14 00:37:22 | Bid: 149.123 | Ask: 149.126
...
[GBPUSD] TP hit on tick at 2025-11-14 14:22:11 | Ticket: 10005 | Close price: 1.26850 | Total TP hits: 1
...
[TICK 156,000/156,789] Progress: 99.50% | Symbol: EURUSD | Time: 2025-11-15 23:45:33 | Bid: 1.05567 | Ask: 1.05570

================================================================================
TICK-BY-TICK BACKTEST COMPLETE
================================================================================
Total ticks processed: 156,789
Stop-Loss hits detected on ticks: 12
Take-Profit hits detected on ticks: 7
Total SL/TP hits on ticks: 19
================================================================================
```

## Files Modified

1. `backtest.py` - Enabled tick data by default
2. `src/backtesting/engine/simulated_broker.py` - Enhanced logging and statistics tracking

## Next Steps

1. Run a backtest and observe the enhanced logging
2. Verify progress updates appear every 1,000 ticks
3. Check SL/TP hit detection and logging
4. Compare tick-level SL/TP hits with candle-level results

