# MT5 API Quick Reference Guide

Quick reference for all MT5 Python API methods and their usage in our codebase.

---

## Connection & Terminal

| Method | Purpose | Our Usage | Status |
|--------|---------|-----------|--------|
| `mt5.initialize()` | Connect to MT5 terminal | `ConnectionManager.connect()` | ✅ Used |
| `mt5.login(account, password, server)` | Login to trading account | `ConnectionManager.connect()` | ✅ Used |
| `mt5.shutdown()` | Close MT5 connection | `ConnectionManager.disconnect()` | ✅ Used |
| `mt5.version()` | Get MT5 version | Not used | ❌ N/A |
| `mt5.last_error()` | Get last error code/message | Error handling throughout | ✅ Used |
| `mt5.terminal_info()` | Get terminal status | `TradingStatusChecker` | ✅ Used |
| `mt5.account_info()` | Get account information | `AccountInfoProvider` | ✅ Used |

---

## Market Data

| Method | Purpose | Our Usage | Status |
|--------|---------|-----------|--------|
| `mt5.copy_rates_from(symbol, tf, from, count)` | Get bars from date | Not used | 💡 Could use |
| `mt5.copy_rates_from_pos(symbol, tf, start, count)` | Get bars from index | `DataProvider.get_candles()` | ✅ Used |
| `mt5.copy_rates_range(symbol, tf, from, to)` | Get bars in range | `BacktestDataLoader` | ✅ Used |
| `mt5.copy_ticks_from(symbol, from, count, flags)` | Get ticks from date | Not used | 💡 Enhancement |
| `mt5.copy_ticks_range(symbol, from, to, flags)` | Get ticks in range | Not used | 💡 Enhancement |

**Tick Flags:**
- `COPY_TICKS_ALL` - All ticks
- `COPY_TICKS_INFO` - Bid/Ask changes only
- `COPY_TICKS_TRADE` - Trade ticks only

---

## Symbol Information

| Method | Purpose | Our Usage | Status |
|--------|---------|-----------|--------|
| `mt5.symbols_total()` | Count all symbols | Not used | ❌ N/A |
| `mt5.symbols_get(group)` | Get symbols list | Not used | ❌ N/A |
| `mt5.symbol_info(symbol)` | Get symbol properties | `SymbolInfoCache` | ✅ Used |
| `mt5.symbol_info_tick(symbol)` | Get latest tick | `PriceProvider` | ✅ Used |
| `mt5.symbol_select(symbol, enable)` | Add to MarketWatch | `BacktestDataLoader` | ✅ Used |

**Symbol Info Properties:**
```python
info = mt5.symbol_info("EURUSD")
info.point           # Minimum price change
info.digits          # Decimal places
info.trade_tick_value    # Tick value
info.trade_tick_size     # Tick size
info.volume_min      # Minimum lot
info.volume_max      # Maximum lot
info.volume_step     # Lot step
info.trade_contract_size # Contract size
info.trade_mode      # Trading mode
info.spread          # Current spread
```

---

## Orders & Positions

| Method | Purpose | Our Usage | Status |
|--------|---------|-----------|--------|
| `mt5.order_send(request)` | Send trading request | `OrderExecutor` | ✅ Used |
| `mt5.order_check(request)` | Validate order | **NOT USED** | ⚠️ **Should add** |
| `mt5.order_calc_margin(action, symbol, vol, price)` | Calculate margin | `AccountInfoProvider` | ✅ Used |
| `mt5.order_calc_profit(action, symbol, vol, open, close)` | Calculate profit | Not used | 💡 Could use |
| `mt5.orders_total()` | Count active orders | Not used | ❌ N/A |
| `mt5.orders_get(symbol, group, ticket)` | Get active orders | Not used | ❌ N/A |
| `mt5.positions_total()` | Count open positions | Used indirectly | ✅ Used |
| `mt5.positions_get(symbol, group, ticket)` | Get open positions | `PositionProvider` | ✅ Used |

**Order Request Structure:**
```python
request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": "EURUSD",
    "volume": 0.1,
    "type": mt5.ORDER_TYPE_BUY,
    "price": 1.1234,
    "sl": 1.1200,
    "tp": 1.1300,
    "deviation": 10,
    "magic": 123456,
    "comment": "My trade",
    "type_filling": mt5.ORDER_FILLING_IOC,
}
```

---

## History

| Method | Purpose | Our Usage | Status |
|--------|---------|-----------|--------|
| `mt5.history_orders_total(from, to)` | Count history orders | Not used | ❌ N/A |
| `mt5.history_orders_get(from, to, group, ticket, position)` | Get history orders | Not used | ❌ N/A |
| `mt5.history_deals_total(from, to)` | Count history deals | Not used | ❌ N/A |
| `mt5.history_deals_get(from, to, group, ticket, position)` | Get history deals | `PositionProvider` | ✅ Used |

---

## Market Depth (Level 2)

| Method | Purpose | Our Usage | Status |
|--------|---------|-----------|--------|
| `mt5.market_book_add(symbol)` | Subscribe to DOM | Not used | 💡 Future |
| `mt5.market_book_get(symbol)` | Get DOM snapshot | Not used | 💡 Future |
| `mt5.market_book_release(symbol)` | Unsubscribe from DOM | Not used | 💡 Future |

---

## Common Patterns

### Pattern 1: Get Current Price
```python
tick = mt5.symbol_info_tick("EURUSD")
if tick:
    bid = tick.bid
    ask = tick.ask
    spread = tick.ask - tick.bid
```

### Pattern 2: Get Historical Bars
```python
rates = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_M1, 0, 100)
df = pd.DataFrame(rates)
df['time'] = pd.to_datetime(df['time'], unit='s')
```

### Pattern 3: Check Margin Before Trade
```python
margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, "EURUSD", 0.1, 1.1234)
account = mt5.account_info()
if margin and margin < account.margin_free:
    # Sufficient margin
    pass
```

### Pattern 4: Validate Order Before Sending
```python
request = {...}  # Order request

# Validate first
check = mt5.order_check(request)
if check and check.retcode == mt5.TRADE_RETCODE_DONE:
    # Validation passed - send order
    result = mt5.order_send(request)
```

### Pattern 5: Get Open Positions
```python
positions = mt5.positions_get(symbol="EURUSD")
for pos in positions:
    print(f"Ticket: {pos.ticket}, Profit: {pos.profit}")
```

---

## Error Handling

### Get Last Error
```python
result = mt5.order_send(request)
if result is None:
    error_code, error_msg = mt5.last_error()
    print(f"Error {error_code}: {error_msg}")
```

### Common Error Codes
- `1` - Generic error
- `2` - Invalid parameters
- `4` - Trade server busy
- `10004` - Requote
- `10006` - Request rejected
- `10007` - Request canceled
- `10008` - Order placed
- `10009` - Request completed (success)
- `10013` - Invalid request
- `10014` - Invalid volume
- `10015` - Invalid price
- `10016` - Invalid stops
- `10019` - Insufficient funds
- `10021` - Market closed

---

## Return Codes

### Trade Return Codes
```python
mt5.TRADE_RETCODE_DONE          # 10009 - Success
mt5.TRADE_RETCODE_REQUOTE       # 10004 - Requote
mt5.TRADE_RETCODE_REJECT        # 10006 - Rejected
mt5.TRADE_RETCODE_CANCEL        # 10007 - Canceled
mt5.TRADE_RETCODE_INVALID       # 10013 - Invalid request
mt5.TRADE_RETCODE_INVALID_VOLUME # 10014 - Invalid volume
mt5.TRADE_RETCODE_INVALID_PRICE # 10015 - Invalid price
mt5.TRADE_RETCODE_INVALID_STOPS # 10016 - Invalid stops
mt5.TRADE_RETCODE_NO_MONEY      # 10019 - Insufficient funds
mt5.TRADE_RETCODE_MARKET_CLOSED # 10021 - Market closed
```

---

## Timeframe Constants

```python
mt5.TIMEFRAME_M1   # 1 minute
mt5.TIMEFRAME_M5   # 5 minutes
mt5.TIMEFRAME_M15  # 15 minutes
mt5.TIMEFRAME_M30  # 30 minutes
mt5.TIMEFRAME_H1   # 1 hour
mt5.TIMEFRAME_H4   # 4 hours
mt5.TIMEFRAME_D1   # 1 day
mt5.TIMEFRAME_W1   # 1 week
mt5.TIMEFRAME_MN1  # 1 month
```

---

## Order Types

```python
mt5.ORDER_TYPE_BUY        # Market buy
mt5.ORDER_TYPE_SELL       # Market sell
mt5.ORDER_TYPE_BUY_LIMIT  # Buy limit
mt5.ORDER_TYPE_SELL_LIMIT # Sell limit
mt5.ORDER_TYPE_BUY_STOP   # Buy stop
mt5.ORDER_TYPE_SELL_STOP  # Sell stop
```

---

## Filling Modes

```python
mt5.ORDER_FILLING_FOK  # Fill or Kill
mt5.ORDER_FILLING_IOC  # Immediate or Cancel
mt5.ORDER_FILLING_RETURN  # Return (partial fills allowed)
```

---

## Quick Checklist

### Before Going Live
- [x] Using `mt5.initialize()` for connection
- [x] Using `mt5.account_info()` for account data
- [x] Using `mt5.symbol_info()` for symbol properties
- [x] Using `mt5.symbol_info_tick()` for current prices
- [x] Using `mt5.order_calc_margin()` for margin calculation
- [x] Using `mt5.positions_get()` for position tracking
- [ ] **Using `mt5.order_check()` for order validation** ⚠️ **TODO**
- [x] Proper error handling with `mt5.last_error()`

---

## Resources

- **Official Documentation:** https://www.mql5.com/en/docs/python_metatrader5
- **Our Analysis:** `docs/MT5_API_OPTIMIZATION_ANALYSIS.md`
- **Code Examples:** `docs/MT5_API_CODE_EXAMPLES.md`
- **Implementation Guide:** `docs/MT5_ORDER_CHECK_IMPLEMENTATION_GUIDE.md`


