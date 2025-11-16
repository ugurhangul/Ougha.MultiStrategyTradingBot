# Tick-Level Backtesting - Executive Summary

**Date**: 2025-11-16  
**Prepared For**: Uğurhan Gül  
**Status**: ✅ **FEASIBLE - RECOMMENDED TO PROCEED**

---

## Problem Statement

Current backtesting uses **OHLCV candle data** (M1 granularity), which has critical limitations:

1. ❌ **HFT Strategy is Broken**: Uses simulated ticks (M1 close price), cannot detect real tick-level momentum
2. ❌ **SL/TP Inaccuracy**: Checks only at candle close, misses intra-candle hits
3. ❌ **Static Spread**: Uses fixed spread, underestimates real trading costs
4. ❌ **No Intra-Candle Visibility**: Cannot see price action within 1-minute bars

**Result**: Backtest results are **overly optimistic** and don't match live trading behavior.

---

## Proposed Solution

**Tick-Level Backtesting** using MT5's `copy_ticks_range()` API:

- ✅ Load **bid/ask/last prices** at tick granularity
- ✅ Advance time **second-by-second** (not minute-by-minute)
- ✅ Check **SL/TP on every tick** (not just candle close)
- ✅ Build **OHLCV candles from ticks** on-demand for strategies
- ✅ Simulate **dynamic spread** from real tick data
- ✅ Enable **proper HFT strategy testing** with real tick momentum

---

## Key Benefits

| Benefit | Impact | Priority |
|---------|--------|----------|
| **HFT Strategy Accuracy** | Critical - currently broken | 🔴 HIGH |
| **SL/TP Precision** | High - catches intra-candle hits | 🔴 HIGH |
| **Realistic Spread Costs** | Medium - better cost estimation | 🟡 MEDIUM |
| **Intra-Candle Visibility** | Medium - better debugging | 🟡 MEDIUM |
| **Future-Proof Architecture** | High - enables advanced strategies | 🟢 LOW |

---

## Performance Impact

### Data Volume
- **Current**: ~10,080 M1 bars per week per symbol
- **Tick-Level**: ~700,000 ticks per week per symbol
- **Ratio**: ~70x more data points

### Processing Time
- **Current**: 30-60 seconds for 7-day backtest
- **Tick-Level (estimated)**: 30-60 minutes for 7-day backtest
- **Ratio**: ~60x slower (second-by-second vs minute-by-minute)

### Memory Usage
- **Current**: ~14 MB for 5 symbols
- **Tick-Level**: ~165 MB for 5 symbols
- **Ratio**: ~12x more memory (still manageable)

**Conclusion**: Performance impact is **acceptable** for the accuracy gains.

---

## Architecture Changes

### 1. BacktestDataLoader
- ✅ Add `load_ticks_from_mt5()` method
- ✅ Add `build_candles_from_ticks()` utility
- ✅ Extend caching to support tick data

### 2. SimulatedBroker
- ✅ Store tick data: `symbol_ticks[symbol] = DataFrame`
- ✅ Track tick indices: `tick_indices[symbol] = int`
- ✅ Cache current tick: `current_ticks[symbol] = TickData`
- ✅ Build candles on-demand with caching
- ✅ Check SL/TP on every tick in each second

### 3. TimeController
- ✅ Add `granularity` parameter: "tick", "second", "minute"
- ✅ Advance by 1 second (recommended) or 1 tick
- ✅ Process tick batches per second

### 4. Strategies
- ✅ **NO CHANGES REQUIRED** - same interface
- ✅ `get_candles()` returns tick-derived OHLCV
- ✅ `get_tick()` returns real tick data
- ✅ `get_current_price()` returns tick bid/ask

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [ ] Implement `load_ticks_from_mt5()` in BacktestDataLoader
- [ ] Add tick storage to SimulatedBroker
- [ ] Implement `build_candles_from_ticks()` utility
- [ ] Add tick data caching

### Phase 2: Time Controller (Week 2)
- [ ] Modify TimeController for second-by-second advancement
- [ ] Implement `advance_global_time_tick_mode()` in SimulatedBroker
- [ ] Add tick index tracking and binary search optimization

### Phase 3: Broker Methods (Week 2-3)
- [ ] Update `get_current_price()` to use tick data
- [ ] Update `get_tick()` to return real ticks
- [ ] Implement `_check_sl_tp_on_ticks()` for intra-candle hits
- [ ] Add candle caching with invalidation

### Phase 4: Testing & Optimization (Week 3-4)
- [ ] Test with 1-day backtest (validate correctness)
- [ ] Profile performance bottlenecks
- [ ] Implement optimizations (batching, caching, binary search)
- [ ] Compare results: tick-level vs candle-level

### Phase 5: Production (Week 4)
- [ ] Add configuration flag: `USE_TICK_DATA=true/false`
- [ ] Update documentation
- [ ] Run full 7-day backtests
- [ ] Validate HFT strategy performance

**Total Timeline**: 3-4 weeks

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Performance too slow | Medium | High | Implement optimizations (batching, caching) |
| Memory overflow | Low | Medium | Use chunked loading, process day-by-day |
| Broker data gaps | Medium | Medium | Fallback to candle-based mode |
| Implementation bugs | Medium | High | Extensive testing, gradual rollout |
| Complexity increase | Low | Low | Keep interface unchanged |

**Overall Risk**: 🟡 **MEDIUM** (manageable with proper planning)

---

## Success Criteria

### Functional Requirements
- ✅ Tick data loads successfully from MT5
- ✅ Candles built from ticks match MT5 candles (±1 pip tolerance)
- ✅ SL/TP hits detected accurately (intra-candle)
- ✅ HFT strategy receives real tick data (not simulated)
- ✅ Existing strategies work unchanged

### Performance Requirements
- ✅ 7-day backtest completes in < 60 minutes
- ✅ Memory usage < 500 MB
- ✅ No crashes or data corruption

### Quality Requirements
- ✅ Backtest results more conservative than current (catches SL hits)
- ✅ HFT strategy generates realistic signals
- ✅ Spread costs match live trading

---

## Recommendation

### ✅ **PROCEED with Tick-Level Backtesting**

**Rationale**:
1. **Critical Need**: HFT strategy is currently broken and unusable
2. **High ROI**: Accuracy gains justify 60x performance cost
3. **Low Risk**: Strategies unchanged, backward compatible
4. **Future-Proof**: Enables advanced strategies (scalping, market-making)
5. **Manageable Scope**: 3-4 weeks for full implementation

**Alternative Rejected**: Hybrid approach (tick data only for HFT)
- **Reason**: Inconsistent simulation fidelity, more complex architecture

---

## Next Steps

1. **Review & Approve**: Review this analysis and technical spec
2. **Start Phase 1**: Implement tick data loading (Week 1)
3. **Test Early**: Run 1-day backtest to validate approach
4. **Iterate**: Optimize based on performance profiling
5. **Scale Up**: Gradually increase to 7-day backtests

**First Milestone**: 1-day tick-level backtest working by end of Week 1

---

## Related Documents

- [TICK_LEVEL_BACKTESTING_ANALYSIS.md](TICK_LEVEL_BACKTESTING_ANALYSIS.md) - Full feasibility analysis
- [TICK_LEVEL_IMPLEMENTATION_SPEC.md](TICK_LEVEL_IMPLEMENTATION_SPEC.md) - Technical specification
- [THREADED_BACKTEST_ARCHITECTURE.md](THREADED_BACKTEST_ARCHITECTURE.md) - Current architecture

---

## Questions & Answers

**Q: Will this break existing backtests?**  
A: No - backward compatible via `USE_TICK_DATA=false` flag.

**Q: Can we run tick-level backtests on older data?**  
A: Yes - if broker provides tick history. Most brokers have 1-3 months of tick data.

**Q: What if tick data is not available?**  
A: Fallback to candle-based mode automatically.

**Q: Will strategies need changes?**  
A: No - they use the same interface (`get_candles()`, `get_tick()`).

**Q: How much faster is live trading vs tick-level backtest?**  
A: Live trading is real-time (1 second = 1 second). Backtest is 60x faster (7 days in 60 minutes).

**Q: Can we speed up tick-level backtests?**  
A: Yes - with optimizations (batching, caching), estimated 5-15 minutes for 7 days.

---

**Prepared by**: Augment Agent  
**Date**: 2025-11-16  
**Status**: Ready for Review

