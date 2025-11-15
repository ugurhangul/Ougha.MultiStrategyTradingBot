"""
Example: Refactoring HFTMomentumStrategy to use @validation_check decorator

This example shows how to refactor the existing HFTMomentumStrategy
from manual validation registration to automatic registration using
the @validation_check decorator.

BEFORE: Manual registration (lines 132-152 in hft_momentum_strategy.py)
AFTER: Automatic registration with decorator (shown below)
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from src.strategy.base_strategy import BaseStrategy, ValidationResult
from src.strategy.validation_decorator import validation_check, auto_register_validations
from src.core.mt5_connector import MT5Connector
from src.execution.order_manager import OrderManager
from src.execution.trade_manager import TradeManager
from src.risk.risk_manager import RiskManager
from src.indicators.technical_indicators import TechnicalIndicators


class HFTMomentumStrategyRefactored(BaseStrategy):
    """
    HFT Momentum Strategy - Refactored with @validation_check decorator
    
    This version uses automatic validation registration instead of manual.
    
    Benefits:
    1. No need to manually maintain _validation_methods list
    2. No need to manually maintain _validation_abbreviations dict
    3. Validation order is explicit in decorator parameters
    4. Self-documenting code with descriptions
    5. Easier to add/remove validations
    """
    
    def __init__(self, symbol: str, connector: MT5Connector,
                 order_manager: OrderManager, risk_manager: RiskManager,
                 trade_manager: TradeManager, indicators: TechnicalIndicators,
                 position_sizer=None, **kwargs):
        """Initialize HFT Momentum strategy with automatic validation registration"""
        
        super().__init__(
            symbol=symbol,
            connector=connector,
            order_manager=order_manager,
            risk_manager=risk_manager,
            trade_manager=trade_manager,
            indicators=indicators,
            position_sizer=position_sizer,
            **kwargs
        )
        
        # BEFORE (Manual Registration):
        # self._validation_methods = [
        #     "_check_momentum_strength",
        #     "_check_volume_confirmation",
        #     "_check_volatility_filter",
        #     "_check_trend_alignment",
        #     "_check_spread_filter"
        # ]
        # self._validation_abbreviations = {
        #     "_check_momentum_strength": "M",
        #     "_check_volume_confirmation": "V",
        #     "_check_volatility_filter": "A",
        #     "_check_trend_alignment": "T",
        #     "_check_spread_filter": "S"
        # }
        
        # AFTER (Automatic Registration):
        # Single line replaces all manual registration above!
        auto_register_validations(self)
        
        # Validation mode can still be set manually
        self._validation_mode = "all"
        
        self.logger.info(f"HFT Momentum Strategy initialized for {symbol}", symbol)
    
    def initialize(self) -> bool:
        """Initialize the strategy"""
        self.is_initialized = True
        return True
    
    def on_tick(self):
        """Main strategy logic"""
        return None
    
    def on_position_closed(self, symbol: str, profit: float, volume: float, comment: str) -> None:
        """Handle position closure"""
        pass
    
    def get_status(self) -> Dict[str, Any]:
        """Get strategy status"""
        return {"initialized": self.is_initialized}
    
    def shutdown(self) -> None:
        """Cleanup"""
        pass
    
    # ========================================================================
    # VALIDATION METHODS - Now with @validation_check decorator
    # ========================================================================
    
    @validation_check(
        abbreviation="M",
        order=1,
        description="Check if momentum strength exceeds minimum threshold"
    )
    def _check_momentum_strength(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if momentum strength exceeds minimum threshold.
        
        Order=1: Fast check, should run first
        """
        ticks = signal_data.get('recent_ticks', [])
        direction = signal_data.get('signal_direction', 0)
        
        if len(ticks) < 2:
            return ValidationResult(
                passed=False,
                method_name="_check_momentum_strength",
                reason="Insufficient tick data"
            )
        
        # Simplified momentum check for example
        momentum = abs(ticks[-1].bid - ticks[0].bid)
        min_strength = 0.0001  # Example threshold
        passed = momentum >= min_strength
        
        return ValidationResult(
            passed=passed,
            method_name="_check_momentum_strength",
            reason=f"Momentum {momentum:.5f} {'≥' if passed else '<'} {min_strength:.5f}"
        )
    
    @validation_check(
        abbreviation="V",
        order=2,
        description="Check if volume exceeds average"
    )
    def _check_volume_confirmation(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if recent volume exceeds average.
        
        Order=2: Medium speed, requires candle data
        """
        # Simplified volume check for example
        volume = signal_data.get('volume', 0)
        avg_volume = signal_data.get('avg_volume', 1)
        min_multiplier = 1.5
        
        passed = volume > avg_volume * min_multiplier
        
        return ValidationResult(
            passed=passed,
            method_name="_check_volume_confirmation",
            reason=f"Volume ratio {volume/avg_volume:.2f}"
        )
    
    @validation_check(
        abbreviation="A",
        order=3,
        description="Check if volatility is within acceptable range"
    )
    def _check_volatility_filter(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if current volatility (ATR) is within acceptable range.
        
        Order=3: Slower, requires ATR calculation
        """
        # Simplified volatility check for example
        atr = signal_data.get('atr', 0)
        max_atr = 0.01
        
        passed = atr <= max_atr
        
        return ValidationResult(
            passed=passed,
            method_name="_check_volatility_filter",
            reason=f"ATR {atr:.5f} {'≤' if passed else '>'} {max_atr:.5f}"
        )
    
    @validation_check(
        abbreviation="T",
        order=4,
        description="Check if signal aligns with higher timeframe trend"
    )
    def _check_trend_alignment(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if signal aligns with higher timeframe trend.
        
        Order=4: Requires additional candle data
        """
        # Simplified trend check for example
        signal_direction = signal_data.get('signal_direction', 0)
        trend_direction = signal_data.get('trend_direction', 0)
        
        passed = signal_direction == trend_direction
        
        return ValidationResult(
            passed=passed,
            method_name="_check_trend_alignment",
            reason=f"Signal {'aligned' if passed else 'not aligned'} with trend"
        )
    
    @validation_check(
        abbreviation="S",
        order=5,
        description="Check if spread is acceptable"
    )
    def _check_spread_filter(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if spread is acceptable.
        
        Order=5: Fast check, but less critical than momentum
        """
        # Simplified spread check for example
        spread = signal_data.get('spread', 0)
        max_spread = 10  # pips
        
        passed = spread <= max_spread
        
        return ValidationResult(
            passed=passed,
            method_name="_check_spread_filter",
            reason=f"Spread {spread} {'≤' if passed else '>'} {max_spread}"
        )


# ============================================================================
# COMPARISON: Lines of Code
# ============================================================================
# 
# BEFORE (Manual Registration):
# - _validation_methods list: 7 lines
# - _validation_abbreviations dict: 7 lines
# - Total: 14 lines of boilerplate
# 
# AFTER (Automatic Registration):
# - auto_register_validations(self): 1 line
# - Decorators on methods: 4 lines each (but self-documenting)
# - Total: 1 line of boilerplate
# 
# BENEFITS:
# 1. Reduced boilerplate: 14 lines → 1 line
# 2. Self-documenting: Order and abbreviations are next to the method
# 3. Type-safe: Can't misspell method names in decorator
# 4. Easier maintenance: Add/remove validations by adding/removing decorator
# 5. Better IDE support: Jump to definition works from decorator
# ============================================================================

