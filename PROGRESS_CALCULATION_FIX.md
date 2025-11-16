# Progress Calculation Fix

## Problem

The backtest progress percentage was calculated based on **bar indices** instead of **time**, which caused confusing behavior:

**Before:**
```
[ 52.7%] 2025-11-14 16:00 | ...
```

This showed 52.7% progress at the very beginning because:
- Progress was calculated as: `current_bar_index / total_bars * 100`
- If the first symbol's data started at bar index 0 but the backtest start time was set to skip historical buffer data, the current index would already be at ~50% of the total bars
- Different symbols might have different amounts of data, causing inconsistent progress calculations

## Solution

Changed progress calculation to use **actual time** instead of bar indices:

```python
# Calculate progress as percentage of time elapsed
total_duration = (end_time - start_time).total_seconds()
elapsed_duration = (current_time - start_time).total_seconds()

if total_duration > 0:
    progress_pct = (elapsed_duration / total_duration * 100)
    # Clamp to 0-100 range
    progress_pct = max(0, min(100, progress_pct))
```

## Changes Made

### 1. Added `get_end_time()` to SimulatedBroker

**File:** `src/backtesting/engine/simulated_broker.py`

```python
def get_end_time(self) -> Optional[datetime]:
    """
    Get the latest time from all loaded symbol data.
    This is the backtest end time.
    """
    if not self.symbol_data:
        return None

    latest_time = None
    for (symbol, timeframe), df in self.symbol_data.items():
        if len(df) > 0:
            last_time = df.iloc[-1]['time']
            # Ensure timezone aware
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)

            if latest_time is None or last_time > latest_time:
                latest_time = last_time

    return latest_time
```

### 2. Store start/end times in BacktestController

**File:** `src/backtesting/engine/backtest_controller.py`

Added instance variables:
```python
# Backtest time range (set during run())
self.start_time: Optional[datetime] = None
self.end_time: Optional[datetime] = None
```

Set during `run()`:
```python
# Store start and end times for progress calculation
self.start_time = backtest_start_time
self.end_time = self.broker.get_end_time()
```

### 3. Updated progress calculation

**File:** `src/backtesting/engine/backtest_controller.py`

Changed from bar-based to time-based:
```python
# Get progress percentage based on time (not bar indices)
progress_pct = 0
if self.start_time and self.end_time and current_time:
    # Calculate progress as percentage of time elapsed
    total_duration = (self.end_time - self.start_time).total_seconds()
    elapsed_duration = (current_time - self.start_time).total_seconds()
    
    if total_duration > 0:
        progress_pct = (elapsed_duration / total_duration * 100)
        # Clamp to 0-100 range
        progress_pct = max(0, min(100, progress_pct))
```

## Impact

### Before Fix
- ❌ Progress percentage based on bar indices (confusing and inconsistent)
- ❌ Could start at 50%+ if historical buffer data was loaded
- ❌ Different symbols with different data lengths caused inconsistent calculations

### After Fix
- ✅ Progress percentage based on actual time (intuitive and accurate)
- ✅ Always starts at 0% (start_time) and ends at 100% (end_time)
- ✅ Consistent across all symbols regardless of data length
- ✅ Shows actual time progress through the backtest period

## Example

**Backtest period:** Nov 14, 2025 00:00 to Nov 15, 2025 00:00 (24 hours)

**Progress display:**
```
[  0.0%] 2025-11-14 00:00 | ...  (Start)
[ 25.0%] 2025-11-14 06:00 | ...  (6 hours elapsed)
[ 50.0%] 2025-11-14 12:00 | ...  (12 hours elapsed)
[ 75.0%] 2025-11-14 18:00 | ...  (18 hours elapsed)
[100.0%] 2025-11-15 00:00 | ...  (End)
```

Now the progress percentage accurately reflects how far through the **time period** you are, not how many bars have been processed.

## Testing

Run the backtest again:

```bash
python backtest.py
```

You should now see:
1. Progress starting at **0.0%** (or close to it)
2. Progress increasing linearly with time
3. Progress reaching **100.0%** at the end of the backtest period
4. Consistent progress regardless of which symbol has more/less data

