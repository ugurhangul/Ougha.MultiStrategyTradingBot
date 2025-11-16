# Backtest Validation Guide

## Overview

This guide explains how to validate the correctness and trustworthiness of your backtest results.

## Recent Improvements (2025-11-16)

### ✅ Implemented Features

1. **Slippage Simulation**
   - Realistic order execution with slippage
   - Base slippage: 0.5 points (configurable)
   - Volume-based slippage: Larger orders = more slippage
   - Volatility-based slippage: High volume bars = more slippage
   - Configuration: `ENABLE_SLIPPAGE` and `SLIPPAGE_POINTS` in `backtest.py`

2. **Intra-Bar SL/TP Detection**
   - Uses high/low prices instead of just close
   - Detects SL/TP hits that occur during the bar
   - More realistic than close-only checking
   - Prevents false position survival

3. **Order Rejection Simulation**
   - Volume validation (min/max lot size)
   - Stops level validation (minimum SL/TP distance)
   - Insufficient margin checks
   - Matches real MT5 rejection behavior

4. **Reproducibility Testing**
   - Test script: `test_backtest_reproducibility.py`
   - Verifies identical results across multiple runs
   - Detects race conditions and threading issues

---

## Trust Levels

### Current Trust Level: 80-85%

**What This Means:**
- ✅ Good for strategy development and optimization
- ✅ Good for relative comparisons between strategies
- ✅ Good for parameter tuning
- ⚠️ Absolute profit predictions may be 10-20% optimistic
- ⚠️ Still need live validation for production deployment

**Why Not 100%?**
- Slippage model is simplified (doesn't account for news events, liquidity)
- No requote simulation during high volatility
- Spread is constant per symbol (real spreads vary)
- No swap/commission simulation (if applicable)
- No connection issues or platform delays

---

## Validation Checklist

### Phase 1: Reproducibility (CRITICAL)

**Goal:** Verify backtest produces identical results every time

**Steps:**
```bash
# Run reproducibility test
python test_backtest_reproducibility.py
```

**Expected Result:**
- ✅ All 3 runs produce identical final balance (to the cent)
- ✅ All 3 runs produce identical trade count
- ✅ All 3 runs produce identical trade tickets and times

**If Test Fails:**
- ❌ Race conditions exist in threading
- ❌ Non-deterministic behavior detected
- ❌ DO NOT TRUST backtest results until fixed

---

### Phase 2: Slippage Validation

**Goal:** Verify slippage is being applied correctly

**Steps:**
1. Run backtest with slippage ENABLED:
   ```python
   # In backtest.py
   ENABLE_SLIPPAGE = True
   SLIPPAGE_POINTS = 0.5
   ```

2. Run backtest with slippage DISABLED:
   ```python
   ENABLE_SLIPPAGE = False
   ```

3. Compare results

**Expected Result:**
- Slippage ENABLED should have LOWER profit than DISABLED
- Difference should be 0.5-2% of total profit
- Check logs for slippage messages: `(slippage: X.Xpts)`

**Example:**
```
No Slippage:  Final Balance: $10,500.00 (+5.0%)
With Slippage: Final Balance: $10,450.00 (+4.5%)
Difference: $50 (0.5% impact) ✅ Reasonable
```

---

### Phase 3: SL/TP Accuracy

**Goal:** Verify SL/TP hits are detected correctly

**Steps:**
1. Review backtest logs for SL/TP hit messages
2. Look for "intra-bar" detection messages
3. Manually verify a few trades:
   - Check if SL was touched by bar's low (BUY) or high (SELL)
   - Check if TP was touched by bar's high (BUY) or low (SELL)

**Expected Result:**
- Should see messages like: `Position X hit SL (intra-bar): bar_low=1.08450 <= SL=1.08455`
- SL/TP should trigger even if close price didn't reach them

**Red Flags:**
- ❌ Positions surviving with SL very close to bar low/high
- ❌ No "intra-bar" messages in logs (old implementation)

---

### Phase 4: Order Rejection Validation

**Goal:** Verify orders are rejected when they should be

**Test Cases:**

1. **Test Invalid Volume:**
   ```python
   # Temporarily modify strategy to use 0.001 lots (below min)
   # Expected: Order rejected with TRADE_RETCODE_INVALID_VOLUME
   ```

2. **Test Stops Level Violation:**
   ```python
   # Temporarily set SL very close to entry (1 point)
   # Expected: Order rejected with TRADE_RETCODE_INVALID_STOPS
   ```

3. **Test Insufficient Margin:**
   ```python
   # Set INITIAL_BALANCE = 100 (very low)
   # Expected: Some orders rejected with TRADE_RETCODE_NO_MONEY
   ```

**Expected Result:**
- Orders should be rejected with appropriate error codes
- Backtest should continue without crashing

---

### Phase 5: Data Quality Validation

**Goal:** Ensure historical data is accurate and complete

**Steps:**
1. Check for data gaps:
   ```python
   # Review backtest logs for warnings about missing data
   ```

2. Verify bar counts:
   ```
   M1: ~1440 bars per day (accounting for weekends)
   M5: ~288 bars per day
   M15: ~96 bars per day
   H4: ~6 bars per day
   ```

3. Check for outliers:
   - Unusually large spreads
   - Price spikes (bad ticks)
   - Zero volume bars

**Red Flags:**
- ❌ Large gaps in data (missing hours/days)
- ❌ Spreads > 10 points for majors
- ❌ Price jumps > 1% in single M1 bar

---

### Phase 6: Live Trading Comparison (GOLD STANDARD)

**Goal:** Compare backtest with actual live trading results

**Steps:**
1. Run backtest on last 30 days of data
2. Run bot in live/paper trading for 30 days
3. Compare metrics:

| Metric | Backtest | Live | Acceptable Difference |
|--------|----------|------|----------------------|
| Trade Count | 100 | 95-105 | ±5% |
| Win Rate | 60% | 55-65% | ±5% |
| Profit Factor | 2.0 | 1.8-2.2 | ±10% |
| Avg Profit/Trade | $50 | $40-$60 | ±20% |
| Max Drawdown | 10% | 8-12% | ±20% |

**Interpretation:**
- ✅ Within acceptable range → Backtest is trustworthy
- ⚠️ Backtest 10-20% better → Slippage/spread underestimated
- ❌ Backtest >30% better → Serious issues, investigate

---

## Common Issues and Solutions

### Issue 1: Backtest Too Optimistic

**Symptoms:**
- Live trading performs 30%+ worse than backtest
- Win rate much lower in live trading

**Solutions:**
- Increase `SLIPPAGE_POINTS` (try 1.0-2.0 for majors)
- Check if spreads in backtest match live spreads
- Verify SL/TP distances are realistic

### Issue 2: Inconsistent Results

**Symptoms:**
- Different results on each run
- Trade count varies

**Solutions:**
- Run `test_backtest_reproducibility.py`
- Check for race conditions in custom code
- Verify time synchronization is working

### Issue 3: No Trades Generated

**Symptoms:**
- Backtest completes with 0 trades
- Strategies not triggering

**Solutions:**
- Check strategy enable flags in `.env`
- Verify symbols have sufficient data
- Review strategy logs for rejection reasons

---

## Best Practices

### 1. Always Test Reproducibility First
```bash
python test_backtest_reproducibility.py
```
If this fails, fix it before trusting any results.

### 2. Use Realistic Slippage
- Majors (EURUSD, GBPUSD): 0.5-1.0 points
- Minors (EURGBP, AUDNZD): 1.0-2.0 points
- Exotics: 2.0-5.0 points

### 3. Compare Multiple Time Periods
- Don't trust a single backtest
- Test on different market conditions:
  - Trending markets
  - Ranging markets
  - High volatility periods
  - Low volatility periods

### 4. Walk-Forward Testing
```
Train: Jan-Mar → Optimize parameters
Test:  Apr-Jun → Validate on unseen data
```
If performance drops >30%, you're overfitting.

### 5. Paper Trading Before Live
- Run in paper trading for 2-4 weeks
- Compare with backtest on same period
- Only go live if results match within 20%

---

## Validation Workflow

```
1. Run Reproducibility Test
   ↓ PASS
2. Run Backtest with Slippage
   ↓ Review Results
3. Compare with No-Slippage Run
   ↓ Verify Reasonable Difference
4. Check SL/TP Detection in Logs
   ↓ Verify Intra-Bar Detection
5. Test Order Rejections
   ↓ Verify Proper Validation
6. Paper Trade for 2-4 Weeks
   ↓ Compare with Backtest
7. Go Live (if results match)
```

---

## Conclusion

Your backtest is now significantly more trustworthy with:
- ✅ Realistic slippage simulation
- ✅ Accurate SL/TP detection
- ✅ Order rejection validation
- ✅ Reproducibility testing

**Next Steps:**
1. Run `test_backtest_reproducibility.py` to verify no race conditions
2. Compare backtest results with/without slippage
3. Start paper trading to validate against live market
4. Document any discrepancies and adjust slippage/spread settings

**Remember:** Backtest is a tool for development, not a guarantee of future performance. Always validate with live/paper trading before risking real capital.

