# Phase 5 Optimization Quick Reference

## Current Performance
- **Baseline**: 1,300 tps
- **After 18 Optimizations**: 20,000 tps (15.4x improvement)
- **Target**: 30,000-50,000 tps (1.5x-2.5x additional gain)

---

## Optimization Summary Table

| # | Name | Impact | Complexity | Risk | Priority | Status |
|---|------|--------|------------|------|----------|--------|
| 19 | Lazy Candle Building | 1.15x-1.25x | MEDIUM | MEDIUM | CRITICAL | ⏳ Pending |
| 20 | Direct NumPy Array Storage | 1.10x-1.15x | MEDIUM | LOW | HIGH | ⏳ Pending |
| 21 | Strategy-Level Candle Caching | 1.05x-1.10x | LOW | LOW | HIGH | ⏳ Pending |
| 22 | Circular Buffer for Candles | 1.02x-1.05x | MEDIUM | LOW | MEDIUM | ⏳ Pending |
| 23 | Batch Position Profit Updates | 1.02x-1.03x | LOW | LOW | MEDIUM | ⏳ Pending |
| 24 | Vectorized SL/TP Checking | 1.05x-1.10x | MEDIUM | LOW | MEDIUM | ⏳ Pending |
| 25 | Cython Compilation | 1.30x-1.80x | HIGH | MEDIUM | HIGH | ⏳ Pending |
| 26 | Parallel Symbol Processing | 4x-8x | HIGH | HIGH | MEDIUM | ⏳ Pending |

---

## Implementation Phases

### **Phase 5A: Quick Wins** (1-2 days)
**Target**: 22,000 tps (10% gain)

```
✅ Optimization #21: Strategy-Level Candle Caching
   - Add caching layer in BaseStrategy
   - Cache key: (timeframe, count, current_time)
   - Eliminates 60-80% of redundant get_candles() calls

✅ Optimization #23: Batch Position Profit Updates
   - Remove profit updates from _check_sl_tp_for_tick()
   - Calculate profit on-demand (lazy evaluation)
   - Update only when closing position or querying
```

**Files to Modify**:
- `src/strategy/base_strategy.py` (add caching)
- `src/backtesting/engine/simulated_broker.py` (lazy profit)

---

### **Phase 5B: Core Improvements** (3-5 days)
**Target**: 30,000 tps (50% gain)

```
✅ Optimization #19: Lazy Candle Building
   - Buffer ticks instead of building candles immediately
   - Build candles only when get_candles() is called
   - Reduces candle building by 95%

✅ Optimization #20: Direct NumPy Array Storage
   - Store candles as NumPy structured arrays
   - Return array views instead of DataFrames
   - Eliminates DataFrame creation overhead

✅ Optimization #24: Vectorized SL/TP Checking
   - Use NumPy for batch SL/TP checks
   - Process all positions of a symbol at once
   - 5-10x faster than Python loops
```

**Files to Modify**:
- `src/backtesting/engine/candle_builder.py` (lazy building, NumPy storage)
- `src/backtesting/engine/simulated_broker.py` (vectorized SL/TP)
- `src/strategy/*.py` (update to use NumPy arrays)

---

### **Phase 5C: Advanced** (1-2 weeks)
**Target**: 35,000-50,000 tps (75-150% gain)

```
✅ Optimization #25: Cython Compilation
   - Compile hot path functions to C
   - Target: add_tick(), _align_to_timeframe(), _check_sl_tp_for_tick()
   - 2-5x speedup for compiled functions

⚠️ Optimization #26: Parallel Symbol Processing
   - Process independent symbols in parallel
   - Use multiprocessing.Pool
   - 4-8x speedup on multi-core CPUs
   - HIGH RISK: Requires careful state management
```

**Files to Create**:
- `src/backtesting/engine/candle_builder.pyx` (Cython version)
- `src/backtesting/engine/simulated_broker_fast.pyx` (Cython version)
- `setup.py` (Cython build configuration)

---

## Code Examples

### Optimization #21: Strategy-Level Candle Caching

```python
# In src/strategy/base_strategy.py

class BaseStrategy:
    def __init__(self, ...):
        # Add candle cache
        self._candle_cache: Dict[Tuple[str, int, datetime], pd.DataFrame] = {}
    
    def get_candles_cached(self, timeframe: str, count: int = 100) -> Optional[pd.DataFrame]:
        """Get candles with strategy-level caching."""
        current_time = self.connector.get_current_time()
        cache_key = (timeframe, count, current_time)
        
        # Check cache
        if cache_key in self._candle_cache:
            return self._candle_cache[cache_key]
        
        # Cache miss - fetch and cache
        df = self.connector.get_candles(self.symbol, timeframe, count)
        self._candle_cache[cache_key] = df
        
        # Limit cache size (keep last 10 entries per timeframe)
        if len(self._candle_cache) > 50:
            # Remove oldest entries
            sorted_keys = sorted(self._candle_cache.keys(), key=lambda k: k[2])
            for old_key in sorted_keys[:10]:
                del self._candle_cache[old_key]
        
        return df
```

**Usage in strategies**:
```python
# Replace:
df = self.connector.get_candles(self.symbol, 'H4', count=2)

# With:
df = self.get_candles_cached('H4', count=2)
```

---

### Optimization #23: Batch Position Profit Updates

```python
# In src/backtesting/engine/simulated_broker.py

class PositionInfo:
    def __init__(self, ...):
        # Remove self.profit field
        # Calculate on-demand instead
        pass
    
    def get_profit(self, current_price: float, symbol_info) -> float:
        """Calculate profit on-demand (lazy evaluation)."""
        if self.position_type == PositionType.BUY:
            price_diff = current_price - self.open_price
        else:
            price_diff = self.open_price - current_price
        
        return (price_diff / symbol_info.tick_size) * symbol_info.tick_value * self.volume

# In _check_sl_tp_for_tick():
# REMOVE THIS LINE:
# self._update_position_profit(position)

# In _close_position_internal():
# Calculate profit only when closing:
position.profit = position.get_profit(close_price, self.symbol_info[position.symbol])
```

---

### Optimization #19: Lazy Candle Building

```python
# In src/backtesting/engine/candle_builder.py

class LazyMultiTimeframeCandleBuilder:
    def __init__(self, symbol: str, timeframes: List[str]):
        self.symbol = symbol
        self.timeframes = timeframes
        
        # Tick buffer (store raw ticks)
        self.tick_buffer: List[Tuple[float, int, datetime]] = []
        self.buffer_start_idx: int = 0  # Track which ticks have been processed
        
        # Completed candles
        self.completed_candles: Dict[str, List[CandleData]] = {tf: [] for tf in timeframes}
        
        # Track last build time for each timeframe
        self.last_build_time: Dict[str, Optional[datetime]] = {tf: None for tf in timeframes}
    
    def add_tick(self, price: float, volume: int, tick_time: datetime) -> set:
        """Buffer tick - don't build candles yet."""
        self.tick_buffer.append((price, volume, tick_time))
        
        # Trim buffer to prevent unbounded growth
        # Keep last 10,000 ticks (enough for ~3 hours at 1 tick/second)
        if len(self.tick_buffer) > 10000:
            self.tick_buffer = self.tick_buffer[-10000:]
            self.buffer_start_idx = 0
        
        return set()  # No candles built yet
    
    def get_candles(self, timeframe: str, count: int = 100) -> Optional[pd.DataFrame]:
        """Build candles on-demand from tick buffer."""
        # Check if we need to rebuild
        if self.tick_buffer and len(self.tick_buffer) > self.buffer_start_idx:
            # New ticks since last build - rebuild candles
            self._build_candles_from_buffer(timeframe)
            self.last_build_time[timeframe] = self.tick_buffer[-1][2]
        
        # Return cached candles
        return self._create_dataframe(timeframe, count)
    
    def _build_candles_from_buffer(self, timeframe: str):
        """Build candles for a specific timeframe from tick buffer."""
        # Process only new ticks since last build
        for i in range(self.buffer_start_idx, len(self.tick_buffer)):
            price, volume, tick_time = self.tick_buffer[i]
            
            # Determine candle boundary
            candle_start = self._align_to_timeframe(tick_time, timeframe)
            
            # Get or create candle builder
            if not self.current_builders[timeframe] or \
               self.current_builders[timeframe].start_time != candle_start:
                # Close previous candle
                if self.current_builders[timeframe]:
                    candle_data = self.current_builders[timeframe].to_candle_data()
                    if candle_data:
                        self.completed_candles[timeframe].append(candle_data)
                
                # Start new candle
                self.current_builders[timeframe] = CandleBuilder(timeframe, candle_start)
            
            # Add tick to candle
            self.current_builders[timeframe].add_tick(price, volume, tick_time)
        
        # Update buffer start index
        self.buffer_start_idx = len(self.tick_buffer)
```

---

### Optimization #20: Direct NumPy Array Storage

```python
# In src/backtesting/engine/candle_builder.py

class NumPyCandleBuilder:
    def __init__(self, symbol: str, timeframes: List[str]):
        self.symbol = symbol
        self.timeframes = timeframes
        
        # Define structured array dtype
        self.candle_dtype = np.dtype([
            ('time', 'datetime64[s]'),
            ('open', 'f8'),
            ('high', 'f8'),
            ('low', 'f8'),
            ('close', 'f8'),
            ('volume', 'i8')
        ])
        
        # Pre-allocate arrays for each timeframe
        self.candle_arrays: Dict[str, np.ndarray] = {}
        self.candle_counts: Dict[str, int] = {}
        
        for tf in timeframes:
            # Start with 10,000 candles capacity
            self.candle_arrays[tf] = np.zeros(10000, dtype=self.candle_dtype)
            self.candle_counts[tf] = 0
    
    def add_candle(self, timeframe: str, candle: CandleData):
        """Add completed candle to NumPy array."""
        idx = self.candle_counts[timeframe]
        arr = self.candle_arrays[timeframe]
        
        # Resize if needed (double capacity)
        if idx >= len(arr):
            new_arr = np.zeros(len(arr) * 2, dtype=self.candle_dtype)
            new_arr[:len(arr)] = arr
            self.candle_arrays[timeframe] = new_arr
            arr = new_arr
        
        # Add candle (direct assignment, very fast)
        arr[idx] = (
            np.datetime64(candle.time, 's'),
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.volume
        )
        
        self.candle_counts[timeframe] += 1
    
    def get_candles_array(self, timeframe: str, count: int = 100) -> np.ndarray:
        """Get candles as NumPy array (zero-copy view)."""
        total = self.candle_counts[timeframe]
        arr = self.candle_arrays[timeframe]
        
        # Return view of last N candles (no copy)
        start = max(0, total - count)
        return arr[start:total]
    
    def get_candles_df(self, timeframe: str, count: int = 100) -> pd.DataFrame:
        """Get candles as DataFrame (for backward compatibility)."""
        arr = self.get_candles_array(timeframe, count)
        
        # Convert to DataFrame (fast, uses array views)
        return pd.DataFrame({
            'time': arr['time'],
            'open': arr['open'],
            'high': arr['high'],
            'low': arr['low'],
            'close': arr['close'],
            'tick_volume': arr['volume']
        })
```

---

### Optimization #24: Vectorized SL/TP Checking

```python
# In src/backtesting/engine/simulated_broker.py

def _check_sl_tp_vectorized(self, symbol: str, tick: GlobalTick, current_time: datetime):
    """Vectorized SL/TP checking using NumPy."""
    if symbol not in self.positions_by_symbol:
        return
    
    tickets = self.positions_by_symbol[symbol]
    if not tickets:
        return
    
    n = len(tickets)
    
    # Extract position data into NumPy arrays
    pos_types = np.empty(n, dtype=np.int8)
    sls = np.empty(n, dtype=np.float64)
    tps = np.empty(n, dtype=np.float64)
    
    for i, ticket in enumerate(tickets):
        pos = self.positions[ticket]
        pos_types[i] = 1 if pos.position_type == PositionType.BUY else -1
        sls[i] = pos.sl if pos.sl else 0.0
        tps[i] = pos.tp if pos.tp else 0.0
    
    # Vectorized checks (5-10x faster than Python loops)
    tick_bid = tick.bid
    tick_ask = tick.ask
    
    # BUY positions: check bid against SL/TP
    buy_mask = pos_types == 1
    sl_hit_buy = buy_mask & (sls > 0) & (tick_bid <= sls)
    tp_hit_buy = buy_mask & (tps > 0) & (tick_bid >= tps)
    
    # SELL positions: check ask against SL/TP
    sell_mask = pos_types == -1
    sl_hit_sell = sell_mask & (sls > 0) & (tick_ask >= sls)
    tp_hit_sell = sell_mask & (tps > 0) & (tick_ask <= tps)
    
    # Find positions to close
    sl_hits = np.where(sl_hit_buy | sl_hit_sell)[0]
    tp_hits = np.where(tp_hit_buy | tp_hit_sell)[0]
    
    # Close positions
    positions_to_close = []
    
    for idx in sl_hits:
        ticket = tickets[idx]
        close_price = tick_bid if pos_types[idx] == 1 else tick_ask
        positions_to_close.append((ticket, close_price, 'SL'))
    
    for idx in tp_hits:
        ticket = tickets[idx]
        close_price = tick_bid if pos_types[idx] == 1 else tick_ask
        positions_to_close.append((ticket, close_price, 'TP'))
    
    # Close all positions
    for ticket, close_price, reason in positions_to_close:
        self._close_position_internal(ticket, close_time=current_time)
```

---

## Testing Checklist

### After Each Optimization:
- [ ] Run unit tests: `pytest tests/`
- [ ] Run integration tests: `pytest tests/integration/`
- [ ] Run short backtest (1 day): `python backtest.py --days 1`
- [ ] Verify results match baseline (within 0.1% tolerance)
- [ ] Measure performance: `python tools/profile_backtest.py --duration 60`
- [ ] Check memory usage: Monitor RAM during backtest
- [ ] Review logs for errors/warnings

### Performance Metrics to Track:
- **Ticks/second**: Should increase with each optimization
- **Memory usage**: Should stay stable or decrease
- **Trade count**: Should match baseline exactly
- **Final balance**: Should match baseline within $0.01
- **SL/TP hits**: Should match baseline exactly

---

## Rollback Plan

If an optimization causes issues:

1. **Revert the changes**:
   ```bash
   git checkout HEAD -- <modified_files>
   ```

2. **Run baseline test**:
   ```bash
   python backtest.py --days 1
   ```

3. **Document the issue**:
   - What went wrong?
   - What was the expected behavior?
   - What was the actual behavior?

4. **Re-evaluate the optimization**:
   - Is the approach fundamentally flawed?
   - Can it be fixed with a different implementation?
   - Should it be postponed to a later phase?

---

## Success Criteria

### Phase 5A (Quick Wins):
- ✅ Performance: 22,000+ tps (10% gain)
- ✅ All tests pass
- ✅ Results match baseline

### Phase 5B (Core Improvements):
- ✅ Performance: 30,000+ tps (50% gain)
- ✅ All tests pass
- ✅ Results match baseline
- ✅ Memory usage stable or reduced

### Phase 5C (Advanced):
- ✅ Performance: 35,000-50,000 tps (75-150% gain)
- ✅ All tests pass
- ✅ Results match baseline
- ✅ Build system works correctly (Cython)
- ✅ Parallel processing validated (if implemented)

---

## Next Steps

1. **Review this analysis** with the team
2. **Run profiler** to validate hot path analysis: `python tools/profile_backtest.py`
3. **Choose implementation phase** (5A, 5B, or 5C)
4. **Implement optimizations** one at a time
5. **Test thoroughly** after each optimization
6. **Measure and document** performance gains
7. **Iterate** based on results

