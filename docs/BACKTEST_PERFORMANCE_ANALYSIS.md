# Backtesting Performance Analysis & Optimization Guide

**Date**: 2025-11-16  
**Status**: Analysis Complete  
**Current Mode**: `TimeMode.MAX_SPEED` with console logging disabled

---

## Executive Summary

This document provides a comprehensive analysis of the backtesting engine's performance characteristics and proposes concrete optimizations. The analysis focuses on the recent architectural change to **minute-by-minute global time advancement** and identifies both bottlenecks and optimization opportunities.

### Key Findings

1. **Primary Bottleneck**: The `advance_global_time()` loop iterates through ALL symbols twice per minute (once to advance indices, once to check for remaining data)
2. **Lock Contention**: The `time_lock` is held for the entire duration of `advance_global_time()`, blocking all symbol threads
3. **Redundant Operations**: `has_data_at_current_time()` performs duplicate DataFrame lookups and timestamp conversions
4. **Inefficient Data Access**: Pandas `.iloc[]` operations and timestamp conversions happen repeatedly for the same data

### Performance Impact Estimate

For a backtest with:
- **20 symbols** × **5 days** × **1440 minutes/day** = **144,000 barrier cycles**
- Each cycle performs: **40+ symbol iterations** (2 loops in advance_global_time) + **20 has_data checks**
- Total operations: **~8.6 million** symbol-level iterations

**Estimated speedup from proposed optimizations**: **2-5x** depending on symbol count and data density.

---

## 1. Current Architecture Analysis

### 1.1 Barrier Synchronization Flow

```
Each Minute (Barrier Cycle):
├─ All symbol threads call has_data_at_current_time()  [20 calls, each with lock]
├─ Symbol threads process on_tick() if data available  [variable time]
├─ All threads wait at barrier                         [synchronization point]
├─ Last thread triggers advance_global_time()          [BOTTLENECK - holds lock]
│  ├─ Loop 1: Advance indices for symbols with data   [20 iterations]
│  └─ Loop 2: Check if any symbol has remaining data  [20 iterations, early break]
└─ All threads released to next minute
```

**Time Breakdown** (estimated per barrier cycle):
- `has_data_at_current_time()`: 20 calls × 0.1ms = **2ms**
- `on_tick()` processing: **5-50ms** (varies by strategy complexity)
- Barrier wait: **<1ms** (minimal overhead)
- `advance_global_time()`: **2-10ms** (scales with symbol count)

**Total per minute**: ~10-60ms
**For 144K minutes**: ~24-144 minutes of wall-clock time

### 1.2 Detailed Bottleneck Analysis

#### Bottleneck #1: `advance_global_time()` - Double Loop Through All Symbols

**Location**: `src/backtesting/engine/simulated_broker.py:979-1043`

**Current Implementation**:
```python
def advance_global_time(self) -> bool:
    with self.time_lock:  # ← Lock held for entire function
        # Loop 1: Advance indices for symbols with data at current_time
        for symbol in self.current_indices.keys():  # ← Iterate ALL symbols
            m1_data = self.symbol_data[(symbol, 'M1')]
            current_idx = self.current_indices[symbol]
            if current_idx < len(m1_data):
                bar = m1_data.iloc[current_idx]  # ← Pandas iloc (slow)
                bar_time = bar['time']
                # Timestamp conversion overhead
                if isinstance(bar_time, pd.Timestamp):
                    bar_time = bar_time.to_pydatetime()
                if bar_time.tzinfo is None:
                    bar_time = bar_time.replace(tzinfo=timezone.utc)
                # Check and advance
                if bar_time == self.current_time:
                    self.current_indices[symbol] = current_idx + 1

        # Loop 2: Check if any symbol has remaining data
        for symbol in self.current_indices.keys():  # ← Iterate ALL symbols AGAIN
            current_idx = self.current_indices[symbol]
            if current_idx < len(m1_data):
                has_any_data = True
                break  # Early exit, but still wasteful
```

**Problems**:
1. **Two full loops** through all symbols (40 iterations for 20 symbols)
2. **Lock held** for entire duration, blocking all threads
3. **Pandas `.iloc[]`** is slow compared to direct array access
4. **Timestamp conversions** repeated for every symbol, every minute
5. **No caching** of bar times or data lengths

**Performance Impact**: **HIGH** - Scales linearly with symbol count (O(N) per minute)

---

#### Bottleneck #2: `has_data_at_current_time()` - Redundant Checks

**Location**: `src/backtesting/engine/simulated_broker.py:920-953`

**Current Implementation**:
```python
def has_data_at_current_time(self, symbol: str) -> bool:
    with self.time_lock:  # ← Lock acquisition (20x per minute)
        # Duplicate lookups
        m1_data = self.symbol_data[(symbol, 'M1')]  # ← Dict lookup
        current_idx = self.current_indices[symbol]   # ← Dict lookup

        if current_idx >= len(m1_data):
            return False

        # Duplicate timestamp conversion (same as advance_global_time)
        bar = m1_data.iloc[current_idx]
        bar_time = bar['time']
        if isinstance(bar_time, pd.Timestamp):
            bar_time = bar_time.to_pydatetime()
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)

        return bar_time == self.current_time
```

**Problems**:
1. **Called 20 times per minute** (once per symbol thread)
2. **Lock contention** - each call acquires the lock
3. **Duplicate work** - same timestamp conversions as `advance_global_time()`
4. **No caching** - could pre-compute which symbols have data at each time

**Performance Impact**: **MEDIUM** - Called frequently but short duration

---

#### Bottleneck #3: Strategy `on_tick()` Processing

**Location**: `src/strategy/fakeout_strategy.py:244-266`, `src/strategy/true_breakout_strategy.py:203-230`

**Current Flow**:
```python
def on_tick(self) -> Optional[TradeSignal]:
    # Check for new reference candle
    self._check_reference_candle()  # ← get_candles() call

    # Check for new confirmation candle
    if self._is_new_confirmation_candle():  # ← get_candles() call
        return self._process_confirmation_candle()  # ← get_candles() call + heavy logic
```

**Typical `_process_confirmation_candle()` operations**:
- Multiple `get_candles()` calls (DataFrame slicing)
- Volume calculations (average over lookback period)
- RSI divergence detection (if enabled)
- Breakout detection logic
- Signal validation

**Problems**:
1. **Multiple DataFrame operations** per tick
2. **Repeated candle fetching** - same data requested multiple times
3. **No caching** of intermediate calculations (e.g., average volume)
4. **Divergence detection** can be expensive (RSI calculation over lookback period)

**Performance Impact**: **MEDIUM-HIGH** - Varies by strategy complexity and number of active strategies

---

#### Bottleneck #4: Lock Contention on `time_lock`

**Contention Points**:
1. `has_data_at_current_time()` - 20 calls/minute
2. `advance_global_time()` - 1 call/minute (but holds lock longest)
3. `get_current_time()` - Called by logging and other components
4. `get_candles()` - Filters data by current_time (acquires lock)

**Lock Hold Times**:
- `has_data_at_current_time()`: ~0.1ms per call
- `advance_global_time()`: ~2-10ms (scales with symbols)
- `get_candles()`: ~0.5-2ms (depends on timeframe and count)

**Performance Impact**: **MEDIUM** - Not a major bottleneck yet, but could become one with more symbols

---

### 1.3 Data Access Patterns

#### Current Data Structure
```python
# Symbol data: Dict[(symbol, timeframe), DataFrame]
self.symbol_data = {
    ('EURUSD', 'M1'): DataFrame[5000 rows],
    ('EURUSD', 'M5'): DataFrame[1000 rows],
    ('GBPUSD', 'M1'): DataFrame[5000 rows],
    ...
}

# Current indices: Dict[symbol, int]
self.current_indices = {
    'EURUSD': 1234,
    'GBPUSD': 1235,
    ...
}
```

**Access Patterns**:
- **Sequential access**: Indices advance linearly (good for caching)
- **Random timeframe access**: Strategies request M1, M5, M15, H4 (cache-friendly)
- **Lookback access**: Strategies request last N candles (repeated slicing)

**Optimization Opportunities**:
- Pre-convert all timestamps to datetime objects (one-time cost)
- Cache DataFrame lengths (avoid repeated `len()` calls)
- Pre-compute symbol data availability map (which symbols have data at which times)
- Use NumPy arrays instead of Pandas for hot paths

---

## 2. Evaluation of New Minute-by-Minute Architecture

### 2.1 Architecture Overview

**Previous Architecture** (per-symbol time advancement):
- Each symbol advanced independently
- Race conditions possible
- Complex synchronization logic

**New Architecture** (global time advancement):
- Single global clock advances minute-by-minute
- All symbols synchronized to same time
- Simpler, more predictable behavior

### 2.2 Performance Analysis

#### ✅ **Advantages**

1. **Correctness**: Eliminates race conditions where symbols could be at different times
2. **Simplicity**: Single source of truth for current time
3. **Behavioral Parity**: Better matches live trading (all symbols see same time)
4. **Debugging**: Easier to reason about system state

#### ⚠️ **Performance Concerns**

1. **Loop Overhead**: Must iterate through all symbols every minute
2. **Lock Duration**: `time_lock` held longer (blocks all threads)
3. **Wasted Iterations**: Symbols without data still checked every minute
4. **No Early Exit**: First loop must complete before second loop starts

### 2.3 Scalability Analysis

**Performance vs. Symbol Count**:

| Symbols | Iterations/Minute | Total Iterations (5 days) | Estimated Overhead |
|---------|-------------------|---------------------------|-------------------|
| 10      | 20                | 1.44M                     | ~3 minutes        |
| 20      | 40                | 2.88M                     | ~6 minutes        |
| 50      | 100               | 7.2M                      | ~15 minutes       |
| 100     | 200               | 14.4M                     | ~30 minutes       |

**Conclusion**: Current architecture scales **linearly (O(N))** with symbol count. This is acceptable for <50 symbols but becomes problematic at scale.

---

## 3. Concrete Optimization Proposals

### Optimization #1: Pre-compute Symbol Data Availability Map

**Priority**: 🔴 **HIGH**
**Complexity**: 🟢 **LOW**
**Expected Speedup**: **2-3x** for `advance_global_time()`
**Impact on Behavioral Parity**: ✅ **NONE**

#### Problem
Currently, we check every symbol's data availability every minute by:
1. Looking up DataFrame
2. Getting current index
3. Accessing row with `.iloc[]`
4. Converting timestamp
5. Comparing with current_time

This is wasteful because **data availability is deterministic** - we can pre-compute it once during initialization.

#### Solution
Create a sorted list of all unique timestamps across all symbols, then use binary search to find which symbols have data at each time.

```python
class SimulatedBroker:
    def __init__(self, ...):
        # New data structures
        self.symbol_timestamps: Dict[str, np.ndarray] = {}  # symbol -> sorted timestamps
        self.symbol_data_lengths: Dict[str, int] = {}       # symbol -> data length (cached)

    def load_symbol_data(self, symbol: str, data: pd.DataFrame, ...):
        # Pre-convert and cache timestamps as NumPy array
        m1_data = data.copy()
        timestamps = pd.to_datetime(m1_data['time'], utc=True).to_numpy()
        self.symbol_timestamps[symbol] = timestamps
        self.symbol_data_lengths[symbol] = len(timestamps)

    def has_data_at_current_time(self, symbol: str) -> bool:
        """Optimized version using pre-computed timestamps."""
        with self.time_lock:
            if symbol not in self.current_indices:
                return False

            current_idx = self.current_indices[symbol]

            # Fast bounds check (no DataFrame access)
            if current_idx >= self.symbol_data_lengths[symbol]:
                return False

            # Fast timestamp comparison (NumPy array access)
            bar_time = self.symbol_timestamps[symbol][current_idx]
            return bar_time == self.current_time
```

**Benefits**:
- ✅ No DataFrame access (`.iloc[]` eliminated)
- ✅ No timestamp conversion (pre-converted once)
- ✅ Cached data lengths (no repeated `len()` calls)
- ✅ NumPy array access is ~10x faster than Pandas

**Trade-offs**:
- ⚠️ Slightly higher memory usage (~8 bytes per bar for timestamp cache)
- ⚠️ One-time initialization cost (negligible)

**Implementation Effort**: ~2 hours

---

### Optimization #2: Combine Loops in `advance_global_time()`

**Priority**: 🔴 **HIGH**
**Complexity**: 🟢 **LOW**
**Expected Speedup**: **1.5-2x** for `advance_global_time()`
**Impact on Behavioral Parity**: ✅ **NONE**

#### Problem
Current implementation loops through all symbols twice:
1. First loop: Advance indices for symbols with data
2. Second loop: Check if any symbol has remaining data

This is inefficient - we can combine both operations into a single loop.

#### Solution
```python
def advance_global_time(self) -> bool:
    """Optimized version with single loop."""
    with self.time_lock:
        if self.current_time is None:
            return False

        has_any_data = False

        # Single loop: advance indices AND check for remaining data
        for symbol in self.current_indices.keys():
            current_idx = self.current_indices[symbol]

            # Fast bounds check using cached length
            if current_idx >= self.symbol_data_lengths[symbol]:
                continue  # Symbol exhausted

            # Fast timestamp check using cached array
            bar_time = self.symbol_timestamps[symbol][current_idx]

            # If bar time matches current global time, advance index
            if bar_time == self.current_time:
                self.current_indices[symbol] = current_idx + 1
                current_idx += 1  # Update local variable

            # Check if symbol has more data (after potential advancement)
            if current_idx < self.symbol_data_lengths[symbol]:
                has_any_data = True
                # Don't break - we need to advance ALL symbols

        if not has_any_data:
            return False

        # Advance global time by 1 minute
        from datetime import timedelta
        self.current_time = self.current_time + timedelta(minutes=1)

        return True
```

**Benefits**:
- ✅ Single loop instead of two (50% reduction in iterations)
- ✅ Shorter lock hold time
- ✅ Better cache locality (process each symbol once)

**Trade-offs**:
- ⚠️ Cannot early-exit when checking for remaining data (must complete loop)
- ✅ But this is acceptable - we need to advance ALL symbols anyway

**Implementation Effort**: ~1 hour

---

### Optimization #3: Cache Symbol Data Availability Bitmap (CORRECTED)

**Priority**: 🟡 **MEDIUM**
**Complexity**: 🟡 **MEDIUM**
**Expected Speedup**: **1.5-2x** overall (reduces `has_data_at_current_time()` overhead)
**Impact on Behavioral Parity**: ✅ **NONE**

⚠️ **CRITICAL UPDATE**: Original proposal had a race condition. This is the CORRECTED version.

#### Problem
Each symbol thread calls `has_data_at_current_time()` every minute, acquiring the lock and performing lookups. This creates lock contention and redundant work.

#### Solution (THREAD-SAFE)
Pre-compute a bitmap of which symbols have data at each minute, then update it during `advance_global_time()`.

```python
class SimulatedBroker:
    def __init__(self, ...):
        # New: Track which symbols have data at current time
        self.symbols_with_data_at_current_time: Set[str] = set()

    def advance_global_time(self) -> bool:
        """Update bitmap during time advancement."""
        with self.time_lock:
            # ... advance indices and time ...

            # Update bitmap for next minute (INSIDE time_lock)
            self.symbols_with_data_at_current_time.clear()
            for symbol in self.current_indices.keys():
                current_idx = self.current_indices[symbol]
                if current_idx < self.symbol_data_lengths[symbol]:
                    bar_time = self.symbol_timestamps[symbol][current_idx]
                    if bar_time == self.current_time:
                        self.symbols_with_data_at_current_time.add(symbol)

    def has_data_at_current_time(self, symbol: str) -> bool:
        """
        Optimized version using bitmap (THREAD-SAFE).

        CRITICAL: Must keep time_lock to prevent race condition.
        Still faster than original due to no Pandas access.
        """
        with self.time_lock:  # ← MUST KEEP LOCK
            return symbol in self.symbols_with_data_at_current_time
```

**Why the Lock is Necessary**:

The original proposal suggested removing the lock, but this creates a race condition where threads can read the bitmap while it's being updated. See `BACKTEST_OPTIMIZATION_THREAD_SAFETY.md` for detailed analysis.

**Benefits**:
- ✅ Much faster than original (no Pandas access, no timestamp conversion)
- ✅ Simple set lookup instead of DataFrame access
- ✅ Thread-safe with proper synchronization

**Trade-offs**:
- ⚠️ Still requires lock acquisition (but lock held for much shorter time)
- ⚠️ Speedup reduced from 2-3x to 1.5-2x (but SAFE)

**Implementation Effort**: ~3 hours

**See Also**: `BACKTEST_OPTIMIZATION_THREAD_SAFETY.md` for race condition analysis and alternative double-buffering solution

---

### Optimization #4: Reduce Logging Overhead

**Priority**: 🟡 **MEDIUM**
**Complexity**: 🟢 **LOW**
**Expected Speedup**: **1.2-1.5x** (if logging is frequent)
**Impact on Behavioral Parity**: ⚠️ **MINOR** (less verbose logs)

#### Problem
Even with console logging disabled, file logging still has overhead:
- String formatting
- Timestamp generation
- File I/O (buffered, but still overhead)
- Lock acquisition in logger

#### Solution
1. **Reduce log frequency**: Only log significant events (signals, trades, errors)
2. **Lazy string formatting**: Use `logger.debug()` with lambda for expensive formatting
3. **Batch logging**: Accumulate logs and write periodically

```python
# Before (logs every tick)
self.logger.debug(f"Checking reference candle: {candle.time}", self.symbol)

# After (only log when something changes)
if new_reference_candle:
    self.logger.info(f"New reference candle: {candle.time}", self.symbol)

# For expensive formatting
self.logger.debug(
    lambda: f"Complex calculation: {expensive_function()}",
    self.symbol
)
```

**Benefits**:
- ✅ Reduced I/O overhead
- ✅ Less string formatting
- ✅ Smaller log files (easier to analyze)

**Trade-offs**:
- ⚠️ Less detailed logs for debugging
- ✅ Can be toggled with log level

**Implementation Effort**: ~2 hours (review all logging calls)

---

### Optimization #5: Vectorize Volume Calculations

**Priority**: 🟡 **MEDIUM**
**Complexity**: 🟡 **MEDIUM**
**Expected Speedup**: **1.3-1.8x** for strategies with volume checks
**Impact on Behavioral Parity**: ✅ **NONE**

#### Problem
Strategies calculate average volume using Pandas operations:
```python
# Current implementation (in TechnicalIndicators)
avg_volume = df['tick_volume'].tail(lookback).mean()
```

This is called multiple times per signal check, creating overhead.

#### Solution
Cache volume calculations and update incrementally:

```python
class VolumeCache:
    """Cache for rolling volume calculations."""
    def __init__(self, lookback: int):
        self.lookback = lookback
        self.volumes = deque(maxlen=lookback)
        self.sum = 0.0

    def update(self, volume: float):
        """Add new volume and update rolling average."""
        if len(self.volumes) == self.lookback:
            # Remove oldest volume from sum
            self.sum -= self.volumes[0]
        self.volumes.append(volume)
        self.sum += volume

    def get_average(self) -> float:
        """Get current rolling average (O(1))."""
        return self.sum / len(self.volumes) if self.volumes else 0.0

# In strategy
class FakeoutStrategy:
    def __init__(self, ...):
        self.volume_cache = VolumeCache(lookback=self.config.volume_lookback)

    def _is_new_confirmation_candle(self):
        if new_candle:
            # Update cache with new volume
            self.volume_cache.update(candle.volume)

    def _is_breakout_volume_low(self, volume: float) -> bool:
        # O(1) average calculation instead of O(N) Pandas operation
        avg_volume = self.volume_cache.get_average()
        return volume < avg_volume * self.config.max_breakout_volume_multiplier
```

**Benefits**:
- ✅ O(1) average calculation instead of O(N)
- ✅ No repeated DataFrame slicing
- ✅ Minimal memory overhead

**Trade-offs**:
- ⚠️ More complex state management
- ⚠️ Need to ensure cache is properly initialized

**Implementation Effort**: ~4 hours

---

### Optimization #6: Use NumPy Arrays for Hot Paths

**Priority**: 🟢 **LOW**
**Complexity**: 🔴 **HIGH**
**Expected Speedup**: **1.5-2x** for data access operations
**Impact on Behavioral Parity**: ✅ **NONE**

#### Problem
Pandas DataFrames have significant overhead for single-row access (`.iloc[]`). For sequential access patterns (which backtesting has), NumPy arrays are much faster.

#### Solution
Convert DataFrames to NumPy structured arrays during initialization:

```python
class SimulatedBroker:
    def load_symbol_data(self, symbol: str, data: pd.DataFrame, ...):
        # Convert to NumPy structured array for fast access
        m1_array = data[['time', 'open', 'high', 'low', 'close', 'tick_volume']].to_records(index=False)
        self.symbol_data_arrays[(symbol, 'M1')] = m1_array

        # Keep DataFrame for compatibility with get_candles()
        self.symbol_data[(symbol, 'M1')] = data

    def get_current_bar(self, symbol: str) -> Optional[dict]:
        """Fast bar access using NumPy array."""
        current_idx = self.current_indices[symbol]
        m1_array = self.symbol_data_arrays[(symbol, 'M1')]

        if current_idx >= len(m1_array):
            return None

        bar = m1_array[current_idx]
        return {
            'time': bar['time'],
            'open': bar['open'],
            'high': bar['high'],
            'low': bar['low'],
            'close': bar['close'],
            'volume': bar['tick_volume']
        }
```

**Benefits**:
- ✅ ~10x faster single-row access
- ✅ Better memory layout (cache-friendly)
- ✅ No Python object overhead

**Trade-offs**:
- ⚠️ Duplicate data storage (both DataFrame and array)
- ⚠️ More complex code (need to maintain both)
- ⚠️ High implementation effort

**Implementation Effort**: ~8 hours

**Recommendation**: ⚠️ **DEFER** - Only implement if other optimizations are insufficient

---

### Optimization #7: Parallel Strategy Execution (Advanced)

**Priority**: 🟢 **LOW**
**Complexity**: 🔴 **VERY HIGH**
**Expected Speedup**: **2-4x** (with 4+ CPU cores)
**Impact on Behavioral Parity**: ⚠️ **SIGNIFICANT** (requires careful validation)

#### Problem
Currently, all strategies for a symbol run sequentially in the symbol's thread. With multiple strategies per symbol, this can be slow.

#### Solution
Use thread pool to execute strategies in parallel:

```python
from concurrent.futures import ThreadPoolExecutor

class TradingController:
    def __init__(self, ...):
        self.strategy_executor = ThreadPoolExecutor(max_workers=4)

    def _symbol_worker(self, symbol: str):
        while running:
            # Submit all strategies for this symbol to thread pool
            futures = []
            for strategy in self.strategies[symbol]:
                future = self.strategy_executor.submit(strategy.on_tick)
                futures.append(future)

            # Wait for all strategies to complete
            for future in futures:
                signal = future.result()
                if signal:
                    self._handle_signal(signal)

            # Wait at barrier
            self.time_controller.wait_for_next_step(symbol)
```

**Benefits**:
- ✅ Utilize multiple CPU cores
- ✅ Significant speedup for multi-strategy setups

**Trade-offs**:
- ⚠️ **MAJOR**: Complex synchronization (strategies share state)
- ⚠️ **MAJOR**: Potential race conditions in strategy code
- ⚠️ **MAJOR**: Different execution order than live trading
- ⚠️ Increased memory usage (thread pool overhead)

**Recommendation**: ❌ **DO NOT IMPLEMENT** - Breaks behavioral parity with live trading

---

## 4. Optimization Priority Matrix

### Recommended Implementation Order

| Priority | Optimization | Speedup | Effort | Risk | Implement? | Notes |
|----------|-------------|---------|--------|------|------------|-------|
| 1️⃣ | **#1: Pre-compute Timestamps** | 2-3x | 2h | Low | ✅ **YES** | Thread-safe |
| 2️⃣ | **#2: Combine Loops** | 1.5-2x | 1h | Low | ✅ **YES** | Thread-safe |
| 3️⃣ | **#3: Cache Data Bitmap (CORRECTED)** | 1.5-2x | 3h | Medium | ✅ **YES** | Must keep lock |
| 4️⃣ | **#4: Reduce Logging** | 1.2-1.5x | 2h | Low | ✅ **YES** | Thread-safe |
| 5️⃣ | **#5: Vectorize Volume** | 1.3-1.8x | 4h | Medium | 🟡 **MAYBE** | Thread-safe |
| 6️⃣ | **#6: NumPy Arrays** | 1.5-2x | 8h | High | ⚠️ **DEFER** | Complex |
| 7️⃣ | **#7: Parallel Strategies** | 2-4x | 20h+ | Very High | ❌ **NO** | Breaks parity |

### Expected Cumulative Speedup (REVISED)

**Phase 1** (Optimizations #1-#4):
- Individual speedups: 2-3x, 1.5-2x, 1.5-2x, 1.2-1.5x
- **Cumulative speedup**: ~**2.5-4x** (revised from 3-5x due to keeping lock in Opt #3)
- **Implementation time**: ~8 hours
- **Risk**: Low
- **Thread Safety**: ✅ All optimizations verified safe (see `BACKTEST_OPTIMIZATION_THREAD_SAFETY.md`)

**Phase 2** (Optimization #5):
- Additional speedup: 1.3-1.8x for volume-heavy strategies
- **Cumulative speedup**: ~**4-7x** total
- **Implementation time**: +4 hours
- **Risk**: Medium

---

## 5. Implementation Roadmap

### Phase 1: Quick Wins (Week 1)

**Goal**: Achieve 3-5x speedup with low-risk changes

#### Step 1: Pre-compute Timestamps (2 hours)
- [ ] Add `symbol_timestamps` and `symbol_data_lengths` to `SimulatedBroker.__init__()`
- [ ] Modify `load_symbol_data()` to pre-convert timestamps to NumPy array
- [ ] Update `has_data_at_current_time()` to use cached data
- [ ] Test: Verify correctness with existing backtest

#### Step 2: Combine Loops in `advance_global_time()` (1 hour)
- [ ] Refactor `advance_global_time()` to single loop
- [ ] Use cached timestamps and lengths
- [ ] Test: Verify time advancement is identical

#### Step 3: Cache Data Availability Bitmap (3 hours)
- [ ] Add `symbols_with_data_at_current_time` set to `SimulatedBroker`
- [ ] Update bitmap during `advance_global_time()`
- [ ] Simplify `has_data_at_current_time()` to set lookup
- [ ] Test: Verify thread safety and correctness

#### Step 4: Reduce Logging Overhead (2 hours)
- [ ] Review all `logger.debug()` calls in strategies
- [ ] Remove or reduce frequency of non-essential logs
- [ ] Add log level checks for expensive formatting
- [ ] Test: Verify important events still logged

**Deliverable**: Backtest runs 3-5x faster with identical results

---

### Phase 2: Advanced Optimizations (Week 2)

**Goal**: Achieve 4-7x speedup with medium-risk changes

#### Step 5: Vectorize Volume Calculations (4 hours)
- [ ] Create `VolumeCache` class with rolling average
- [ ] Integrate into `FakeoutStrategy` and `TrueBreakoutStrategy`
- [ ] Update volume checks to use cached averages
- [ ] Test: Verify volume calculations are identical

**Deliverable**: Additional 1.3-1.8x speedup for volume-heavy strategies

---

### Phase 3: Future Optimizations (Deferred)

**Goal**: Evaluate need for further optimization

#### Optimization #6: NumPy Arrays
- **Trigger**: If Phase 1-2 speedup is insufficient
- **Effort**: 8 hours
- **Risk**: High (code complexity)

#### Optimization #7: Parallel Strategies
- **Recommendation**: ❌ **DO NOT IMPLEMENT**
- **Reason**: Breaks behavioral parity with live trading

---

## 6. Performance Measurement Plan

### Baseline Metrics (Before Optimization)

Run backtest with:
- **Symbols**: 20 symbols from active.set
- **Date Range**: 5 days (2025-11-10 to 2025-11-15)
- **Strategies**: All enabled strategies
- **Time Mode**: `TimeMode.MAX_SPEED`
- **Console Logging**: Disabled

**Measure**:
1. Total wall-clock time
2. Steps per second (from `TimeController.get_statistics()`)
3. Memory usage (peak RSS)
4. Log file size

### Post-Optimization Metrics

After each optimization phase, re-run the same backtest and compare:

| Metric | Baseline | Phase 1 | Phase 2 | Target |
|--------|----------|---------|---------|--------|
| Wall-clock time | ? | ? | ? | <20% of baseline |
| Steps/second | ? | ? | ? | >5x baseline |
| Memory usage | ? | ? | ? | <120% of baseline |
| Log file size | ? | ? | ? | <50% of baseline |

### Validation Checklist

After each optimization, verify:
- ✅ Final balance matches baseline (within $0.01)
- ✅ Trade count matches baseline
- ✅ Trade tickets and timestamps match baseline
- ✅ No new errors or warnings in logs
- ✅ All tests pass

---

## 7. Conclusion

### Summary

The backtesting engine's performance can be significantly improved through targeted optimizations:

1. **Primary Bottleneck**: `advance_global_time()` iterates through all symbols twice per minute
2. **Secondary Bottleneck**: Redundant timestamp conversions and DataFrame access
3. **Recommended Approach**: Implement Phase 1 optimizations (3-5x speedup, 8 hours effort)
4. **Advanced Optimizations**: Defer until Phase 1 results are evaluated

### Key Takeaways

✅ **DO**:
- Pre-compute and cache frequently accessed data
- Combine loops to reduce iterations
- Use NumPy arrays for hot paths
- Reduce logging overhead

⚠️ **CONSIDER**:
- Vectorize calculations (if Phase 1 is insufficient)
- Profile actual performance to validate assumptions

❌ **DON'T**:
- Parallelize strategies (breaks behavioral parity)
- Optimize prematurely (measure first)
- Sacrifice correctness for speed

### Next Steps

1. **Measure baseline performance** with current implementation
2. **Implement Phase 1 optimizations** (8 hours)
3. **Validate results** match baseline exactly
4. **Measure speedup** and decide if Phase 2 is needed
5. **Document findings** and update this analysis

---

## Appendix: Profiling Commands

### Python Profiling

```bash
# Profile backtest execution
python -m cProfile -o backtest.prof backtest.py

# Analyze profile
python -m pstats backtest.prof
>>> sort cumtime
>>> stats 20

# Visual profiling with snakeviz
pip install snakeviz
snakeviz backtest.prof
```

### Memory Profiling

```bash
# Profile memory usage
pip install memory_profiler
python -m memory_profiler backtest.py

# Line-by-line memory profiling
# Add @profile decorator to functions
python -m memory_profiler backtest.py
```

### Lock Contention Analysis

```python
# Add to SimulatedBroker.__init__()
import threading
import time

class TimedLock:
    def __init__(self, name):
        self.lock = threading.Lock()
        self.name = name
        self.wait_time = 0.0
        self.hold_time = 0.0
        self.acquisitions = 0

    def __enter__(self):
        start = time.perf_counter()
        self.lock.acquire()
        self.wait_time += time.perf_counter() - start
        self.acquisitions += 1
        self.acquire_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.hold_time += time.perf_counter() - self.acquire_time
        self.lock.release()

    def stats(self):
        return {
            'acquisitions': self.acquisitions,
            'total_wait_time': self.wait_time,
            'total_hold_time': self.hold_time,
            'avg_wait_time': self.wait_time / self.acquisitions if self.acquisitions > 0 else 0,
            'avg_hold_time': self.hold_time / self.acquisitions if self.acquisitions > 0 else 0,
        }

# Replace self.time_lock = threading.Lock() with:
self.time_lock = TimedLock('time_lock')

# At end of backtest, print stats:
print(f"Lock stats: {broker.time_lock.stats()}")
```

---

**Document Version**: 1.0
**Last Updated**: 2025-11-16
**Author**: Augment Agent
**Status**: Ready for Implementation


