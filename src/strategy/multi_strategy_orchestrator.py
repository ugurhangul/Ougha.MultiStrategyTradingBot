"""
Multi-Strategy Orchestrator - Manages multiple plugin-based strategies per symbol.

This orchestrator allows running multiple strategies simultaneously on the same symbol:
- True Breakout (4H_5M and/or 15M_1M)
- Fakeout (4H_5M and/or 15M_1M)
- Martingale Pulse (HFT tick momentum)

Each strategy operates independently with its own state and signal generation.
"""
from typing import Dict, List, Optional
from datetime import datetime, timezone

from src.models.data_models import TradeSignal, SymbolCategory
from src.core.mt5_connector import MT5Connector
from src.execution.order_manager import OrderManager
from src.execution.trade_manager import TradeManager
from src.indicators.technical_indicators import TechnicalIndicators
from src.risk.risk_manager import RiskManager
from src.strategy.base_strategy import BaseStrategy
from src.strategy.strategy_factory import StrategyFactory
from src.strategy.symbol_performance_persistence import SymbolPerformancePersistence
from src.config import config
from src.config.symbols import SymbolOptimizer
from src.models.data_models import SymbolParameters
from src.utils.logger import get_logger
from src.utils.comment_parser import CommentParser

# Import strategy package to trigger @register_strategy decorator registration
import src.strategy  # noqa: F401


class MultiStrategyOrchestrator:
    """
    Orchestrates multiple plugin-based strategies for a single symbol.

    This replaces the old SymbolStrategy and HybridSymbolStrategy classes
    with a flexible plugin-based approach.
    """

    def __init__(self, symbol: str, connector: MT5Connector,
                 order_manager: OrderManager, risk_manager: RiskManager,
                 trade_manager: TradeManager, indicators: TechnicalIndicators,
                 symbol_persistence: Optional[SymbolPerformancePersistence] = None):
        """
        Initialize multi-strategy orchestrator.

        Args:
            symbol: Symbol name
            connector: MT5 connector instance
            order_manager: Order manager instance
            risk_manager: Risk manager instance
            trade_manager: Trade manager instance
            indicators: Technical indicators instance
            symbol_persistence: Symbol performance persistence instance (optional)
        """
        self.symbol = symbol
        self.connector = connector
        self.order_manager = order_manager
        self.risk_manager = risk_manager
        self.trade_manager = trade_manager
        self.indicators = indicators
        self.symbol_persistence = symbol_persistence
        self.logger = get_logger()

        # Get symbol category and parameters
        mt5_category = None
        symbol_info = connector.get_symbol_info(symbol)
        if symbol_info:
            mt5_category = symbol_info.get('category')

        self.category, self.symbol_params = SymbolOptimizer.get_symbol_parameters(
            symbol,
            SymbolParameters(),
            mt5_category=mt5_category
        )

        self.logger.info(
            f"Symbol category: {SymbolOptimizer.get_category_name(self.category)}",
            symbol
        )

        # Strategy instances
        self.strategies: Dict[str, BaseStrategy] = {}
        self.factory = StrategyFactory(
            connector=connector,
            order_manager=order_manager,
            risk_manager=risk_manager,
            trade_manager=trade_manager,
            indicators=indicators,
            symbol_persistence=symbol_persistence
        )

        self.is_initialized = False

    def initialize(self) -> bool:
        """
        Initialize all enabled strategies for this symbol.

        Returns:
            True if at least one strategy initialized successfully
        """
        self.logger.info("=" * 60, self.symbol)
        self.logger.info("Initializing Multi-Strategy Orchestrator", self.symbol)
        self.logger.info("=" * 60, self.symbol)

        enabled_strategies = []

        # Check which strategies are enabled
        if config.strategy_enable.true_breakout_enabled:
            # Add True Breakout strategies for enabled ranges
            if config.strategy_enable.range_4h5m_enabled:
                enabled_strategies.append(("true_breakout", "4H_5M"))
            if config.strategy_enable.range_15m1m_enabled:
                enabled_strategies.append(("true_breakout", "15M_1M"))

        if config.strategy_enable.fakeout_enabled:
            # Add Fakeout strategies for enabled ranges
            if config.strategy_enable.range_4h5m_enabled:
                enabled_strategies.append(("fakeout", "4H_5M"))
            if config.strategy_enable.range_15m1m_enabled:
                enabled_strategies.append(("fakeout", "15M_1M"))

        if config.strategy_enable.hft_momentum_enabled:
            # Add HFT Momentum strategy (no range_id)
            enabled_strategies.append(("hft_momentum", None))

        if not enabled_strategies:
            self.logger.warning(
                "No strategies enabled in configuration!",
                self.symbol
            )
            return False

        self.logger.info(
            f"Enabled strategies: {len(enabled_strategies)}",
            self.symbol
        )

        # Create and initialize each strategy
        success_count = 0

        for strategy_name, range_id in enabled_strategies:
            try:
                # Create unique key for this strategy instance
                if range_id:
                    strategy_key = f"{strategy_name}_{range_id}"
                else:
                    strategy_key = strategy_name

                # Create strategy instance
                kwargs = {}
                if range_id:
                    kwargs["range_id"] = range_id

                strategy = self.factory.create_strategy(
                    strategy_name=strategy_name,
                    symbol=self.symbol,
                    **kwargs
                )

                # Initialize strategy
                if strategy.initialize():
                    self.strategies[strategy_key] = strategy
                    success_count += 1

                    if range_id:
                        self.logger.info(
                            f"✓ {strategy_name} ({range_id}) initialized",
                            self.symbol
                        )
                    else:
                        self.logger.info(
                            f"✓ {strategy_name} initialized",
                            self.symbol
                        )
                else:
                    self.logger.warning(
                        f"✗ {strategy_name} ({range_id}) initialization failed",
                        self.symbol
                    )

            except Exception as e:
                self.logger.error(
                    f"Error creating {strategy_name} ({range_id}): {e}",
                    self.symbol
                )

        if success_count == 0:
            self.logger.error(
                "No strategies initialized successfully!",
                self.symbol
            )
            return False

        self.logger.info("=" * 60, self.symbol)
        self.logger.info(
            f"✓ {success_count}/{len(enabled_strategies)} strategies initialized",
            self.symbol
        )
        self.logger.info("=" * 60, self.symbol)

        self.is_initialized = True
        return True

    def on_tick(self):
        """
        Process tick event for all strategies.

        This is called every second by the trading controller.
        Each strategy processes the tick independently and may generate trade signals.
        Signals are executed immediately via the order manager.
        """
        if not self.is_initialized:
            return

        # Process each strategy
        for strategy_key, strategy in self.strategies.items():
            try:
                # Call strategy's on_tick and capture any trade signal
                signal = strategy.on_tick()

                # If strategy generated a signal, execute it
                if signal is not None:
                    self.logger.info(
                        f"Signal received from {strategy_key}: {signal.signal_type.value} @ {signal.entry_price:.5f}",
                        self.symbol
                    )

                    # Execute the signal via order manager
                    ticket = self.order_manager.execute_signal(signal)

                    if ticket:
                        self.logger.info(
                            f"✓ Signal executed successfully by {strategy_key} - Ticket: {ticket}",
                            self.symbol
                        )
                    else:
                        self.logger.warning(
                            f"✗ Signal execution failed for {strategy_key}",
                            self.symbol
                        )

            except Exception as e:
                self.logger.error(
                    f"Error in {strategy_key}.on_tick(): {e}",
                    self.symbol
                )

    def on_position_closed(self, symbol: str, profit: float,
                          volume: float, comment: str):
        """
        Handle position closure event.

        Routes the event to the appropriate strategy based on the comment.

        Args:
            symbol: Symbol name
            profit: Position profit/loss
            volume: Position volume
            comment: Position comment (contains strategy type and range_id)
        """
        if not self.is_initialized:
            return

        # Parse comment using CommentParser for robust parsing
        # Comment format: "TB|15M_1M|BV" or "FB|4H_5M|RT" or "HFT|MV"
        parsed = CommentParser.parse(comment)

        if parsed is None:
            self.logger.warning(
                f"Cannot parse comment for position closure: [{comment}]",
                symbol
            )
            return

        # Map strategy type to strategy name
        strategy_map = {
            'TB': 'true_breakout',
            'FB': 'fakeout',
            'HFT': 'hft_momentum',
            'MP': 'hft_momentum'  # Legacy support for old comments
        }

        strategy_name = strategy_map.get(parsed.strategy_type)
        if not strategy_name:
            self.logger.warning(
                f"Unknown strategy type in comment: {parsed.strategy_type}",
                symbol
            )
            return

        # Determine strategy key
        if parsed.strategy_type in ['TB', 'FB']:
            # Breakout strategies have range_id
            if not parsed.range_id:
                self.logger.warning(
                    f"Missing range_id for breakout strategy: {comment}",
                    symbol
                )
                return

            # Use normalized range_id (already has underscore: 4H_5M or 15M_1M)
            range_id = parsed.normalized_range_id

            strategy_key = f"{strategy_name}_{range_id}"
        else:
            # HFT Momentum has no range_id
            strategy_key = strategy_name

        # Notify the appropriate strategy
        strategy = self.strategies.get(strategy_key)
        if strategy:
            try:
                strategy.on_position_closed(symbol, profit, volume, comment)
            except Exception as e:
                self.logger.error(
                    f"Error in {strategy_key}.on_position_closed(): {e}",
                    symbol
                )
        else:
            self.logger.warning(
                f"Strategy not found for key: {strategy_key}",
                symbol
            )

    def get_status(self) -> Dict:
        """
        Get status of all strategies.

        Returns:
            Dictionary with status of each strategy
        """
        status = {
            "symbol": self.symbol,
            "category": SymbolOptimizer.get_category_name(self.category),
            "initialized": self.is_initialized,
            "strategies": {}
        }

        for strategy_key, strategy in self.strategies.items():
            try:
                status["strategies"][strategy_key] = strategy.get_status()
            except Exception as e:
                status["strategies"][strategy_key] = {"error": str(e)}

        return status

    def shutdown(self):
        """Shutdown all strategies."""
        self.logger.info("Shutting down Multi-Strategy Orchestrator", self.symbol)

        for strategy_key, strategy in self.strategies.items():
            try:
                strategy.shutdown()
                self.logger.info(f"✓ {strategy_key} shutdown", self.symbol)
            except Exception as e:
                self.logger.error(
                    f"Error shutting down {strategy_key}: {e}",
                    self.symbol
                )

        self.strategies.clear()
        self.is_initialized = False
