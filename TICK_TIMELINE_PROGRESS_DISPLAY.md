# Tick Timeline Loading Progress Display

## Overview

Added a Rich Live progress display for STEP 4.5 (Loading Tick Timeline) to show real-time progress as tick data is loaded from cache files and converted into the global timeline.

## Problem

**Before**: STEP 4.5 only showed basic log messages:
```
STEP 4.5: Loading Tick Timeline
  Symbols with tick data: 5/5
Using TRADITIONAL mode (all ticks loaded into memory)
  Memory usage: ~20-30 GB for full year backtest

  Loading EURUSD from EURUSD_20250611_20251120_INFO.parquet...
    6,517,963 ticks loaded
    Converted in 2.45s (2,661,209 ticks/sec)
  Loading GBPUSD from GBPUSD_20250611_20251120_INFO.parquet...
    5,234,123 ticks loaded
    Converted in 1.98s (2,643,496 ticks/sec)
  ...
```

**Issues**:
- No visual progress indication
- Hard to see which symbols are currently loading
- No overall progress summary
- Difficult to estimate completion time

## Solution

**After**: Rich Live display with real-time progress table:

```
┌─ 📊 Tick Timeline Loading ─────────────────────────────────┐
│ Symbols: 3/5 | Ticks: 18,234,567/25,000,000              │
└─────────────────────────────────────────────────────────────┘
Symbol      Status                                      Ticks
EURUSD      ✓ Converted in 2.45s (2,661,209 ticks/sec)  6,517,963
GBPUSD      ✓ Converted in 1.98s (2,643,496 ticks/sec)  5,234,123
USDJPY      ⚡ Converting to timeline...                 6,482,481
AUDUSD      ⏳ Loading from cache...                     0
NZDUSD      ○ Waiting...                                 0
```

**Benefits**:
- ✅ Real-time visual progress
- ✅ Clear status for each symbol
- ✅ Overall progress summary
- ✅ Performance metrics (ticks/sec)
- ✅ Easy to monitor

## Implementation Details

### 1. Progress Display in `backtest.py`

Added Rich Live display for STEP 4.5 (lines ~1380-1499):

**Key Components**:

**a) Progress Callback Function**
```python
def progress_callback(symbol, status, ticks=0, message='', total_ticks=None):
    """Callback to update progress display."""
    tick_load_status[symbol] = {
        'status': status,
        'ticks': ticks,
        'message': message,
        'total_ticks': total_ticks
    }
```

**b) Table Creator Function**
```python
def create_tick_loading_table():
    """Create a table showing tick loading progress."""
    # Calculate overall progress
    total_symbols = len(tick_cache_files)
    completed_symbols = 0
    total_ticks = 0
    loaded_ticks = 0
    
    # ... calculate progress ...
    
    # Create summary
    summary = Text()
    summary.append("Symbols: ", style="bold")
    summary.append(f"{completed_symbols}/{total_symbols}", style="green")
    summary.append("  |  Ticks: ", style="bold")
    summary.append(f"{loaded_ticks:,}/{total_ticks:,}", style="yellow")
    
    # Create table with status for each symbol
    # ...
```

**c) Live Display**
```python
with Live(create_tick_loading_table(), console=console, refresh_per_second=4) as live:
    broker.load_ticks_from_cache_files(
        tick_cache_files, 
        progress_callback=progress_callback, 
        live_display=live, 
        table_creator=create_tick_loading_table
    )
```

### 2. Enhanced `load_ticks_from_cache_files()` Method

Modified `src/backtesting/engine/simulated_broker.py` (lines ~515-591):

**New Parameters**:
- `progress_callback`: Optional callback for progress updates
- `live_display`: Optional Rich Live display object
- `table_creator`: Optional function to create updated table

**Progress Updates**:

**a) Loading Phase**
```python
# Update progress: loading
if progress_callback:
    progress_callback(symbol, 'loading', 0, '')
    if live_display and table_creator:
        live_display.update(table_creator())
```

**b) Converting Phase**
```python
# Update progress: loaded, now converting
if progress_callback:
    progress_callback(symbol, 'converting', len(df), '', total_ticks=len(df))
    if live_display and table_creator:
        live_display.update(table_creator())
```

**c) Complete Phase**
```python
# Update progress: complete
if progress_callback:
    progress_callback(symbol, 'complete', len(df), 
                     f'Converted in {conversion_time:.2f}s ({ticks_per_sec:,.0f} ticks/sec)', 
                     total_ticks=len(df))
    if live_display and table_creator:
        live_display.update(table_creator())
```

**d) Error Phase**
```python
if not cache_path.exists():
    if progress_callback:
        progress_callback(symbol, 'error', 0, 'Cache file not found')
        if live_display and table_creator:
            live_display.update(table_creator())
```

## Display States

### State 1: Initial Loading
```
┌─ 📊 Tick Timeline Loading ─────────────────────────────────┐
│ Symbols: 0/5 | Ticks: 0/0                                  │
└─────────────────────────────────────────────────────────────┘
Symbol      Status                                      Ticks
EURUSD      ⏳ Loading from cache...                     0
GBPUSD      ○ Waiting...                                 0
USDJPY      ○ Waiting...                                 0
AUDUSD      ○ Waiting...                                 0
NZDUSD      ○ Waiting...                                 0
```

### State 2: Converting
```
┌─ 📊 Tick Timeline Loading ─────────────────────────────────┐
│ Symbols: 0/5 | Ticks: 6,517,963/6,517,963                 │
└─────────────────────────────────────────────────────────────┘
Symbol      Status                                      Ticks
EURUSD      ⚡ Converting to timeline...                 6,517,963
GBPUSD      ○ Waiting...                                 0
USDJPY      ○ Waiting...                                 0
AUDUSD      ○ Waiting...                                 0
NZDUSD      ○ Waiting...                                 0
```

### State 3: Mid-Loading (Some Complete)
```
┌─ 📊 Tick Timeline Loading ─────────────────────────────────┐
│ Symbols: 2/5 | Ticks: 11,752,086/25,000,000               │
└─────────────────────────────────────────────────────────────┘
Symbol      Status                                      Ticks
EURUSD      ✓ Converted in 2.45s (2,661,209 ticks/sec)  6,517,963
GBPUSD      ✓ Converted in 1.98s (2,643,496 ticks/sec)  5,234,123
USDJPY      ⏳ Loading from cache...                     0
AUDUSD      ○ Waiting...                                 0
NZDUSD      ○ Waiting...                                 0
```

### State 4: All Complete
```
┌─ 📊 Tick Timeline Loading ─────────────────────────────────┐
│ Symbols: 5/5 | Ticks: 25,000,000/25,000,000               │
└─────────────────────────────────────────────────────────────┘
Symbol      Status                                      Ticks
EURUSD      ✓ Converted in 2.45s (2,661,209 ticks/sec)  6,517,963
GBPUSD      ✓ Converted in 1.98s (2,643,496 ticks/sec)  5,234,123
USDJPY      ✓ Converted in 2.12s (3,058,717 ticks/sec)  6,482,481
AUDUSD      ✓ Converted in 1.87s (2,789,234 ticks/sec)  5,217,890
NZDUSD      ✓ Converted in 1.65s (2,912,345 ticks/sec)  4,805,369
```

### State 5: With Errors
```
┌─ 📊 Tick Timeline Loading ─────────────────────────────────┐
│ Symbols: 4/5 | Ticks: 20,194,631/20,194,631               │
└─────────────────────────────────────────────────────────────┘
Symbol      Status                                      Ticks
EURUSD      ✓ Converted in 2.45s (2,661,209 ticks/sec)  6,517,963
GBPUSD      ✓ Converted in 1.98s (2,643,496 ticks/sec)  5,234,123
USDJPY      ✓ Converted in 2.12s (3,058,717 ticks/sec)  6,482,481
AUDUSD      ✗ Cache file not found                       0
NZDUSD      ✓ Converted in 1.65s (2,912,345 ticks/sec)  4,805,369
```

## Status Icons

- **⏳** - Loading from cache (reading parquet file)
- **⚡** - Converting to timeline (DataFrame → GlobalTick objects)
- **✓** - Complete (with performance metrics)
- **✗** - Error (with error message)
- **○** - Waiting (not started yet)

## Console Output

The display also shows console messages for key milestones:

```
================================================================================
STEP 4.5: Loading Tick Timeline
================================================================================

Using TRADITIONAL mode (all ticks loaded into memory)
  Memory usage: ~20-30 GB for full year backtest

[Live progress table here]

✓ Global tick timeline initialized
```

## Benefits

### 1. **Better User Experience**
- Real-time visual feedback
- Clear progress indication
- Easy to monitor long-running loads

### 2. **Performance Visibility**
- Shows conversion speed (ticks/sec)
- Helps identify slow symbols
- Useful for performance tuning

### 3. **Error Detection**
- Errors are immediately visible
- Clear error messages
- Easy to identify problematic symbols

### 4. **Consistency**
- Matches STEP 2 data loading display
- Familiar interface for users
- Professional appearance

## Backward Compatibility

The enhancement is fully backward compatible:
- ✅ Progress callback is optional (defaults to None)
- ✅ Works without live display (falls back to log messages)
- ✅ No breaking changes to API
- ✅ Existing code continues to work

**Without progress display**:
```python
broker.load_ticks_from_cache_files(tick_cache_files)
```

**With progress display**:
```python
broker.load_ticks_from_cache_files(
    tick_cache_files, 
    progress_callback=callback, 
    live_display=live, 
    table_creator=creator
)
```

## Code Location

**Files Modified**:
- `backtest.py` (lines ~1380-1499) - Added Rich Live display for STEP 4.5
- `src/backtesting/engine/simulated_broker.py` (lines ~515-591) - Enhanced `load_ticks_from_cache_files()` with progress callbacks

## Testing

### Verify Display Works

Run a backtest with tick data enabled and observe:

1. **STEP 4.5 header**: Shows in cyan with console formatting
2. **Mode message**: Shows streaming vs traditional mode
3. **Progress table**: Updates in real-time as symbols load
4. **Status transitions**: Waiting → Loading → Converting → Complete
5. **Summary updates**: Symbols and ticks counts increase
6. **Completion message**: Shows when all symbols loaded

### Expected Behavior

- ✅ Table updates every 250ms (4 times per second)
- ✅ Status icons change as loading progresses
- ✅ Tick counts increase during conversion
- ✅ Performance metrics shown when complete
- ✅ Errors displayed clearly if any occur

## Performance Impact

Minimal performance impact:
- Progress updates are lightweight (just dict updates)
- Table rendering happens at 4 FPS (not every tick)
- No additional I/O or computation
- Negligible overhead compared to tick loading

## Memory Optimization: Limited Candle Seeding

### Problem

Previously, the candle builders were seeded with **ALL** historical candles:
```python
historical_df = self.symbol_data[data_key].copy()  # Loads entire history!
```

For a full year backtest:
- **H4**: 1998 candles (~333 days)
- **H1**: 7992 candles (~333 days)
- **M15**: 31968 candles (~333 days)
- **M5**: 95904 candles (~333 days)
- **M1**: 479520 candles (~333 days)

This defeats the purpose of day-by-day streaming!

### Solution

Now only seeds with **LIMITED** lookback period:

```python
max_lookback_candles = {
    'M1': 500,   # ~8 hours of M1 candles
    'M5': 500,   # ~42 hours of M5 candles
    'M15': 500,  # ~5 days of M15 candles
    'H1': 500,   # ~21 days of H1 candles
    'H4': 200    # ~33 days of H4 candles
}

# Take only the last N candles
if len(full_historical_df) > max_candles:
    historical_df = full_historical_df.iloc[-max_candles:].copy()
```

### Benefits

- ✅ **Reduced memory usage** - only loads recent candles for seeding
- ✅ **Faster initialization** - doesn't copy entire historical dataset
- ✅ **Sufficient for indicators** - 200-500 candles is enough for most indicators
- ✅ **True day-by-day loading** - doesn't load entire year upfront

### Log Output

**Before**:
```
2025-01-01 00:00:00 UTC | INFO     |   ✓ BTCJPY H4: Seeded with 1998 historical candles
```

**After**:
```
2025-01-01 00:00:00 UTC | INFO     |   ✓ BTCJPY H4: Seeded with 200 recent candles (limited from 1998 total)
```

## Summary

Successfully added Rich Live progress display for STEP 4.5 (Loading Tick Timeline):
- ✅ **Real-time progress** - shows loading status for each symbol
- ✅ **Performance metrics** - displays conversion speed (ticks/sec)
- ✅ **Clear summary** - shows overall progress (symbols and ticks)
- ✅ **Error visibility** - errors are immediately visible
- ✅ **Consistent UX** - matches STEP 2 data loading display
- ✅ **Backward compatible** - no breaking changes
- ✅ **Memory optimized** - limited candle seeding (200-500 candles vs entire history)

The display provides clear visibility into the tick timeline loading process, making it easy to monitor progress and identify any issues during long-running backtests.

