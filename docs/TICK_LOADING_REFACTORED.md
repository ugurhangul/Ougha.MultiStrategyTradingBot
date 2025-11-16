# Tick Loading Refactored to STEP 2

## Overview

Refactored tick data loading to happen in **STEP 2: Loading Historical Data** alongside candle data, instead of in a separate STEP 4.5.

## Changes Made

### Before (Old Structure)

```
STEP 2: Loading Historical Data
  ├─ Load candles for EURUSD (M1, M5, M15, H4)
  ├─ Load candles for GBPUSD (M1, M5, M15, H4)
  └─ Load candles for USDJPY (M1, M5, M15, H4)

STEP 4.5: Loading Tick Data for Tick-Level Backtesting
  ├─ Load ticks for EURUSD → Save to cache
  ├─ Load ticks for GBPUSD → Save to cache
  ├─ Load ticks for USDJPY → Save to cache
  └─ Merge global tick timeline
```

### After (New Structure)

```
STEP 2: Loading Historical Data
  ├─ Load candles for EURUSD (M1, M5, M15, H4)
  ├─ Load ticks for EURUSD → Save to cache ✨
  ├─ Load candles for GBPUSD (M1, M5, M15, H4)
  ├─ Load ticks for GBPUSD → Save to cache ✨
  ├─ Load candles for USDJPY (M1, M5, M15, H4)
  └─ Load ticks for USDJPY → Save to cache ✨

STEP 4.5: Loading Tick Timeline
  └─ Merge global tick timeline from cache files
```

## Benefits

### 1. Logical Organization
- **All data loading in one place** - Candles and ticks loaded together
- **Per-symbol loading** - Each symbol's data (candles + ticks) loaded sequentially
- **Clearer flow** - Data loading → Data processing → Timeline merging

### 2. Better Error Handling
- **Early detection** - If ticks fail to load, symbol is skipped immediately
- **Consistent validation** - Same validation logic for candles and ticks
- **No partial data** - Symbol either has all data (candles + ticks) or is skipped

### 3. Memory Efficiency
- **Immediate cleanup** - Tick DataFrames deleted right after caching
- **No duplicate storage** - Ticks saved to cache, then loaded into timeline
- **Lower peak memory** - Process one symbol at a time

### 4. Faster Debugging
- **See all data loading together** - Easier to spot missing data
- **Single log section** - All loading messages in STEP 2
- **Clear progress** - "Loading EURUSD... candles ✓ ticks ✓"

## Implementation Details

### STEP 2: Loading Historical Data

**Initialization** (before symbol loop):
```python
if USE_TICK_DATA:
    import MetaTrader5 as mt5
    tick_cache_dir = Path("data/ticks")
    tick_cache_dir.mkdir(parents=True, exist_ok=True)
    tick_type_flag = mt5.COPY_TICKS_ALL  # or INFO, TRADE
    tick_cache_files = {}
```

**Per-symbol loading** (inside symbol loop):
```python
for symbol in symbols:
    # Load candles for all timeframes
    for timeframe in TIMEFRAMES:
        df, info = data_loader.load_from_mt5(symbol, timeframe, ...)
        symbol_data[(symbol, timeframe)] = df
    
    # Load ticks (if tick mode enabled)
    if USE_TICK_DATA:
        ticks_df = data_loader.load_ticks_from_mt5(
            symbol, START_DATE, END_DATE, tick_type_flag, cache_dir
        )
        # Save cache file path
        tick_cache_files[symbol] = cache_file_path
        # Delete DataFrame immediately
        del ticks_df
```

**Summary** (after symbol loop):
```python
logger.info(f"Successfully loaded {len(symbols)} symbols")
if USE_TICK_DATA:
    logger.info(f"Tick data loaded for {len(tick_cache_files)}/{len(symbols)} symbols")
    log_memory(logger, "after tick data loading")
```

### STEP 4.5: Loading Tick Timeline

**Simplified to just timeline merging**:
```python
if USE_TICK_DATA:
    logger.info("STEP 4.5: Loading Tick Timeline")
    logger.info(f"Loading ticks from cache files into global timeline...")
    logger.info(f"  Symbols with tick data: {len(tick_cache_files)}/{len(symbols)}")
    
    # Load from cache files directly into timeline
    broker.load_ticks_from_cache_files(tick_cache_files)
    
    logger.info("  ✓ Global tick timeline loaded and sorted")
```

## Example Output

### STEP 2: Loading Historical Data

```
================================================================================
STEP 2: Loading Historical Data
================================================================================
Loading data from 2025-11-13 (1 day buffer)
Backtest execution: 2025-11-14 to 2025-11-15

Data caching: ENABLED
  Cache directory: data/cache

Tick data mode: ENABLED (ALL)
  Tick cache directory: C:\repos\...\data\ticks
  (Ticks will be saved/loaded from cache for faster subsequent runs)

Loading EURUSD...
  ✓ EURUSD M1: 1,440 bars loaded
  ✓ EURUSD M5: 288 bars loaded
  ✓ EURUSD M15: 96 bars loaded
  ✓ EURUSD H4: 6 bars loaded
  Loading tick data for EURUSD...
    Loading EURUSD ticks from cache: EURUSD_20251114_20251115_ALL.parquet
    ✓ Loaded 52,341 ticks from cache
  ✓ EURUSD: 52,341 ticks loaded
  ✓ EURUSD: All 4 timeframes loaded successfully

Loading GBPUSD...
  ✓ GBPUSD M1: 1,440 bars loaded
  ✓ GBPUSD M5: 288 bars loaded
  ✓ GBPUSD M15: 96 bars loaded
  ✓ GBPUSD H4: 6 bars loaded
  Loading tick data for GBPUSD...
    Loading GBPUSD ticks from cache: GBPUSD_20251114_20251115_ALL.parquet
    ✓ Loaded 48,123 ticks from cache
  ✓ GBPUSD: 48,123 ticks loaded
  ✓ GBPUSD: All 4 timeframes loaded successfully

Successfully loaded 2 symbols with all 4 timeframes
Symbols to backtest: EURUSD, GBPUSD

Tick data loaded for 2/2 symbols
  💾 Memory usage (after tick data loading): 245.3 MB
```

### STEP 4.5: Loading Tick Timeline

```
================================================================================
STEP 4.5: Loading Tick Timeline
================================================================================
Loading ticks from cache files into global timeline...
  Symbols with tick data: 2/2
  💾 Memory usage (before timeline loading): 245.3 MB

============================================================
Loading ticks from cache files (memory-efficient mode)...
  Memory before loading: 245.3 MB
  Loading EURUSD from EURUSD_20251114_20251115_ALL.parquet...
    52,341 ticks loaded
  Loading GBPUSD from GBPUSD_20251114_20251115_ALL.parquet...
    48,123 ticks loaded
  Sorting 100,464 ticks chronologically...
  ✓ Global timeline created: 100,464 ticks
  Time range: 2025-11-14 00:00:01 to 2025-11-14 23:59:58
  Memory after loading: 395.8 MB
  Memory used: 150.5 MB
  Duration: 24.0 hours
  Average: 1.2 ticks/second
  Symbol distribution:
    EURUSD: 52,341 ticks (52.1%)
    GBPUSD: 48,123 ticks (47.9%)
============================================================

  ✓ Global tick timeline loaded and sorted
  💾 Memory usage (after timeline loading): 395.8 MB
```

## Files Modified

1. **`backtest.py`**
   - Moved tick loading initialization to STEP 2 (before symbol loop)
   - Added tick loading inside symbol loop (after candle loading)
   - Simplified STEP 4.5 to just timeline merging
   - Added tick data summary at end of STEP 2

## Migration Notes

### No Breaking Changes
- Existing backtests continue to work
- Cache files remain compatible
- Same memory usage and performance

### Configuration
No changes needed - tick loading automatically happens in STEP 2 when:
```python
USE_TICK_DATA = True
```

### Validation
Tick loading now participates in symbol validation:
- If ticks fail to load for a symbol, that symbol is skipped
- Ensures all symbols have both candles AND ticks (if tick mode enabled)
- No partial data scenarios

## Summary

✅ **Tick loading moved to STEP 2** - Alongside candle loading  
✅ **Per-symbol loading** - Candles + ticks loaded together  
✅ **Better organization** - All data loading in one place  
✅ **Improved validation** - Early detection of missing tick data  
✅ **Memory efficient** - Immediate DataFrame cleanup  
✅ **Clearer logs** - See all data loading progress together  

