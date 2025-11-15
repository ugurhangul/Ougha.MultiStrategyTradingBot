"""
Validation decorator for strategy validation methods.

This module provides a decorator that automatically discovers and registers
validation methods within strategy classes, integrating seamlessly with the
existing BaseStrategy validation system.

Usage:
    @validation_check(abbreviation="M", order=1)
    def _check_momentum_strength(self, signal_data: Dict[str, Any]) -> ValidationResult:
        # validation logic
        return ValidationResult(passed=True, method_name="_check_momentum_strength", reason="OK")
"""
from typing import Dict, Any, Union, Callable, Optional
from functools import wraps
from dataclasses import dataclass

# Import ValidationResult from base_strategy to avoid circular imports
# This will be available when the module is imported
ValidationResult = None


@dataclass
class ValidationMetadata:
    """Metadata for a validation method"""
    method_name: str
    abbreviation: str
    order: int
    description: str


def validation_check(
    abbreviation: str = "",
    order: int = 0,
    description: str = ""
) -> Callable:
    """
    Decorator for strategy validation methods.
    
    This decorator:
    1. Marks methods as validation checks
    2. Stores metadata (abbreviation, order, description)
    3. Enables automatic discovery via get_validation_methods()
    4. Integrates with BaseStrategy's _validation_methods list
    
    Args:
        abbreviation: Short code for trade comments (e.g., "M" for momentum)
        order: Execution order (lower numbers execute first)
        description: Human-readable description of the validation
    
    Returns:
        Decorated validation method
    
    Example:
        @validation_check(abbreviation="M", order=1, description="Check momentum strength")
        def _check_momentum_strength(self, signal_data: Dict[str, Any]) -> ValidationResult:
            # validation logic
            return ValidationResult(passed=True, method_name="_check_momentum_strength", reason="OK")
    """
    def decorator(func: Callable) -> Callable:
        # Store metadata as function attributes
        func._is_validation_check = True
        func._validation_metadata = ValidationMetadata(
            method_name=func.__name__,
            abbreviation=abbreviation,
            order=order,
            description=description or func.__doc__ or ""
        )
        
        @wraps(func)
        def wrapper(self, signal_data: Dict[str, Any]) -> Union[bool, 'ValidationResult']:
            """Wrapper that calls the original validation method"""
            return func(self, signal_data)
        
        # Preserve metadata on wrapper
        wrapper._is_validation_check = True
        wrapper._validation_metadata = func._validation_metadata
        
        return wrapper
    
    return decorator


def get_validation_methods(instance: object) -> Dict[str, ValidationMetadata]:
    """
    Discover all validation methods decorated with @validation_check in an instance.

    This function introspects the instance and finds all methods marked with
    the @validation_check decorator, returning their metadata.

    Args:
        instance: Strategy instance to introspect

    Returns:
        Dictionary mapping method names to their ValidationMetadata

    Example:
        class MyStrategy(BaseStrategy):
            @validation_check(abbreviation="M", order=1)
            def _check_momentum(self, signal_data):
                return ValidationResult(passed=True, method_name="_check_momentum", reason="OK")

        strategy = MyStrategy(...)
        methods = get_validation_methods(strategy)
        # methods = {"_check_momentum": ValidationMetadata(...)}
    """
    validation_methods = {}

    # Iterate through all attributes of the instance's class
    for attr_name in dir(instance):
        # Skip private attributes that aren't validation methods
        if attr_name.startswith('__'):
            continue

        try:
            attr = getattr(instance, attr_name)

            # Check if this attribute is a validation check
            # Must be callable and have the validation marker
            if not callable(attr):
                continue

            if not hasattr(attr, '_is_validation_check'):
                continue

            if not attr._is_validation_check:
                continue

            # Verify it has valid metadata
            if not hasattr(attr, '_validation_metadata'):
                continue

            metadata = attr._validation_metadata

            # Ensure metadata is a ValidationMetadata instance, not a Mock
            if not isinstance(metadata, ValidationMetadata):
                continue

            validation_methods[metadata.method_name] = metadata

        except (AttributeError, TypeError):
            # Skip attributes that can't be accessed or cause errors
            continue

    return validation_methods


def auto_register_validations(instance: object) -> None:
    """
    Automatically register all decorated validation methods in a strategy instance.
    
    This function should be called during strategy initialization (typically in __init__)
    to automatically populate the _validation_methods and _validation_abbreviations
    attributes based on decorated methods.
    
    Args:
        instance: Strategy instance (must have _validation_methods and _validation_abbreviations)
    
    Example:
        class MyStrategy(BaseStrategy):
            def __init__(self, ...):
                super().__init__(...)
                
                # Automatically discover and register validation methods
                auto_register_validations(self)
    """
    # Get all validation methods
    methods = get_validation_methods(instance)
    
    # Sort by order
    sorted_methods = sorted(methods.values(), key=lambda m: m.order)
    
    # Populate _validation_methods list
    if hasattr(instance, '_validation_methods'):
        instance._validation_methods = [m.method_name for m in sorted_methods]
    
    # Populate _validation_abbreviations dict
    if hasattr(instance, '_validation_abbreviations'):
        instance._validation_abbreviations = {
            m.method_name: m.abbreviation
            for m in sorted_methods
            if m.abbreviation  # Only include if abbreviation is provided
        }

