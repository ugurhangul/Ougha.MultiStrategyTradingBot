# MT5 Order Check Implementation Guide

## Overview

This guide provides a detailed implementation plan for adding `mt5.order_check()` validation to the OrderExecutor to prevent order rejections and improve reliability.

**Priority:** ⭐ HIGH  
**Effort:** Low (1-2 hours)  
**Impact:** High (prevents order rejections, better error messages)

---

## What is `mt5.order_check()`?

The `mt5.order_check()` function validates a trading request **before** sending it to the broker. It checks:

1. **Margin requirements** - Whether account has sufficient margin
2. **Stop levels** - Whether SL/TP meet minimum distance requirements
3. **Volume limits** - Whether volume is within min/max/step constraints
4. **Trading permissions** - Whether trading is allowed for the symbol
5. **Price validity** - Whether prices are within acceptable ranges
6. **Broker-specific rules** - Any custom broker restrictions

**Returns:** `OrderCheckResult` object with:
- `retcode` - Result code (10009 = success, others = failure)
- `balance` - Account balance after operation
- `equity` - Account equity after operation
- `profit` - Expected profit
- `margin` - Required margin
- `margin_free` - Free margin after operation
- `margin_level` - Margin level after operation
- `comment` - Error description if validation failed

---

## Current Implementation (Without order_check)

**File:** `src/execution/order_management/order_executor.py`

**Current Flow:**
```
1. Validate signal
2. Get symbol info
3. Calculate position size
4. Validate stops (custom logic)
5. Check margin (custom logic)
6. Build order request
7. Send order with mt5.order_send()
8. Handle rejection (if it fails)
```

**Problem:**
- Order can still be rejected by broker even after our validation
- Rejection reasons may not be clear
- Wasted API calls for orders that would fail
- No visibility into margin impact before execution

---

## Proposed Implementation (With order_check)

**New Flow:**
```
1. Validate signal
2. Get symbol info
3. Calculate position size
4. Validate stops (custom logic)
5. Check margin (custom logic)
6. Build order request
7. ⭐ Validate with mt5.order_check() ⭐
8. If validation fails, log detailed reason and abort
9. If validation passes, send order with mt5.order_send()
10. Handle execution result
```

**Benefits:**
- ✅ Catch rejections before sending order
- ✅ Get detailed rejection reasons from broker
- ✅ See margin impact before execution
- ✅ Reduce failed order attempts
- ✅ Better logging and debugging

---

## Implementation Steps

### Step 1: Add order_check() Helper Method

Add a new method to `OrderExecutor` class:

```python
def _validate_order_with_broker(self, request: dict, symbol: str) -> tuple[bool, str]:
    """
    Validate order request with broker using mt5.order_check().
    
    This performs a pre-flight check to ensure the order would be accepted
    by the broker before actually sending it.
    
    Args:
        request: Order request dictionary
        symbol: Symbol name (for logging)
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        # Validate order with broker
        check_result = mt5.order_check(request)
        
        if check_result is None:
            error_code, error_msg = mt5.last_error()
            error_message = f"Order check failed: ({error_code}) {error_msg}"
            self.logger.trade_error(
                symbol=symbol,
                error_type="Order Validation",
                error_message=error_message,
                context={"request": request}
            )
            return False, error_message
        
        # Check if validation passed
        if check_result.retcode != mt5.TRADE_RETCODE_DONE:
            error_message = (
                f"Order validation failed: {check_result.comment} "
                f"(retcode: {check_result.retcode})"
            )
            
            # Log detailed validation failure
            self.logger.trade_error(
                symbol=symbol,
                error_type="Order Validation",
                error_message=error_message,
                context={
                    "retcode": check_result.retcode,
                    "comment": check_result.comment,
                    "margin_required": check_result.margin,
                    "margin_free": check_result.margin_free,
                    "balance": check_result.balance,
                    "equity": check_result.equity,
                    "request": request
                }
            )
            return False, error_message
        
        # Validation passed - log margin impact
        self.logger.verbose(
            f"Order validation passed | "
            f"Margin required: ${check_result.margin:.2f} | "
            f"Free margin after: ${check_result.margin_free:.2f} | "
            f"Margin level: {check_result.margin_level:.2f}%",
            symbol
        )
        
        return True, ""
        
    except Exception as e:
        error_message = f"Exception during order validation: {type(e).__name__}: {e}"
        self.logger.trade_error(
            symbol=symbol,
            error_type="Order Validation",
            error_message=error_message,
            context={"request": request}
        )
        return False, error_message
```

### Step 2: Integrate into execute_signal()

Modify the `execute_signal()` method to call validation before sending order:

**Location:** After building the request, before `mt5.order_send()`

```python
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

# ⭐ NEW: Validate order with broker before sending
is_valid, error_message = self._validate_order_with_broker(request, symbol)
if not is_valid:
    self.logger.warning(
        f"Order rejected by broker validation: {error_message}",
        symbol
    )
    return None

# If validation passed, send the order
result = mt5.order_send(request)
```

---

## Testing Plan

### Test Case 1: Insufficient Margin
**Setup:**
- Set account balance to $100
- Try to open 10 lot EURUSD position (requires ~$100,000 margin)

**Expected Result:**
- `order_check()` returns retcode != DONE
- Error logged with margin details
- Order NOT sent to broker
- Clear error message about insufficient margin

### Test Case 2: Invalid Stop Level
**Setup:**
- Try to place order with SL 1 point away from entry
- Broker requires minimum 10 points

**Expected Result:**
- `order_check()` returns retcode != DONE
- Error logged with stop level violation
- Order NOT sent to broker
- Clear error message about minimum stop distance

### Test Case 3: Valid Order
**Setup:**
- Normal trade with sufficient margin and valid stops

**Expected Result:**
- `order_check()` returns retcode = DONE
- Margin impact logged
- Order sent to broker successfully
- Position opened

### Test Case 4: Market Closed
**Setup:**
- Try to trade when market is closed

**Expected Result:**
- `order_check()` returns market closed error
- Order NOT sent to broker
- Clear error message about market status

---

## Configuration

### Enable/Disable Order Validation

Add configuration option to enable/disable this feature:

**File:** `src/config/config.py`

```python
# Order execution settings
ENABLE_ORDER_PREVALIDATION = True  # Set to False to disable order_check()
```

**Usage in OrderExecutor:**
```python
if config.ENABLE_ORDER_PREVALIDATION:
    is_valid, error_message = self._validate_order_with_broker(request, symbol)
    if not is_valid:
        return None
```

This allows disabling the feature if it causes issues with specific brokers.

---

## Monitoring & Metrics

### Add Metrics Tracking

Track validation statistics:

```python
class OrderExecutor:
    def __init__(self, ...):
        # ... existing code ...
        
        # Order validation metrics
        self.validation_stats = {
            'total_validations': 0,
            'validation_passed': 0,
            'validation_failed': 0,
            'rejection_reasons': {}  # retcode -> count
        }
    
    def get_validation_stats(self) -> dict:
        """Get order validation statistics."""
        return self.validation_stats.copy()
```

### Log Statistics Periodically

```python
def log_validation_stats(self):
    """Log order validation statistics."""
    stats = self.validation_stats
    
    if stats['total_validations'] == 0:
        return
    
    pass_rate = (stats['validation_passed'] / stats['total_validations']) * 100
    
    self.logger.info("=== Order Validation Statistics ===")
    self.logger.info(f"Total Validations: {stats['total_validations']}")
    self.logger.info(f"Passed: {stats['validation_passed']}")
    self.logger.info(f"Failed: {stats['validation_failed']}")
    self.logger.info(f"Pass Rate: {pass_rate:.1f}%")
    
    if stats['rejection_reasons']:
        self.logger.info("Rejection Reasons:")
        for retcode, count in stats['rejection_reasons'].items():
            self.logger.info(f"  {retcode}: {count} times")
```

---

## Rollout Plan

### Phase 1: Implementation (Day 1)
1. Add `_validate_order_with_broker()` method
2. Integrate into `execute_signal()`
3. Add configuration option
4. Add metrics tracking

### Phase 2: Testing (Day 2)
1. Test with demo account
2. Verify all test cases pass
3. Monitor validation statistics
4. Check for false rejections

### Phase 3: Deployment (Day 3)
1. Deploy to production with feature enabled
2. Monitor for 24 hours
3. Review validation statistics
4. Adjust if needed

---

## Expected Impact

### Before Implementation
- ~5-10% of orders rejected by broker
- Unclear rejection reasons
- Wasted API calls
- Poor user experience

### After Implementation
- 0% broker rejections (caught by validation)
- Clear rejection reasons in logs
- Reduced API calls
- Better debugging capability
- Improved reliability

---

## Conclusion

Adding `mt5.order_check()` validation is a **high-value, low-effort improvement** that will:
- ✅ Prevent order rejections
- ✅ Improve error messages
- ✅ Reduce API calls
- ✅ Better visibility into margin impact
- ✅ Easier debugging

**Estimated Time:** 1-2 hours  
**Recommended Priority:** ⭐ HIGH - Implement this week


