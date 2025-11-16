# Tick Mode Progress Display

## Overview

Enhanced the backtest progress display to properly show tick-by-tick progress when running in tick mode.

## Problem

When running tick-level backtesting, the console appeared to be "stuck" because:
1. Console logging was disabled for performance (`ENABLE_CONSOLE_LOGS = False`)
2. Progress calculation was time-based, which doesn't reflect tick processing speed
3. No visual feedback that ticks were being processed

## Solution

Updated `BacktestController._print_progress_to_console()` to detect tick mode and show tick progress.

## Implementation

### Progress Calculation

**Tick Mode** (when `USE_TICK_DATA = True`):
```python
progress_pct = (current_tick_index / total_ticks * 100)
tick_info = f" | Tick: {current_tick:,}/{total_ticks:,}"
```

**Candle Mode** (when `USE_TICK_DATA = False`):
```python
progress_pct = (elapsed_time / total_time * 100)
tick_info = ""  # No tick info
```

### Console Output

**Every 1 second**, the console displays (overwrites previous line with `\r`):

**Tick Mode Example**:
```
[  2.5%] 2025-11-14 00:15 | Tick: 1,234/50,000 | Equity: $10,150.00 | P&L: $150.00 (+1.50%) | Floating: $25.00 | Trades:   12 (8W/4L) | WR:  66.7% | PF:   2.15 | Open:  2 | Waiting: 0/4
```

**Candle Mode Example**:
```
[ 15.3%] 2025-11-14 02:30 | Equity: $10,450.00 | P&L: $450.00 (+4.50%) | Floating: $75.00 | Trades:   25 (18W/7L) | WR:  72.0% | PF:   2.85 | Open:  3 | Waiting: 0/4
```

### Progress Information

| Field | Description |
|-------|-------------|
| `[2.5%]` | Overall progress percentage |
| `2025-11-14 00:15` | Current simulated time |
| `Tick: 1,234/50,000` | Current tick / Total ticks (tick mode only) |
| `Equity: $10,150.00` | Current account equity |
| `P&L: $150.00 (+1.50%)` | Profit/Loss (absolute and percentage) |
| `Floating: $25.00` | Floating P&L from open positions |
| `Trades: 12 (8W/4L)` | Total trades (Wins/Losses) |
| `WR: 66.7%` | Win rate percentage |
| `PF: 2.15` | Profit factor |
| `Open: 2` | Number of open positions |
| `Waiting: 0/4` | Barrier sync status (symbols waiting) |

## File Logging vs Console Display

### Console (Every 1 second)
- **Purpose**: Real-time progress monitoring
- **Frequency**: Every 1 second
- **Format**: Single line, overwrites previous (using `\r`)
- **Content**: Concise metrics
- **Controlled by**: `BacktestController._print_progress_to_console()`

### File Logs (Every 1,000 ticks)
- **Purpose**: Detailed audit trail
- **Frequency**: Every 1,000 ticks (~every few seconds depending on speed)
- **Format**: Multi-line detailed logs
- **Content**: Full tick details (symbol, bid, ask, time)
- **Controlled by**: `SimulatedBroker.advance_global_time_tick_by_tick()`

**Example file log**:
```
[TICK 1,000/50,000] Progress: 2.00% | Symbol: EURUSD | Time: 2025-11-14 00:12:34 | Bid: 1.05432 | Ask: 1.05435
[TICK 2,000/50,000] Progress: 4.00% | Symbol: GBPUSD | Time: 2025-11-14 00:25:11 | Bid: 1.26789 | Ask: 1.26792
```

## Performance Impact

✅ **No performance impact**:
- Console updates run in separate thread (`BacktestController._wait_for_completion()`)
- Updates only every 1 second (not every tick)
- Single `print()` call with pre-formatted string
- File logging only every 1,000 ticks

## Configuration

No configuration needed - automatically detects tick mode:

```python
# In backtest.py
USE_TICK_DATA = True   # Enables tick mode
TICK_TYPE = "ALL"      # Tick type

# Console logging can be disabled for max speed
ENABLE_CONSOLE_LOGS = False  # Progress still shows via print()
```

## Benefits

### 1. Visual Feedback
- See that backtest is running (not stuck)
- Monitor progress in real-time
- Estimate time remaining

### 2. Performance Monitoring
- See ticks/second processing rate
- Identify if backtest is slow
- Monitor memory usage indirectly (via equity/trades)

### 3. Early Problem Detection
- See if trades are being executed
- Monitor win rate in real-time
- Detect if strategies are working

### 4. No Performance Cost
- Updates only every 1 second
- Runs in separate monitoring thread
- Doesn't slow down tick processing

## Example Session

```
================================================================================
STEP 7: Running Backtest
================================================================================

Backtest is now running...

This may take a while depending on:
  - Number of symbols
  - Date range
  - Number of enabled strategies
  - Time mode (MAX_SPEED is fastest)

NOTE: Console logging is DISABLED for maximum speed.
      Detailed logs are being saved to: C:\repos\...\logs\backtest\2025-11-14

================================================================================

[  0.5%] 2025-11-14 00:05 | Tick: 250/50,000 | Equity: $10,000.00 | P&L: $0.00 (+0.00%) | Floating: $0.00 | Trades:    0 (0W/0L) | WR:   0.0% | PF:   0.00 | Open:  0 | 
[  1.2%] 2025-11-14 00:12 | Tick: 600/50,000 | Equity: $10,025.00 | P&L: $25.00 (+0.25%) | Floating: $10.00 | Trades:    2 (2W/0L) | WR: 100.0% | PF:   ∞ | Open:  1 | 
[  2.5%] 2025-11-14 00:25 | Tick: 1,250/50,000 | Equity: $10,150.00 | P&L: $150.00 (+1.50%) | Floating: $25.00 | Trades:   12 (8W/4L) | WR:  66.7% | PF:   2.15 | Open:  2 | 
...
[ 98.5%] 2025-11-14 23:45 | Tick: 49,250/50,000 | Equity: $11,250.00 | P&L: $1,250.00 (+12.50%) | Floating: $50.00 | Trades:  125 (85W/40L) | WR:  68.0% | PF:   2.45 | Open:  3 | 
[100.0%] 2025-11-14 23:59 | Tick: 50,000/50,000 | Equity: $11,300.00 | P&L: $1,300.00 (+13.00%) | Floating: $0.00 | Trades:  128 (87W/41L) | WR:  68.0% | PF:   2.48 | Open:  0 | 

================================================================================
STEP 8: Analyzing Results
================================================================================
```

## Files Modified

1. `src/backtesting/engine/backtest_controller.py`
   - Updated `_print_progress_to_console()` to detect tick mode
   - Show tick progress when in tick mode
   - Show time-based progress when in candle mode

2. `src/backtesting/engine/simulated_broker.py`
   - Removed duplicate console prints
   - File logging only (every 1,000 ticks)
   - Console handled by BacktestController

## Troubleshooting

### Progress not updating?
- Check that backtest is actually running (not crashed)
- Look at log files in `logs/backtest/YYYY-MM-DD/`
- Enable console logging: `ENABLE_CONSOLE_LOGS = True`

### Progress stuck at 0%?
- Tick data may not be loaded
- Check cache directory: `data/ticks/`
- Check logs for tick loading errors

### Progress updates too slow?
- Normal for tick mode (processing millions of ticks)
- Each 1% = ~500-1000 ticks depending on dataset
- Monitor ticks/second in file logs

