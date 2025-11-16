# Backtesting Optimization - Phase 2 Plan

**Date**: 2025-11-16  
**Status**: Ready for Implementation  
**Prerequisites**: Phase 1 complete (2.5-4x speedup achieved)

---

## Executive Summary

Phase 2 optimizations target an additional **1.5-2.5x speedup** on top of Phase 1, bringing total speedup to **4-10x** compared to baseline.

### Two Optimization Paths

**Path A: Maximum Performance** (Recommended if Phase 1 < 3x)
- Optimization #3b: Double-buffering (lock-free reads)
- Optimization #5: Vectorize volume calculations
- **Total speedup**: ~4-7x (cumulative with Phase 1)
- **Effort**: 8-10 hours
- **Risk**: Medium

**Path B: Balanced Approach** (Recommended if Phase 1 ≥ 3x)
- Optimization #5 only: Vectorize volume calculations
- **Total speedup**: ~3-6x (cumulative with Phase 1)
- **Effort**: 4-5 hours
- **Risk**: Low-Medium

---

## Optimization #3b: Double-Buffering (Lock-Free Reads)

### Overview

**Goal**: Eliminate lock acquisition in `has_data_at_current_time()` (called 20 times per minute)  
**Method**: Use two bitmap buffers - one for reading, one for writing  
**Expected Speedup**: **1.3-1.5x** additional (on top of Phase 1)  
**Complexity**: Medium  
**Risk**: Medium (requires careful synchronization)

### Current Implementation (Phase 1)

```python
class SimulatedBroker:
    def __init__(self):
        self.symbols_with_data_at_current_time: Set[str] = set()
    
    def has_data_at_current_time(self, symbol: str) -> bool:
        with self.time_lock:  # ← Lock acquisition (20x per minute)
            return symbol in self.symbols_with_data_at_current_time
```

**Problem**: Lock acquisition overhead (20 times per minute × 144K minutes = 2.9M lock operations)

### Proposed Implementation (Phase 2)

```python
class SimulatedBroker:
    def __init__(self):
        # Double buffer: one for reading, one for writing
        self.symbols_with_data_current: Set[str] = set()  # Read by threads (stable)
        self.symbols_with_data_next: Set[str] = set()     # Written during barrier
        self.bitmap_swap_lock = threading.Lock()          # Only for swap operation
    
    def advance_global_time(self) -> bool:
        """Called from barrier - updates next buffer and swaps."""
        with self.time_lock:
            # ... advance indices and time ...
            
            # Update NEXT buffer (not visible to threads yet)
            self.symbols_with_data_next.clear()
            for symbol in self.current_indices.keys():
                current_idx = self.current_indices[symbol]
                data_length = self.symbol_data_lengths.get(symbol, 0)
                
                if current_idx < data_length:
                    bar_time = self.symbol_timestamps[symbol][current_idx]
                    if bar_time == self.current_time:
                        self.symbols_with_data_next.add(symbol)
            
            # Atomic swap: make next buffer current
            # This is the ONLY place where bitmap_swap_lock is needed
            with self.bitmap_swap_lock:
                self.symbols_with_data_current, self.symbols_with_data_next = \
                    self.symbols_with_data_next, self.symbols_with_data_current
            
            return True
    
    def has_data_at_current_time(self, symbol: str) -> bool:
        """
        Check if symbol has data (LOCK-FREE READ).
        
        No lock needed - we read from the stable 'current' buffer.
        The swap happens atomically, so we always see a consistent state.
        """
        # No lock acquisition - just read from stable buffer
        return symbol in self.symbols_with_data_current
```

### How It Works

**Key Insight**: Separate reading and writing into different buffers

```
Minute N (e.g., 10:00:00):

Symbol Threads:                          Barrier Thread:
1. Read from current buffer              1. Wait at barrier
   (symbols for 10:00:00)                2. advance_global_time() called
2. Process on_tick()                     3. Update NEXT buffer
3. Wait at barrier                          (symbols for 10:01:00)
                                         4. Atomic swap (with bitmap_swap_lock)
                                         5. Release barrier

Minute N+1 (10:01:00):

Symbol Threads:                          
1. Read from current buffer              
   (now contains symbols for 10:01:00)   
2. Process on_tick()
3. Wait at barrier
```

**Timeline**:
```
T=0: All threads at barrier
T=1: advance_global_time() starts (time_lock held)
T=2: Update symbols_with_data_next (time_lock held)
T=3: Swap buffers (bitmap_swap_lock held, very brief)
T=4: advance_global_time() returns (time_lock released)
T=5: barrier_generation++, notify_all()
T=6: Threads wake up
T=7: Threads read from symbols_with_data_current (NO LOCK!)
```

### Benefits

✅ **No lock acquisition** for `has_data_at_current_time()` (eliminates 2.9M lock operations)  
✅ **Atomic swap** ensures threads always see consistent state  
✅ **Very short critical section** for swap (just pointer swap)  
✅ **Additional 1.3-1.5x speedup** on top of Phase 1

### Trade-offs

⚠️ **Slightly higher memory** (~100 bytes per buffer for 20 symbols)  
⚠️ **More complex code** (need to manage two buffers)  
⚠️ **Requires careful testing** (verify no race conditions)

### Thread Safety Analysis

**Question**: Can threads read stale data during swap?

**Answer**: No, because:
1. Swap happens with `bitmap_swap_lock` held (atomic operation)
2. Python's GIL ensures reference swap is atomic
3. Threads either see old buffer (before swap) or new buffer (after swap)
4. Both states are valid - old buffer is for previous minute, new buffer is for current minute
5. Threads are synchronized by barrier, so they won't read until after swap completes

**Edge Case**: What if thread reads during swap?

```python
# Thread 1 (reading):
symbol in self.symbols_with_data_current  # Reads reference

# Thread 2 (swapping):
with self.bitmap_swap_lock:
    self.symbols_with_data_current, self.symbols_with_data_next = \
        self.symbols_with_data_next, self.symbols_with_data_current
```

**Result**: Thread 1 gets a reference to one of the buffers (either old or new). Both are valid sets, so the read is safe. The GIL ensures the reference read is atomic.

### Implementation Effort

**Estimated Time**: 4-5 hours

**Steps**:
1. Add `symbols_with_data_next` and `bitmap_swap_lock` to `__init__()` (15 min)
2. Update `advance_global_time()` to use double-buffering (30 min)
3. Remove lock from `has_data_at_current_time()` (5 min)
4. Add comprehensive tests for thread safety (2 hours)
5. Run multiple backtests to verify correctness (1-2 hours)

---

## Optimization #5: Vectorize Volume Calculations

### Overview

**Goal**: Eliminate repeated Pandas operations for volume calculations  
**Method**: Cache rolling volume averages with O(1) updates  
**Expected Speedup**: **1.3-1.8x** for volume-heavy strategies  
**Complexity**: Medium  
**Risk**: Low-Medium

### Current Implementation

```python
# In FakeoutStrategy._is_breakout_volume_low()
df = self.connector.get_candles(
    self.symbol,
    self.config.range_config.breakout_timeframe,
    count=VOLUME_CALCULATION_PERIOD  # 20 candles
)
avg_volume = df['tick_volume'].tail(20).mean()  # O(N) operation
```

**Problems**:
1. **Repeated DataFrame operations** - called multiple times per signal check
2. **O(N) complexity** - calculates average over 20 candles each time
3. **No caching** - same calculation repeated for same data

### Proposed Implementation

#### Step 1: Create VolumeCache Class

```python
"""
Rolling volume cache for efficient average calculations.

File: src/utils/volume_cache.py
"""
from collections import deque
from typing import Optional


class VolumeCache:
    """
    Cache for rolling volume calculations.
    
    Provides O(1) average calculation instead of O(N) Pandas operations.
    Uses a sliding window approach with running sum.
    """
    
    def __init__(self, lookback: int):
        """
        Initialize volume cache.
        
        Args:
            lookback: Number of periods for rolling average
        """
        self.lookback = lookback
        self.volumes = deque(maxlen=lookback)  # Automatically drops oldest
        self.sum = 0.0
    
    def update(self, volume: float):
        """
        Add new volume and update rolling sum (O(1) operation).
        
        Args:
            volume: New volume value
        """
        # If deque is full, oldest value will be dropped
        if len(self.volumes) == self.lookback:
            # Subtract the value that will be dropped
            self.sum -= self.volumes[0]
        
        # Add new volume
        self.volumes.append(volume)
        self.sum += volume
    
    def get_average(self) -> float:
        """
        Get current rolling average (O(1) operation).
        
        Returns:
            Average volume over lookback period
        """
        if not self.volumes:
            return 0.0
        return self.sum / len(self.volumes)
    
    def is_ready(self) -> bool:
        """
        Check if cache has enough data for reliable average.
        
        Returns:
            True if cache has at least lookback periods
        """
        return len(self.volumes) >= self.lookback
    
    def reset(self):
        """Clear cache (e.g., when reference candle changes)."""
        self.volumes.clear()
        self.sum = 0.0
    
    def __repr__(self):
        return f"VolumeCache(lookback={self.lookback}, size={len(self.volumes)}, avg={self.get_average():.2f})"
```

#### Step 2: Integrate into FakeoutStrategy

```python
# In src/strategy/fakeout_strategy.py

from src.utils.volume_cache import VolumeCache

class FakeoutStrategy(BaseStrategy):
    def __init__(self, ...):
        # ... existing code ...

        # NEW: Volume cache for efficient calculations
        self.volume_cache = VolumeCache(lookback=VOLUME_CALCULATION_PERIOD)

    def _is_new_confirmation_candle(self) -> bool:
        """Check if a new confirmation candle has formed."""
        # ... existing code to get current candle ...

        if new_candle:
            # NEW: Update volume cache with new candle
            self.volume_cache.update(candle.volume)
            self.last_confirmation_candle_time = candle_time
            return True

        return False

    def _is_breakout_volume_low(self, volume: float) -> bool:
        """
        Check if breakout volume is low (OPTIMIZED).

        Uses cached rolling average instead of Pandas operation.
        """
        # NEW: O(1) average calculation
        if not self.volume_cache.is_ready():
            # Fallback to Pandas if cache not ready (first few candles)
            df = self.connector.get_candles(
                self.symbol,
                self.config.range_config.breakout_timeframe,
                count=VOLUME_CALCULATION_PERIOD
            )
            if df is None or len(df) < VOLUME_CALCULATION_PERIOD:
                return False
            avg_volume = df['tick_volume'].mean()
        else:
            # Use cached average (much faster)
            avg_volume = self.volume_cache.get_average()

        # Check if volume is low
        is_low = volume < avg_volume * self.config.max_breakout_volume_multiplier

        return is_low

    def _check_reference_candle(self):
        """Check for new reference candle."""
        # ... existing code ...

        if new_reference_candle:
            # NEW: Reset volume cache when reference candle changes
            # This ensures we calculate volume for the new range
            self.volume_cache.reset()
            # ... rest of existing code ...
```

#### Step 3: Integrate into TrueBreakoutStrategy

```python
# In src/strategy/true_breakout_strategy.py

from src.utils.volume_cache import VolumeCache

class TrueBreakoutStrategy(BaseStrategy):
    def __init__(self, ...):
        # ... existing code ...

        # NEW: Volume cache for efficient calculations
        self.volume_cache = VolumeCache(lookback=VOLUME_CALCULATION_PERIOD)

    def _is_new_confirmation_candle(self) -> bool:
        """Check if a new confirmation candle has formed."""
        # ... existing code to get current candle ...

        if new_candle:
            # NEW: Update volume cache with new candle
            self.volume_cache.update(candle.volume)
            self.last_confirmation_candle_time = candle_time
            return True

        return False

    def _is_true_breakout_volume_high(self, volume: float) -> bool:
        """
        Check if breakout volume is high (OPTIMIZED).

        Uses cached rolling average instead of Pandas operation.
        """
        # NEW: O(1) average calculation
        if not self.volume_cache.is_ready():
            # Fallback to Pandas if cache not ready
            df = self.connector.get_candles(
                self.symbol,
                self.config.range_config.breakout_timeframe,
                count=VOLUME_CALCULATION_PERIOD
            )
            if df is None or len(df) < VOLUME_CALCULATION_PERIOD:
                return False
            avg_volume = df['tick_volume'].mean()
        else:
            # Use cached average (much faster)
            avg_volume = self.volume_cache.get_average()

        # Check if volume is high
        is_high = volume >= avg_volume * self.config.min_breakout_volume_multiplier

        return is_high

    def _check_reference_candle(self):
        """Check for new reference candle."""
        # ... existing code ...

        if new_reference_candle:
            # NEW: Reset volume cache when reference candle changes
            self.volume_cache.reset()
            # ... rest of existing code ...
```

### How It Works

**Traditional Approach** (O(N)):
```
Every signal check:
1. Fetch last 20 candles from DataFrame
2. Extract volume column
3. Calculate mean (sum all 20 values, divide by 20)
4. Compare with breakout volume

Cost: O(N) where N = 20
```

**Optimized Approach** (O(1)):
```
On each new candle:
1. Add new volume to cache
2. Update running sum (add new, subtract oldest)

On signal check:
1. Get average from cache (sum / count)
2. Compare with breakout volume

Cost: O(1)
```

### Benefits

✅ **O(1) average calculation** instead of O(N)
✅ **No DataFrame operations** during signal checks
✅ **Minimal memory overhead** (~160 bytes per cache)
✅ **Automatic cleanup** (deque drops oldest values)
✅ **Easy to test** (simple class with clear behavior)

### Trade-offs

⚠️ **State management** - need to reset cache when reference changes
⚠️ **Initialization period** - first 20 candles use fallback
⚠️ **Memory overhead** - ~160 bytes per strategy instance

### Performance Impact

**For a strategy that checks volume 10 times per minute**:
- Traditional: 10 × O(20) = 200 operations per minute
- Optimized: 10 × O(1) = 10 operations per minute
- **Speedup**: ~20x for volume calculations
- **Overall speedup**: ~1.3-1.8x (volume checks are ~10-20% of total time)

### Implementation Effort

**Estimated Time**: 4-5 hours

**Steps**:
1. Create `src/utils/volume_cache.py` (1 hour)
2. Write unit tests for VolumeCache (1 hour)
3. Integrate into FakeoutStrategy (1 hour)
4. Integrate into TrueBreakoutStrategy (1 hour)
5. Test with backtest and verify results match (1 hour)

---

## Phase 2 Implementation Roadmap

### Decision Matrix

**Choose Path A if**:
- Phase 1 speedup < 3x
- You need maximum performance
- You're comfortable with medium complexity
- You have 8-10 hours available

**Choose Path B if**:
- Phase 1 speedup ≥ 3x
- You prefer lower risk
- You want simpler code
- You have 4-5 hours available

### Path A: Maximum Performance (Recommended)

**Goal**: 4-7x total speedup

**Week 1: Optimization #3b (Double-buffering)**
- Day 1: Implement double-buffering (4 hours)
- Day 2: Test thread safety (1 hour)
- Day 3: Run multiple backtests to verify (1 hour)

**Week 2: Optimization #5 (Vectorize Volume)**
- Day 1: Create VolumeCache class and tests (2 hours)
- Day 2: Integrate into strategies (2 hours)
- Day 3: Test and verify results match (1 hour)

**Total**: 8-10 hours over 2 weeks

### Path B: Balanced Approach

**Goal**: 3-6x total speedup

**Week 1: Optimization #5 (Vectorize Volume)**
- Day 1: Create VolumeCache class and tests (2 hours)
- Day 2: Integrate into strategies (2 hours)
- Day 3: Test and verify results match (1 hour)

**Total**: 4-5 hours over 1 week

---

## Testing Strategy

### Correctness Tests

**For Optimization #3b (Double-buffering)**:

```python
# Test 1: Verify no race conditions
for i in range(10):
    run_backtest()
    verify_results_identical()

# Test 2: Verify bitmap consistency
def test_bitmap_consistency():
    # All threads should see same bitmap state for same minute
    # Log bitmap state from each thread
    # Verify all logs show same symbols at same time
    pass

# Test 3: Verify swap timing
def test_swap_timing():
    # Verify swap happens before threads wake from barrier
    # Add debug logging to track swap timing
    pass
```

**For Optimization #5 (Volume Cache)**:

```python
# Test 1: Verify cache calculations match Pandas
def test_volume_cache_accuracy():
    cache = VolumeCache(lookback=20)
    volumes = [100, 110, 105, 115, 120, ...]  # 20 values

    for v in volumes:
        cache.update(v)

    assert cache.get_average() == np.mean(volumes)

# Test 2: Verify backtest results match
def test_backtest_with_volume_cache():
    # Run backtest with cache
    results_with_cache = run_backtest()

    # Run backtest without cache (using Pandas)
    results_without_cache = run_backtest_baseline()

    # Verify results match
    assert results_with_cache.final_balance == results_without_cache.final_balance
    assert results_with_cache.trade_count == results_without_cache.trade_count
```

### Performance Tests

```python
# Measure speedup
import time

# Baseline (Phase 1)
start = time.time()
run_backtest_phase1()
phase1_time = time.time() - start

# With Phase 2
start = time.time()
run_backtest_phase2()
phase2_time = time.time() - start

speedup = phase1_time / phase2_time
print(f"Phase 2 speedup: {speedup:.2f}x")
print(f"Total speedup: {baseline_time / phase2_time:.2f}x")
```

---

## Risk Assessment

### Optimization #3b (Double-buffering)

**Risks**:
- ⚠️ **Medium**: Race condition if swap not atomic
- ⚠️ **Low**: Memory corruption if buffers not properly managed
- ⚠️ **Low**: Performance regression if swap overhead too high

**Mitigation**:
- ✅ Use Python's GIL for atomic reference swap
- ✅ Comprehensive thread safety tests
- ✅ Measure swap overhead (should be <0.1ms)

### Optimization #5 (Volume Cache)

**Risks**:
- ⚠️ **Low**: Cache not reset properly (stale data)
- ⚠️ **Low**: Floating point precision errors
- ⚠️ **Low**: Memory leak if cache grows unbounded

**Mitigation**:
- ✅ Reset cache when reference candle changes
- ✅ Use same precision as Pandas (float64)
- ✅ Use deque with maxlen (automatic cleanup)

---

## Expected Results

### Performance Metrics

**Path A (Both optimizations)**:
| Metric | Phase 1 | Phase 2 | Improvement |
|--------|---------|---------|-------------|
| Wall-clock time | 40 min | 10-15 min | 2.7-4x faster |
| Steps/second | 120/sec | 300-400/sec | 2.5-3.3x faster |
| Lock acquisitions | 2.9M | 144K | 20x reduction |

**Path B (Volume only)**:
| Metric | Phase 1 | Phase 2 | Improvement |
|--------|---------|---------|-------------|
| Wall-clock time | 40 min | 20-25 min | 1.6-2x faster |
| Volume calculations | O(N) | O(1) | 20x faster |

### Code Complexity

**Path A**:
- Lines added: ~150
- New files: 1 (`volume_cache.py`)
- Modified files: 3 (`simulated_broker.py`, `fakeout_strategy.py`, `true_breakout_strategy.py`)
- Complexity increase: Medium

**Path B**:
- Lines added: ~100
- New files: 1 (`volume_cache.py`)
- Modified files: 2 (`fakeout_strategy.py`, `true_breakout_strategy.py`)
- Complexity increase: Low

---

## Recommendation

### If Phase 1 achieved < 3x speedup:
**Implement Path A** (both optimizations)
- You need the extra performance
- Double-buffering will provide significant gains
- Total effort (8-10 hours) is justified

### If Phase 1 achieved ≥ 3x speedup:
**Implement Path B** (volume only)
- Phase 1 already provides good performance
- Volume optimization is lower risk
- Simpler implementation (4-5 hours)

### If Phase 1 achieved ≥ 4x speedup:
**Consider stopping at Phase 1**
- Diminishing returns for additional optimization
- Focus on other features or strategies
- Re-evaluate if performance becomes an issue

---

**Document Version**: 1.0
**Last Updated**: 2025-11-16
**Status**: Ready for Implementation


