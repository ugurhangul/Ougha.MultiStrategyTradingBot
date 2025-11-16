# Strategy Naming Explanation

## Understanding the Symbol/Strategy Pair Names

### Format
The analysis shows pairs in the format: `SYMBOL_STRATEGY`

Examples:
- `EURUSD_TB_15M_1M` - EURUSD symbol with True Breakout strategy on 15M/1M timeframes
- `US30_x10_TB_4H_5M` - US30 with 10x leverage, True Breakout strategy on 4H/5M timeframes
- `USTEC_x100_FB_4H_5M` - USTEC with 100x leverage, Fakeout strategy on 4H/5M timeframes

### Leveraged Symbols

Some symbols have leverage suffixes as part of their **symbol name**:
- `US30_x10` - US30 with 10x leverage
- `US500_x100` - US500 with 100x leverage  
- `USTEC_x100` - USTEC with 100x leverage

These are **different symbols**, not different strategies. They have:
- Different contract sizes
- Different margin requirements
- Different risk profiles
- Different profit/loss magnitudes

### Strategy Components

The strategy part consists of:
1. **Strategy Type**: `TB` (True Breakout), `FB` (Fakeout), or `HFT` (High-Frequency Momentum)
2. **Range Timeframe**: `15M`, `1H`, `4H`, etc.
3. **Execution Timeframe**: `1M`, `5M`, etc.

Examples:
- `TB_15M_1M` - True Breakout, 15-minute range, 1-minute execution
- `FB_4H_5M` - Fakeout, 4-hour range, 5-minute execution

### Why This Matters

When you see results like:

```
USTEC_x100_TB_4H_5M    $254.90 profit
```

This means:
- **Symbol**: USTEC_x100 (USTEC with 100x leverage)
- **Strategy**: TB_4H_5M (True Breakout on 4H/5M timeframes)
- **Result**: $254.90 profit

This is **different** from:
```
USTEC_TB_4H_5M    (would be USTEC without leverage)
```

### Verification

From the backtest data:
```
Symbol: US30_x10        Comment: TB|4H_5M|RT
Symbol: US500_x100      Comment: FB|4H_5M|RVDIV
Symbol: USTEC_x100      Comment: TB|4H_5M|RT
```

The comment field shows only the strategy (`TB|4H_5M`), while the symbol field contains the full symbol name including leverage (`US30_x10`).

### Analysis Interpretation

When reviewing the results:

**Best Performers:**
- `USTEC_x100_TB_4H_5M` - This is the leveraged USTEC symbol performing well
- `US30_x10_TB_15M_1M` - This is the leveraged US30 symbol performing well

**Worst Performers:**
- `US500_x100_FB_4H_5M` - This is the leveraged US500 symbol performing poorly
- `US30_x10_FB_15M_1M` - This is the leveraged US30 symbol performing poorly

### Comparing Leveraged vs Non-Leveraged

To compare performance:

**Leveraged symbols (x10, x100):**
- Higher profit/loss per trade
- Higher risk
- Smaller position sizes needed
- Better capital efficiency (if profitable)

**Non-leveraged symbols:**
- Lower profit/loss per trade
- Lower risk
- Larger position sizes needed
- More stable returns

### Configuration

These leveraged symbols are configured in your `.env` file:
```
SYMBOLS=EURUSD,GBPUSD,USDJPY,...,US30_x10,US500_x100,USTEC_x100,...
```

Each is treated as a separate, independent symbol by the trading system.

## Summary

The naming is **correct as-is**:
- `x10` and `x100` are part of the **symbol name**, not the strategy name
- They represent different trading instruments with different leverage
- They should be analyzed separately from their base symbols
- The analysis correctly shows them as distinct symbol/strategy pairs

