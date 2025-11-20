# Backtest Progress Output Guide

## Progress Display Format

The backtesting engine displays real-time progress updates during execution via **BacktestController** (unified display for both tick and candle modes). Here's what each field means:

### Example Output (Tick Mode)
```
[  0.1%] 2025-11-14 00:10 | Tick: 5,800/5,800,000 | ETA:  4m 30s | Equity: $  1,050.00 | P&L: $   50.00 (+5.00%) | Floating: $   10.00 | Trades:   12 (8W/4L) | WR:  66.7% | PF:   2.50 | Open:  3 | Waiting: 0/696
```

### Field Breakdown

| Field | Description | Example | Notes |
|-------|-------------|---------|-------|
| **Progress %** | Percentage of ticks processed | `[  0.1%]` | Updates every 1000 ticks or 0.1% |
| **Simulated Time** | Current time in the backtest | `2025-11-14 00:10` | The simulated market time |
| **Tick Progress** | Current tick / Total ticks | `Tick: 5,800/5,800,000` | Shows exact progress |
| **ETA** | Estimated Time to Arrival | `ETA:      4m 30s` | Time until backtest completes |
| **Equity** | Current account equity | `Equity: $  1,050.00` | Balance + floating P&L |
| **P&L** | Realized profit/loss | `P&L: $   50.00 (+5.00%)` | Closed trades only |
| **Floating** | Unrealized P&L | `Floating: $   10.00` | Open positions P&L |
| **Trades** | Total closed trades | `Trades:   12 (8W/4L)` | Wins/Losses breakdown |
| **WR** | Win Rate | `WR:  66.7%` | Percentage of winning trades |
| **PF** | Profit Factor | `PF:   2.50` | Gross profit / Gross loss |
| **Open** | Open positions count | `Open:  3` | Currently active positions |
| **Waiting** | Barrier sync status | `Waiting: 0/696` | Symbols waiting at barrier / Total participants |

## ETA Calculation

### How ETA Works

The ETA (Estimated Time to Arrival) is calculated using a **moving average window** of the last 1000 ticks:

1. **Warmup Period (First 500 ticks)**
   - Display: `ETA: calculating...`
   - Reason: Initial ticks are slower due to initialization overhead

2. **Active Calculation (After 500 ticks)**
   - Tracks processing speed over last 1000 ticks
   - Calculates: `remaining_ticks / ticks_per_second`
   - Updates every progress interval (1000 ticks)

3. **Format**
   - Less than 1 minute: `45s`
   - 1-60 minutes: `4m 30s`
   - Over 1 hour: `2h 15m`

### ETA Accuracy

The ETA becomes more accurate as the backtest progresses:

- **First 1000 ticks:** May fluctuate as speed stabilizes
- **After 5000 ticks:** Usually accurate within ±10%
- **Mid-backtest:** Most accurate, reflects actual processing speed
- **Near completion:** May show slight variations due to final operations

### Factors Affecting ETA

1. **Trading Activity**
   - More trades = slightly slower (due to position management)
   - SL/TP hits require logging and position closing

2. **Number of Symbols**
   - More symbols = more data to process per tick
   - Multi-symbol backtests may be slower

3. **System Load**
   - Other applications running on your computer
   - Background processes can affect speed

4. **Disk I/O**
   - Log file writing (especially with many trades)
   - Position persistence operations

## Progress Update Frequency

### Unified Display (BacktestController)
- **Update Interval:** Every 1 second (wall clock time)
- **Source:** `BacktestController._print_progress_to_console()`
- **Reason:** Provides real-time feedback without excessive overhead
- **Performance Impact:** Negligible (<0.1% overhead)

### Example Timeline (5.8M ticks)
```
[  0.0%] 2025-11-14 00:00 | Tick:       1/5,800,000 | ETA: calculating... | Equity: $  1,000.00 | ... | Waiting: 0/696
[  0.1%] 2025-11-14 00:10 | Tick:   5,800/5,800,000 | ETA:  4m 30s | Equity: $  1,050.00 | ... | Waiting: 0/696
[  0.2%] 2025-11-14 00:20 | Tick:  11,600/5,800,000 | ETA:  4m 15s | Equity: $  1,075.00 | ... | Waiting: 0/696
[  0.3%] 2025-11-14 00:30 | Tick:  17,400/5,800,000 | ETA:  4m 00s | Equity: $  1,100.00 | ... | Waiting: 0/696
...
[ 50.0%] 2025-11-14 12:00 | Tick: 2,900,000/5,800,000 | ETA:  2m 15s | Equity: $  1,150.00 | ... | Waiting: 0/696
...
[100.0%] 2025-11-14 23:59 | Tick: 5,800,000/5,800,000 | ETA:     0s | Equity: $  1,250.00 | ... | Waiting: 0/696
```

## Interpreting Progress

### Healthy Backtest Indicators

✅ **Good Signs:**
- ETA decreases steadily over time
- Processing speed stable (ETA doesn't jump wildly)
- Win rate and profit factor visible early on
- Equity curve trending (up or down, but consistent)

⚠️ **Warning Signs:**
- ETA increasing instead of decreasing (system overload)
- Processing speed dropping significantly (memory issues)
- Equity dropping rapidly (strategy losing money)
- Many open positions accumulating (position limit issues)

### Performance Benchmarks

| Dataset Size | Expected ETA | Processing Speed |
|-------------|--------------|------------------|
| 1 day (5.8M ticks) | 3-5 minutes | 20,000-30,000 ticks/sec |
| 3 days (17M ticks) | 10-15 minutes | 20,000-25,000 ticks/sec |
| 1 week (40M ticks) | 25-35 minutes | 18,000-25,000 ticks/sec |

*Note: Actual speed depends on system specs, number of symbols, and trading activity*

## Console Output Behavior

### Real-Time Updates
- Progress line **overwrites itself** (no scrolling)
- Uses carriage return (`\r`) to update in place
- Terminal width is auto-detected and cached

### Log Files
- Progress updates are **NOT** written to log files
- Only trade executions, SL/TP hits, and errors are logged
- Keeps log files clean and focused on trade history

### Interrupting the Backtest
- Press `Ctrl+C` to stop the backtest
- Partial results will be available
- Log files will contain all trades up to interruption point

## Customizing Progress Display

### Changing Update Frequency

The progress display updates every 1 second (wall clock time) in `BacktestController._print_progress_to_console()`.

To change the update frequency, modify the sleep interval in `BacktestController._wait_for_completion()`:

```python
# Current: Update every 1 second
time.sleep(1)

# More frequent (every 0.5 seconds):
time.sleep(0.5)

# Less frequent (every 2 seconds):
time.sleep(2)
```

**Trade-off:** More frequent updates = slightly more CPU usage (but still negligible)

### Disabling Progress Display

To disable console progress (keep only log files), comment out the call in `BacktestController._wait_for_completion()`:

```python
# Console progress (lightweight, once per second)
# self._print_progress_to_console()  # DISABLED
```

**Note:** This won't significantly improve performance since progress overhead is already negligible

## Troubleshooting

### ETA Shows "calculating..." for Too Long

**Cause:** Backtest hasn't processed 500 ticks yet (warmup period)

**Solution:** Wait for first progress update after 500 ticks

### ETA Jumps Around Wildly

**Cause:** Variable processing speed (system load, disk I/O)

**Solution:** 
- Close other applications
- Check disk space and I/O performance
- Reduce number of symbols if memory-constrained

### Progress Updates Too Slow

**Cause:** Large progress interval for small datasets

**Solution:** Reduce `progress_interval` (see Customizing section above)

### Progress Updates Too Fast (Scrolling)

**Cause:** Very small dataset or very high processing speed

**Solution:** Increase `progress_interval` to reduce update frequency

## Example Session

```bash
$ python backtest.py

================================================================================
MULTI-STRATEGY TRADING BOT - BACKTESTING ENGINE
================================================================================

Backtest logs directory: C:/repos/.../logs/backtest/2025-11-14

BACKTEST CONFIGURATION:
  Date Range:       2025-11-14 to 2025-11-15
  Duration:         1 day(s)
  Initial Balance:  $1,000.00
  ...

================================================================================
STEP 7: Running Backtest
================================================================================

Backtest is now running...
================================================================================

[  0.0%] 2025-11-14 00:00 | Tick:       1/5,800,000 | ETA: calculating... | Equity: $  1,000.00 | P&L: $    0.00 (+0.00%) | Floating: $    0.00 | Trades:    0 (0W/0L) | WR:   0.0% | PF:   0.00 | Open:  0
[  0.1%] 2025-11-14 00:10 | Tick:   5,800/5,800,000 | ETA:      4m 30s | Equity: $  1,050.00 | P&L: $   50.00 (+5.00%) | Floating: $   10.00 | Trades:   12 (8W/4L) | WR:  66.7% | PF:   2.50 | Open:  3
[  0.2%] 2025-11-14 00:20 | Tick:  11,600/5,800,000 | ETA:      4m 15s | Equity: $  1,075.00 | P&L: $   75.00 (+7.50%) | Floating: $   15.00 | Trades:   18 (12W/6L) | WR:  66.7% | PF:   2.45 | Open:  4
...
[100.0%] 2025-11-14 23:59 | Tick: 5,800,000/5,800,000 | ETA:         0s | Equity: $  1,250.00 | P&L: $  250.00 (+25.00%) | Floating: $    0.00 | Trades:  156 (98W/58L) | WR:  62.8% | PF:   2.15 | Open:  0

================================================================================
STEP 8: Analyzing Results
================================================================================
...
```

## Summary

The progress display is **unified and consolidated** in BacktestController. You'll see:

```
[  1.4%] 2025-11-14 00:35 | Tick: 83,446/5,783,708 | ETA:  4m 30s | Equity: $    997.69 | P&L: $  -15.05 ( -1.50%) | Floating: $   12.73 | Trades:    7 (0W/7L) | WR:   0.0% | PF:   0.00 | Open:  8 | Waiting: 61/696
```

Key features:
- **Single unified display** - No duplicate or conflicting progress lines
- **ETA included** - Shows "calculating..." for first 10 updates, then accurate estimates
- **Updates every second** - Real-time feedback without excessive overhead
- **Complete metrics** - Progress, tick count, ETA, equity, P&L, trades, win rate, profit factor, open positions, barrier status

Just run the backtest and watch the single, clean progress line! 🚀

