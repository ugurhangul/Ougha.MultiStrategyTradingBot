# Position Limit Enforcement Implementation

## Overview

This document describes the implementation of the "1 position per strategy and direction" rule enforcement in the trading system.

## Problem Statement

Previously, the `RiskManager.can_open_new_position()` method existed but was **never called** during trade execution. This meant the system could open multiple positions for the same strategy/direction/symbol combination, violating the intended position limit rules.

## Solution

The position limit check has been integrated into the order execution flow by:

1. **Passing RiskManager through the dependency chain**
2. **Parsing strategy metadata from signal comments**
3. **Enforcing the check before executing trades**

## Implementation Details

### 1. Modified Files

#### `src/execution/order_management/order_manager.py`
- Added `risk_manager` parameter to `__init__`
- Passes `risk_manager` to `OrderExecutor`

#### `src/execution/order_management/order_executor.py`
- Added `risk_manager` parameter to `__init__`
- Added position limit check in `execute_signal()` method (lines 110-140)
- Parses signal comment to extract `strategy_type` and `range_id`
- Calls `risk_manager.can_open_new_position()` before executing trade
- Rejects trade if position limit is exceeded

#### `main.py`
- Reordered initialization: `RiskManager` created before `OrderManager`
- Passes `risk_manager` to `OrderManager` constructor

### 2. Comment Parsing Logic

Signal comments follow the format: `"STRATEGY|RANGE_ID|VALIDATIONS"` for TB/FB or `"STRATEGY|VALIDATIONS"` for HFT

**Note:** Direction is not included in comments as it's already visible in MT5 position type (Buy/Sell).

**Examples:**
- `"HFT|MV"` → strategy="HFT", range=None, confirmations="MV" (momentum+volume)
- `"TB|15M_1M|BV"` → strategy="TB", range="15M_1M", confirmations="BV" (breakout volume)
- `"FB|4H_5M|RT"` → strategy="FB", range="4H_5M", confirmations="RT" (retest)

**Parsing Code:**
```python
from src.utils.comment_parser import CommentParser

if signal.comment:
    parsed = CommentParser.parse(signal.comment)
    if parsed:
        strategy_type = parsed.strategy_type  # "HFT", "TB", "FB"
        range_id = parsed.range_id if parsed.range_id else None  # "15M_1M", "4H_5M", or None
        confirmations = parsed.confirmations  # "BV", "RT", "CV", "MV", etc.
```

### 3. Position Limit Check Flow

```
execute_signal(signal)
  ↓
Check trading enabled
  ↓
Parse comment → extract strategy_type, range_id
  ↓
Call risk_manager.can_open_new_position(
    magic_number, symbol, position_type,
    strategy_type, range_id
)
  ↓
If can_open == False → Log warning, return None
  ↓
If can_open == True → Continue with trade execution
```

### 4. Position Limit Rules (from RiskManager)

The `can_open_new_position()` method enforces:

1. **Maximum total positions** across all strategies
2. **1 position per strategy/direction/symbol** combination
3. **Special case**: Allows 2 positions when `all_confirmations_met=True`
4. **Persistence check**: Prevents duplicates after bot restart

**Filtering Logic:**
- Queries MT5 positions by magic number
- Filters by symbol and direction
- Extracts strategy type and range from position comments
- Compares with requested strategy type and range
- Returns `(can_open: bool, reason: str)`

## Testing

### Test File: `test_position_limit_check.py`

Tests verify:
1. ✅ Comment parsing for all formats (HFT, TB, FB)
2. ✅ Handling of empty ranges (HFT strategies)
3. ✅ Handling of range IDs (TB/FB strategies)
4. ✅ Signal creation with proper comments

**All tests pass successfully.**

## Expected Behavior

### Scenario 1: First Position
- **Input**: HFT BUY signal for BTCUSD
- **Result**: ✅ Position opened
- **Reason**: No existing HFT BUY position for BTCUSD

### Scenario 2: Duplicate Position (Same Strategy)
- **Input**: Second HFT BUY signal for BTCUSD
- **Result**: ❌ Trade rejected
- **Reason**: "BUY position already exists for symbol BTCUSD (strategy: HFT)"

### Scenario 3: Different Direction (Same Strategy)
- **Input**: HFT SELL signal for BTCUSD (HFT BUY already open)
- **Result**: ✅ Position opened
- **Reason**: Different direction allowed

### Scenario 4: Different Strategy (Same Direction)
- **Input**: TB BUY signal for BTCUSD (HFT BUY already open)
- **Result**: ✅ Position opened
- **Reason**: Different strategy allowed

### Scenario 5: Different Range (Same Strategy)
- **Input**: TB BUY 15M1M signal (TB BUY 4H5M already open)
- **Result**: ✅ Position opened
- **Reason**: Different range ID allowed

## Configuration

No new configuration required. The system uses existing `RiskConfig.max_positions` setting.

## Backward Compatibility

- ✅ Fully backward compatible
- ✅ If `risk_manager=None`, check is skipped (graceful degradation)
- ✅ Existing code continues to work without changes

## Logging

When a trade is rejected due to position limits:
```
WARNING | [BTCUSD] Position limit check failed: BUY position already exists for symbol BTCUSD (strategy: HFT)
```

## Next Steps

1. ✅ Implementation complete
2. ✅ Tests passing
3. ✅ Files compile successfully
4. 🔄 Deploy and monitor in production
5. 🔄 Verify logs show position limit rejections when appropriate

## Summary

The position limit enforcement is now **ACTIVE** and will prevent duplicate positions from being opened when:
- Same symbol
- Same strategy type (HFT, TB, FB)
- Same direction (BUY or SELL)
- Same range ID (for TB/FB strategies)

This ensures proper risk management and prevents unintended position accumulation.

