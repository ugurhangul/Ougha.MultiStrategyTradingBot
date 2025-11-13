# MT5 Volume Data Guide

## Overview

This guide explains the different volume fields available in MetaTrader 5 and how to use them correctly in trading strategies.

## Volume Fields in MT5

### 1. Tick Data (`symbol_info_tick()`)

```python
tick = mt5.symbol_info_tick(symbol)
```

| Field | Description | Availability |
|-------|-------------|--------------|
| `tick.volume` | Tick volume (price changes) OR last trade volume | All symbols |
| `tick.volume_real` | Real cumulative volume from exchange | Exchange-traded only |
| `tick.last` | Last trade price | Exchange-traded only |
| `tick.flags` | Tick flags (BID, ASK, LAST, VOLUME, etc.) | All symbols |

### 2. Candle Data (`copy_rates_from()`)

```python
rates = mt5.copy_rates_from(symbol, timeframe, from_date, count)
```

| Field | Description | Availability |
|-------|-------------|--------------|
| `tick_volume` | Number of price changes in the candle | All symbols |
| `real_volume` | Actual trading volume in the candle | Exchange-traded only |

### 3. Tick History (`copy_ticks_from()`)

```python
# Different flags return different tick types
ticks = mt5.copy_ticks_from(symbol, from_date, count, flag)
```

| Flag | Description |
|------|-------------|
| `COPY_TICKS_ALL` | All ticks |
| `COPY_TICKS_INFO` | Ticks with Bid/Ask changes |
| `COPY_TICKS_TRADE` | Ticks with Last and Volume changes |

## Symbol Type Differences

### Forex & CFD Symbols (EURUSD, XAUUSD, etc.)

- **No centralized exchange** → No real volume data
- `tick.volume` is usually **0** or represents tick count
- `real_volume` is typically **0**
- Volume data is **NOT reliable**

**Recommendation**: Skip volume validation or use tick count as activity proxy

### Exchange-Traded Symbols (US500, Stocks, Futures)

- **Centralized exchange** → Real volume available
- `tick.volume` may contain actual trade volume
- `real_volume` contains actual trading volume
- Volume data **IS reliable**

**Recommendation**: Use `volume_real` or `real_volume` for validation

## Implementation Strategy

### Current Issue (XAUUSD)

```python
# Problem: tick.volume is 0 for XAUUSD
tick = mt5.symbol_info_tick("XAUUSD")
print(tick.volume)  # Output: 0 (not useful)
```

### Solution 1: Use M1 Candle Tick Volume (Current Implementation)

```python
def _check_volume_confirmation(self, signal_data):
    # Fetch M1 candles for volume analysis
    df = self.connector.get_candles(self.symbol, "M1", count=self.config.volume_lookback + 5)

    if df is None or len(df) < self.config.volume_lookback:
        return ValidationResult(passed=True, reason="Not enough M1 candle data, skipping")

    # Calculate average volume using tick_volume from candles
    avg_volume = df.tail(self.config.volume_lookback)['tick_volume'].mean()

    # Calculate recent volume from most recent candles
    recent_volume = df.tail(3)['tick_volume'].mean()

    # Compare recent to average
    passed = recent_volume / avg_volume >= self.config.min_volume_multiplier

    return ValidationResult(
        passed=passed,
        reason=f"M1 volume ratio {recent_volume/avg_volume:.2f}"
    )
```

**Benefits**:
- ✅ Works for all symbols (Forex, CFD, Exchange-traded)
- ✅ Always available and non-zero for active symbols
- ✅ More stable than tick-level volume
- ✅ Represents actual market activity (price changes per minute)

### Solution 2: Use volume_real (If Available)

```python
def _update_tick_buffer(self):
    tick = mt5.symbol_info_tick(self.symbol)
    
    # Try to use real volume first, fall back to tick volume
    volume = tick.volume_real if hasattr(tick, 'volume_real') and tick.volume_real > 0 else tick.volume
    
    tick_data = TickData(
        time=datetime.fromtimestamp(tick.time, tz=timezone.utc),
        bid=tick.bid,
        ask=tick.ask,
        volume=volume  # Use real volume if available
    )
```

### Solution 3: Use Spread Changes as Activity Indicator

```python
def _get_spread_volatility(self):
    """Use spread volatility as market activity indicator"""
    spreads = [tick.ask - tick.bid for tick in self.tick_buffer]
    spread_volatility = np.std(spreads)
    return spread_volatility
```

## Recommendations for HFT Strategy

### For All Symbols (Current Implementation)

1. ✅ **Use M1 candle tick_volume** (implemented)
2. ✅ Works reliably for Forex/CFD and Exchange-traded symbols
3. ✅ Provides stable measure of market activity
4. ✅ Always available and non-zero for active symbols

### Additional Options for Exchange-Traded (US500, Stocks)

1. ✅ Can also use `real_volume` from candles for actual trading volume
2. ✅ Consider volume-price divergence analysis
3. ✅ Both tick_volume and real_volume are available

## Testing

Run the exploration script to see volume data for your symbols:

```bash
python test_tick_volume_exploration.py
```

This will show:
- Available volume fields for each symbol
- Volume statistics (min, max, mean, zero count)
- Recommendations for each symbol type

## Conclusion

**Key Takeaway**: The HFT Momentum Strategy now uses M1 candle `tick_volume` for volume validation, which works reliably for all symbol types. This provides a stable measure of market activity (price changes per minute) that is always available for active symbols, solving the zero-volume issue for Forex/CFD symbols like XAUUSD.

