# Validation Decorator - Quick Reference

## Import
```python
from src.strategy.validation_decorator import validation_check, auto_register_validations
```

## Basic Usage

### 1. Decorate Validation Methods
```python
@validation_check(abbreviation="M", order=1, description="Check momentum")
def _check_momentum(self, signal_data: Dict[str, Any]) -> ValidationResult:
    return ValidationResult(passed=True, method_name="_check_momentum", reason="OK")
```

### 2. Auto-Register in __init__
```python
def __init__(self, ...):
    super().__init__(...)
    auto_register_validations(self)  # One line!
```

## Decorator Parameters

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `abbreviation` | str | No | Short code for trade comments | `"M"`, `"V"`, `"RT"` |
| `order` | int | No | Execution order (lower = first) | `1`, `2`, `3` |
| `description` | str | No | Human-readable description | `"Check momentum strength"` |

## Complete Example

```python
from src.strategy.base_strategy import BaseStrategy, ValidationResult
from src.strategy.validation_decorator import validation_check, auto_register_validations

class MyStrategy(BaseStrategy):
    def __init__(self, symbol, connector, order_manager, risk_manager,
                 trade_manager, indicators, position_sizer=None, **kwargs):
        super().__init__(symbol, connector, order_manager, risk_manager,
                        trade_manager, indicators, position_sizer, **kwargs)
        
        # Auto-register all decorated validation methods
        auto_register_validations(self)
    
    @validation_check(abbreviation="M", order=1)
    def _check_momentum(self, signal_data: Dict[str, Any]) -> ValidationResult:
        momentum = signal_data.get('momentum', 0)
        passed = momentum > 0.001
        return ValidationResult(
            passed=passed,
            method_name="_check_momentum",
            reason=f"Momentum: {momentum:.5f}"
        )
    
    @validation_check(abbreviation="V", order=2)
    def _check_volume(self, signal_data: Dict[str, Any]) -> ValidationResult:
        volume = signal_data.get('volume', 0)
        passed = volume > 1000
        return ValidationResult(
            passed=passed,
            method_name="_check_volume",
            reason=f"Volume: {volume}"
        )
```

## What Gets Auto-Populated

After calling `auto_register_validations(self)`:

```python
# Automatically populated (sorted by order):
self._validation_methods = [
    "_check_momentum",  # order=1
    "_check_volume"     # order=2
]

# Automatically populated:
self._validation_abbreviations = {
    "_check_momentum": "M",
    "_check_volume": "V"
}
```

## Validation Method Signature

```python
def _check_something(self, signal_data: Dict[str, Any]) -> ValidationResult:
    """
    Args:
        signal_data: Dictionary containing validation data
            Common keys: 'signal_direction', 'recent_ticks', 'volume', etc.
    
    Returns:
        ValidationResult with passed, method_name, and reason
    """
    passed = # your validation logic
    
    return ValidationResult(
        passed=passed,
        method_name="_check_something",
        reason="Descriptive reason"
    )
```

## Common Patterns

### Fast Checks First
```python
@validation_check(order=1)  # Fast: simple comparison
def _check_spread(self, signal_data):
    pass

@validation_check(order=2)  # Slow: requires data fetch
def _check_volume(self, signal_data):
    pass
```

### Conditional Validation
```python
def __init__(self, enable_divergence=False, ...):
    super().__init__(...)
    auto_register_validations(self)
    
    if enable_divergence:
        self._validation_methods.append("_check_divergence")
```

### Optional Abbreviation
```python
@validation_check(order=1)  # No abbreviation
def _check_internal(self, signal_data):
    pass  # Won't appear in trade comments
```

## Execution Flow

```
1. Strategy.__init__()
   └─> auto_register_validations(self)
       └─> Discovers decorated methods
       └─> Sorts by order
       └─> Populates _validation_methods
       └─> Populates _validation_abbreviations

2. Strategy.on_tick()
   └─> self._validate_signal(signal_data)
       └─> Iterates _validation_methods
       └─> Calls each validation method
       └─> Aggregates results
       └─> Returns (is_valid, results)
```

## Troubleshooting

### Methods Not Being Discovered
- ✅ Check decorator is applied: `@validation_check(...)`
- ✅ Check `auto_register_validations(self)` is called in `__init__`
- ✅ Check method signature matches: `def _check_xxx(self, signal_data) -> ValidationResult`

### Wrong Execution Order
- ✅ Check `order` parameter: lower numbers execute first
- ✅ Verify with: `print(self._validation_methods)` after auto-registration

### Abbreviations Not Showing
- ✅ Check `abbreviation` parameter is provided
- ✅ Verify with: `print(self._validation_abbreviations)` after auto-registration

## Migration Checklist

- [ ] Import decorator: `from src.strategy.validation_decorator import ...`
- [ ] Add `auto_register_validations(self)` to `__init__`
- [ ] Decorate validation methods with `@validation_check(...)`
- [ ] Remove manual `_validation_methods` list
- [ ] Remove manual `_validation_abbreviations` dict
- [ ] Test: `python -m pytest tests/test_validation_decorator.py -v`

## See Also

- **Full Guide**: `docs/validation_decorator_guide.md`
- **Examples**: `examples/validation_decorator_example.py`
- **Refactoring Example**: `examples/hft_momentum_with_decorator.py`
- **Tests**: `tests/test_validation_decorator.py`

