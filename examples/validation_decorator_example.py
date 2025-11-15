"""
Example demonstrating the use of @validation_check decorator.

This example shows three approaches to using validation in strategies:
1. Manual registration (existing pattern)
2. Automatic registration with decorator
3. Hybrid approach (decorator + manual override)
"""
from typing import Dict, Any, Optional
from src.strategy.base_strategy import BaseStrategy, ValidationResult
from src.strategy.validation_decorator import (
    validation_check,
    auto_register_validations,
    get_validation_methods
)


# ============================================================================
# APPROACH 1: Manual Registration (Existing Pattern)
# ============================================================================
class ManualValidationStrategy(BaseStrategy):
    """Strategy using manual validation registration (existing pattern)"""
    
    def __init__(self, symbol, connector, order_manager, risk_manager, 
                 trade_manager, indicators, position_sizer=None, **kwargs):
        super().__init__(symbol, connector, order_manager, risk_manager,
                        trade_manager, indicators, position_sizer, **kwargs)
        
        # Manually configure validation methods (existing pattern)
        self._validation_methods = [
            "_check_momentum_strength",
            "_check_volume_confirmation",
            "_check_spread_filter"
        ]
        
        # Manually configure abbreviations
        self._validation_abbreviations = {
            "_check_momentum_strength": "M",
            "_check_volume_confirmation": "V",
            "_check_spread_filter": "S"
        }
    
    def initialize(self) -> bool:
        self.is_initialized = True
        return True
    
    def on_tick(self):
        return None
    
    def _check_momentum_strength(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """Check momentum strength"""
        return ValidationResult(
            passed=True,
            method_name="_check_momentum_strength",
            reason="Momentum OK"
        )
    
    def _check_volume_confirmation(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """Check volume confirmation"""
        return ValidationResult(
            passed=True,
            method_name="_check_volume_confirmation",
            reason="Volume OK"
        )
    
    def _check_spread_filter(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """Check spread filter"""
        return ValidationResult(
            passed=True,
            method_name="_check_spread_filter",
            reason="Spread OK"
        )


# ============================================================================
# APPROACH 2: Automatic Registration with Decorator
# ============================================================================
class AutoValidationStrategy(BaseStrategy):
    """Strategy using automatic validation registration with decorator"""
    
    def __init__(self, symbol, connector, order_manager, risk_manager,
                 trade_manager, indicators, position_sizer=None, **kwargs):
        super().__init__(symbol, connector, order_manager, risk_manager,
                        trade_manager, indicators, position_sizer, **kwargs)
        
        # Automatically discover and register validation methods
        auto_register_validations(self)
        
        # Validation mode can still be set manually
        self._validation_mode = "all"
    
    def initialize(self) -> bool:
        self.is_initialized = True
        return True
    
    def on_tick(self):
        return None
    
    @validation_check(abbreviation="M", order=1, description="Check momentum strength")
    def _check_momentum_strength(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """Check if momentum exceeds threshold"""
        return ValidationResult(
            passed=True,
            method_name="_check_momentum_strength",
            reason="Momentum OK"
        )
    
    @validation_check(abbreviation="V", order=2, description="Check volume confirmation")
    def _check_volume_confirmation(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """Check if volume exceeds average"""
        return ValidationResult(
            passed=True,
            method_name="_check_volume_confirmation",
            reason="Volume OK"
        )
    
    @validation_check(abbreviation="S", order=3, description="Check spread filter")
    def _check_spread_filter(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """Check if spread is acceptable"""
        return ValidationResult(
            passed=True,
            method_name="_check_spread_filter",
            reason="Spread OK"
        )


# ============================================================================
# APPROACH 3: Hybrid (Decorator + Manual Override)
# ============================================================================
class HybridValidationStrategy(BaseStrategy):
    """Strategy using decorator but with manual override capability"""
    
    def __init__(self, symbol, connector, order_manager, risk_manager,
                 trade_manager, indicators, position_sizer=None, 
                 enable_divergence: bool = False, **kwargs):
        super().__init__(symbol, connector, order_manager, risk_manager,
                        trade_manager, indicators, position_sizer, **kwargs)
        
        # Start with auto-registration
        auto_register_validations(self)
        
        # Conditionally add/remove validations based on config
        if enable_divergence:
            self._validation_methods.append("_check_divergence")
            self._validation_abbreviations["_check_divergence"] = "DIV"
        
        # Can also remove validations
        # if not some_condition:
        #     self._validation_methods.remove("_check_spread_filter")
    
    def initialize(self) -> bool:
        self.is_initialized = True
        return True
    
    def on_tick(self):
        return None
    
    @validation_check(abbreviation="M", order=1)
    def _check_momentum_strength(self, signal_data: Dict[str, Any]) -> ValidationResult:
        return ValidationResult(passed=True, method_name="_check_momentum_strength", reason="OK")
    
    @validation_check(abbreviation="V", order=2)
    def _check_volume_confirmation(self, signal_data: Dict[str, Any]) -> ValidationResult:
        return ValidationResult(passed=True, method_name="_check_volume_confirmation", reason="OK")
    
    # This method is NOT decorated, so it won't be auto-registered
    # It can be added manually in __init__ based on config
    def _check_divergence(self, signal_data: Dict[str, Any]) -> ValidationResult:
        return ValidationResult(passed=True, method_name="_check_divergence", reason="OK")

