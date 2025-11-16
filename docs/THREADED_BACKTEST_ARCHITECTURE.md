# Threaded Backtest Architecture

## Overview

This document describes the **threaded backtest architecture** that runs the actual `TradingController.start()` method with all its real threading components, ensuring 100% behavioral parity between backtesting and live trading.

## Architecture Goals

1. **Run Real Live Code**: Execute the actual `main.py` → `TradingController.start()` code path
2. **Full Threading**: Create all worker threads (one per symbol + position monitor)
3. **Deterministic Execution**: Ensure same inputs produce same outputs despite threading
4. **Speed Control**: Support `TimeMode.MAX_SPEED`, `FAST`, and `REALTIME`
5. **Thread Safety**: Prevent race conditions in multi-threaded data access

## Key Components

### 1. TimeController (Barrier Coordinator)

**Location**: `src/backtesting/engine/time_controller.py`

**Purpose**: Synchronizes all threads using barrier pattern

**How It Works**:
- Each thread (symbol worker or position monitor) calls `wait_for_next_step(participant_id)`
- Thread blocks until ALL participants reach the barrier
- When all ready, TimeController:
  - Increments step counter
  - Applies time delay based on `TimeMode`
  - Notifies all threads to continue
  - All threads wake up and process next bar

**Key Methods**:
```python
def wait_for_next_step(participant: str) -> bool:
    """
    Barrier synchronization point.
    Returns True to continue, False to stop.
    """
```

### 2. TradingController (Modified for Backtest Mode)

**Location**: `src/core/trading_controller.py`

**Changes**:
- Added `time_controller` parameter (optional, backtest only)
- Added `is_backtest_mode` flag
- Modified `_symbol_worker()` to use barrier synchronization in backtest mode
- Modified `_position_monitor()` to participate in barrier

**Backtest Mode Behavior**:

#### Symbol Worker Thread:
```python
while running:
    # Process tick (same as live)
    strategy.on_tick()
    
    # BACKTEST: Wait at barrier
    if is_backtest_mode:
        time_controller.wait_for_next_step(symbol)
        broker.advance_time(symbol)
    
    # LIVE: Sleep 1 second
    else:
        time.sleep(1)
```

#### Position Monitor Thread:
```python
while running:
    # Get and manage positions (same as live)
    positions = connector.get_positions()
    trade_manager.manage_positions(positions)
    
    # BACKTEST: Wait at barrier
    if is_backtest_mode:
        time_controller.wait_for_next_step("position_monitor")
    
    # LIVE: Sleep 5 seconds
    else:
        time.sleep(5)
```

### 3. SimulatedBroker (Thread-Safe)

**Location**: `src/backtesting/engine/simulated_broker.py`

**Thread Safety**:
- `advance_time()` uses `time_lock` to protect `current_indices` and `current_time`
- All position operations use `position_lock`
- All order operations use `order_lock`

**Key Methods**:
```python
def advance_time(symbol: str) -> bool:
    """
    Thread-safe time advancement.
    Called by each symbol thread after barrier release.
    """
    with self.time_lock:
        # Advance current_indices[symbol]
        # Update current_time
```

### 4. BacktestController (Simplified)

**Location**: `src/backtesting/engine/backtest_controller.py`

**New Approach**:
- No longer runs manual sequential loop
- Simply calls `TradingController.start()` and waits for completion
- All threading logic delegated to `TradingController`

**Flow**:
```python
def run(self):
    # Start TimeController
    time_controller.start()
    
    # Start TradingController (creates all threads)
    trading_controller.start()
    
    # Wait for all threads to complete
    _wait_for_completion()
```

## Execution Flow

### Initialization Phase

1. `backtest.py` loads historical data into `SimulatedBroker`
2. Creates `TimeController` with symbols + position monitor
3. Creates `BacktestController` with `SimulatedBroker` and `TimeController`
4. `BacktestController.initialize()` calls `TradingController.initialize()`
   - Creates `MultiStrategyOrchestrator` for each symbol
   - Initializes strategies

### Execution Phase

1. `BacktestController.run()` starts `TimeController` and `TradingController`
2. `TradingController.start()` creates threads:
   - One `_symbol_worker` thread per symbol
   - One `_position_monitor` thread
3. Each thread enters its main loop:

**Symbol Worker Loop** (per symbol):
```
┌─────────────────────────────────────┐
│ strategy.on_tick()                  │
│   ↓                                 │
│ wait_for_next_step(symbol)          │
│   ↓ [BLOCKS until all ready]        │
│ advance_time(symbol)                │
│   ↓                                 │
│ [Loop back to top]                  │
└─────────────────────────────────────┘
```

**Position Monitor Loop**:
```
┌─────────────────────────────────────┐
│ get_positions()                     │
│   ↓                                 │
│ manage_positions()                  │
│   ↓                                 │
│ wait_for_next_step("pos_monitor")  │
│   ↓ [BLOCKS until all ready]        │
│ [Loop back to top]                  │
└─────────────────────────────────────┘
```

4. **Barrier Synchronization**:
   - All threads call `wait_for_next_step()`
   - Last thread to arrive triggers barrier release
   - All threads wake up simultaneously
   - Each symbol thread calls `advance_time(symbol)`
   - Repeat

5. **Completion**:
   - When a symbol runs out of data, its thread exits
   - When all symbol threads exit, backtest completes

## Addressing Threading Challenges

### Challenge 1: Time Synchronization

**Solution**: Barrier pattern ensures all threads process the same time step before advancing

### Challenge 2: Determinism

**Solution**: 
- Barrier ensures deterministic ordering (all threads process bar N before any thread processes bar N+1)
- Thread-safe locks in `SimulatedBroker` prevent race conditions
- Same seed data → same execution order → same results

### Challenge 3: Speed Control

**Solution**: `TimeController._apply_time_delay()` controls speed:
- `MAX_SPEED`: No delay (as fast as CPU allows)
- `FAST`: 100ms delay per step (10x speed)
- `REALTIME`: 1 second delay per step (1x speed)

### Challenge 4: Data Coordination

**Solution**: 
- `advance_time()` is called AFTER barrier release
- All threads advance together
- `time_lock` prevents race conditions in index updates

## Benefits

✅ **100% Code Parity**: Runs exact same code as live trading
✅ **All Components Active**: Position monitor, session checks, all background tasks
✅ **No Code Duplication**: Single code path for live and backtest
✅ **Realistic Testing**: Tests actual threading behavior, race conditions, etc.
✅ **Maintainability**: Changes to live code automatically apply to backtest

## Trade-offs

⚠️ **Complexity**: More complex than sequential loop
⚠️ **Debugging**: Harder to debug multi-threaded execution
⚠️ **Performance**: Barrier synchronization adds overhead (but still fast with MAX_SPEED)

## Usage

```python
# backtest.py
time_controller = TimeController(symbols, mode=TimeMode.MAX_SPEED, include_position_monitor=True)
backtest_controller = BacktestController(broker, time_controller, ...)
backtest_controller.run()
```

## Future Enhancements

- [ ] Add visual progress bar showing thread status
- [ ] Add thread-level performance metrics
- [ ] Support dynamic symbol addition/removal during backtest
- [ ] Add breakpoint/pause functionality for debugging

