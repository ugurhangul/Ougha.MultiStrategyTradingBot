# Threaded Backtest Quick Reference

## TL;DR

The backtest now runs the **actual `TradingController.start()` method** with real threading, ensuring 100% parity with live trading.

## Key Concepts

### Barrier Synchronization

All threads wait at a "barrier" until everyone is ready, then all advance together:

```
Thread 1: [Process] → [Wait at barrier] ────┐
Thread 2: [Process] → [Wait at barrier] ────┼→ [All ready] → [All advance]
Thread 3: [Process] → [Wait at barrier] ────┘
```

### Determinism Despite Threading

Even though threads run concurrently, results are deterministic because:
1. Barrier ensures all threads process bar N before any thread processes bar N+1
2. Locks prevent race conditions
3. Same data + same barrier order = same results

## Code Changes Summary

### 1. TradingController (Modified)

**Added backtest mode detection**:
```python
def __init__(self, ..., time_controller=None):
    self.time_controller = time_controller
    self.is_backtest_mode = time_controller is not None
```

**Modified symbol worker**:
```python
def _symbol_worker(self, symbol, strategy):
    while running:
        strategy.on_tick()
        
        if is_backtest_mode:
            time_controller.wait_for_next_step(symbol)  # Barrier
            broker.advance_time(symbol)
        else:
            time.sleep(1)  # Live mode
```

**Modified position monitor**:
```python
def _position_monitor(self):
    while running:
        positions = connector.get_positions()
        trade_manager.manage_positions(positions)
        
        if is_backtest_mode:
            time_controller.wait_for_next_step("position_monitor")
        else:
            time.sleep(5)
```

### 2. TimeController (Enhanced)

**Added position monitor to barrier**:
```python
def __init__(self, symbols, mode, include_position_monitor=True):
    self.total_participants = len(symbols) + (1 if include_position_monitor else 0)
```

**Barrier synchronization**:
```python
def wait_for_next_step(self, participant):
    with self.barrier_condition:
        self.symbols_ready.add(participant)
        
        if len(self.symbols_ready) == self.total_participants:
            # All ready - release barrier
            self.symbols_ready.clear()
            self.barrier_condition.notify_all()
        else:
            # Wait for others
            while participant in self.symbols_ready:
                self.barrier_condition.wait()
```

### 3. SimulatedBroker (Thread-Safe)

**Enhanced advance_time**:
```python
def advance_time(self, symbol):
    with self.time_lock:  # Full lock protection
        # Increment current_indices[symbol]
        # Update current_time
```

### 4. BacktestController (Simplified)

**Old approach** (manual loop):
```python
def run(self):
    while has_data:
        for symbol in symbols:
            broker.advance_time(symbol)
            strategy.on_tick()
        broker.update_positions()
        trade_manager.manage_positions()
```

**New approach** (threaded):
```python
def run(self):
    time_controller.start()
    trading_controller.start()  # Creates all threads
    _wait_for_completion()      # Wait for threads to finish
```

## Usage

### Running a Backtest

```python
# backtest.py (no changes needed - already updated)
python backtest.py
```

### Configuration

```python
# In backtest.py
TIME_MODE = TimeMode.MAX_SPEED  # As fast as possible
TIME_MODE = TimeMode.FAST       # 10x speed (100ms per bar)
TIME_MODE = TimeMode.REALTIME   # 1x speed (1 second per bar)
```

## Debugging Tips

### Enable Detailed Logging

```python
# In backtest.py
init_logger(log_to_file=True, log_to_console=True, log_level="DEBUG")
```

### Check Thread Status

Look for these log messages:
- `"Worker thread started for {symbol}"`
- `"Position monitor thread started"`
- `"TimeController initialized for N symbols + position monitor"`
- `"All participants ready - releasing barrier"`

### Verify Barrier Synchronization

Add debug logging in `TimeController.wait_for_next_step()`:
```python
self.logger.debug(f"{participant} reached barrier ({len(self.symbols_ready)}/{self.total_participants})")
```

## Common Issues

### Issue 1: Deadlock (Threads Never Complete)

**Symptom**: Backtest hangs indefinitely

**Cause**: Barrier participant count mismatch

**Solution**: Verify `total_participants` matches actual thread count
```python
# Should be: len(symbols) + 1 (position monitor)
```

### Issue 2: Race Condition (Non-Deterministic Results)

**Symptom**: Different results on repeated runs

**Cause**: Missing lock in data access

**Solution**: Ensure all shared data access uses locks

### Issue 3: Slow Performance

**Symptom**: Backtest runs slower than expected

**Cause**: Using REALTIME or FAST mode instead of MAX_SPEED

**Solution**: Set `TIME_MODE = TimeMode.MAX_SPEED`

## Testing Checklist

- [ ] Single symbol backtest completes successfully
- [ ] Multi-symbol backtest completes successfully
- [ ] Results are deterministic (same on repeated runs)
- [ ] Results match old sequential backtest
- [ ] Position monitor manages positions correctly
- [ ] Breakeven and trailing stops work
- [ ] No deadlocks or race conditions
- [ ] Performance is acceptable

## Performance Expectations

**Sequential Backtest** (old):
- 1 day, 1 symbol: ~5 seconds
- 1 week, 10 symbols: ~60 seconds

**Threaded Backtest** (new):
- Similar performance (slight overhead from barrier)
- But provides 100% code parity with live trading

## FAQ

**Q: Why is threaded backtest not faster than sequential?**

A: The barrier synchronization prevents true parallelism. All threads must wait for the slowest thread at each step. However, the goal is **code parity**, not speed.

**Q: Can I disable the position monitor in backtest?**

A: Yes, set `include_position_monitor=False` in `TimeController`, but this reduces parity with live trading.

**Q: How do I verify determinism?**

A: Run the same backtest 3 times and compare results. They should be identical.

**Q: What if I add a new background thread in live trading?**

A: You must also add it to the barrier in backtest mode:
1. Add to `total_participants` count
2. Call `time_controller.wait_for_next_step("thread_name")` in the thread loop

## References

- **Architecture**: `docs/THREADED_BACKTEST_ARCHITECTURE.md`
- **Testing Plan**: `docs/THREADED_BACKTEST_TESTING_PLAN.md`
- **Implementation Summary**: `docs/THREADED_BACKTEST_IMPLEMENTATION_SUMMARY.md`

