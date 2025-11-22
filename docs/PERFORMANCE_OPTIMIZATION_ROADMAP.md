# Backtesting Performance Optimization Roadmap

## Overview

This document provides a comprehensive roadmap for optimizing the backtesting engine performance from the current 20,000 ticks/second to 30,000-50,000 ticks/second.

---

## Performance Journey

### Historical Performance

| Phase | Optimizations | Performance | Speedup | Status |
|-------|--------------|-------------|---------|--------|
| **Baseline** | None | 1,300 tps | 1.0x | ✅ Complete |
| **Phase 1** | Core (6 opts) | ~3,500 tps | 2.7x | ✅ Complete |
| **Phase 2** | Advanced (5 opts) | ~7,500 tps | 5.8x | ✅ Complete |
| **Phase 3** | Micro (3 opts) | ~12,000 tps | 9.2x | ✅ Complete |
| **Phase 4** | Fine-tuning (4 opts) | ~20,000 tps | 15.4x | ✅ Complete |
| **Phase 5A** | Quick Wins (2 opts) | ~22,000 tps | 16.9x | ⏳ Pending |
| **Phase 5B** | Core Improvements (3 opts) | ~30,000 tps | 23.1x | ⏳ Pending |
| **Phase 5C** | Advanced (2 opts) | ~40,000 tps | 30.8x | ⏳ Pending |

### Full-Year Backtest Time Estimates

| Phase | Ticks/sec | Time (hours) | Reduction |
|-------|-----------|--------------|-----------|
| Baseline | 1,300 | 20-30 | - |
| Phase 4 (Current) | 20,000 | 1.3-2.0 | 93% |
| Phase 5A | 22,000 | 1.2-1.8 | 94% |
| Phase 5B | 30,000 | 0.9-1.3 | 96% |
| Phase 5C | 40,000 | 0.7-1.0 | 97% |

---

## Current Bottleneck Analysis

### CPU Time Distribution (Estimated)

```
Total CPU Time per Tick:
├─ Strategy Execution: 60%
│  ├─ get_candles() calls: 25%
│  ├─ DataFrame operations: 20%
│  ├─ Indicator calculations: 10%
│  └─ Signal validation: 5%
├─ Candle Building: 15%
│  ├─ Boundary checks: 3%
│  ├─ OHLCV updates: 8%
│  └─ Candle completion: 4%
├─ SL/TP Checking: 10%
│  ├─ Position lookup: 2%
│  ├─ Price comparisons: 5%
│  └─ Position close: 3%
├─ Progress & Logging: 10%
└─ Broker State Updates: 5%
```

### Key Findings

1. **Strategy execution (60%)** is now the dominant bottleneck
2. **Candle building (15%)** still has optimization potential
3. **DataFrame operations (20%)** are expensive
4. **95%+ of candle building is wasted** (strategies don't call get_candles() on every tick)

---

## Phase 5 Optimization Plan

### Phase 5A: Quick Wins (1-2 days)

**Target**: 22,000 tps (10% gain, low risk)

| # | Optimization | Impact | Complexity | Risk |
|---|-------------|--------|------------|------|
| 21 | Strategy-Level Candle Caching | 1.05x-1.10x | LOW | LOW |
| 23 | Batch Position Profit Updates | 1.02x-1.03x | LOW | LOW |

**Combined Gain**: 1.07x-1.13x (7-13% faster)

**Implementation**:
1. Add caching layer in `BaseStrategy.get_candles_cached()`
2. Remove profit updates from `_check_sl_tp_for_tick()`
3. Calculate profit on-demand (lazy evaluation)

**Files to Modify**:
- `src/strategy/base_strategy.py`
- `src/backtesting/engine/simulated_broker.py`

---

### Phase 5B: Core Improvements (3-5 days)

**Target**: 30,000 tps (50% gain, medium risk)

| # | Optimization | Impact | Complexity | Risk |
|---|-------------|--------|------------|------|
| 19 | Lazy Candle Building | 1.15x-1.25x | MEDIUM | MEDIUM |
| 20 | Direct NumPy Array Storage | 1.10x-1.15x | MEDIUM | LOW |
| 24 | Vectorized SL/TP Checking | 1.05x-1.10x | MEDIUM | LOW |

**Combined Gain**: 1.33x-1.58x (33-58% faster)

**Implementation**:
1. **Lazy Candle Building**:
   - Buffer ticks instead of building candles immediately
   - Build candles only when `get_candles()` is called
   - Reduces candle building by 95%

2. **Direct NumPy Array Storage**:
   - Store candles as NumPy structured arrays
   - Return array views instead of DataFrames
   - Eliminates DataFrame creation overhead

3. **Vectorized SL/TP Checking**:
   - Use NumPy for batch SL/TP checks
   - Process all positions of a symbol at once
   - 5-10x faster than Python loops

**Files to Modify**:
- `src/backtesting/engine/candle_builder.py`
- `src/backtesting/engine/simulated_broker.py`
- `src/strategy/*.py` (update to use NumPy arrays)

---

### Phase 5C: Advanced (1-2 weeks)

**Target**: 40,000+ tps (100%+ gain, higher risk)

| # | Optimization | Impact | Complexity | Risk |
|---|-------------|--------|------------|------|
| 25 | Cython Compilation | 1.30x-1.80x | HIGH | MEDIUM |
| 26 | Parallel Symbol Processing | 4x-8x | HIGH | HIGH |

**Cython Compilation**:
- Compile hot path functions to C
- Target functions:
  - `MultiTimeframeCandleBuilder.add_tick()`
  - `CandleBuilder.add_tick()`
  - `_align_to_timeframe()`
  - `_check_sl_tp_for_tick()`
- Expected: 2-5x speedup for compiled functions
- Overall: 1.3x-1.8x system-wide improvement

**Parallel Symbol Processing**:
- Process independent symbols in parallel
- Use `multiprocessing.Pool`
- Expected: 4-8x speedup on 8-core CPU
- **HIGH RISK**: Requires careful state management
- **Limitation**: Only works if symbols are truly independent

**Files to Create**:
- `src/backtesting/engine/candle_builder.pyx`
- `src/backtesting/engine/simulated_broker_fast.pyx`
- `setup.py` (Cython build configuration)

---

## Implementation Strategy

### Recommended Order

1. **Week 1**: Phase 5A (Quick Wins)
   - Low risk, immediate gains
   - Builds confidence in optimization process
   - Target: 22,000 tps

2. **Week 2-3**: Phase 5B (Core Improvements)
   - High impact, manageable risk
   - Addresses main bottlenecks
   - Target: 30,000 tps

3. **Week 4-6**: Phase 5C (Advanced) - Optional
   - Evaluate based on performance needs
   - Cython: Medium risk, high reward
   - Parallel: High risk, very high reward (if feasible)
   - Target: 40,000+ tps

### Risk Mitigation

**For Each Optimization**:
1. Create feature branch
2. Implement optimization
3. Run unit tests
4. Run integration tests
5. Run short backtest (1 day)
6. Verify results match baseline
7. Measure performance gain
8. If successful: merge to main
9. If failed: document and rollback

**Baseline Validation**:
- Trade count must match exactly
- Final balance must match within $0.01
- SL/TP hits must match exactly
- Performance must improve (no regressions)

---

## Profiling Tools

### 1. Profile Backtest Script

```bash
# Run profiler for 60 seconds
python tools/profile_backtest.py --duration 60 --output profile_results.txt

# Run profiler for 5 minutes, show top 100 functions
python tools/profile_backtest.py --duration 300 --top 100 --output profile_5min.txt

# Sort by total time instead of cumulative time
python tools/profile_backtest.py --duration 60 --sort time
```

### 2. Memory Profiler

```bash
# Install memory_profiler
pip install memory_profiler

# Run with memory profiling
python -m memory_profiler backtest.py
```

### 3. Line Profiler

```bash
# Install line_profiler
pip install line_profiler

# Add @profile decorator to functions
# Run with line profiler
kernprof -l -v backtest.py
```

---

## Success Metrics

### Performance Metrics

| Metric | Baseline | Phase 4 | Phase 5A | Phase 5B | Phase 5C |
|--------|----------|---------|----------|----------|----------|
| Ticks/sec | 1,300 | 20,000 | 22,000 | 30,000 | 40,000 |
| Full Year (hours) | 20-30 | 1.3-2.0 | 1.2-1.8 | 0.9-1.3 | 0.7-1.0 |
| Memory (GB) | 8-12 | 4-6 | 4-6 | 3-5 | 3-5 |
| CPU Usage (%) | 100 | 100 | 100 | 100 | 100 |

### Quality Metrics

| Metric | Target | Validation |
|--------|--------|------------|
| Trade Count | Exact match | Compare with baseline |
| Final Balance | ±$0.01 | Compare with baseline |
| SL/TP Hits | Exact match | Compare with baseline |
| Test Pass Rate | 100% | All tests must pass |
| Code Coverage | >80% | Maintain or improve |

---

## Documentation

### Created Documents

1. **PHASE_5_OPTIMIZATION_ANALYSIS.md** (300 lines)
   - Detailed analysis of current bottlenecks
   - 8 optimization proposals with impact estimates
   - Implementation complexity and risk assessment

2. **PHASE_5_QUICK_REFERENCE.md** (300 lines)
   - Quick reference for all optimizations
   - Code examples for each optimization
   - Testing checklist and rollback plan

3. **PERFORMANCE_OPTIMIZATION_ROADMAP.md** (this document)
   - High-level roadmap and strategy
   - Historical performance journey
   - Success metrics and validation criteria

4. **tools/profile_backtest.py** (300 lines)
   - Profiling tool for performance analysis
   - Identifies hot spots and bottlenecks
   - Generates detailed profiling reports

### Existing Documents

1. **BACKTESTING_OPTIMIZATIONS.md**
   - Detailed explanation of Phases 1-4 (18 optimizations)
   - Performance impact analysis
   - Implementation details

2. **OPTIMIZATION_QUICK_REFERENCE.md**
   - Quick reference for Phases 1-4
   - Code snippets and examples
   - Before/after comparisons

---

## Next Steps

### Immediate Actions

1. **Run Profiler** to validate hot path analysis:
   ```bash
   python tools/profile_backtest.py --duration 60
   ```

2. **Review Analysis** with team:
   - Validate bottleneck identification
   - Confirm optimization priorities
   - Assess risk tolerance

3. **Choose Implementation Phase**:
   - Phase 5A: Low risk, quick wins
   - Phase 5B: High impact, medium risk
   - Phase 5C: Advanced, higher risk

### Implementation Workflow

1. **Create Feature Branch**:
   ```bash
   git checkout -b feature/phase-5a-optimizations
   ```

2. **Implement Optimization**:
   - Follow code examples in PHASE_5_QUICK_REFERENCE.md
   - Write unit tests for new functionality
   - Update integration tests if needed

3. **Test Thoroughly**:
   ```bash
   # Run unit tests
   pytest tests/
   
   # Run integration tests
   pytest tests/integration/
   
   # Run short backtest
   python backtest.py --days 1
   
   # Verify results match baseline
   python tools/compare_results.py baseline.json current.json
   ```

4. **Measure Performance**:
   ```bash
   # Profile before optimization
   python tools/profile_backtest.py --duration 60 --output before.txt
   
   # Profile after optimization
   python tools/profile_backtest.py --duration 60 --output after.txt
   
   # Compare results
   python tools/compare_profiles.py before.txt after.txt
   ```

5. **Document Results**:
   - Update performance metrics
   - Document any issues encountered
   - Update this roadmap with actual results

6. **Merge to Main**:
   ```bash
   git add .
   git commit -m "feat: Implement Phase 5A optimizations (#21, #23)"
   git push origin feature/phase-5a-optimizations
   # Create PR and merge after review
   ```

---

## Conclusion

The backtesting engine has achieved impressive performance gains (15.4x speedup) through 18 optimizations across 4 phases. Phase 5 offers additional optimization opportunities that could push performance to 30,000-50,000 tps (1.5x-2.5x additional gain).

**Recommended Approach**:
1. Start with Phase 5A (low risk, quick wins)
2. Proceed to Phase 5B (high impact, manageable risk)
3. Evaluate Phase 5C based on performance needs and resources

**Key Success Factors**:
- Thorough testing after each optimization
- Baseline validation (results must match)
- Performance measurement (actual vs. expected gains)
- Risk mitigation (feature branches, rollback plan)

**Expected Outcome**:
- Full-year tick-level backtest: **0.7-1.3 hours** (down from 20-30 hours)
- Memory usage: **3-5 GB** (down from 8-12 GB)
- Accuracy: **100% match** with baseline results

The optimization journey continues! 🚀

