# Dynamic Signal Validation System

## Overview

The BaseStrategy class now includes a dynamic, extensible signal validation system that allows strategies to configure and execute multiple validation checks in a flexible, maintainable way.

## Key Features

1. **Dynamic Method Invocation**: Validation methods are called dynamically using `getattr()`, allowing for runtime configuration
2. **Extensible Registry**: Subclasses can easily add, remove, or override validation methods
3. **Flexible Aggregation**: Supports both AND (all must pass) and OR (any must pass) logic
4. **Detailed Results**: Returns comprehensive validation results for debugging and logging
5. **Error Handling**: Gracefully handles missing methods and exceptions

## Architecture

### ValidationResult Class

```python
@dataclass
class ValidationResult:
    """Result of a single validation check"""
    passed: bool
    method_name: str
    reason: str = ""
```

### BaseStrategy Attributes

- `_validation_methods: List[str]` - List of validation method names to execute
- `_validation_mode: Literal["all", "any"]` - Aggregation mode (default: "all")

### Core Method

```python
def _validate_signal(self, signal_data: Dict[str, Any]) -> Tuple[bool, List[ValidationResult]]:
    """
    Validate a trading signal through a dynamic, extensible confirmation system.
    
    Args:
        signal_data: Dictionary containing all data needed for validation
    
    Returns:
        Tuple of (is_valid, validation_results)
    """
```

## Usage Examples

### Example 1: Basic Usage in HFTMomentumStrategy

```python
class HFTMomentumStrategy(BaseStrategy):
    def __init__(self, ...):
        super().__init__(...)
        
        # Configure validation methods registry
        self._validation_methods = [
            "_check_momentum_strength",
            "_check_volume_confirmation",
            "_check_volatility_filter",
            "_check_trend_alignment",
            "_check_spread_filter"
        ]
        self._validation_mode = "all"  # All checks must pass
    
    def _validate_hft_signal(self, signal_direction: int) -> bool:
        # Prepare signal data
        signal_data = {
            'signal_direction': signal_direction,
            'recent_ticks': self.tick_buffer[-self.config.tick_momentum_count:],
            'current_price': self.tick_buffer[-1].mid
        }
        
        # Use dynamic validation system
        is_valid, validation_results = self._validate_signal(signal_data)
        return is_valid
    
    def _check_momentum_strength(self, signal_data: Dict[str, Any]) -> ValidationResult:
        ticks = signal_data.get('recent_ticks', [])
        direction = signal_data.get('signal_direction', 0)
        
        passed = self.tick_momentum_indicator.check_momentum_strength(
            ticks=ticks,
            direction=direction,
            min_strength=self.config.min_momentum_strength
        )
        
        return ValidationResult(
            passed=passed,
            method_name="_check_momentum_strength",
            reason="Momentum sufficient" if passed else "Momentum too weak"
        )
```

### Example 2: Extending Validation in a Subclass

```python
class AdvancedHFTStrategy(HFTMomentumStrategy):
    def __init__(self, ...):
        super().__init__(...)
        
        # Extend parent's validation methods
        self._validation_methods.extend([
            "_check_market_hours",
            "_check_news_filter",
            "_check_correlation"
        ])
    
    def _check_market_hours(self, signal_data: Dict[str, Any]) -> ValidationResult:
        current_hour = datetime.now().hour
        is_trading_hours = 8 <= current_hour <= 17
        
        return ValidationResult(
            passed=is_trading_hours,
            method_name="_check_market_hours",
            reason=f"Current hour {current_hour} {'within' if is_trading_hours else 'outside'} trading hours"
        )
```

### Example 3: Optional Validations (OR Logic)

```python
class FlexibleStrategy(BaseStrategy):
    def __init__(self, ...):
        super().__init__(...)
        
        # At least one confirmation must pass
        self._validation_methods = [
            "_check_volume_spike",
            "_check_price_momentum",
            "_check_divergence"
        ]
        self._validation_mode = "any"  # At least one must pass
```

## Validation Method Signature

All validation methods must follow this signature:

```python
def _check_something(self, signal_data: Dict[str, Any]) -> Union[bool, ValidationResult]:
    """
    Validation method description.
    
    Args:
        signal_data: Dictionary containing validation data
    
    Returns:
        ValidationResult (preferred) or bool
    """
```

### Return Types

- **ValidationResult** (recommended): Provides detailed pass/fail status and reason
- **bool**: Simple pass/fail (will be wrapped in ValidationResult automatically)

## Best Practices

1. **Use ValidationResult**: Return ValidationResult instead of bool for better debugging
2. **Descriptive Reasons**: Provide clear, actionable reasons in ValidationResult
3. **Handle Missing Data**: Check for required keys in signal_data and handle gracefully
4. **Skip on Error**: Return `passed=True` with reason when data is unavailable (don't fail signal)
5. **Consistent Naming**: Use `_check_*` prefix for validation methods
6. **Document Requirements**: Document what keys are expected in signal_data

## Validation Comments for MT5 Trades

The validation system includes a `get_validations_for_comment()` method that generates compact strings suitable for MT5 trade comments (31 character limit).

### Comment Formats

```python
# Compact format (default) - only show passed validations
comment = strategy.get_validations_for_comment(format="compact")
# Returns: "MVATS" (all passed) or "MV" (only M and V passed) or "NC" (none passed)

# Detailed format - show all with pass/fail indicators
comment = strategy.get_validations_for_comment(format="detailed")
# Returns: "M+V+A+T+S+" (all passed) or "M+V+A-T-S-" (M,V passed; A,T,S failed)

# All format - show all configured validations
comment = strategy.get_validations_for_comment(format="all")
# Returns: "MVATS" (shows all configured, regardless of pass/fail)
```

### Validation Abbreviations

Subclasses define abbreviations in `_validation_abbreviations` dict:

```python
self._validation_abbreviations = {
    "_check_momentum_strength": "M",    # Momentum
    "_check_volume_confirmation": "V",  # Volume
    "_check_volatility_filter": "A",    # ATR/Volatility
    "_check_trend_alignment": "T",      # Trend
    "_check_spread_filter": "S"         # Spread
}
```

### Integration with Trade Comments

```python
def get_confirmations_for_trade(self) -> str:
    """Get confirmations for MT5 trade comment"""
    return self.get_validations_for_comment(format="compact")
```

This automatically includes validation results in trade comments:
- `"HFT|buy|MVATS"` - All validations passed
- `"HFT|buy|MV"` - Only Momentum and Volume passed
- `"HFT|buy|NC"` - No confirmations (validations failed)
- `"TB|15M_1M|sell|V"` - True Breakout SELL with volume
- `"FB|4H_5M|buy|N"` - False Breakout BUY with no confirmations

## Benefits

1. **Maintainability**: Easy to add/remove validation checks without modifying core logic
2. **Testability**: Each validation method can be tested independently
3. **Flexibility**: Subclasses can customize validation without overriding large methods
4. **Debugging**: Detailed validation results make it easy to diagnose signal rejections
5. **Reusability**: Validation methods can be shared across strategies
6. **Configuration**: Validation methods can be enabled/disabled at runtime
7. **Traceability**: Validation results are automatically included in MT5 trade comments

## Migration Guide

### Before (Hardcoded Validation)

```python
def _validate_signal(self, direction: int) -> bool:
    if not self._check_momentum(direction):
        return False
    if not self._check_volume():
        return False
    if not self._check_trend(direction):
        return False
    return True
```

### After (Dynamic Validation)

```python
def __init__(self, ...):
    self._validation_methods = [
        "_check_momentum",
        "_check_volume",
        "_check_trend"
    ]

def _validate_signal(self, direction: int) -> bool:
    signal_data = {'direction': direction}
    is_valid, _ = self._validate_signal(signal_data)
    return is_valid
```

