# Threaded Backtest Testing Plan

## Overview

This document outlines the testing strategy for the new threaded backtest architecture.

## Phase 1: Syntax and Import Validation ✅

**Status**: COMPLETE

- [x] Compile `trading_controller.py`
- [x] Compile `time_controller.py`
- [x] Compile `backtest_controller.py`
- [x] Compile `backtest.py`

## Phase 2: Single Symbol Backtest

**Goal**: Verify basic threading works with one symbol

### Test Case 2.1: Single Symbol, Short Period

```python
# In backtest.py
START_DATE = datetime(2024, 11, 1, tzinfo=timezone.utc)
END_DATE = datetime(2024, 11, 2, tzinfo=timezone.utc)  # 1 day
SYMBOLS = ["EURUSD"]
TIME_MODE = TimeMode.MAX_SPEED
```

**Expected Behavior**:
- 1 symbol worker thread created
- 1 position monitor thread created
- TimeController barrier with 2 participants
- Threads synchronize at each step
- Backtest completes successfully

**Validation**:
- Check logs for "Worker thread started for EURUSD"
- Check logs for "Position monitor thread started"
- Check logs for "TimeController initialized for 1 symbols + position monitor"
- Verify final results are calculated
- Compare results with old sequential backtest (should be identical)

### Test Case 2.2: Single Symbol, MAX_SPEED vs REALTIME

**Goal**: Verify TimeMode controls speed correctly

```python
# Run twice with different TIME_MODE
TIME_MODE = TimeMode.MAX_SPEED  # Should complete in seconds
TIME_MODE = TimeMode.REALTIME   # Should take ~1 day of real time for 1 day of data
```

**Expected Behavior**:
- MAX_SPEED: Completes quickly (no delays)
- REALTIME: Takes proportional time (1 second per bar)

**Validation**:
- Measure execution time
- Verify results are identical regardless of speed

## Phase 3: Multi-Symbol Backtest

**Goal**: Verify barrier synchronization with multiple symbols

### Test Case 3.1: Two Symbols

```python
SYMBOLS = ["EURUSD", "GBPUSD"]
START_DATE = datetime(2024, 11, 1, tzinfo=timezone.utc)
END_DATE = datetime(2024, 11, 2, tzinfo=timezone.utc)
TIME_MODE = TimeMode.MAX_SPEED
```

**Expected Behavior**:
- 2 symbol worker threads created
- 1 position monitor thread created
- TimeController barrier with 3 participants
- All threads synchronize at each step

**Validation**:
- Check logs for both symbol threads starting
- Verify barrier synchronization (all threads wait for each other)
- Check for any race conditions or deadlocks
- Verify results match sequential backtest

### Test Case 3.2: Many Symbols (Stress Test)

```python
SYMBOLS = None  # Load from active.set (10+ symbols)
START_DATE = datetime(2024, 11, 1, tzinfo=timezone.utc)
END_DATE = datetime(2024, 11, 7, tzinfo=timezone.utc)  # 1 week
TIME_MODE = TimeMode.MAX_SPEED
```

**Expected Behavior**:
- N symbol worker threads created
- 1 position monitor thread created
- TimeController barrier with N+1 participants
- All threads complete without deadlock

**Validation**:
- Monitor CPU usage (should use multiple cores)
- Check for thread safety issues
- Verify no data corruption
- Compare performance vs sequential backtest

## Phase 4: Position Management

**Goal**: Verify position monitor thread works correctly

### Test Case 4.1: Breakeven and Trailing Stops

```python
# In .env
USE_BREAKEVEN=true
BREAKEVEN_TRIGGER_RR=1.0
USE_TRAILING_STOP=true
TRAILING_STOP_TRIGGER_RR=1.5
```

**Expected Behavior**:
- Position monitor thread manages positions
- Breakeven moves SL to entry when profit reaches 1.0 R:R
- Trailing stop activates when profit reaches 1.5 R:R

**Validation**:
- Check logs for "Moving SL to breakeven"
- Check logs for "Activating trailing stop"
- Verify positions are managed correctly
- Compare with live trading behavior

### Test Case 4.2: Position Closure Detection

**Expected Behavior**:
- Position monitor detects closed positions
- Calls `strategy.on_position_closed()`
- Updates performance tracking

**Validation**:
- Check logs for "Position closed" messages
- Verify `on_position_closed()` is called
- Check symbol performance persistence updates

## Phase 5: Determinism Testing

**Goal**: Verify same inputs produce same outputs

### Test Case 5.1: Repeated Runs

```python
# Run backtest 3 times with identical settings
for i in range(3):
    run_backtest()
    save_results(f"run_{i}.json")
```

**Expected Behavior**:
- All 3 runs produce identical results
- Same trades at same times
- Same final balance/equity

**Validation**:
- Compare `run_0.json`, `run_1.json`, `run_2.json`
- Verify byte-for-byte identical results
- Check trade logs are identical

## Phase 6: Live vs Backtest Parity

**Goal**: Verify backtest behaves identically to live trading

### Test Case 6.1: Code Path Comparison

**Manual Review**:
- Verify `_symbol_worker()` executes same code in both modes
- Verify `_position_monitor()` executes same code in both modes
- Check for any conditional logic that differs

### Test Case 6.2: Component Coverage

**Checklist**:
- [x] Symbol worker threads
- [x] Position monitor thread
- [ ] Background symbol monitoring (inactive symbols)
- [ ] Position reconciliation on startup
- [ ] Session-based position closing
- [ ] Symbol performance tracking

**Action Items**:
- Verify all components run in backtest mode
- Add missing components if needed

## Phase 7: Error Handling

**Goal**: Verify graceful error handling

### Test Case 7.1: Strategy Exception

```python
# Inject error in strategy
def on_tick(self):
    if random.random() < 0.01:  # 1% chance
        raise ValueError("Test error")
```

**Expected Behavior**:
- Error logged
- Thread continues (doesn't crash)
- Other symbols unaffected

### Test Case 7.2: Data Exhaustion

**Expected Behavior**:
- When symbol runs out of data, thread exits gracefully
- Other symbols continue
- Backtest completes when all symbols finish

## Phase 8: Performance Benchmarking

**Goal**: Measure performance vs sequential backtest

### Test Case 8.1: Speed Comparison

```python
# Sequential backtest (old)
start = time.time()
run_sequential_backtest()
sequential_time = time.time() - start

# Threaded backtest (new)
start = time.time()
run_threaded_backtest()
threaded_time = time.time() - start

print(f"Sequential: {sequential_time:.2f}s")
print(f"Threaded: {threaded_time:.2f}s")
print(f"Speedup: {sequential_time / threaded_time:.2f}x")
```

**Expected Results**:
- Threaded should be similar or slightly slower (barrier overhead)
- But threaded provides 100% code parity (worth the trade-off)

## Success Criteria

✅ All test cases pass
✅ No deadlocks or race conditions
✅ Deterministic results (same inputs → same outputs)
✅ Results match sequential backtest
✅ All live trading components active
✅ Graceful error handling
✅ Performance acceptable (within 2x of sequential)

## Known Limitations

1. **Barrier Overhead**: Slight performance penalty vs sequential
2. **Debugging Complexity**: Multi-threaded execution harder to debug
3. **Thread Scheduling**: Non-deterministic thread scheduling (but results are deterministic due to barrier)

## Next Steps

1. Run Phase 2 tests (single symbol)
2. Fix any issues found
3. Run Phase 3 tests (multi-symbol)
4. Run Phase 5 tests (determinism)
5. Run Phase 6 tests (parity)
6. Document results
7. Update user documentation

