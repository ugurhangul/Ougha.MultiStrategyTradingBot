# Multi-Timeframe Backtesting Fix

## Issue

When running backtests, strategies were unable to retrieve reference candles in higher timeframes (M15, H4):

```
13:45:00 UTC | ERROR    | Failed to resample GBPCHF to M15: "Column(s) ['volume'] do not exist"
13:45:00 UTC | WARNING  | Could not resample GBPCHF to M15
13:45:00 UTC | WARNING  | [GBPCHF] [TB|15M_1M] Could not retrieve M15 candles for fallback [15M_1M]
13:45:00 UTC | ERROR    | Failed to resample GBPCHF to H4: "Column(s) ['volume'] do not exist"
```

## Root Cause

The `SimulatedBroker` was trying to resample M1 data to higher timeframes (M15, H4), but:
1. **Resampling is less accurate** than using actual MT5 data
2. **Some symbols don't have 'volume' column** (only 'tick_volume'), causing resampling errors
3. **Resampling adds complexity** and potential bugs

## Solution

**Changed approach from resampling to fetching all timeframes directly from MT5:**

### 1. Load All Timeframes from MT5

Instead of loading only M1 and resampling, now we load all required timeframes:
- **M1**: Base timeframe for breakout detection (15M_1M, 4H_5M) and HFT
- **M5**: Breakout detection (4H_5M range), ATR calculation, HFT trend filter
- **M15**: Reference candle (15M_1M range)
- **H4**: Reference candle (4H_5M range)

### 2. Updated SimulatedBroker Storage

Changed from single timeframe storage to multi-timeframe storage:

**Before:**
```python
self.symbol_data: Dict[str, pd.DataFrame] = {}  # symbol -> DataFrame
```

**After:**
```python
self.symbol_data: Dict[Tuple[str, str], pd.DataFrame] = {}  # (symbol, timeframe) -> DataFrame
```

### 3. Updated load_symbol_data()

Added `timeframe` parameter to load data for specific timeframes:

```python
def load_symbol_data(self, symbol: str, data: pd.DataFrame, 
                     symbol_info: Dict, timeframe: str = "M1"):
    """Load historical data for a symbol and timeframe."""
    # Store data with (symbol, timeframe) key
    self.symbol_data[(symbol, timeframe)] = data.copy()
```

### 4. Updated get_candles()

Removed resampling logic and use pre-loaded data directly:

```python
def get_candles(self, symbol: str, timeframe: str, count: int = 100):
    """Get historical candles for a symbol and timeframe."""
    # Check if we have data for this symbol and timeframe
    data_key = (symbol, timeframe)
    if data_key not in self.symbol_data:
        return None
    
    # Get the full dataset for this timeframe
    full_data = self.symbol_data[data_key]
    
    # Filter by current simulation time
    # ... (returns data up to current time)
```

### 5. Updated backtest.py

Changed configuration to load multiple timeframes:

**Before:**
```python
TIMEFRAME = "M1"  # Single timeframe

for symbol in symbols:
    result = data_loader.load_from_mt5(symbol, TIMEFRAME, start, end)
    symbol_data[symbol] = df
```

**After:**
```python
TIMEFRAMES = ["M1", "M5", "M15", "H4"]  # Multiple timeframes

for symbol in symbols:
    for timeframe in TIMEFRAMES:
        result = data_loader.load_from_mt5(symbol, timeframe, start, end)
        symbol_data[(symbol, timeframe)] = df
```

## Benefits

### 1. More Accurate Data
- ✅ Uses actual MT5 candles instead of resampled data
- ✅ Proper OHLC values from broker
- ✅ Accurate volume/tick_volume data

### 2. No Resampling Errors
- ✅ No "Column(s) ['volume'] do not exist" errors
- ✅ Works with all symbols (Forex, indices, commodities)
- ✅ Handles symbols with only tick_volume

### 3. Simpler Code
- ✅ Removed complex resampling logic (~120 lines)
- ✅ Cleaner data storage structure
- ✅ Easier to debug and maintain

### 4. Better Performance
- ✅ No runtime resampling overhead
- ✅ Data loaded once at startup
- ✅ Fast lookups with (symbol, timeframe) keys

## Files Modified

### 1. `src/backtesting/engine/simulated_broker.py`
- Changed `symbol_data` from `Dict[str, DataFrame]` to `Dict[Tuple[str, str], DataFrame]`
- Updated `load_symbol_data()` to accept `timeframe` parameter
- Removed resampling methods (`_timeframe_to_resample_rule`, `_resample_data`, `_get_resampled_data`)
- Updated `get_candles()` to use pre-loaded data with (symbol, timeframe) keys
- Updated `get_latest_candle()` to support multiple timeframes and handle empty timeframe string
- Updated `advance_time()` to use `(symbol, 'M1')` key instead of `symbol`
- Updated `get_start_time()` to iterate over `(symbol, timeframe)` tuples
- Updated `get_progress()` to use `(symbol, 'M1')` key
- Updated `is_data_available()` to use `(symbol, 'M1')` key

### 2. `backtest.py`
- Changed `TIMEFRAME` to `TIMEFRAMES = ["M1", "M5", "M15", "H4"]`
- Updated data loading loop to load all timeframes
- Updated broker initialization to load all timeframes
- Updated logging to show timeframe loading progress
- Fixed configuration display to show `TIMEFRAMES` instead of `TIMEFRAME`

## Testing

Run backtest to verify:
```bash
python backtest.py
```

Expected output:
```
NOTE: Loading 4 timeframes from MT5 for accurate simulation
  Timeframes: M1, M5, M15, H4
  - M1: Base timeframe for breakout detection and HFT
  - M5: Breakout detection (4H_5M), ATR, HFT trend filter
  - M15: Reference candle (15M_1M range)
  - H4: Reference candle (4H_5M range)

Loading EURUSD...
  ✓ EURUSD M1: 20,160 bars loaded
  ✓ EURUSD M5: 4,032 bars loaded
  ✓ EURUSD M15: 1,344 bars loaded
  ✓ EURUSD H4: 84 bars loaded
```

## Summary

✅ **Removed resampling - now fetching all timeframes from MT5**  
✅ **More accurate data using actual broker candles**  
✅ **No more volume column errors**  
✅ **Simpler, cleaner code**  
✅ **Better performance**  
✅ **Strategies can retrieve M1, M5, M15, H4 data correctly**  

The custom backtest engine now loads all required timeframes directly from MT5 for maximum accuracy!

