# Tick-Level Backtesting Feasibility Analysis

**Date**: 2025-11-16  
**Status**: Feasibility Study  
**Objective**: Evaluate tick-level backtesting vs current candle-based approach

---

## Executive Summary

**Recommendation**: ✅ **FEASIBLE with significant benefits, but requires careful implementation**

Tick-level backtesting would provide:
- ✅ **Higher fidelity** simulation matching real-world execution
- ✅ **Proper HFT strategy testing** (currently impossible with OHLCV data)
- ✅ **Accurate spread/slippage** simulation with real bid/ask prices
- ✅ **Intra-candle price action** visibility (critical for stop-loss hits)
- ⚠️ **Performance impact**: 60-1440x more data points (manageable with optimizations)

---

## 1. MT5 Tick Data API Analysis

### `mt5.copy_ticks_range()` Capabilities

**Function Signature**:
```python
mt5.copy_ticks_range(symbol, date_from, date_to, flags)
```

**Returns**: NumPy array with columns:
- `time` (int): Unix timestamp in seconds
- `bid` (float): Bid price
- `ask` (float): Ask price
- `last` (float): Last trade price
- `volume` (int): Tick volume
- `time_msc` (int): Timestamp in milliseconds
- `flags` (int): Tick flags (TICK_FLAG_BID, TICK_FLAG_ASK, TICK_FLAG_LAST, etc.)

**Flags**:
- `COPY_TICKS_ALL`: All ticks (default)
- `COPY_TICKS_INFO`: Info ticks (bid/ask changes)
- `COPY_TICKS_TRADE`: Trade ticks only

**Limitations**:
- ⚠️ **Data volume**: 1 day of tick data can be 50,000-500,000+ ticks per symbol
- ⚠️ **Broker-dependent**: Not all brokers provide full tick history
- ⚠️ **Memory**: Large datasets require careful memory management
- ✅ **Speed**: NumPy arrays are fast to process

---

## 2. Current Architecture Analysis

### Current Time Granularity: **1 MINUTE**

**TimeController**:
- Advances time by `timedelta(minutes=1)` per barrier cycle
- All symbols synchronize at 1-minute boundaries
- Processes ~1,440 bars per day per symbol (M1 data)

**SimulatedBroker**:
- Stores OHLCV data per timeframe: `symbol_data[(symbol, timeframe)]`
- Current index: `current_indices[symbol]` points to M1 bar
- `get_current_price()`: Returns `close` price from current M1 bar
- `get_tick()`: Simulates tick from M1 bar (bid = close - spread/2, ask = close + spread/2)

**Strategies**:
- `on_tick()` called once per minute (per M1 bar)
- `get_candles()`: Fetches higher timeframe data (M5, M15, H4) filtered by current time
- HFT strategy: Uses `mt5.symbol_info_tick()` which returns simulated tick from M1 close

### Current Limitations

1. **HFT Strategy**: Cannot properly simulate tick-level momentum
   - Currently uses M1 close price as "tick"
   - Misses intra-minute price movements
   - Tick buffer contains only 1 tick per minute (not realistic)

2. **Stop-Loss Execution**: Inaccurate
   - Checks SL/TP only at M1 bar close
   - Misses intra-candle SL hits (could hit SL mid-candle but backtest shows profit)

3. **Spread Simulation**: Static
   - Uses fixed spread from symbol info
   - Real spreads vary tick-by-tick

4. **Slippage**: Simplified
   - Applied as fixed points
   - Real slippage depends on tick-level liquidity

---

## 3. Tick-Level Architecture Design

### 3.1 Data Loading (`BacktestDataLoader`)

**Current**:
```python
rates = mt5.copy_rates_range(symbol, timeframe, start_date, end_date)
# Returns: time, open, high, low, close, tick_volume, spread, real_volume
```

**Proposed**:
```python
ticks = mt5.copy_ticks_range(symbol, start_date, end_date, mt5.COPY_TICKS_INFO)
# Returns: time, bid, ask, last, volume, time_msc, flags
```

**Changes Required**:
- Add `load_ticks_from_mt5()` method
- Store tick data in efficient format (NumPy arrays or chunked DataFrames)
- Build OHLCV candles from ticks on-the-fly for strategy use

### 3.2 Time Controller

**Current**: Advances by 1 minute
```python
self.current_time = self.current_time + timedelta(minutes=1)
```

**Proposed**: Advances by 1 second (or tick-by-tick)
```python
# Option A: Second-by-second (86,400 steps per day)
self.current_time = self.current_time + timedelta(seconds=1)

# Option B: Tick-by-tick (variable steps, ~50k-500k per day)
self.current_time = next_tick_time
```

**Recommendation**: **Second-by-second** for balance between fidelity and performance

### 3.3 SimulatedBroker

**Current**: Stores OHLCV bars
```python
self.symbol_data[(symbol, timeframe)] = DataFrame[time, open, high, low, close, volume]
```

**Proposed**: Stores tick data + builds candles on-demand
```python
# Primary data: Tick-level
self.symbol_ticks[symbol] = DataFrame[time, bid, ask, last, volume]

# Derived data: OHLCV candles (cached)
self.symbol_candles[(symbol, timeframe)] = build_candles_from_ticks(ticks, timeframe)
```

**Key Methods to Modify**:

1. **`load_symbol_data()`**: Load ticks instead of candles
2. **`advance_global_time()`**: Advance by 1 second, process all ticks in that second
3. **`get_current_price()`**: Return bid/ask from current tick (not M1 close)
4. **`get_tick()`**: Return actual tick data (bid, ask, last, volume)
5. **`get_candles()`**: Build OHLCV from ticks up to current time
6. **`update_positions()`**: Check SL/TP on every tick (not just M1 close)

### 3.4 Strategy Changes

**Minimal changes required** (major benefit!):

- `FakeoutStrategy` / `TrueBreakoutStrategy`: 
  - Already use `get_candles()` → will automatically get tick-derived candles
  - No code changes needed
  
- `HFTMomentumStrategy`:
  - `_update_tick_buffer()`: Will get real ticks instead of simulated
  - No code changes needed (already uses `mt5.symbol_info_tick()`)

---

## 4. Performance Impact Analysis

### Data Volume Comparison

**Current (M1 candles)**:
- 1 day = 1,440 bars per symbol
- 7 days = 10,080 bars per symbol
- 5 symbols × 7 days = 50,400 bars total

**Proposed (Tick data)**:
- **Forex majors**: ~50,000-100,000 ticks/day (active hours)
- **Crypto**: ~100,000-500,000 ticks/day (24/7 trading)
- **Stocks**: ~20,000-50,000 ticks/day (market hours only)

**Average**: ~100,000 ticks/day per symbol

**7-day backtest**:
- 5 symbols × 7 days × 100,000 ticks = **3.5 million ticks**
- vs current: 50,400 bars
- **Ratio**: ~70x more data points

### Processing Time Estimate

**Current Performance** (from optimization work):
- 7-day backtest: ~30-60 seconds (MAX_SPEED mode)
- ~840 bars/second per symbol

**Tick-Level Estimate**:

**Option A: Tick-by-tick processing** (worst case)
- 3.5M ticks × (current processing time / 50k bars) = ~2,100 seconds = **35 minutes**

**Option B: Second-by-second processing** (recommended)
- 7 days × 86,400 seconds = 604,800 time steps
- vs current 10,080 steps
- **Ratio**: ~60x more steps
- Estimated time: 30-60 sec × 60 = **30-60 minutes**

**Option C: Optimized tick batching**
- Process ticks in 1-second batches
- Only call `on_tick()` when tick data changes significantly
- Estimated time: **5-15 minutes** (with optimizations)

### Memory Usage

**Current**:
- M1 data: 10,080 bars × 8 bytes × 7 columns = ~560 KB per symbol
- 5 symbols × 5 timeframes = ~14 MB total

**Tick-Level**:
- Tick data: 700,000 ticks × 8 bytes × 6 columns = ~33 MB per symbol
- 5 symbols = ~165 MB total
- **Still manageable** for modern systems (< 200 MB)

---

## 5. Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [ ] Add `load_ticks_from_mt5()` to `BacktestDataLoader`
- [ ] Modify `SimulatedBroker` to store tick data
- [ ] Implement tick-to-candle conversion (build OHLCV from ticks)
- [ ] Add tick data caching (similar to candle caching)

### Phase 2: Time Controller (Week 2)
- [ ] Modify `TimeController` to advance by 1 second
- [ ] Update `advance_global_time()` to process tick batches
- [ ] Implement tick index tracking (similar to current bar index)

### Phase 3: Broker Methods (Week 2-3)
- [ ] Update `get_current_price()` to return tick bid/ask
- [ ] Update `get_tick()` to return real tick data
- [ ] Modify `update_positions()` to check SL/TP on every tick
- [ ] Implement dynamic spread from tick data

### Phase 4: Testing & Optimization (Week 3-4)
- [ ] Test with 1-day backtest (validate correctness)
- [ ] Profile performance bottlenecks
- [ ] Implement optimizations (tick batching, caching)
- [ ] Compare results: tick-level vs candle-level

### Phase 5: Production (Week 4)
- [ ] Add configuration flag: `USE_TICK_DATA=true/false`
- [ ] Update documentation
- [ ] Run full 7-day backtests
- [ ] Validate HFT strategy performance

---

## 6. Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Performance degradation** | High | Implement tick batching, optimize hot paths |
| **Memory overflow** | Medium | Use chunked loading, process day-by-day |
| **Broker data gaps** | Medium | Fallback to candle-based simulation |
| **Complexity increase** | Low | Keep interface unchanged, strategies unaffected |
| **Debugging difficulty** | Medium | Add detailed tick-level logging (optional) |

---

## 7. Recommendation

✅ **PROCEED with tick-level backtesting**

**Rationale**:
1. **Critical for HFT strategy**: Current approach is fundamentally flawed for tick-based strategies
2. **Better accuracy**: Intra-candle SL/TP hits, realistic spread/slippage
3. **Manageable performance**: 30-60 min for 7-day backtest is acceptable
4. **Low strategy impact**: Existing strategies work unchanged
5. **Future-proof**: Enables more sophisticated strategies (scalping, market-making)

**Next Steps**:
1. Start with Phase 1 (data loading)
2. Test with 1-day backtest first
3. Optimize before scaling to 7-day backtests
4. Keep candle-based mode as fallback option

---

## 8. Alternative: Hybrid Approach

**Compromise**: Use tick data only when needed

- **Fakeout/TrueBreakout**: Use M1 candles (sufficient for range-based strategies)
- **HFT Momentum**: Use tick data (required for tick-level signals)
- **SL/TP checking**: Use tick data (critical for accuracy)

**Benefits**:
- Lower performance impact
- Gradual migration path

**Drawbacks**:
- More complex architecture
- Inconsistent simulation fidelity

---

## 9. Comparison Table: Current vs Tick-Level

| Aspect | Current (Candle-Based) | Tick-Level (Proposed) |
|--------|------------------------|----------------------|
| **Data Source** | `copy_rates_range()` | `copy_ticks_range()` |
| **Data Points** | ~10,080 bars/week | ~700,000 ticks/week |
| **Time Granularity** | 1 minute | 1 second |
| **Time Steps** | 10,080/week | 604,800/week |
| **Price Data** | OHLCV | Bid/Ask/Last |
| **Spread** | Static (from symbol_info) | Dynamic (from ticks) |
| **SL/TP Check** | At M1 close only | Every tick |
| **HFT Strategy** | ❌ Broken (simulated ticks) | ✅ Accurate (real ticks) |
| **Intra-Candle Accuracy** | ❌ No visibility | ✅ Full visibility |
| **Backtest Duration** | 30-60 seconds | 30-60 minutes (est.) |
| **Memory Usage** | ~14 MB | ~165 MB |
| **Strategy Changes** | N/A | None required |
| **Backward Compatible** | N/A | ✅ Yes (config flag) |

---

## 10. Key Insights

### Why Tick-Level is Critical

1. **HFT Strategy is Currently Broken**
   - Uses `mt5.symbol_info_tick()` which returns M1 close price
   - Tick buffer contains only 1 "tick" per minute
   - Cannot detect tick-level momentum (requires consecutive tick movements)
   - **Result**: Strategy generates false signals

2. **SL/TP Execution is Inaccurate**
   - Current: Checks SL/TP only at M1 bar close
   - Problem: Price can hit SL mid-candle, then recover by close
   - **Result**: Backtest shows profit, but live trading would have stopped out

3. **Spread Simulation is Unrealistic**
   - Current: Uses fixed spread from symbol_info (e.g., 10 points)
   - Reality: Spread varies tick-by-tick (can spike to 50+ points during news)
   - **Result**: Backtest underestimates trading costs

### Example: Intra-Candle SL Hit

**Scenario**: BUY position at 1.1000, SL at 1.0990, TP at 1.1020

**M1 Candle**: Open=1.1000, High=1.1025, Low=1.0985, Close=1.1015

**Current Backtest**:
- Checks SL/TP at close (1.1015)
- SL not hit (1.1015 > 1.0990)
- Position still open
- **Result**: Profit

**Tick-Level Backtest**:
- Tick 1: 1.1000 (entry)
- Tick 2: 1.0995
- Tick 3: 1.0988 ← **SL HIT** (position closed at loss)
- Tick 4: 1.0985 (low)
- Tick 5: 1.1015 (close)
- **Result**: Loss

**Conclusion**: Current backtest is **overly optimistic**

---

## 11. Implementation Priority

### Must-Have (Phase 1)
1. ✅ Tick data loading (`load_ticks_from_mt5`)
2. ✅ Tick storage in SimulatedBroker
3. ✅ Second-by-second time advancement
4. ✅ SL/TP checking on every tick

### Should-Have (Phase 2)
5. ✅ Tick-to-candle conversion with caching
6. ✅ Dynamic spread from tick data
7. ✅ Performance optimizations (binary search, batching)

### Nice-to-Have (Phase 3)
8. ⚠️ Tick-by-tick mode (vs second-by-second)
9. ⚠️ Tick data visualization
10. ⚠️ Tick-level slippage simulation

---

## 12. Final Recommendation

### ✅ **PROCEED with Tick-Level Backtesting**

**Justification**:
1. **Critical for HFT**: Current approach is fundamentally broken
2. **Better accuracy**: Catches intra-candle SL hits
3. **Realistic costs**: Dynamic spread simulation
4. **Manageable impact**: 30-60 min for 7-day backtest is acceptable
5. **Low risk**: Strategies unchanged, backward compatible

**Next Steps**:
1. Implement Phase 1 (data loading + tick storage)
2. Test with 1-day backtest
3. Validate HFT strategy behavior
4. Optimize performance
5. Scale to 7-day backtests

**Timeline**: 3-4 weeks for full implementation

