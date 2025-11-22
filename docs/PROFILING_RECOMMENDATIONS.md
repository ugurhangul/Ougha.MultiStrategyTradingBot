# Profiling Recommendations - 20k TPS Analysis

## Executive Summary

Since profiling with MT5 data is not feasible (MT5 doesn't have historical tick data for the dates we tried), I've analyzed the codebase to identify the most likely bottlenecks at **20,000 tps**.

**Key Finding**: At 20k tps, you've already achieved **excellent performance** (15.4x speedup). Further optimization requires **targeted, data-driven** changes based on actual profiling data from your working backtest.

---

## Current Performance Analysis

**Baseline**: 1,300 tps  
**Current**: 20,000 tps  
**Improvement**: 15.4x speedup  
**Full-year backtest**: 1.3-2.0 hours (down from 20-30 hours)

**Status**: ✅ **Excellent performance** for production use

---

## Why Phase 5A Didn't Work

### Investigation Results

1. **Optimization #21 (Strategy Candle Caching)**: **Redundant**
   - The broker's `MultiTimeframeCandleBuilder` already has DataFrame caching (Optimization #9)
   - Adding another cache layer at strategy level provides no benefit
   - In fact, it adds overhead (cache key creation, dictionary lookups)

2. **Optimization #23 (Lazy Profit Updates)**: **Already Implemented**
   - Sequential mode already uses lazy profit calculation
   - Profit only calculated when getting equity (every 1000 ticks), closing positions, or querying positions
   - Already optimal

**Lesson**: Always check if an optimization already exists before implementing it!

---

## Likely Bottlenecks (Based on Code Analysis)

Without actual profiling data, here are the most likely bottlenecks based on code structure:

### 1. **Indicator Calculations** (~10-15% of CPU time)

**Evidence**:
- Strategies calculate indicators on every signal check
- RSI, EMA, ATR, Bollinger Bands using TA-Lib
- Called multiple times per strategy

**Example** (from `hft_momentum_strategy.py`):
```python
def _check_trend_alignment(self):
    df = self.get_candles_cached('M5', count=self.config.trend_ema_period + 50)
    ema_values = talib.EMA(df['close'].values, timeperiod=self.config.trend_ema_period)
    # ... more calculations ...
```

**Potential Optimization**: Indicator caching
- Cache indicator results for each timeframe
- Invalidate when new candle forms
- **Expected Gain**: 3-5%
- **Risk**: LOW

---

### 2. **DataFrame Operations** (~15-20% of CPU time)

**Evidence**:
- Strategies use pandas DataFrames extensively
- `df.iloc[-1]` to get last candle
- `df['close'].values` to get price arrays
- DataFrame slicing and indexing

**Example** (from `fakeout_strategy.py`):
```python
df = self.get_candles_cached('H4', count=2)
last_candle = df.iloc[-2]  # DataFrame indexing
close_price = last_candle['close']  # Series indexing
```

**Potential Optimization**: Use NumPy arrays directly
- Convert DataFrame to NumPy array once
- Use array indexing instead of DataFrame operations
- **Expected Gain**: 5-10%
- **Risk**: MEDIUM (requires refactoring)

---

### 3. **Candle Building** (~10-15% of CPU time)

**Evidence**:
- Candles are built on every tick for all timeframes
- Already has 6 optimizations (#4, #9, #10, #11, #12, #16)
- Further optimization requires architectural changes

**Current Implementation** (from `candle_builder.py`):
```python
def add_tick(self, price: float, volume: int, tick_time: datetime) -> set:
    for timeframe in self.timeframes:  # 5 timeframes
        # Check candle boundary
        # Update OHLCV
        # Close candle if boundary crossed
```

**Potential Optimization**: Lazy candle building
- Only build candles when strategies call `get_candles()`
- **Expected Gain**: 5-10%
- **Risk**: HIGH (breaks event-driven strategy calls)

---

### 4. **Strategy Validation Logic** (~5-10% of CPU time)

**Evidence**:
- Strategies perform extensive validation
- Volume checks, trend alignment, divergence detection
- Multiple timeframe checks

**Example** (from `fakeout_strategy.py`):
```python
def _validate_signal(self, signal):
    # Check volume
    if not self._is_reversal_volume_high():
        return False
    
    # Check divergence
    if not self._check_divergence():
        return False
    
    # ... more checks ...
```

**Potential Optimization**: Early exit optimization
- Check cheapest conditions first
- Skip expensive checks if early conditions fail
- **Expected Gain**: 2-3%
- **Risk**: LOW

---

## Recommended Optimization Path

Since we can't profile with MT5 data, here's the recommended approach:

### **Step 1: Profile Your Working Backtest** ⭐ (CRITICAL)

Instead of using the profiler tool, manually profile your actual backtest:

```python
# Add to backtest.py (around line 1767)
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Run backtest
backtest_controller.run_sequential(backtest_start_time=START_DATE)

profiler.disable()

# Save results
stats = pstats.Stats(profiler)
stats.sort_stats('cumtime')
stats.print_stats(50)
stats.dump_stats('backtest_profile.prof')
```

Then analyze with:
```bash
python -m pstats backtest_profile.prof
> sort cumtime
> stats 50
```

**This will show you the ACTUAL bottlenecks in your working backtest!**

---

### **Step 2: Implement Targeted Optimizations**

Based on profiling results, implement the highest-impact optimizations:

#### **Option A: Indicator Caching** (If indicators are bottleneck)

```python
# In BaseStrategy
class BaseStrategy:
    def __init__(self, ...):
        self._indicator_cache: Dict[Tuple[str, str, int, datetime], float] = {}
    
    def get_rsi_cached(self, timeframe: str, period: int) -> Optional[float]:
        """Get RSI with caching."""
        # Get last candle time for cache key
        df = self.get_candles_cached(timeframe, count=1)
        if df is None or len(df) == 0:
            return None
        
        last_time = pd.Timestamp(df.iloc[-1]['time']).to_pydatetime()
        cache_key = ('RSI', timeframe, period, last_time)
        
        # Check cache
        if cache_key in self._indicator_cache:
            return self._indicator_cache[cache_key]
        
        # Calculate and cache
        df_full = self.get_candles_cached(timeframe, count=period + 50)
        rsi = self.indicators.calculate_rsi(df_full['close'], period)
        
        self._indicator_cache[cache_key] = rsi
        return rsi
```

**Expected Gain**: 3-5%  
**Risk**: LOW

---

#### **Option B: Reduce DataFrame Operations** (If DataFrame ops are bottleneck)

```python
# Add to MultiTimeframeCandleBuilder
def get_candles_array(self, timeframe: str, count: int = 100) -> Optional[np.ndarray]:
    """
    Get candles as NumPy array instead of DataFrame.
    
    Returns:
        NumPy array with shape (n, 6) where columns are:
        [time, open, high, low, close, volume]
    """
    candles = self.completed_candles[timeframe]
    if len(candles) == 0:
        return None
    
    candles_to_return = candles[-count:] if len(candles) > count else candles
    n = len(candles_to_return)
    
    # Create array directly
    arr = np.empty((n, 6), dtype=object)
    for i, c in enumerate(candles_to_return):
        arr[i] = [c.time, c.open, c.high, c.low, c.close, c.volume]
    
    return arr
```

Then in strategies:
```python
# Instead of:
df = self.get_candles_cached('H4', count=2)
close_price = df.iloc[-2]['close']

# Use:
candles = self.connector.get_candles_array('H4', count=2)
close_price = candles[-2, 4]  # Column 4 = close
```

**Expected Gain**: 5-10%  
**Risk**: MEDIUM (requires refactoring strategies)

---

#### **Option C: Early Exit Optimization** (If validation is bottleneck)

```python
# In strategy validation methods
def _validate_signal(self, signal):
    # Check cheapest conditions first
    
    # 1. Simple comparisons (fastest)
    if signal.price <= 0:
        return False
    
    # 2. Cached values (fast)
    if not self._check_simple_conditions():
        return False
    
    # 3. DataFrame operations (medium)
    if not self._check_volume():
        return False
    
    # 4. Indicator calculations (slowest)
    if not self._check_divergence():
        return False
    
    return True
```

**Expected Gain**: 2-3%  
**Risk**: LOW

---

## Alternative: Accept Current Performance

### **Reality Check**

**Current Performance**: 20,000 tps
- **72 million ticks/hour**
- **1.7 billion ticks/day**
- **Full year**: 1.3-2.0 hours

**Is this good enough?**
- ✅ For production backtesting: **Absolutely!**
- ✅ For research/development: **More than sufficient!**
- ✅ For strategy optimization: **Excellent!**

**Consider**:
- Diminishing returns on further optimization
- Increasing complexity and risk
- Time better spent on strategy development

**Question**: Is squeezing out another 3-5% worth the effort?

---

## Conclusion

### **Recommended Path**

1. **Profile your actual working backtest** (Step 1 above)
2. **Analyze the top 10 functions** by cumulative time
3. **Implement targeted optimizations** based on profiling data
4. **Measure improvement** and iterate

### **Alternative Path**

1. **Accept current performance** (20k tps is excellent!)
2. **Focus on strategy development** instead of optimization
3. **Revisit optimization** only if performance becomes a blocker

---

## Summary

**Phase 5 Status**: ✅ **Investigation Complete**

**Key Findings**:
- Phase 5A provided 0% gain (redundant optimizations)
- Phase 5B not recommended (too risky or already implemented)
- Current performance (20k tps) is excellent

**Next Steps**:
1. **Profile your working backtest** to identify actual bottlenecks
2. **Implement targeted optimizations** based on profiling data
3. **OR accept current performance** and focus on strategy development

**Total Optimizations**: 18 optimizations (Phases 1-4)

**Performance**: 15.4x speedup (1,300 → 20,000 tps)

---

**Status**: Ready for profiling or production use.

