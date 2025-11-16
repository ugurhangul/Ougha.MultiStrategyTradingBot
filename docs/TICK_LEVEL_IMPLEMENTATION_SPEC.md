# Tick-Level Backtesting Implementation Specification

**Date**: 2025-11-16  
**Status**: Technical Specification  
**Related**: [TICK_LEVEL_BACKTESTING_ANALYSIS.md](TICK_LEVEL_BACKTESTING_ANALYSIS.md)

---

## 1. Data Structures

### 1.1 Tick Data Format

```python
@dataclass
class TickData:
    """Single tick data point."""
    time: datetime          # Timestamp (UTC)
    bid: float             # Bid price
    ask: float             # Ask price
    last: float            # Last trade price
    volume: int            # Tick volume
    spread: float          # Calculated spread (ask - bid)
    
    @property
    def mid(self) -> float:
        """Mid price (average of bid/ask)."""
        return (self.bid + self.ask) / 2.0
```

### 1.2 Tick Storage (SimulatedBroker)

```python
class SimulatedBroker:
    def __init__(self, ...):
        # NEW: Tick-level data storage
        self.symbol_ticks: Dict[str, pd.DataFrame] = {}  # symbol -> tick DataFrame
        self.tick_indices: Dict[str, int] = {}           # symbol -> current tick index
        self.tick_timestamps: Dict[str, np.ndarray] = {} # symbol -> sorted timestamps (optimization)
        
        # NEW: Current tick cache (for fast access)
        self.current_ticks: Dict[str, TickData] = {}     # symbol -> current tick
        
        # EXISTING: Candle data (now derived from ticks)
        self.symbol_candles: Dict[Tuple[str, str], pd.DataFrame] = {}  # (symbol, tf) -> candles
        self.candle_cache_valid: Dict[Tuple[str, str], datetime] = {}  # Cache invalidation
```

### 1.3 Time Granularity

```python
# Configuration option
class BacktestConfig:
    time_granularity: str = "second"  # Options: "tick", "second", "minute"
    
    # If "second": advance 1 second at a time, process all ticks in that second
    # If "tick": advance tick-by-tick (slowest, highest fidelity)
    # If "minute": current behavior (backward compatibility)
```

---

## 2. BacktestDataLoader Changes

### 2.1 New Method: `load_ticks_from_mt5()`

```python
def load_ticks_from_mt5(
    self, 
    symbol: str, 
    start_date: datetime, 
    end_date: datetime,
    tick_type: int = mt5.COPY_TICKS_INFO,  # INFO ticks (bid/ask changes)
    force_refresh: bool = False
) -> Optional[Tuple[pd.DataFrame, Dict]]:
    """
    Load tick data from MT5 with caching support.
    
    Args:
        symbol: Symbol name
        start_date: Start date (UTC)
        end_date: End date (UTC)
        tick_type: MT5 tick type (COPY_TICKS_ALL, COPY_TICKS_INFO, COPY_TICKS_TRADE)
        force_refresh: Bypass cache
        
    Returns:
        Tuple of (DataFrame with tick data, symbol_info dict) or None
        
    DataFrame columns:
        - time: datetime (UTC)
        - bid: float
        - ask: float
        - last: float
        - volume: int
        - spread: float (calculated: ask - bid)
    """
    # Check cache first
    if self.use_cache and not force_refresh:
        cached_data = self.cache.load_ticks_from_cache(symbol, start_date, end_date)
        if cached_data is not None:
            return cached_data
    
    # Download from MT5
    result = self._download_ticks_from_mt5(symbol, start_date, end_date, tick_type)
    
    # Save to cache
    if result is not None and self.use_cache:
        df, symbol_info = result
        self.cache.save_ticks_to_cache(symbol, start_date, end_date, df, symbol_info)
    
    return result
```

### 2.2 Tick-to-Candle Conversion

```python
def build_candles_from_ticks(
    ticks: pd.DataFrame, 
    timeframe: str,
    up_to_time: Optional[datetime] = None
) -> pd.DataFrame:
    """
    Build OHLCV candles from tick data.
    
    Args:
        ticks: DataFrame with tick data (time, bid, ask, last, volume)
        timeframe: Target timeframe (M1, M5, M15, H1, H4, D1)
        up_to_time: Only include ticks up to this time (for backtesting)
        
    Returns:
        DataFrame with OHLCV candles
        
    Algorithm:
        1. Use 'last' price for OHLC (actual trade prices)
        2. Use 'bid' if 'last' is 0 (no trades, use bid)
        3. Resample by timeframe
        4. Aggregate: open=first, high=max, low=min, close=last, volume=sum
    """
    if up_to_time is not None:
        ticks = ticks[ticks['time'] <= up_to_time]
    
    # Use 'last' price, fallback to 'bid' if last=0
    ticks['price'] = ticks['last'].where(ticks['last'] > 0, ticks['bid'])
    
    # Set time as index for resampling
    ticks = ticks.set_index('time')
    
    # Resample to target timeframe
    resample_rule = TimeframeConverter.to_pandas_resample_rule(timeframe)
    
    candles = ticks.resample(resample_rule).agg({
        'price': ['first', 'max', 'min', 'last'],
        'volume': 'sum',
        'bid': 'last',  # Last bid in candle
        'ask': 'last',  # Last ask in candle
    })
    
    # Flatten multi-level columns
    candles.columns = ['open', 'high', 'low', 'close', 'tick_volume', 'bid', 'ask']
    candles = candles.reset_index()
    
    # Calculate spread
    candles['spread'] = (candles['ask'] - candles['bid']) / symbol_info['point']
    
    return candles
```

---

## 3. SimulatedBroker Changes

### 3.1 Load Tick Data

```python
def load_tick_data(
    self, 
    symbol: str, 
    ticks: pd.DataFrame, 
    symbol_info: Dict
):
    """
    Load tick data for a symbol.
    
    Args:
        symbol: Symbol name
        ticks: DataFrame with tick data (time, bid, ask, last, volume)
        symbol_info: Symbol information dict
    """
    # Store tick data
    self.symbol_ticks[symbol] = ticks.copy()
    
    # Initialize tick index
    self.tick_indices[symbol] = 0
    
    # Pre-compute timestamps for fast lookup (OPTIMIZATION)
    self.tick_timestamps[symbol] = ticks['time'].to_numpy()
    
    # Store symbol info (same as before)
    if symbol not in self.symbol_info:
        self.symbol_info[symbol] = SimulatedSymbolInfo(...)
    
    self.logger.info(f"Loaded {len(ticks)} ticks for {symbol}")
```

### 3.2 Advance Time (Second-by-Second)

```python
def advance_global_time_tick_mode(self) -> bool:
    """
    Advance global time by 1 second (tick-level mode).
    
    Process all ticks that occurred in the current second for all symbols.
    Update current_ticks cache with the last tick in each second.
    
    Returns:
        True if time advanced, False if all symbols exhausted
    """
    with self.time_lock:
        if self.current_time is None:
            return False
        
        # Target time: current_time + 1 second
        next_time = self.current_time + timedelta(seconds=1)
        
        has_any_data = False
        
        # Process ticks for each symbol in the current second
        for symbol in self.tick_indices.keys():
            ticks_df = self.symbol_ticks.get(symbol)
            if ticks_df is None:
                continue
            
            current_idx = self.tick_indices[symbol]
            
            # Find all ticks in the current second [current_time, next_time)
            tick_times = self.tick_timestamps[symbol]
            
            # Binary search for efficiency (OPTIMIZATION)
            start_idx = current_idx
            end_idx = np.searchsorted(tick_times[start_idx:], next_time, side='left') + start_idx
            
            if start_idx < end_idx:
                # Process ticks in this second
                second_ticks = ticks_df.iloc[start_idx:end_idx]
                
                # Update current tick to LAST tick in this second
                last_tick_row = second_ticks.iloc[-1]
                self.current_ticks[symbol] = TickData(
                    time=last_tick_row['time'],
                    bid=last_tick_row['bid'],
                    ask=last_tick_row['ask'],
                    last=last_tick_row['last'],
                    volume=last_tick_row['volume'],
                    spread=last_tick_row['ask'] - last_tick_row['bid']
                )
                
                # Update tick index
                self.tick_indices[symbol] = end_idx
                
                # Check for SL/TP hits on EACH tick in this second
                self._check_sl_tp_on_ticks(symbol, second_ticks)
                
                has_any_data = True
            
            # Check if symbol has more data
            if end_idx < len(tick_times):
                has_any_data = True
        
        # Advance global time
        self.current_time = next_time
        
        # Invalidate candle cache (candles need to be rebuilt)
        self.candle_cache_valid.clear()
        
        return has_any_data
```

### 3.3 Get Current Price (from Tick)

```python
def get_current_price(self, symbol: str, price_type: str = 'bid') -> Optional[float]:
    """
    Get current price from tick data.
    
    Args:
        symbol: Symbol name
        price_type: 'bid', 'ask', or 'mid'
        
    Returns:
        Current price or None
    """
    tick = self.current_ticks.get(symbol)
    if tick is None:
        return None
    
    if price_type == 'bid':
        return tick.bid
    elif price_type == 'ask':
        return tick.ask
    elif price_type == 'mid':
        return tick.mid
    else:
        return tick.bid  # Default
```

### 3.4 Get Candles (Build from Ticks)

```python
def get_candles(self, symbol: str, timeframe: str, count: int = 100) -> Optional[pd.DataFrame]:
    """
    Get OHLCV candles built from tick data.
    
    Uses caching to avoid rebuilding candles on every call.
    Cache is invalidated when time advances.
    
    Args:
        symbol: Symbol name
        timeframe: Timeframe (M1, M5, M15, H1, H4)
        count: Number of candles to return
        
    Returns:
        DataFrame with OHLCV candles or None
    """
    cache_key = (symbol, timeframe)
    
    # Check if cache is valid
    if cache_key in self.candle_cache_valid:
        if self.candle_cache_valid[cache_key] == self.current_time:
            # Cache is valid, return cached candles
            cached = self.symbol_candles.get(cache_key)
            if cached is not None:
                return cached.tail(count).copy()
    
    # Build candles from ticks
    ticks_df = self.symbol_ticks.get(symbol)
    if ticks_df is None:
        return None
    
    # Build candles up to current time
    candles = build_candles_from_ticks(
        ticks_df, 
        timeframe, 
        up_to_time=self.current_time
    )
    
    # Cache the result
    self.symbol_candles[cache_key] = candles
    self.candle_cache_valid[cache_key] = self.current_time
    
    return candles.tail(count).copy()
```

### 3.5 Check SL/TP on Ticks

```python
def _check_sl_tp_on_ticks(self, symbol: str, ticks: pd.DataFrame):
    """
    Check if any positions hit SL/TP during the ticks in this second.
    
    This is CRITICAL for accurate backtesting - we need to check SL/TP
    on every tick, not just at candle close.
    
    Args:
        symbol: Symbol name
        ticks: DataFrame with ticks in the current second
    """
    with self.position_lock:
        # Get positions for this symbol
        symbol_positions = [
            (ticket, pos) for ticket, pos in self.positions.items()
            if pos.symbol == symbol
        ]
        
        if not symbol_positions:
            return  # No positions for this symbol
        
        # Check each tick
        for _, tick_row in ticks.iterrows():
            tick_bid = tick_row['bid']
            tick_ask = tick_row['ask']
            tick_time = tick_row['time']
            
            positions_to_close = []
            
            for ticket, position in symbol_positions:
                # Check SL/TP hit
                if position.position_type == PositionType.BUY:
                    # BUY position: close at bid price
                    if position.sl > 0 and tick_bid <= position.sl:
                        # Stop loss hit
                        positions_to_close.append((ticket, tick_bid, 'SL', tick_time))
                    elif position.tp > 0 and tick_bid >= position.tp:
                        # Take profit hit
                        positions_to_close.append((ticket, tick_bid, 'TP', tick_time))
                
                else:  # SELL position
                    # SELL position: close at ask price
                    if position.sl > 0 and tick_ask >= position.sl:
                        # Stop loss hit
                        positions_to_close.append((ticket, tick_ask, 'SL', tick_time))
                    elif position.tp > 0 and tick_ask <= position.tp:
                        # Take profit hit
                        positions_to_close.append((ticket, tick_ask, 'TP', tick_time))
            
            # Close positions that hit SL/TP
            for ticket, close_price, reason, close_time in positions_to_close:
                self._close_position_at_price(ticket, close_price, reason, close_time)
```

---

## 4. TimeController Changes

### 4.1 Time Granularity Configuration

```python
class TimeController:
    def __init__(
        self, 
        symbols: List[str], 
        mode: TimeMode = TimeMode.MAX_SPEED,
        granularity: str = "second",  # NEW: "tick", "second", "minute"
        broker=None
    ):
        self.granularity = granularity
        # ... rest of init
```

### 4.2 Time Advancement

```python
def wait_for_next_step(self, participant: str) -> bool:
    """
    Wait for all participants to be ready, then advance time.
    
    Time advancement depends on granularity:
    - "minute": advance by 1 minute (current behavior)
    - "second": advance by 1 second (tick-level mode)
    - "tick": advance to next tick (highest fidelity, slowest)
    """
    # ... existing barrier logic ...
    
    # Advance time based on granularity
    if self.broker is not None:
        if self.granularity == "second":
            if not self.broker.advance_global_time_tick_mode():
                self.running = False
        elif self.granularity == "minute":
            if not self.broker.advance_global_time():  # Existing method
                self.running = False
        # "tick" mode: TBD (most complex)
    
    # ... rest of method
```

---

## 5. Configuration

### 5.1 backtest.py Configuration

```python
# Tick-Level Backtesting Configuration
USE_TICK_DATA = True  # Set to False for candle-based backtesting (backward compatibility)
TIME_GRANULARITY = "second"  # Options: "tick", "second", "minute"

# Tick data type
TICK_TYPE = mt5.COPY_TICKS_INFO  # INFO ticks (bid/ask changes) - recommended
# TICK_TYPE = mt5.COPY_TICKS_ALL  # All ticks (slower, more data)
# TICK_TYPE = mt5.COPY_TICKS_TRADE  # Trade ticks only (less data, but misses bid/ask)
```

---

## 6. Performance Optimizations

### 6.1 Tick Batching
- Process ticks in 1-second batches (not individual ticks)
- Reduces barrier synchronization overhead

### 6.2 Binary Search for Tick Lookup
- Use `np.searchsorted()` for fast tick range queries
- O(log N) instead of O(N) for finding ticks in time range

### 6.3 Candle Caching
- Cache built candles, invalidate on time advancement
- Avoid rebuilding candles on every `get_candles()` call

### 6.4 Lazy SL/TP Checking
- Only check SL/TP for symbols with open positions
- Skip symbols with no positions

### 6.5 Chunked Data Loading
- Load tick data day-by-day to avoid memory overflow
- Process one day at a time for long backtests

---

## 7. Backward Compatibility

### 7.1 Configuration Flag

```python
if USE_TICK_DATA:
    # Load tick data
    ticks, symbol_info = data_loader.load_ticks_from_mt5(...)
    broker.load_tick_data(symbol, ticks, symbol_info)
else:
    # Load candle data (existing behavior)
    df, symbol_info = data_loader.load_from_mt5(...)
    broker.load_symbol_data(symbol, df, symbol_info, timeframe)
```

### 7.2 Strategy Compatibility

**No changes required** - strategies use the same interface:
- `get_candles()`: Returns OHLCV (built from ticks or loaded directly)
- `get_tick()`: Returns tick data (real or simulated)
- `get_current_price()`: Returns price (from tick or candle)

---

## 8. Testing Plan

### 8.1 Unit Tests
- Test tick-to-candle conversion accuracy
- Test SL/TP hit detection on ticks
- Test time advancement logic

### 8.2 Integration Tests
- Run 1-day backtest with tick data
- Compare results: tick-level vs candle-level
- Validate HFT strategy performance

### 8.3 Performance Tests
- Measure backtest duration (1-day, 7-day)
- Profile memory usage
- Identify bottlenecks

---

## 9. Success Criteria

✅ **Functional**:
- [ ] Tick data loads successfully from MT5
- [ ] Candles built from ticks match MT5 candles
- [ ] SL/TP hits detected accurately (intra-candle)
- [ ] HFT strategy receives real tick data

✅ **Performance**:
- [ ] 7-day backtest completes in < 60 minutes
- [ ] Memory usage < 500 MB

✅ **Compatibility**:
- [ ] Existing strategies work unchanged
- [ ] Candle-based mode still available (backward compatibility)

---

## 10. Worker Thread Synchronization (FAQ)

### Q: How do we synchronize workers when advancing tick-by-tick or second-by-second?

**A: The existing barrier pattern already handles this - no changes needed!**

### Key Insight: Barrier Pattern is Time-Granularity Agnostic

The barrier synchronization works the same whether we advance by:
- **1 minute** (current)
- **1 second** (proposed)
- **1 tick** (future)

**Current Flow (Minute-by-Minute)**:
```
All threads process current minute → Wait at barrier →
Last thread advances time by 1 minute → All threads released → Repeat
```

**New Flow (Second-by-Second)**:
```
All threads process current second → Wait at barrier →
Last thread advances time by 1 second → All threads released → Repeat
```

**The synchronization logic is identical!**

### What Changes

**SimulatedBroker**:
```python
# OLD: Advance by 1 minute
def advance_global_time(self) -> bool:
    self.current_time += timedelta(minutes=1)
    # ... update indices ...

# NEW: Advance by 1 second
def advance_global_time_second_by_second(self) -> bool:
    self.current_time += timedelta(seconds=1)
    # ... process ticks in this second ...
```

**TimeController**:
```python
# Only change: which method to call
if self.granularity == TimeGranularity.SECOND:
    success = self.broker.advance_global_time_second_by_second()
else:
    success = self.broker.advance_global_time()
```

### What Doesn't Change

- ✅ Barrier synchronization logic
- ✅ Symbol worker thread structure
- ✅ Position monitor thread
- ✅ Two-phase barrier pattern
- ✅ Thread safety guarantees

### Why This Works

The barrier pattern ensures:
1. **All threads finish** processing current time step before any thread advances
2. **Only one thread** advances time (atomically)
3. **All threads see** the new time before proceeding

**It doesn't matter** if "next time step" means:
- Next minute
- Next second
- Next tick

The synchronization guarantees are the same!

### No Race Conditions

**Scenario**: EURUSD thread finishes processing before GBPUSD thread

**Current (Minute)**:
- EURUSD waits at barrier
- GBPUSD finishes, reaches barrier
- Last thread advances time by 1 minute
- Both threads released, process next minute

**New (Second)**:
- EURUSD waits at barrier
- GBPUSD finishes, reaches barrier
- Last thread advances time by 1 second
- Both threads released, process next second

**Same synchronization, different time granularity!**

### Conclusion

**Synchronization is NOT a problem** for tick-level backtesting!

The existing barrier pattern is **time-granularity agnostic** and works perfectly for:
- Minute-by-minute (current)
- Second-by-second (proposed)
- Tick-by-tick (future)

**See**: [TICK_BY_TICK_SYNCHRONIZATION.md](TICK_BY_TICK_SYNCHRONIZATION.md) for detailed analysis.

