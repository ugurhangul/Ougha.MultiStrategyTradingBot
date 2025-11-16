# Tick-Level Backtesting - Example Scenario

**Date**: 2025-11-16  
**Purpose**: Demonstrate the difference between candle-based and tick-level backtesting

---

## Scenario: Stop-Loss Hit During Volatile Candle

### Setup

**Symbol**: EURUSD  
**Strategy**: FakeoutStrategy (15M_1M)  
**Position**: BUY at 1.10000  
**Stop Loss**: 1.09900 (10 pips below entry)  
**Take Profit**: 1.10200 (20 pips above entry, 2:1 R:R)  
**Time**: 2025-11-15 14:30:00 UTC (NFP news release)

---

## Market Data

### M1 Candle (14:30:00 - 14:31:00)

```
Time:   2025-11-15 14:30:00
Open:   1.10000
High:   1.10250
Low:    1.09850  ← Below SL!
Close:  1.10150
Volume: 5,000 (high volume - news spike)
```

### Tick Data (14:30:00 - 14:31:00)

```
Time                Bid       Ask       Last      Volume
14:30:00.000       1.10000   1.10010   1.10005   100
14:30:00.500       1.09995   1.10005   1.10000   150
14:30:01.000       1.09980   1.09990   1.09985   200
14:30:01.500       1.09950   1.09960   1.09955   300
14:30:02.000       1.09920   1.09930   1.09925   400  ← Approaching SL
14:30:02.500       1.09890   1.09900   1.09895   500  ← SL HIT! (bid = 1.09890)
14:30:03.000       1.09850   1.09860   1.09855   600  ← Lowest point
14:30:03.500       1.09880   1.09890   1.09885   400
14:30:04.000       1.09920   1.09930   1.09925   300
...
14:30:59.000       1.10140   1.10150   1.10145   100
14:30:59.500       1.10145   1.10155   1.10150   100
```

**Key Events**:
- **14:30:02.500**: Bid drops to 1.09890 → **SL triggered** (BUY position closes at bid)
- **14:30:03.000**: Price continues down to 1.09850 (candle low)
- **14:30:59.500**: Price recovers to 1.10150 (candle close)

---

## Backtest Results Comparison

### Current Approach (Candle-Based)

**Processing**:
```python
# At 14:31:00 (M1 candle close)
candle = get_latest_candle("EURUSD", "M1")
# candle.close = 1.10150

# Check SL/TP
position.current_price = candle.close  # 1.10150
if position.sl > 0 and position.current_price <= position.sl:
    # 1.10150 <= 1.09900? NO
    # SL NOT triggered
    pass
```

**Result**:
- ✅ Position still open at 1.10150
- ✅ Unrealized profit: +15 pips (+$150 on 1.0 lot)
- ✅ Waiting for TP at 1.10200

**Backtest Output**:
```
[2025-11-15 14:31:00] [15M_1M] EURUSD: Position open
[2025-11-15 14:31:00] [15M_1M] Entry: 1.10000, Current: 1.10150
[2025-11-15 14:31:00] [15M_1M] Unrealized P&L: +$150.00 (+15 pips)
[2025-11-15 14:31:00] [15M_1M] Waiting for TP at 1.10200...
```

---

### Proposed Approach (Tick-Level)

**Processing**:
```python
# At 14:30:02 (second-by-second processing)
# Process ticks in [14:30:02.000, 14:30:03.000)

for tick in ticks_in_second:
    # Tick at 14:30:02.500
    # tick.bid = 1.09890, tick.ask = 1.09900
    
    # Check SL/TP for BUY position (close at bid)
    if position.sl > 0 and tick.bid <= position.sl:
        # 1.09890 <= 1.09900? YES
        # SL TRIGGERED!
        close_position(position, price=tick.bid, reason="SL")
        break
```

**Result**:
- ❌ Position closed at 1.09890 (SL hit)
- ❌ Realized loss: -11 pips (-$110 on 1.0 lot)
- ❌ Position no longer exists

**Backtest Output**:
```
[2025-11-15 14:30:02] [15M_1M] EURUSD: SL HIT at 1.09890
[2025-11-15 14:30:02] [15M_1M] Entry: 1.10000, Exit: 1.09890
[2025-11-15 14:30:02] [15M_1M] Realized P&L: -$110.00 (-11 pips)
[2025-11-15 14:30:02] [15M_1M] Reason: Stop Loss
[2025-11-15 14:30:02] [15M_1M] Position closed
```

---

## Impact Analysis

### Difference in Results

| Metric | Candle-Based | Tick-Level | Difference |
|--------|--------------|------------|------------|
| **Position Status** | Open | Closed | ❌ |
| **P&L** | +$150 (unrealized) | -$110 (realized) | **-$260** |
| **Outcome** | Waiting for TP | Stopped out | ❌ |
| **Accuracy** | ❌ Incorrect | ✅ Correct | - |

**Conclusion**: Candle-based backtest is **$260 off** for this single trade!

---

## Why This Matters

### 1. Overly Optimistic Backtest Results

If this happens on **10% of trades** in a 100-trade backtest:
- **Candle-based**: 90 trades + 10 "false winners" = 100 trades, 60% win rate
- **Tick-level**: 90 trades + 10 stopped out = 100 trades, 50% win rate
- **Impact**: 10% win rate difference!

### 2. Live Trading Mismatch

**Backtest says**: "This strategy has 60% win rate, profitable"  
**Live trading shows**: "This strategy has 50% win rate, break-even"  
**Trader reaction**: "Why is my live trading worse than backtest?"

**Root cause**: Backtest didn't account for intra-candle SL hits.

### 3. Risk Management Failure

**Backtest**: Max drawdown = 5% (based on candle-close SL checks)  
**Live trading**: Max drawdown = 8% (real SL hits during candles)  
**Impact**: Risk limits exceeded, account blown!

---

## Real-World Example: HFT Strategy

### Current Approach (Broken)

**HFT Strategy Logic**:
```python
def on_tick(self):
    # Get latest tick
    tick = mt5.symbol_info_tick(self.symbol)  # In backtest: returns M1 close
    
    # Update tick buffer
    self.tick_buffer.append(tick)
    
    # Detect momentum (need 5 consecutive upward ticks)
    if len(self.tick_buffer) >= 5:
        # Check if last 5 ticks are all upward
        is_upward = all(
            self.tick_buffer[i].bid > self.tick_buffer[i-1].bid
            for i in range(-4, 0)
        )
        
        if is_upward:
            return self.generate_buy_signal()
```

**Problem in Backtest**:
- `mt5.symbol_info_tick()` returns **M1 close price** (same price for 60 seconds)
- Tick buffer contains: `[1.10000, 1.10000, 1.10000, 1.10000, 1.10000]`
- **Never detects momentum** (all ticks are identical!)
- Strategy generates **ZERO signals** in backtest

**Live Trading**:
- `mt5.symbol_info_tick()` returns **real tick data** (changes every millisecond)
- Tick buffer contains: `[1.10000, 1.10005, 1.10010, 1.10015, 1.10020]`
- **Detects momentum** correctly
- Strategy generates signals as expected

**Result**: HFT strategy appears broken in backtest, but works in live trading!

---

### Tick-Level Approach (Fixed)

**HFT Strategy Logic** (unchanged):
```python
def on_tick(self):
    # Get latest tick
    tick = mt5.symbol_info_tick(self.symbol)  # In backtest: returns REAL tick
    
    # Update tick buffer
    self.tick_buffer.append(tick)
    
    # Detect momentum (need 5 consecutive upward ticks)
    if len(self.tick_buffer) >= 5:
        is_upward = all(
            self.tick_buffer[i].bid > self.tick_buffer[i-1].bid
            for i in range(-4, 0)
        )
        
        if is_upward:
            return self.generate_buy_signal()
```

**Tick-Level Backtest**:
- `mt5.symbol_info_tick()` returns **real tick from tick data**
- Tick buffer contains: `[1.10000, 1.10005, 1.10010, 1.10015, 1.10020]`
- **Detects momentum** correctly (same as live trading)
- Strategy generates signals as expected

**Result**: HFT strategy works identically in backtest and live trading!

---

## Conclusion

### Candle-Based Backtesting Issues

1. ❌ **Misses intra-candle SL hits** → Overly optimistic results
2. ❌ **HFT strategy broken** → Cannot test tick-level strategies
3. ❌ **Static spread** → Underestimates costs
4. ❌ **No intra-candle visibility** → Cannot debug price action

### Tick-Level Backtesting Benefits

1. ✅ **Catches all SL hits** → Realistic results
2. ✅ **HFT strategy works** → Can test all strategy types
3. ✅ **Dynamic spread** → Accurate cost estimation
4. ✅ **Full visibility** → Better debugging

### Bottom Line

**Candle-based backtesting is fundamentally flawed for:**
- Strategies with tight stop-losses
- HFT / scalping strategies
- Volatile market conditions (news events)
- Accurate risk management

**Tick-level backtesting is essential for:**
- Realistic performance estimation
- Proper HFT strategy testing
- Accurate SL/TP execution
- Production-ready strategies

---

**Recommendation**: Migrate to tick-level backtesting to ensure backtest results match live trading behavior.

