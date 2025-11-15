# Validation Decorator Guide

## Overview

The `@validation_check` decorator provides an elegant way to automatically discover and register validation methods in trading strategies. It eliminates the need for manual registration of validation methods while maintaining full compatibility with the existing `BaseStrategy` validation system.

## Key Features

1. **Automatic Discovery**: Decorated methods are automatically discovered and registered
2. **Ordered Execution**: Control validation execution order with the `order` parameter
3. **Abbreviation Management**: Automatically populate validation abbreviations for trade comments
4. **Backward Compatible**: Works seamlessly with existing manual registration pattern
5. **Hybrid Approach**: Supports mixing decorated and manually-registered validations

## Basic Usage

### Approach 1: Automatic Registration (Recommended)

```python
from src.strategy.base_strategy import BaseStrategy, ValidationResult
from src.strategy.validation_decorator import validation_check, auto_register_validations

class MyStrategy(BaseStrategy):
    def __init__(self, symbol, connector, order_manager, risk_manager,
                 trade_manager, indicators, position_sizer=None, **kwargs):
        super().__init__(symbol, connector, order_manager, risk_manager,
                        trade_manager, indicators, position_sizer, **kwargs)
        
        # Automatically discover and register all decorated validation methods
        auto_register_validations(self)
    
    @validation_check(abbreviation="M", order=1, description="Check momentum strength")
    def _check_momentum_strength(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """Check if momentum exceeds threshold"""
        momentum = signal_data.get('momentum', 0)
        passed = momentum > self.config.min_momentum
        
        return ValidationResult(
            passed=passed,
            method_name="_check_momentum_strength",
            reason=f"Momentum {momentum:.2f} {'>' if passed else '<='} {self.config.min_momentum}"
        )
    
    @validation_check(abbreviation="V", order=2, description="Check volume confirmation")
    def _check_volume_confirmation(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """Check if volume exceeds average"""
        volume = signal_data.get('volume', 0)
        avg_volume = signal_data.get('avg_volume', 1)
        passed = volume > avg_volume * self.config.min_volume_multiplier
        
        return ValidationResult(
            passed=passed,
            method_name="_check_volume_confirmation",
            reason=f"Volume ratio {volume/avg_volume:.2f}"
        )
```

After calling `auto_register_validations(self)`, the strategy will have:
- `_validation_methods = ["_check_momentum_strength", "_check_volume_confirmation"]` (sorted by order)
- `_validation_abbreviations = {"_check_momentum_strength": "M", "_check_volume_confirmation": "V"}`

### Approach 2: Manual Registration (Existing Pattern)

The existing manual registration pattern continues to work without any changes:

```python
class MyStrategy(BaseStrategy):
    def __init__(self, ...):
        super().__init__(...)
        
        # Manual registration (existing pattern)
        self._validation_methods = [
            "_check_momentum_strength",
            "_check_volume_confirmation"
        ]
        
        self._validation_abbreviations = {
            "_check_momentum_strength": "M",
            "_check_volume_confirmation": "V"
        }
    
    # Methods don't need to be decorated
    def _check_momentum_strength(self, signal_data: Dict[str, Any]) -> ValidationResult:
        # validation logic
        pass
```

### Approach 3: Hybrid (Decorator + Manual Override)

Combine automatic registration with conditional manual additions:

```python
class MyStrategy(BaseStrategy):
    def __init__(self, enable_divergence: bool = False, **kwargs):
        super().__init__(**kwargs)
        
        # Start with auto-registration
        auto_register_validations(self)
        
        # Conditionally add extra validations based on config
        if enable_divergence:
            self._validation_methods.append("_check_divergence")
            self._validation_abbreviations["_check_divergence"] = "DIV"
    
    @validation_check(abbreviation="M", order=1)
    def _check_momentum_strength(self, signal_data: Dict[str, Any]) -> ValidationResult:
        # Always registered via decorator
        pass
    
    @validation_check(abbreviation="V", order=2)
    def _check_volume_confirmation(self, signal_data: Dict[str, Any]) -> ValidationResult:
        # Always registered via decorator
        pass
    
    # Not decorated - only added manually when enabled
    def _check_divergence(self, signal_data: Dict[str, Any]) -> ValidationResult:
        # Conditionally registered in __init__
        pass
```

## Decorator Parameters

### `abbreviation` (str, optional)
Short code for trade comments (MT5 has 31-char limit).
- Example: `"M"` for momentum, `"V"` for volume
- If empty, method won't be added to `_validation_abbreviations`

### `order` (int, optional, default=0)
Execution order of validation methods.
- Lower numbers execute first
- Example: `order=1` executes before `order=2`
- Useful for optimizing validation performance (fast checks first)

### `description` (str, optional)
Human-readable description of the validation.
- Used for documentation and debugging
- Defaults to method's docstring if not provided

## Utility Functions

### `auto_register_validations(instance)`
Automatically discovers and registers all decorated validation methods.
- Call in `__init__` after `super().__init__()`
- Populates `_validation_methods` (sorted by order)
- Populates `_validation_abbreviations`

### `get_validation_methods(instance)`
Returns dictionary of all decorated validation methods and their metadata.
- Useful for introspection and debugging
- Returns: `Dict[str, ValidationMetadata]`

## Integration with Existing System

The decorator integrates seamlessly with the existing validation system:

1. **Validation Execution**: Uses the same `_validate_signal()` method from `BaseStrategy`
2. **Return Types**: Supports both `ValidationResult` and `bool` return types
3. **Validation Modes**: Works with both `"all"` and `"any"` validation modes
4. **Trade Comments**: Abbreviations are used by `get_validations_for_comment()`

## Best Practices

### 1. Order Validations by Performance
Put fast checks first to fail early:
```python
@validation_check(abbreviation="S", order=1)  # Fast: simple comparison
def _check_spread_filter(self, signal_data):
    pass

@validation_check(abbreviation="V", order=2)  # Medium: requires candle data
def _check_volume_confirmation(self, signal_data):
    pass

@validation_check(abbreviation="DIV", order=3)  # Slow: complex calculation
def _check_divergence(self, signal_data):
    pass
```

### 2. Use Descriptive Abbreviations
Keep abbreviations short but meaningful:
- ✅ Good: `"M"` (Momentum), `"V"` (Volume), `"RT"` (Retest)
- ❌ Bad: `"X"`, `"CHK1"`, `"VALIDATION"`

### 3. Provide Clear Reasons
Return detailed reasons for debugging:
```python
return ValidationResult(
    passed=passed,
    method_name="_check_momentum_strength",
    reason=f"Momentum {momentum:.2f} {'>' if passed else '<='} threshold {threshold:.2f}"
)
```

### 4. Use Hybrid Approach for Conditional Validations
Decorate core validations, manually add optional ones:
```python
# Core validations - always active
@validation_check(abbreviation="M", order=1)
def _check_momentum(self, signal_data):
    pass

# Optional validation - conditionally added
def _check_divergence(self, signal_data):
    pass
```

## Migration Guide

### From Manual to Automatic Registration

**Before:**
```python
def __init__(self, ...):
    super().__init__(...)
    self._validation_methods = ["_check_momentum", "_check_volume"]
    self._validation_abbreviations = {"_check_momentum": "M", "_check_volume": "V"}
```

**After:**
```python
def __init__(self, ...):
    super().__init__(...)
    auto_register_validations(self)

@validation_check(abbreviation="M", order=1)
def _check_momentum(self, signal_data):
    pass

@validation_check(abbreviation="V", order=2)
def _check_volume(self, signal_data):
    pass
```

## Examples

See `examples/validation_decorator_example.py` for complete working examples of all three approaches.

## Validation Timing

The decorator works with the existing validation flow, which executes validations:

### During Signal Generation (Current Pattern)
```python
def on_tick(self):
    # Generate signal data
    signal_data = {
        'signal_direction': 1,
        'recent_ticks': self.tick_buffer[-10:],
        'volume': 1000
    }

    # Validate signal using decorated methods
    is_valid, results = self._validate_signal(signal_data)

    if not is_valid:
        return None  # Reject signal

    return self._generate_signal(signal_direction)
```

### On-Demand Validation
```python
def validate_strategy_state(self) -> bool:
    """Validate strategy is in good state"""
    validation_data = {
        'spread': self.get_current_spread(),
        'volatility': self.get_current_atr()
    }

    is_valid, results = self._validate_signal(validation_data)
    return is_valid
```

### During Initialization (Optional)
```python
def initialize(self) -> bool:
    """Initialize and validate configuration"""
    # Perform initialization
    self.is_initialized = True

    # Optionally validate initial state
    if hasattr(self, '_validate_configuration'):
        return self._validate_configuration()

    return True
```

## Testing

Run the decorator tests:
```bash
python -m pytest tests/test_validation_decorator.py -v
```

All tests should pass:
```
test_auto_register_validations ✓
test_decorator_marks_method ✓
test_decorator_preserves_functionality ✓
test_decorator_without_abbreviation ✓
test_get_validation_methods ✓
test_hybrid_approach ✓
```

