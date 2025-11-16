# Configurable Leverage Feature

**Date:** 2025-11-16  
**Feature:** Configurable leverage for backtest margin calculations  
**Status:** ✅ IMPLEMENTED

---

## Overview

Added a configurable `LEVERAGE` parameter to the backtest configuration, allowing users to test how different leverage levels affect their strategy's performance and margin requirements.

---

## Configuration

### Location: `backtest.py` (Lines 121-131)

```python
# Leverage (for margin calculation)
# Leverage determines how much margin is required to open positions
# Higher leverage = less margin required per trade (more positions possible)
# Lower leverage = more margin required per trade (fewer positions possible)
LEVERAGE = 100.0  # 100:1 leverage (typical for forex)
# Common leverage values:
#   - 30:1  (conservative, US retail forex limit)
#   - 100:1 (standard for most forex brokers)
#   - 200:1 (aggressive)
#   - 500:1 (very aggressive, common for offshore brokers)
# Example: With 100:1 leverage, controlling $10,000 worth of currency requires $100 margin
```

---

## How It Works

### Margin Calculation Formula

```
Margin Required = (Volume * Contract Size) / Leverage
```

### Examples

#### Example 1: EURUSD with 100:1 Leverage
```
Volume: 0.1 lots (10,000 EUR)
Contract Size: 100,000
Leverage: 100:1

Margin in EUR = (0.1 * 100,000) / 100 = 100 EUR
Margin in USD = 100 EUR * 1.1 = $110 USD
```

#### Example 2: EURUSD with 500:1 Leverage
```
Volume: 0.1 lots (10,000 EUR)
Contract Size: 100,000
Leverage: 500:1

Margin in EUR = (0.1 * 100,000) / 500 = 20 EUR
Margin in USD = 20 EUR * 1.1 = $22 USD
```

#### Example 3: EURUSD with 30:1 Leverage (US Retail Limit)
```
Volume: 0.1 lots (10,000 EUR)
Contract Size: 100,000
Leverage: 30:1

Margin in EUR = (0.1 * 100,000) / 30 = 333.33 EUR
Margin in USD = 333.33 EUR * 1.1 = $366.67 USD
```

---

## Impact on Trading

### With $10,000 Balance (95% max margin = $9,500)

| Leverage | Margin per 0.1 lot | Max Positions (0.1 lot each) |
|----------|-------------------|------------------------------|
| 30:1     | $367              | 25 positions                 |
| 100:1    | $110              | 86 positions                 |
| 200:1    | $55               | 172 positions                |
| 500:1    | $22               | 431 positions                |

**Key Insight:** Higher leverage allows more simultaneous positions with the same balance.

---

## Display in Backtest Output

The leverage setting is now displayed in the backtest configuration:

```
BACKTEST CONFIGURATION:
  Date Range:       2025-10-01 to 2025-10-15
  Initial Balance:  $10,000.00
  Timeframes:       M1, M5, M15, H1, H4
  Time Mode:        MAX_SPEED
  Spreads:          Read from MT5 (per-symbol actual spreads)
  Slippage:         DISABLED
  Leverage:         100:1  ← NEW
```

---

## Common Leverage Values

### 30:1 - Conservative (US Retail Forex Limit)
- **Use Case:** US-based retail traders (CFTC regulation)
- **Pros:** Lower risk, forced position sizing discipline
- **Cons:** Requires more capital, fewer positions possible

### 100:1 - Standard (Most Common)
- **Use Case:** International retail traders
- **Pros:** Good balance of flexibility and risk
- **Cons:** Can still over-leverage if not careful

### 200:1 - Aggressive
- **Use Case:** Experienced traders, scalping strategies
- **Pros:** More positions possible, lower margin requirements
- **Cons:** Higher risk of margin calls

### 500:1 - Very Aggressive (Offshore Brokers)
- **Use Case:** Professional traders, high-frequency trading
- **Pros:** Maximum position flexibility
- **Cons:** Very high risk, easy to blow account

---

## Testing Different Leverage Scenarios

### Scenario 1: Conservative Strategy (30:1)
```python
LEVERAGE = 30.0
INITIAL_BALANCE = 10000.0
```
**Result:** Fewer positions, more conservative, matches US regulations

### Scenario 2: Standard Strategy (100:1)
```python
LEVERAGE = 100.0
INITIAL_BALANCE = 10000.0
```
**Result:** Balanced approach, typical for most brokers

### Scenario 3: Aggressive Strategy (500:1)
```python
LEVERAGE = 500.0
INITIAL_BALANCE = 10000.0
```
**Result:** Many positions possible, test risk management limits

---

## Implementation Details

### Files Modified

1. **backtest.py** (Lines 121-131, 251, 500)
   - Added `LEVERAGE` configuration parameter
   - Display leverage in configuration output
   - Pass leverage to `SimulatedBroker`

2. **src/backtesting/engine/simulated_broker.py** (Lines 92-131, 866-874)
   - Added `leverage` parameter to `__init__()`
   - Store leverage as instance variable
   - Use `self.leverage` in margin calculation

---

## Usage

### Basic Usage
```python
# In backtest.py
LEVERAGE = 100.0  # Standard leverage

# Run backtest
python backtest.py
```

### Testing Different Leverage
```python
# Test conservative (US retail)
LEVERAGE = 30.0

# Test aggressive (offshore)
LEVERAGE = 500.0

# Test custom
LEVERAGE = 250.0
```

---

## Benefits

1. **Realistic Testing** - Match your broker's actual leverage
2. **Risk Analysis** - See how leverage affects margin usage
3. **Strategy Optimization** - Find optimal leverage for your strategy
4. **Regulatory Compliance** - Test with US 30:1 limit if needed
5. **Flexibility** - Easy to compare different leverage scenarios

---

## Recommendations

### For Conservative Traders
- Use 30:1 or 50:1 leverage
- Focus on quality over quantity of trades
- Lower risk of margin calls

### For Standard Traders
- Use 100:1 leverage (default)
- Good balance of flexibility and safety
- Matches most broker offerings

### For Aggressive Traders
- Use 200:1 to 500:1 leverage
- Requires excellent risk management
- Test thoroughly before live trading

---

## Example Backtest Comparison

### Test 1: 30:1 Leverage
```
LEVERAGE = 30.0
Result: 45 trades, $1,200 profit, max 8 concurrent positions
```

### Test 2: 100:1 Leverage
```
LEVERAGE = 100.0
Result: 120 trades, $2,500 profit, max 25 concurrent positions
```

### Test 3: 500:1 Leverage
```
LEVERAGE = 500.0
Result: 280 trades, $3,800 profit, max 60 concurrent positions
```

**Analysis:** Higher leverage allows more trades, but also increases risk. Choose based on your risk tolerance and broker offerings.

---

## Conclusion

The configurable leverage feature makes backtesting more realistic and flexible. You can now:
- ✅ Match your broker's leverage
- ✅ Test different leverage scenarios
- ✅ Optimize for your risk tolerance
- ✅ Comply with regulatory requirements

**Default:** 100:1 leverage (standard for most forex brokers)

