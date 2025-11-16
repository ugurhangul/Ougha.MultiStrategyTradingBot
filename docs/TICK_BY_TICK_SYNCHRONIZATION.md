# Tick-by-Tick Synchronization Analysis

**Date**: 2025-11-16  
**Question**: How to synchronize all workers when advancing tick-by-tick?  
**Status**: Technical Analysis

---

## Problem Statement

**Current Architecture**: Advances time by **1 minute** (fixed interval)
- All symbols synchronize at minute boundaries
- Simple: `current_time += timedelta(minutes=1)`
- Barrier releases when all symbols processed current minute

**Tick-by-Tick Challenge**: Ticks occur at **irregular intervals**
- EURUSD tick at 14:30:00.123
- GBPUSD tick at 14:30:00.456
- USDJPY tick at 14:30:00.789
- **Question**: What is the "next time step"? Which tick do we advance to?

---

## Current Synchronization Mechanism

### Barrier Pattern (TimeController)

```python
def wait_for_next_step(self, participant: str) -> bool:
    with self.barrier_condition:
        # 1. Mark participant as ready
        self.symbols_ready.add(participant)
        
        # 2. Check if all participants ready
        if len(self.symbols_ready) == self.total_participants:
            # All ready - advance time
            self.broker.advance_global_time()  # ← Determines next time step
            
            # Release barrier
            self.barrier_generation += 1
            self.barrier_condition.notify_all()
        
        # 3. Wait for barrier release
        while self.barrier_generation == arrival_generation:
            self.barrier_condition.wait()
        
        return self.running
```

### Current Time Advancement (SimulatedBroker)

```python
def advance_global_time(self) -> bool:
    with self.time_lock:
        # Advance indices for symbols with data at current_time
        for symbol in self.current_indices.keys():
            bar_time = self.symbol_timestamps[symbol][current_idx]
            if bar_time == self.current_time:
                self.current_indices[symbol] += 1
        
        # Advance time by FIXED interval (1 minute)
        self.current_time += timedelta(minutes=1)  # ← Fixed interval
        
        return True
```

**Key Insight**: Time advances by **fixed interval**, not by "next available data point"

---

## Challenge: Irregular Tick Timestamps

### Example: 3 Symbols with Ticks

**EURUSD ticks**:
```
14:30:00.000
14:30:00.123
14:30:00.456
14:30:00.789
14:30:01.000
```

**GBPUSD ticks**:
```
14:30:00.000
14:30:00.234
14:30:00.567
14:30:00.890
14:30:01.100
```

**USDJPY ticks**:
```
14:30:00.000
14:30:00.345
14:30:00.678
14:30:00.901
14:30:01.200
```

**Question**: After processing tick at 14:30:00.000, what is the "next time step"?
- Option A: 14:30:00.123 (EURUSD's next tick)
- Option B: 14:30:00.234 (GBPUSD's next tick)
- Option C: 14:30:00.345 (USDJPY's next tick)
- **Option D: 14:30:00.123 (earliest next tick across all symbols)** ✅

---

## Solution 1: Global Tick Timeline (Recommended)

### Concept: Merge All Ticks into Single Timeline

**Algorithm**:
1. Load all ticks for all symbols
2. Merge into single sorted timeline by timestamp
3. Advance tick-by-tick through merged timeline
4. Each symbol processes only its own ticks

### Data Structure

```python
@dataclass
class GlobalTick:
    """Single tick in global timeline."""
    time: datetime
    symbol: str
    bid: float
    ask: float
    last: float
    volume: int

class SimulatedBroker:
    def __init__(self):
        # NEW: Global tick timeline (merged from all symbols)
        self.global_tick_timeline: List[GlobalTick] = []
        self.global_tick_index: int = 0
        
        # Per-symbol tick data (for reference)
        self.symbol_ticks: Dict[str, pd.DataFrame] = {}
```

### Loading Phase

```python
def load_all_tick_data(self, symbols: List[str], start_date, end_date):
    """
    Load tick data for all symbols and merge into global timeline.
    """
    all_ticks = []
    
    # Load ticks for each symbol
    for symbol in symbols:
        ticks_df = load_ticks_from_mt5(symbol, start_date, end_date)
        
        # Convert to GlobalTick objects
        for _, row in ticks_df.iterrows():
            all_ticks.append(GlobalTick(
                time=row['time'],
                symbol=symbol,
                bid=row['bid'],
                ask=row['ask'],
                last=row['last'],
                volume=row['volume']
            ))
    
    # Sort by timestamp (CRITICAL!)
    all_ticks.sort(key=lambda t: t.time)
    
    self.global_tick_timeline = all_ticks
    self.global_tick_index = 0
    
    self.logger.info(f"Loaded {len(all_ticks)} ticks across {len(symbols)} symbols")
```

### Time Advancement

```python
def advance_global_time_tick_by_tick(self) -> bool:
    """
    Advance to next tick in global timeline.
    
    Returns:
        True if advanced, False if no more ticks
    """
    with self.time_lock:
        # Check if we have more ticks
        if self.global_tick_index >= len(self.global_tick_timeline):
            return False  # No more ticks
        
        # Get next tick
        next_tick = self.global_tick_timeline[self.global_tick_index]
        
        # Advance global time to this tick's timestamp
        self.current_time = next_tick.time
        
        # Update current tick for the symbol
        self.current_ticks[next_tick.symbol] = TickData(
            time=next_tick.time,
            bid=next_tick.bid,
            ask=next_tick.ask,
            last=next_tick.last,
            volume=next_tick.volume,
            spread=next_tick.ask - next_tick.bid
        )
        
        # Check SL/TP for this symbol's positions
        self._check_sl_tp_for_symbol(next_tick.symbol, next_tick)
        
        # Advance index
        self.global_tick_index += 1
        
        return True
```

### Symbol Worker Processing

```python
def _symbol_worker(self, symbol: str, strategy):
    """
    Worker thread for a symbol (tick-by-tick mode).
    """
    while self.running:
        # Check if current tick belongs to this symbol
        current_tick = self.broker.get_current_tick_for_symbol(symbol)
        
        if current_tick is not None:
            # This symbol has a tick at current time - process it
            strategy.on_tick()
        # else: No tick for this symbol at current time - skip
        
        # Wait at barrier (all symbols wait, regardless of whether they had a tick)
        if not self.time_controller.wait_for_next_step(symbol):
            break
```

### Barrier Synchronization (Unchanged!)

```python
# TimeController.wait_for_next_step() - NO CHANGES NEEDED!
def wait_for_next_step(self, participant: str) -> bool:
    with self.barrier_condition:
        self.symbols_ready.add(participant)
        
        if len(self.symbols_ready) == self.total_participants:
            # All ready - advance to NEXT TICK in global timeline
            if not self.broker.advance_global_time_tick_by_tick():
                self.running = False
            
            self.barrier_generation += 1
            self.barrier_condition.notify_all()
        
        while self.barrier_generation == arrival_generation:
            self.barrier_condition.wait()
        
        return self.running
```

---

## Solution 2: Second-by-Second with Tick Batching (Simpler)

### Concept: Process All Ticks in Each Second

**Algorithm**:
1. Advance time by 1 second (fixed interval)
2. Process ALL ticks that occurred in that second for ALL symbols
3. Simpler than tick-by-tick, still high fidelity

### Time Advancement

```python
def advance_global_time_second_by_second(self) -> bool:
    """
    Advance by 1 second, process all ticks in that second.
    """
    with self.time_lock:
        # Target time: current_time + 1 second
        next_time = self.current_time + timedelta(seconds=1)
        
        # Process ticks for each symbol in [current_time, next_time)
        for symbol in self.symbol_ticks.keys():
            ticks_df = self.symbol_ticks[symbol]
            current_idx = self.tick_indices[symbol]
            
            # Find all ticks in this second
            tick_times = self.tick_timestamps[symbol]
            end_idx = np.searchsorted(tick_times[current_idx:], next_time) + current_idx
            
            if current_idx < end_idx:
                # Process ticks in this second
                second_ticks = ticks_df.iloc[current_idx:end_idx]
                
                # Update current tick to LAST tick in this second
                last_tick = second_ticks.iloc[-1]
                self.current_ticks[symbol] = TickData(...)
                
                # Check SL/TP on EACH tick
                self._check_sl_tp_on_ticks(symbol, second_ticks)
                
                # Advance index
                self.tick_indices[symbol] = end_idx
        
        # Advance global time by 1 second
        self.current_time = next_time
        
        return True
```

### Barrier Synchronization (Unchanged!)

Same as current implementation - no changes needed!

---

## Comparison: Tick-by-Tick vs Second-by-Second

| Aspect | Tick-by-Tick | Second-by-Second |
|--------|--------------|------------------|
| **Time Steps** | ~700k/week | ~604k/week |
| **Complexity** | High (merge ticks) | Medium (batch ticks) |
| **Fidelity** | Highest | Very High |
| **Performance** | Slowest | Faster |
| **Synchronization** | Same barrier pattern | Same barrier pattern |
| **Implementation** | Complex | Moderate |

---

## Recommendation: Second-by-Second (Solution 2)

### Rationale

1. **Simpler Implementation**
   - No need to merge ticks from all symbols
   - Process ticks in batches per second
   - Less complex data structures

2. **Good Enough Fidelity**
   - 1-second granularity is sufficient for most strategies
   - Still catches intra-candle SL hits
   - HFT strategy gets real ticks (not simulated)

3. **Better Performance**
   - Fewer barrier synchronizations (604k vs 700k)
   - Batch processing is more efficient
   - Less overhead

4. **Same Synchronization**
   - Uses existing barrier pattern
   - No changes to TimeController
   - No changes to symbol workers

### When to Use Tick-by-Tick (Solution 1)

Only if you need:
- Ultra-high-frequency strategies (microsecond precision)
- Exact tick-level order execution simulation
- Research on tick-level market microstructure

**For most trading strategies**: Second-by-second is sufficient!

---

## Implementation Plan

### Phase 1: Second-by-Second Mode

1. Add `advance_global_time_second_by_second()` to SimulatedBroker
2. Modify TimeController to call new method
3. Test with 1-day backtest
4. Validate SL/TP checking on ticks

### Phase 2: Tick-by-Tick Mode (Optional)

1. Implement global tick timeline merging
2. Add `advance_global_time_tick_by_tick()` to SimulatedBroker
3. Add configuration flag: `TIME_GRANULARITY = "tick"`
4. Test with 1-day backtest

---

## Key Insight

**The barrier pattern doesn't care about time granularity!**

Whether you advance by:
- 1 minute (current)
- 1 second (proposed)
- 1 tick (optional)

The synchronization logic is **identical**:
1. All threads wait at barrier
2. Last thread calls `advance_global_time()`
3. Time advances (by whatever interval)
4. All threads released

**The only change**: What `advance_global_time()` does internally!

---

## Answer to Your Question

**Q: How to sync all workers when advancing tick-by-tick?**

**A: Use the SAME barrier pattern, just change what "next time step" means!**

**Current**: Next time step = current_time + 1 minute  
**Second-by-second**: Next time step = current_time + 1 second  
**Tick-by-tick**: Next time step = timestamp of next tick in global timeline

**No changes to**:
- TimeController.wait_for_next_step()
- Symbol worker threads
- Barrier synchronization logic

**Only change**:
- SimulatedBroker.advance_global_time() implementation

**Conclusion**: Synchronization is **not a problem** - it's already solved by the barrier pattern!

