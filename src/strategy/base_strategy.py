"""
Base strategy interface for all trading strategies.

Defines the common interface that all strategies must implement,
following the Liskov Substitution Principle - all strategies are
interchangeable through this base interface.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Literal, List, Callable, Tuple
from datetime import datetime
from dataclasses import dataclass

from src.models.data_models import TradeSignal, SymbolCategory, SymbolParameters
from src.core.mt5_connector import MT5Connector
from src.execution.order_manager import OrderManager
from src.execution.trade_manager import TradeManager
from src.indicators.technical_indicators import TechnicalIndicators
from src.models.models import PositionType
from src.risk.risk_manager import RiskManager
from src.risk.position_sizing.base_position_sizer import BasePositionSizer
from src.utils.logger import get_logger


@dataclass
class ValidationResult:
    """Result of a single validation check"""
    passed: bool
    method_name: str
    reason: str = ""


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    
    All strategies must implement this interface to be compatible
    with the strategy factory and trading controller.
    
    Principles:
    - Single Responsibility: Each strategy handles only its own logic
    - Open/Closed: New strategies can be added without modifying this base
    - Liskov Substitution: All strategies are interchangeable
    - Interface Segregation: Only essential methods required
    - Dependency Injection: Dependencies passed via constructor
    """

    def __init__(self, symbol: str, connector: MT5Connector,
                 order_manager: OrderManager, risk_manager: RiskManager,
                 trade_manager: TradeManager, indicators: TechnicalIndicators,
                 position_sizer: Optional[BasePositionSizer] = None,
                 **kwargs):
        """
        Initialize base strategy.

        Args:
            symbol: Trading symbol
            connector: MT5 connector instance
            order_manager: Order manager instance
            risk_manager: Risk manager instance
            trade_manager: Trade manager instance
            indicators: Technical indicators instance
            position_sizer: Position sizing plugin (optional, defaults to fixed sizing)
            **kwargs: Additional strategy-specific parameters
        """
        self.kwargs = kwargs
        self.symbol = symbol
        self.connector = connector
        self.order_manager = order_manager
        self.risk_manager = risk_manager
        self.trade_manager = trade_manager
        self.indicators = indicators
        self.position_sizer = position_sizer
        self.logger = get_logger()
        self.key = "base_strategy"
        # Common state
        self.is_initialized = False
        self.category: Optional[SymbolCategory] = None
        self.symbol_params: Optional[SymbolParameters] = None

        # Validation system - extensible registry of validation methods
        # Subclasses can override this to add/remove validation methods
        self._validation_methods: List[str] = []
        # Whether all validations must pass (AND) or at least one (OR)
        self._validation_mode: Literal["all", "any"] = "all"

        # Validation tracking - stores most recent validation results
        self._last_validation_results: List[ValidationResult] = []

        # Validation abbreviations - maps method names to short codes for comments
        # Subclasses should override this to define their own abbreviations
        # Example: {"_check_momentum_strength": "M", "_check_volume": "V"}
        self._validation_abbreviations: Dict[str, str] = {}

    @abstractmethod
    def initialize(self) -> bool:
        """
        Initialize the strategy.
        
        This method should:
        - Detect symbol category
        - Load/create symbol parameters
        - Initialize any strategy-specific components
        - Perform any required setup
        
        Returns:
            True if initialization successful, False otherwise
        """
        pass

    @abstractmethod
    def on_tick(self) -> Optional[TradeSignal]:
        """
        Main strategy execution logic called on each tick/iteration.
        
        This method should:
        - Analyze market conditions
        - Check for trade signals
        - Apply filters and validations
        - Return trade signal if conditions met
        
        Returns:
            TradeSignal if signal detected, None otherwise
        """
        pass

    @abstractmethod
    def on_position_closed(self, symbol: str, profit: float, volume: float, comment: str) -> None:
        """
        Handle position closure event.
        
        This method should:
        - Update strategy state based on trade result
        - Adjust position sizing if using martingale/progression
        - Update performance tracking
        - Log trade results
        
        Args:
            symbol: Symbol of closed position
            profit: Profit/loss of closed position
            volume: Volume of closed position
            comment: Comment of closed position
        """
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """
        Get current strategy status.
        
        Returns:
            Dictionary containing strategy status information:
            - is_initialized: bool
            - category: str
            - last_signal_time: datetime or None
            - active_positions: int
            - strategy_specific_metrics: Any
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """
        Cleanup and shutdown the strategy.
        
        This method should:
        - Save any persistent state
        - Close any open resources
        - Log shutdown information
        """
        pass

    def get_strategy_name(self) -> str:
        """
        Get the strategy name.
        
        Returns:
            Strategy class name
        """
        return self.__class__.__name__

    def get_symbol(self) -> str:
        """
        Get the trading symbol.
        
        Returns:
            Symbol name
        """
        return self.symbol

    def is_ready(self) -> bool:
        """
        Check if strategy is ready to trade.

        Returns:
            True if initialized and ready
        """
        return self.is_initialized

    def get_lot_size(self) -> float:
        """
        Get the lot size for the next trade from the position sizer.

        Returns:
            Lot size to use for next trade
        """
        if self.position_sizer is not None and self.position_sizer.is_enabled():
            return self.position_sizer.calculate_lot_size()
        else:
            # Fallback to risk manager if no position sizer
            self.logger.warning(
                f"No position sizer configured for {self.symbol}, using risk manager default",
                self.symbol
            )
            return 0.0  # Strategy should handle this case

    def generate_trade_comment(self,direction: Literal[PositionType.BUY, PositionType.SELL]) -> str:
        """
        Generate informative trade comment based on signal details.

        This method is now fully dynamic, using properties from the TradeSignal
        object to determine strategy type, confirmations, and range information.
        No hardcoded mappings or conditional logic required.

        Args:
            direction: PositionType enum representing the direction of the trade (BUY or SELL)

        Returns:
            Formatted comment string (max 31 characters for MT5)

        Format: "{strategy}|{range_id}|{direction}|{confirmations}"
        Examples:
            - "TB|15M_1M|sell|N" - True Breakout SELL, 15M/1M range, no confirmations
            - "FB|4H_5M|buy|V" - False Breakout BUY, 4H/5M range, volume confirmation
            - "HFT|buy|MV" - HFT Momentum BUY, momentum+volume (no range)
        """

        # Extract direction value from enum and convert to lowercase
        direction_str = direction.value if isinstance(direction, PositionType) else str(direction)
        direction_str = direction_str.lower()

        # Build comment based on strategy type
        # self.key format for TB/FB: "TB|15M_1M" or "FB|4H_5M"
        # self.key format for HFT: "HFT"
        confirmations = self.get_validations_for_comment()

        comment = f"{self.key}|{direction_str}|{confirmations}"

        # MT5 has a 31 character limit for comments
        if len(comment) > 31:
            comment = comment[:31]

        return comment

    def get_validations_for_comment(self, format: str = "compact") -> str:
        """
        Get a compact string representation of validation results for MT5 trade comments.

        This method generates a string based on the most recent validation results,
        suitable for inclusion in MT5 trade comments (31 character limit).

        Formats:
        - "compact": Only show abbreviations of passed validations (e.g., "MVT")
        - "detailed": Show all validations with pass/fail indicators (e.g., "M+V+T-A-")
        - "all": Show all configured validations regardless of pass/fail (e.g., "MVTAS")

        Args:
            format: Output format - "compact" (default), "detailed", or "all"

        Returns:
            String representation of validation results:
            - "NC" if no validations were configured or executed
            - Abbreviated validation codes based on format

        Examples:
            - "MVT" (compact) = Momentum, Volume, Trend passed
            - "M+V+T-A-S+" (detailed) = Shows pass/fail for each
            - "MVTAS" (all) = All 5 validations were checked

        Note:
            Subclasses should define `_validation_abbreviations` dict to map
            validation method names to short codes.
        """
        # Return "NC" if no validations configured or no results available
        if not self._validation_methods or not self._last_validation_results:
            return "NC"

        result_parts = []

        if format == "compact":
            # Only show abbreviations of validations that passed
            for validation_result in self._last_validation_results:
                if validation_result.passed:
                    abbrev = self._validation_abbreviations.get(
                        validation_result.method_name,
                        validation_result.method_name[0].upper()  # Fallback to first letter
                    )
                    result_parts.append(abbrev)

            # Return "NC" if no validations passed
            return "".join(result_parts) if result_parts else "NC"

        elif format == "detailed":
            # Show all validations with pass/fail indicators
            for validation_result in self._last_validation_results:
                abbrev = self._validation_abbreviations.get(
                    validation_result.method_name,
                    validation_result.method_name[0].upper()
                )
                indicator = "+" if validation_result.passed else "-"
                result_parts.append(f"{abbrev}{indicator}")

            return "".join(result_parts) if result_parts else "NC"

        elif format == "all":
            # Show all configured validations (from results, not just passed ones)
            for validation_result in self._last_validation_results:
                abbrev = self._validation_abbreviations.get(
                    validation_result.method_name,
                    validation_result.method_name[0].upper()
                )
                result_parts.append(abbrev)

            return "".join(result_parts) if result_parts else "NC"

        else:
            self.logger.warning(
                f"Invalid format '{format}' for get_validations_for_comment, using 'compact'",
                self.symbol
            )
            return self.get_validations_for_comment(format="compact")

    def _validate_signal(self, signal_data: Dict[str, Any]) -> Tuple[bool, List[ValidationResult]]:
        """
        Validate a trading signal through a dynamic, extensible confirmation system.

        This method iterates through the configured validation methods registry,
        calls each validation method dynamically, and aggregates the results.

        Design:
        - Uses getattr() for dynamic method invocation
        - Handles missing methods gracefully (logs warning and skips)
        - Supports both AND (all must pass) and OR (any must pass) logic
        - Returns detailed results for debugging and logging

        Args:
            signal_data: Dictionary containing all data needed for validation.
                        Common keys might include:
                        - 'signal_direction': int (1 for BUY, -1 for SELL)
                        - 'recent_ticks': List[TickData]
                        - 'current_price': float
                        - Any other strategy-specific data

        Returns:
            Tuple of (is_valid, validation_results):
            - is_valid: bool - Whether the signal passed validation
            - validation_results: List[ValidationResult] - Detailed results from each check

        Example usage in subclass:
            signal_data = {
                'signal_direction': 1,
                'recent_ticks': self.tick_buffer[-10:],
                'current_price': 1.2345
            }
            is_valid, results = self._validate_signal(signal_data)
            if not is_valid:
                self.logger.debug(f"Signal rejected: {[r.reason for r in results if not r.passed]}")
                return None
        """
        validation_results: List[ValidationResult] = []

        # If no validation methods configured, signal is valid by default
        if not self._validation_methods:
            self.logger.debug(
                f"No validation methods configured for {self.get_strategy_name()}, signal passes by default",
                self.symbol
            )
            return True, validation_results

        # Iterate through each validation method
        for method_name in self._validation_methods:
            try:
                # Get the method dynamically using getattr
                validation_method = getattr(self, method_name, None)

                # Check if method exists
                if validation_method is None:
                    self.logger.warning(
                        f"Validation method '{method_name}' not found in {self.get_strategy_name()}, skipping",
                        self.symbol
                    )
                    # Create a result indicating the method was skipped
                    validation_results.append(ValidationResult(
                        passed=True,  # Don't fail the signal due to missing method
                        method_name=method_name,
                        reason=f"Method not found, skipped"
                    ))
                    continue

                # Check if it's callable
                if not callable(validation_method):
                    self.logger.warning(
                        f"Validation method '{method_name}' is not callable in {self.get_strategy_name()}, skipping",
                        self.symbol
                    )
                    validation_results.append(ValidationResult(
                        passed=True,
                        method_name=method_name,
                        reason=f"Not callable, skipped"
                    ))
                    continue

                # Call the validation method with signal_data
                # The method should return a bool or ValidationResult
                result = validation_method(signal_data)

                # Handle different return types
                if isinstance(result, ValidationResult):
                    validation_results.append(result)
                elif isinstance(result, bool):
                    validation_results.append(ValidationResult(
                        passed=result,
                        method_name=method_name,
                        reason="Passed" if result else "Failed"
                    ))
                else:
                    self.logger.warning(
                        f"Validation method '{method_name}' returned unexpected type {type(result)}, treating as False",
                        self.symbol
                    )
                    validation_results.append(ValidationResult(
                        passed=False,
                        method_name=method_name,
                        reason=f"Invalid return type: {type(result)}"
                    ))

            except Exception as e:
                self.logger.error(
                    f"Error executing validation method '{method_name}': {e}",
                    self.symbol
                )
                validation_results.append(ValidationResult(
                    passed=False,
                    method_name=method_name,
                    reason=f"Exception: {str(e)}"
                ))

        # Aggregate results based on validation mode
        if self._validation_mode == "all":
            # All validations must pass (AND logic)
            is_valid = all(result.passed for result in validation_results)
        elif self._validation_mode == "any":
            # At least one validation must pass (OR logic)
            is_valid = any(result.passed for result in validation_results)
        else:
            self.logger.error(
                f"Invalid validation mode '{self._validation_mode}', defaulting to 'all'",
                self.symbol
            )
            is_valid = all(result.passed for result in validation_results)

        # Store validation results for later use (e.g., in trade comments)
        self._last_validation_results = validation_results

        # Log validation summary
        if is_valid:
            self.logger.debug(
                f"✓ Signal passed validation ({len([r for r in validation_results if r.passed])}/{len(validation_results)} checks)",
                self.symbol
            )
        else:
            failed_checks = [r for r in validation_results if not r.passed]
            self.logger.debug(
                f"✗ Signal failed validation: {', '.join([f'{r.method_name}: {r.reason}' for r in failed_checks])}",
                self.symbol
            )

        return is_valid, validation_results

