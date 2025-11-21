# Backtesting Optimization Quick Reference

## Performance Gains Summary

| Scenario | Speedup | Ticks/sec | Full Year Time | Memory |
|----------|---------|-----------|----------------|--------|
| Conservative | 1.78x | 2,314 | 11-17h | -40% |
| Typical | 2.58x | 3,354 | 8-12h | -47% |
| Optimistic | 4.68x | 6,084 | 4-6h | -55% |

---

## All 18 Optimizations at a Glance

| # | Optimization | Impact | Type |
|---|-------------|--------|------|
| 1 | Selective Timeframe Building | 1.05x-1.67x | Core |
| 2 | Async Logging | 1.13x-1.25x | Core |
| 3 | Event-Driven Strategy Calls | 1.10x-1.15x | Core |
| 4 | Cached Candle Boundary Checks | 1.02x-1.05x | Core |
| 5 | Reduced Logging Verbosity | 1.05x-1.10x | Core |
| 6 | __slots__ for Tick Dataclasses | 1.03x-1.08x + 40% mem | Core |
| 7 | __slots__ for Candle Dataclasses | 1.02x-1.05x + 30% mem | Advanced |
| 8 | Pre-computed Strategy Timeframes | 1.02x-1.04x | Advanced |
| 9 | Cached DataFrame Creation | 1.10x-1.30x | Advanced |
| 10 | Pre-computed Timeframe Durations | 1.01x-1.03x | Advanced |
| 11 | Skip Timezone Checks | 1.01x-1.02x | Advanced |
| 12 | NumPy Arrays for DataFrames | 1.05x-1.15x | Micro |
| 13 | Reduced Dictionary Lookups | 1.01x-1.03x | Micro |
| 14 | Reduced Attribute Access | 1.02x-1.04x | Micro |
| 15 | Optimized String Formatting | 1.01x-1.02x | Fine-tuning |
| 16 | Reuse Set Objects | 1.01x-1.02x | Fine-tuning |
| 17 | Cached Tick/Position Attributes | 1.02x-1.04x | Fine-tuning |
| 18 | Reduced Progress Update Frequency | 1.01x-1.02x | Fine-tuning |

---

## Top 5 Most Impactful Optimizations

1. **#1: Selective Timeframe Building** (1.05x-1.67x)
   - Only build candles for timeframes strategies actually use
   - Biggest single optimization

2. **#2: Async Logging** (1.13x-1.25x)
   - Move I/O to background thread
   - Eliminates blocking on file writes

3. **#3: Event-Driven Strategy Calls** (1.10x-1.15x)
   - Only call `on_tick()` when relevant candles update
   - Reduces unnecessary strategy processing

4. **#9: Cached DataFrame Creation** (1.10x-1.30x)
   - Avoid rebuilding DataFrames when candles unchanged
   - High impact for strategies that call `get_candles()` frequently

5. **#12: NumPy Arrays for DataFrames** (1.05x-1.15x)
   - 2-3x faster than list comprehensions
   - Significant when cache misses occur

---

## Configuration Checklist

### In `backtest.py`:

```python
# Enable async logging
USE_ASYNC_LOGGING = True

# Set log level to WARNING
BACKTEST_LOG_LEVEL = "WARNING"

# Initialize logger with async support
init_logger(
    log_to_file=True,
    log_to_console=ENABLE_CONSOLE_LOGS,
    log_level=BACKTEST_LOG_LEVEL,
    use_async_logging=USE_ASYNC_LOGGING
)

# Collect required timeframes from strategies
required_timeframes_set = set()
for symbol, strategy in backtest_controller.trading_controller.strategies.items():
    if hasattr(strategy, 'strategies') and isinstance(strategy.strategies, dict):
        for strategy_key, sub_strategy in strategy.strategies.items():
            timeframes = sub_strategy.get_required_timeframes()
            if timeframes:
                required_timeframes_set.update(timeframes)

# Pass to broker
broker.load_ticks_streaming(
    symbols=symbols,
    start_date=START_DATE,
    end_date=END_DATE,
    required_timeframes=list(required_timeframes_set)
)
```

---

## Strategy Implementation

### Required Method:

All strategies must implement `get_required_timeframes()`:

```python
def get_required_timeframes(self) -> List[str]:
    """Get list of timeframes required by this strategy for candle data."""
    return [
        self.config.range_config.reference_timeframe,  # e.g., 'H4'
        self.config.range_config.breakout_timeframe    # e.g., 'M5'
    ]
```

### Examples:

**Fakeout Strategy** (uses H4 + M5):
```python
def get_required_timeframes(self) -> List[str]:
    return [
        self.config.range_config.reference_timeframe,  # H4
        self.config.range_config.breakout_timeframe    # M5
    ]
```

**HFT Strategy** (tick-only, no candles):
```python
def get_required_timeframes(self) -> List[str]:
    return []  # Tick-only strategy, no candles needed
```

**Multi-Strategy Orchestrator** (aggregates from sub-strategies):
```python
def get_required_timeframes(self) -> List[str]:
    required_timeframes = set()
    for strategy in self.strategies.values():
        if hasattr(strategy, 'get_required_timeframes'):
            timeframes = strategy.get_required_timeframes()
            required_timeframes.update(timeframes)
    return sorted(list(required_timeframes))
```

---

## Key Code Patterns

### 1. Using __slots__ in Dataclasses

```python
@dataclass
class MyDataClass:
    """PERFORMANCE: Uses __slots__ to reduce memory overhead"""
    __slots__ = ('field1', 'field2', 'field3')
    
    field1: str
    field2: float
    field3: int
```

### 2. Caching Expensive Operations

```python
# Cache initialization
self._cache: Dict[str, Any] = {}

# Check cache before expensive operation
if key in self._cache:
    return self._cache[key]

# Compute and cache
result = expensive_operation()
self._cache[key] = result
return result
```

### 3. Reducing Attribute Access

```python
# Bad: repeated attribute access
for item in items:
    self.broker.process(item)
    self.broker.update(item)
    self.broker.log(item)

# Good: cache attribute
broker = self.broker
for item in items:
    broker.process(item)
    broker.update(item)
    broker.log(item)
```

### 4. Reusing Objects

```python
# Bad: create new object on every iteration
for i in range(1000000):
    result = set()
    # ... use result ...

# Good: reuse object
result = set()
for i in range(1000000):
    result.clear()
    # ... use result ...
```

### 5. Pre-computing Values

```python
# Bad: compute on every iteration
for item in items:
    if hasattr(obj, 'method'):
        value = obj.method()
        # ... use value ...

# Good: pre-compute before loop
has_method = hasattr(obj, 'method')
for item in items:
    if has_method:
        value = obj.method()
        # ... use value ...
```

---

## Files Modified

### Core Files:
1. `src/backtesting/engine/backtest_controller.py` - Event-driven calls, pre-computed timeframes, reduced lookups
2. `src/backtesting/engine/simulated_broker.py` - Selective timeframes, WARNING logs, __slots__, cached attributes
3. `src/backtesting/engine/candle_builder.py` - Cached boundaries, DataFrame caching, NumPy arrays, set reuse
4. `backtest.py` - Configuration, timeframe collection, async logging

### Strategy Files:
5. `src/strategy/base_strategy.py` - Added `get_required_timeframes()`
6. `src/strategy/fakeout_strategy.py` - Implemented `get_required_timeframes()`
7. `src/strategy/true_breakout_strategy.py` - Implemented `get_required_timeframes()`
8. `src/strategy/hft_momentum_strategy.py` - Implemented `get_required_timeframes()`
9. `src/strategy/multi_strategy_orchestrator.py` - Aggregates timeframes

### Model Files:
10. `src/models/models/candle_models.py` - Added __slots__ to CandleData, ReferenceCandle

### Utility Files:
11. `src/utils/logging/trading_logger.py` - Async logging infrastructure
12. `src/utils/logging/logger_factory.py` - Async logging support

### Data Loading:
13. `src/backtesting/engine/streaming_tick_loader.py` - Added __slots__ to GlobalTick

---

## Verification Commands

### Compile Check:
```bash
python -m py_compile src/backtesting/engine/backtest_controller.py
python -m py_compile src/backtesting/engine/simulated_broker.py
python -m py_compile src/backtesting/engine/candle_builder.py
python -m py_compile src/models/models/candle_models.py
```

### Import Check:
```bash
python -c "from src.backtesting.engine.backtest_controller import BacktestController; print('OK')"
python -c "from src.backtesting.engine.simulated_broker import SimulatedBroker; print('OK')"
python -c "from src.backtesting.engine.candle_builder import MultiTimeframeCandleBuilder; print('OK')"
```

### Run Backtest:
```bash
python backtest.py
```

---

## Monitoring Performance

### During Backtest:

Watch for these metrics in the progress display:
- **Ticks/sec**: Should be 2,300-6,000 (vs 1,300 before)
- **Memory usage**: Should be 40-55% lower
- **Balance/Equity**: Should match previous backtests (validates correctness)

### After Backtest:

Check the final summary:
- Total execution time
- Average ticks/sec
- Total trades executed
- Final balance/equity

### Validation:

Run the same backtest configuration before and after optimizations:
- Trade count should be identical
- Final balance should be identical (within rounding)
- Trade entry/exit prices should match
- SL/TP hits should match

---

## Troubleshooting

### Issue: Slower than expected

**Check**:
1. Is async logging enabled? (`USE_ASYNC_LOGGING = True`)
2. Is log level set to WARNING? (`BACKTEST_LOG_LEVEL = "WARNING"`)
3. Are strategies implementing `get_required_timeframes()`?
4. Is console logging disabled? (`ENABLE_CONSOLE_LOGS = False`)

### Issue: Different results

**Check**:
1. Are all strategies returning correct timeframes in `get_required_timeframes()`?
2. Is the same date range being used?
3. Are the same symbols being tested?
4. Is the same initial balance being used?

### Issue: Memory usage still high

**Check**:
1. Are __slots__ properly defined in all dataclasses?
2. Is DataFrame caching working? (check cache hit rate in logs)
3. Are there memory leaks in custom strategy code?

---

## Best Practices

1. **Always implement `get_required_timeframes()`** in new strategies
2. **Use WARNING level** for important trade logs
3. **Enable async logging** for production backtests
4. **Monitor ticks/sec** to detect performance regressions
5. **Validate results** after making changes
6. **Profile before optimizing** to find real bottlenecks
7. **Test incrementally** - enable optimizations one at a time
8. **Document changes** to optimization configuration

---

## Next Steps

After implementing these optimizations:

1. **Run test backtest** to measure actual gains
2. **Validate results** match previous backtests
3. **Profile code** to identify remaining bottlenecks
4. **Consider Phase 5 optimizations** (lazy candle building, vectorization)
5. **Document performance** for future reference

---

## Support

For questions or issues:
1. Check `docs/BACKTESTING_OPTIMIZATIONS.md` for detailed explanations
2. Review code comments marked with `PERFORMANCE OPTIMIZATION #N`
3. Run verification commands to ensure correct setup
4. Compare results with pre-optimization baseline

---

**Last Updated**: 2025-11-21
**Optimizations**: 18 total (6 core + 5 advanced + 3 micro + 4 fine-tuning)
**Expected Speedup**: 1.78x-4.68x
**Memory Savings**: 40-55%

