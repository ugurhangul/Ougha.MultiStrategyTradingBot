"""
Strategy factory for dynamic strategy loading and registration.

Implements the Factory pattern with plugin registration system,
allowing strategies to be loaded dynamically based on configuration.

Principles:
- Open/Closed: New strategies can be registered without modifying factory
- Dependency Injection: Factory creates strategies with required dependencies
- Single Responsibility: Factory only handles strategy creation
"""
from typing import Dict, Type, Optional, Any, List
from dataclasses import dataclass

from src.strategy.base_strategy import BaseStrategy
from src.core.mt5_connector import MT5Connector
from src.execution.order_manager import OrderManager
from src.execution.trade_manager import TradeManager
from src.indicators.technical_indicators import TechnicalIndicators
from src.risk.risk_manager import RiskManager
from src.risk.position_sizing import create_position_sizer
from src.strategy.symbol_performance_persistence import SymbolPerformancePersistence
from src.utils.logger import get_logger
from src.config import config


@dataclass
class StrategyMetadata:
    """Metadata for a registered strategy"""
    strategy_class: Type[BaseStrategy]
    name: str
    description: str
    enabled_by_default: bool = False
    requires_tick_data: bool = False


class StrategyRegistry:
    """
    Registry for available strategies.

    Strategies can register themselves using the @register_strategy decorator
    or by calling register() directly.
    """

    _strategies: Dict[str, StrategyMetadata] = {}

    @classmethod
    def register(cls, name: str, strategy_class: Type[BaseStrategy],
                description: str = "", enabled_by_default: bool = False,
                requires_tick_data: bool = False) -> None:
        """
        Register a strategy.

        Args:
            name: Unique strategy identifier
            strategy_class: Strategy class (must inherit from BaseStrategy)
            description: Strategy description
            key: Unique key for the strategy
            enabled_by_default: Whether strategy is enabled by default
            requires_tick_data: Whether strategy requires tick-level data
        """
        if not issubclass(strategy_class, BaseStrategy):
            raise ValueError(f"Strategy {name} must inherit from BaseStrategy")

        metadata = StrategyMetadata(
            strategy_class=strategy_class,
            name=name,
            description=description,
            enabled_by_default=enabled_by_default,
            requires_tick_data=requires_tick_data
        )

        cls._strategies[name] = metadata
        logger = get_logger()
        logger.info(f"Registered strategy: {name} ({strategy_class.__name__})")

    @classmethod
    def get(cls, name: str) -> Optional[StrategyMetadata]:
        """Get strategy metadata by name"""
        return cls._strategies.get(name)

    @classmethod
    def list_all(cls) -> List[str]:
        """List all registered strategy names"""
        return list(cls._strategies.keys())

    @classmethod
    def list_enabled(cls) -> List[str]:
        """List strategies enabled by default"""
        return [name for name, meta in cls._strategies.items() if meta.enabled_by_default]

    @classmethod
    def clear(cls) -> None:
        """Clear all registered strategies (mainly for testing)"""
        cls._strategies.clear()


def register_strategy(name: str, description: str = "",key: str = "",
                     enabled_by_default: bool = False,
                     requires_tick_data: bool = False):
    """
    Decorator for registering strategies.

    Usage:
        @register_strategy("my_strategy", description="My custom strategy")
        class MyStrategy(BaseStrategy):
            ...

    Args:
        name: Unique strategy identifier
        description: Strategy description
        enabled_by_default: Whether strategy is enabled by default
        requires_tick_data: Whether strategy requires tick-level data
    """
    def decorator(strategy_class: Type[BaseStrategy]):
        StrategyRegistry.register(
            name=name,
            strategy_class=strategy_class,
            description=description,
            enabled_by_default=enabled_by_default,
            requires_tick_data=requires_tick_data
        )
        return strategy_class
    return decorator


class StrategyFactory:
    """
    Factory for creating strategy instances.

    Handles dependency injection and strategy instantiation based on
    configuration and registration.
    """

    def __init__(self, connector: MT5Connector, order_manager: OrderManager,
                 risk_manager: RiskManager, trade_manager: TradeManager,
                 indicators: TechnicalIndicators,
                 symbol_persistence: Optional[SymbolPerformancePersistence] = None):
        """
        Initialize strategy factory.

        Args:
            connector: MT5 connector instance
            order_manager: Order manager instance
            risk_manager: Risk manager instance
            trade_manager: Trade manager instance
            indicators: Technical indicators instance
            symbol_persistence: Symbol performance persistence (optional)
        """
        self.connector = connector
        self.order_manager = order_manager
        self.risk_manager = risk_manager
        self.trade_manager = trade_manager
        self.indicators = indicators
        self.symbol_persistence = symbol_persistence
        self.logger = get_logger()

    def create_strategy(self, strategy_name: str, symbol: str,
                       position_sizer_name: Optional[str] = None,
                       **kwargs) -> Optional[BaseStrategy]:
        """
        Create a strategy instance.

        Args:
            strategy_name: Name of registered strategy
            symbol: Trading symbol
            position_sizer_name: Name of position sizer to use (optional, uses config default)
            **kwargs: Additional strategy-specific parameters

        Returns:
            Strategy instance or None if strategy not found
        """
        metadata = StrategyRegistry.get(strategy_name)
        if metadata is None:
            self.logger.error(f"Strategy '{strategy_name}' not found in registry")
            return None

        try:
            # Determine position sizer name from config if not provided
            if position_sizer_name is None:
                position_sizer_name = self._get_position_sizer_for_strategy(strategy_name)

            # Create position sizer
            position_sizer = self._create_position_sizer(position_sizer_name, symbol, **kwargs)

            # Create strategy with dependency injection
            strategy = metadata.strategy_class(
                symbol=symbol,
                connector=self.connector,
                order_manager=self.order_manager,
                risk_manager=self.risk_manager,
                trade_manager=self.trade_manager,
                indicators=self.indicators,
                position_sizer=position_sizer,
                symbol_persistence=self.symbol_persistence,
                **kwargs
            )

            self.logger.info(
                f"Created strategy '{strategy_name}' for {symbol} "
                f"with position sizer '{position_sizer_name}'"
            )
            return strategy

        except Exception as e:
            self.logger.error(f"Failed to create strategy '{strategy_name}': {e}")
            return None

    def _get_position_sizer_for_strategy(self, strategy_name: str) -> str:
        """
        Get the position sizer name for a strategy from configuration.

        Args:
            strategy_name: Strategy name

        Returns:
            Position sizer name
        """
        # Map strategy names to config attributes
        sizer_map = {
            'true_breakout': config.strategy_enable.true_breakout_position_sizer,
            'fakeout': config.strategy_enable.fakeout_position_sizer,
            'hft_momentum': config.strategy_enable.hft_momentum_position_sizer
        }

        return sizer_map.get(strategy_name, 'fixed')  # Default to fixed

    def _create_position_sizer(self, sizer_name: str, symbol: str, **kwargs):
        """
        Create a position sizer instance.

        Args:
            sizer_name: Position sizer name
            symbol: Trading symbol
            **kwargs: Additional parameters for position sizer

        Returns:
            Position sizer instance or None
        """
        # Extract martingale-specific parameters from config if needed
        if sizer_name == 'martingale':
            from src.config.strategies import MartingaleType

            # Map string to enum
            martingale_type_map = {
                'classic_multiplier': MartingaleType.CLASSIC_MULTIPLIER,
                'multiplier_with_sum': MartingaleType.MULTIPLIER_WITH_SUM,
                'sum_with_initial': MartingaleType.SUM_WITH_INITIAL
            }

            martingale_type = martingale_type_map.get(
                config.hft_momentum.martingale_type,
                MartingaleType.CLASSIC_MULTIPLIER
            )

            # Create martingale position sizer with config parameters
            position_sizer = create_position_sizer(
                sizer_name,
                symbol=symbol,
                connector=self.connector,
                martingale_type=martingale_type,
                multiplier=config.hft_momentum.martingale_multiplier,
                max_orders_per_round=config.hft_momentum.max_orders_per_round,
                max_consecutive_losses=config.hft_momentum.max_consecutive_losses,
                enable_loss_protection=config.hft_momentum.enable_consecutive_loss_protection,
                max_lot_size=config.hft_momentum.max_lot_size
            )
        elif sizer_name == 'pattern_based':
            # Create pattern-based position sizer with connector and execution timeframe
            # Extract execution_timeframe from strategy config if available
            execution_timeframe = 'M1'  # Default

            if 'config' in kwargs:
                strategy_config = kwargs.get('config')
                # Extract execution timeframe from range_config.breakout_timeframe
                if hasattr(strategy_config, 'range_config') and strategy_config.range_config:
                    execution_timeframe = strategy_config.range_config.breakout_timeframe

            position_sizer = create_position_sizer(
                sizer_name,
                symbol=symbol,
                connector=self.connector,
                execution_timeframe=execution_timeframe
            )
        else:
            # Create fixed position sizer (or other types)
            position_sizer = create_position_sizer(sizer_name, symbol=symbol)

        return position_sizer


    def create_strategies_for_symbol(self, symbol: str,
                                    enabled_strategies: List[str]) -> List[BaseStrategy]:
        """
        Create multiple strategy instances for a symbol.

        Args:
            symbol: Trading symbol
            enabled_strategies: List of strategy names to create

        Returns:
            List of created strategy instances
        """
        strategies = []

        for strategy_name in enabled_strategies:
            strategy = self.create_strategy(strategy_name, symbol)
            if strategy is not None:
                strategies.append(strategy)

        return strategies

    def get_available_strategies(self) -> List[str]:
        """
        Get list of all available (registered) strategies.

        Returns:
            List of strategy names
        """
        return StrategyRegistry.list_all()

    def get_enabled_strategies(self) -> List[str]:
        """
        Get list of strategies enabled by default.

        Returns:
            List of strategy names
        """
        return StrategyRegistry.list_enabled()

