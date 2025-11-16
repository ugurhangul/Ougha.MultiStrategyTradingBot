# Backtest Thread Count Fix

## Problem

During backtest, only **50 out of 69 symbols** were being initialized and creating threads.

**Observed:**
```
[ 89.6%] ... | Open: 47 | Waiting: 46/50
```

**Expected:**
```
[ 89.6%] ... | Open: 47 | Waiting: 46/69
```

## Root Cause

The `TradingController.initialize()` method was checking **real-time trading sessions** during backtest initialization:

```python
if config.trading_hours.check_symbol_session:
    # Check trading session status for all symbols
    active_symbols, inactive_symbols = self.session_monitor.filter_active_symbols(symbols)
    
    # Initialize active symbols immediately
    for symbol in active_symbols:
        success_count += self._initialize_symbol(symbol)
```

This meant:
- Only symbols that were **currently in their trading session** (at the time you ran the backtest) were initialized
- The other 19 symbols were put into "pending" status
- In live trading, these would be initialized later when their sessions start
- In backtest mode, this doesn't make sense because we're simulating **historical time**, not real-time

## Solution

Modified `src/core/trading_controller.py` to **skip session checking in backtest mode**:

```python
# In backtest mode, always initialize all symbols regardless of session status
# because we're simulating historical time, not real-time
if self.is_backtest_mode:
    self.logger.info("BACKTEST MODE: Initializing all symbols (session checking skipped)")
    for symbol in symbols:
        success_count += self._initialize_symbol(symbol)
# Check if session checking is enabled (live trading only)
elif config.trading_hours.check_symbol_session:
    # ... existing session checking logic for live trading ...
```

## Impact

### Before Fix
- ❌ Only 50/69 symbols initialized
- ❌ Missing 19 symbols worth of backtest data
- ❌ Incomplete performance analysis
- ❌ Barrier synchronization waiting for 50 threads instead of 69

### After Fix
- ✅ All 69/69 symbols initialized
- ✅ Complete backtest coverage
- ✅ Accurate performance metrics
- ✅ Barrier synchronization with correct thread count

## Testing

Run the backtest again:

```bash
python backtest.py
```

You should now see:
1. **"BACKTEST MODE: Initializing all symbols (session checking skipped)"** in the logs
2. **69 symbols initialized** instead of 50
3. **Barrier participants: 69 symbols + 1 position monitor** (70 total)
4. Progress showing **"Waiting: X/69"** instead of **"Waiting: X/50"**

## Why This Matters

1. **Complete Data**: All 69 symbols will now be backtested, not just the 50 that happened to be in session when you ran the backtest

2. **Accurate Results**: Performance metrics will reflect all configured symbols

3. **Proper Analysis**: The `analyze_backtest_results.py` script will show results for all 69 symbols

4. **Consistent Behavior**: Backtest results won't vary based on what time of day you run the backtest

## Live Trading Behavior (Unchanged)

This fix **only affects backtest mode**. Live trading behavior remains unchanged:
- Session checking still works normally
- Inactive symbols still wait for their sessions to start
- Background monitoring still functions as designed

## Related Configuration

Your `.env` has:
```
CHECK_SYMBOL_SESSION=true
WAIT_FOR_SESSION=true
```

These settings are **correct for live trading** but were being incorrectly applied during backtest initialization. The fix ensures they only apply to live trading, not backtests.

