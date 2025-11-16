# MT5 API Code Examples - Before & After

This document shows concrete code examples comparing our current implementation with MT5 native methods.

---

## Example 1: Order Validation (HIGH PRIORITY)

### ❌ Current Implementation (Without order_check)

**File:** `src/execution/order_management/order_executor.py`

```python
def execute_signal(self, signal: TradeSignal) -> Optional[PositionInfo]:
    """Execute a trade signal."""
    
    # ... validation and preparation ...
    
    # Build order request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": magic_number,
        "comment": comment,
        "type_filling": filling_mode,
    }
    
    # Send order directly (no pre-validation)
    result = mt5.order_send(request)
    
    # Handle rejection AFTER it happens
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        self.logger.error(f"Order failed: {result.comment}")
        return None
    
    # ... rest of code ...
```

**Problems:**
- ❌ Order can be rejected by broker
- ❌ Unclear why it was rejected
- ❌ Wasted API call
- ❌ No visibility into margin impact

---

### ✅ Improved Implementation (With order_check)

```python
def execute_signal(self, signal: TradeSignal) -> Optional[PositionInfo]:
    """Execute a trade signal."""
    
    # ... validation and preparation ...
    
    # Build order request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": magic_number,
        "comment": comment,
        "type_filling": filling_mode,
    }
    
    # ⭐ NEW: Validate order BEFORE sending
    check_result = mt5.order_check(request)
    
    if check_result is None:
        error_code, error_msg = mt5.last_error()
        self.logger.error(f"Order check failed: ({error_code}) {error_msg}")
        return None
    
    if check_result.retcode != mt5.TRADE_RETCODE_DONE:
        # Log detailed rejection reason
        self.logger.error(
            f"Order validation failed: {check_result.comment} | "
            f"Retcode: {check_result.retcode} | "
            f"Margin required: ${check_result.margin:.2f} | "
            f"Free margin: ${check_result.margin_free:.2f}"
        )
        return None
    
    # Log margin impact BEFORE execution
    self.logger.info(
        f"Order validated | "
        f"Margin: ${check_result.margin:.2f} | "
        f"Free margin after: ${check_result.margin_free:.2f} | "
        f"Margin level: {check_result.margin_level:.2f}%"
    )
    
    # If validation passed, send the order
    result = mt5.order_send(request)
    
    # This should rarely fail now
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        self.logger.error(f"Order execution failed: {result.comment}")
        return None
    
    # ... rest of code ...
```

**Benefits:**
- ✅ Catches rejections BEFORE sending
- ✅ Clear rejection reasons
- ✅ Visibility into margin impact
- ✅ Reduced failed attempts

---

## Example 2: Margin Calculation

### ✅ Current Implementation (Already Optimal)

**File:** `src/core/mt5/account_info_provider.py`

```python
def calculate_margin(self, symbol: str, volume: float, price: float) -> Optional[float]:
    """
    Calculate required margin for opening a position.
    
    Uses MT5's order_calc_margin() to get accurate margin requirements.
    """
    if not self.connection_manager.is_connected:
        return None
    
    # ✅ Using MT5 native method
    margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, volume, price)
    
    if margin is None or margin < 0:
        return None
    
    return margin
```

**Status:** ✅ Already using MT5 native method - no changes needed.

---

### 🔒 Backtest Implementation (Cannot Use MT5 Method)

**File:** `src/backtesting/engine/simulated_broker.py`

```python
def calculate_margin(self, symbol: str, volume: float, price: float) -> Optional[float]:
    """
    Calculate required margin for opening a position.
    
    In backtest mode, we use a simplified calculation:
    Margin = (volume * contract_size * price) / leverage
    
    NOTE: Cannot use mt5.order_calc_margin() in backtest mode
    as it requires live MT5 connection.
    """
    if symbol not in self.symbol_info:
        return None
    
    info = self.symbol_info[symbol]
    
    # Simplified calculation (acceptable for backtesting)
    notional = volume * info.contract_size * price
    margin = notional / self.leverage  # Configurable leverage
    
    return margin
```

**Status:** ✅ Correct approach - MT5 method cannot be used in backtest mode.

---

## Example 3: Getting Historical Data

### ✅ Current Implementation (Already Optimal)

**File:** `src/core/mt5/data_provider.py`

```python
def get_candles(self, symbol: str, timeframe: str, count: int = 100) -> Optional[pd.DataFrame]:
    """Get historical candles for a symbol."""
    
    if not self.connection_manager.is_connected:
        return None
    
    # Convert timeframe string to MT5 constant
    tf = TimeframeConverter.to_mt5_constant(timeframe)
    if tf is None:
        return None
    
    try:
        # ✅ Using MT5 native method
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        
        if rates is None or len(rates) == 0:
            self.logger.error(f"Failed to get candles: {mt5.last_error()}")
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        
        return df
        
    except Exception as e:
        self.logger.error(f"Exception getting candles: {e}")
        return None
```

**Status:** ✅ Already using MT5 native method - no changes needed.

---

## Example 4: Getting Current Price

### ✅ Current Implementation (Already Optimal)

**File:** `src/core/mt5/price_provider.py`

```python
def get_current_price(self, symbol: str, price_type: str = 'bid') -> Optional[float]:
    """Get current price for symbol."""
    
    try:
        # ✅ Using MT5 native method
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        
        return tick.bid if price_type == 'bid' else tick.ask
        
    except Exception as e:
        self.logger.error(f"Error getting price for {symbol}: {e}")
        return None
```

**Status:** ✅ Already using MT5 native method - no changes needed.

---

## Example 5: Getting Open Positions

### ✅ Current Implementation (Already Optimal)

**File:** `src/core/mt5/position_provider.py`

```python
def get_positions(self, symbol: Optional[str] = None, 
                 magic_number: Optional[int] = None) -> List[PositionInfo]:
    """Get open positions with optional filtering."""
    
    if not self.connection_manager.is_connected:
        return []
    
    try:
        # ✅ Using MT5 native method with filtering
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
        
        if positions is None:
            return []
        
        result = []
        for pos in positions:
            # Filter by magic number if specified
            if magic_number is not None and pos.magic != magic_number:
                continue
            
            # Convert to our PositionInfo model
            pos_info = PositionInfo(
                ticket=pos.ticket,
                symbol=pos.symbol,
                position_type=PositionType.BUY if pos.type == mt5.ORDER_TYPE_BUY else PositionType.SELL,
                volume=pos.volume,
                open_price=pos.price_open,
                current_price=pos.price_current,
                sl=pos.sl,
                tp=pos.tp,
                profit=pos.profit,
                open_time=datetime.fromtimestamp(pos.time),
                magic_number=pos.magic,
                comment=pos.comment
            )
            result.append(pos_info)
        
        return result
        
    except Exception as e:
        self.logger.error(f"Error getting positions: {e}")
        return []
```

**Status:** ✅ Already using MT5 native method - no changes needed.

---

## Example 6: Symbol Information with Caching

### ✅ Current Implementation (Already Optimal)

**File:** `src/core/symbol_info_cache.py`

```python
def get(self, symbol: str) -> Optional[dict]:
    """Get symbol info from cache or MT5."""
    
    # Check cache first
    cached_entry = self._cache.get(symbol)
    
    if cached_entry is not None:
        info_dict, timestamp = cached_entry
        
        # Check if cache entry is still valid
        if self._is_cache_valid(timestamp):
            self._hits += 1
            return info_dict
        else:
            # Cache expired
            self._invalidate_symbol(symbol)
    
    # Cache miss - fetch from MT5
    self._misses += 1
    
    try:
        # ✅ Using MT5 native method
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        
        # Convert to dictionary
        symbol_dict = {
            'point': info.point,
            'digits': info.digits,
            'tick_value': info.trade_tick_value,
            'tick_size': info.trade_tick_size,
            'min_lot': info.volume_min,
            'max_lot': info.volume_max,
            'lot_step': info.volume_step,
            'contract_size': info.trade_contract_size,
            'filling_mode': info.filling_mode,
            'stops_level': info.trade_stops_level,
            'freeze_level': info.trade_freeze_level,
            'trade_mode': info.trade_mode,
            'currency_base': info.currency_base,
            'currency_profit': info.currency_profit,
            'currency_margin': info.currency_margin,
            'category': info.category,
            'spread': info.spread,
        }
        
        # Store in cache
        self._cache[symbol] = (symbol_dict, datetime.now())
        
        return symbol_dict
        
    except Exception as e:
        self.logger.error(f"Error getting symbol info: {e}")
        return None
```

**Status:** ✅ Already using MT5 native method with effective caching - no changes needed.

---

## Example 7: Potential Enhancement - Tick Data for Backtesting

### 💡 Current Implementation (Using M1 Bars)

**File:** `src/backtesting/engine/data_loader.py`

```python
def load_from_mt5(self, symbol: str, timeframe: str, 
                  start_date: datetime, end_date: datetime):
    """Load historical data from MT5."""
    
    # Convert timeframe
    mt5_timeframe = self._convert_timeframe(timeframe)
    
    # ✅ Using MT5 native method for bars
    rates = mt5.copy_rates_range(symbol, mt5_timeframe, start_date, end_date)
    
    if rates is None or len(rates) == 0:
        return None
    
    # Convert to DataFrame
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    
    return df
```

**Current Accuracy:** Good (M1 bars with intra-bar high/low)

---

### 💡 Potential Enhancement (Using Tick Data)

```python
def load_tick_data_from_mt5(self, symbol: str, 
                            start_date: datetime, end_date: datetime):
    """Load tick data from MT5 for high-accuracy backtesting."""
    
    # 💡 Using MT5 native method for ticks
    ticks = mt5.copy_ticks_range(
        symbol, 
        start_date, 
        end_date, 
        mt5.COPY_TICKS_ALL  # Get all ticks (bid, ask, last)
    )
    
    if ticks is None or len(ticks) == 0:
        return None
    
    # Convert to DataFrame
    df = pd.DataFrame(ticks)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    
    return df
```

**Potential Accuracy:** Excellent (tick-by-tick execution)

**Trade-offs:**
- ✅ Higher accuracy
- ✅ Realistic slippage
- ✅ Better SL/TP simulation
- ❌ Large data volume
- ❌ Slower processing
- ❌ More complex implementation

**Recommendation:** Implement as optional mode for final validation.

---

## Summary

### Already Using MT5 Native Methods ✅
1. Connection management (`initialize`, `login`, `shutdown`)
2. Market data (`copy_rates_from_pos`, `copy_rates_range`)
3. Account info (`account_info`, `order_calc_margin`)
4. Positions (`positions_get`, `history_deals_get`)
5. Prices (`symbol_info_tick`)
6. Symbol info (`symbol_info`)
7. Trading status (`terminal_info`)

### Should Add (High Priority) ⭐
1. **Order validation** (`order_check`) - Prevents rejections

### Could Add (Medium Priority) 💡
2. **Tick data** (`copy_ticks_range`) - Improves backtest accuracy
3. **Profit calculation** (`order_calc_profit`) - Better profit estimation

### Future Enhancements (Low Priority) 💡
4. **Market Depth** (`market_book_*`) - Advanced order flow analysis


