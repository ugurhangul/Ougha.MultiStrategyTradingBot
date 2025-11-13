"""
Ougha Multi Strategy Trading Bot
Main entry point for the trading system.
"""
import sys
import signal
import time
from typing import List

from src.config import config
from src.core.mt5_connector import MT5Connector
from src.core.trading_controller import TradingController
from src.execution.order_manager import OrderManager
from src.execution.position_persistence import PositionPersistence
from src.execution.trade_manager import TradeManager
from src.indicators.technical_indicators import TechnicalIndicators
from src.risk.risk_manager import RiskManager
from src.utils.logger import init_logger, get_logger
from src.constants import DATA_DIR


class TradingBot:
    """Main trading bot controller"""
    
    def __init__(self):
        """Initialize the trading bot"""
        # Initialize logger
        self.logger = init_logger(
            log_to_file=config.logging.log_to_file,
            log_to_console=config.logging.log_to_console,
            log_level=config.logging.log_level,
            enable_detailed=config.logging.enable_detailed_logging
        )
        
        self.logger.header("Ougha Multi Strategy Trading Bot")
        self.logger.info("Initializing trading system...")

        # Validate configuration (skip symbols check - will load from Market Watch)
        try:
            config.validate(check_symbols=False)
            self.logger.info("Configuration validated successfully")
        except ValueError as e:
            self.logger.error(f"Configuration error: {e}")
            sys.exit(1)
        
        # Initialize components
        self.connector = MT5Connector(config.mt5)

        # Initialize position persistence (shared between OrderManager and RiskManager)
        self.persistence = PositionPersistence(data_dir=DATA_DIR)

        # Initialize symbol performance persistence (shared across all symbols)
        from src.strategy.symbol_performance_persistence import SymbolPerformancePersistence
        self.symbol_persistence = SymbolPerformancePersistence(data_dir=DATA_DIR)

        # Initialize risk manager first (needed by order manager)
        self.risk_manager = RiskManager(
            connector=self.connector,
            risk_config=config.risk,
            persistence=self.persistence
        )

        # Initialize order manager with risk manager for position limit checks
        self.order_manager = OrderManager(
            connector=self.connector,
            magic_number=config.advanced.magic_number,
            trade_comment=config.advanced.trade_comment,
            persistence=self.persistence,
            risk_manager=self.risk_manager
        )
        self.indicators = TechnicalIndicators()
        self.trade_manager = TradeManager(
            connector=self.connector,
            order_manager=self.order_manager,
            trailing_config=config.trailing_stop,
            use_breakeven=config.advanced.use_breakeven,
            breakeven_trigger_rr=config.advanced.breakeven_trigger_rr,
            indicators=self.indicators,
            range_configs=config.range_config.ranges
        )

        # Trading controller
        self.controller = TradingController(
            connector=self.connector,
            order_manager=self.order_manager,
            risk_manager=self.risk_manager,
            trade_manager=self.trade_manager,
            indicators=self.indicators,
            symbol_persistence=self.symbol_persistence
        )

        # Running flag
        self.is_running = False
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.warning("Shutdown signal received")
        self.stop()
    
    def start(self):
        """Start the trading bot"""
        self.logger.info("Starting trading bot...")

        # Connect to MT5
        if not self.connector.connect():
            self.logger.error("Failed to connect to MT5")
            return False

        # Load symbols from active.set file with prioritization
        self.logger.info("Loading symbols from active.set...")
        self.logger.info("Applying symbol prioritization: Raw spread (r) > Standard > Micro (m)")
        if not config.load_symbols_from_active_set(connector=self.connector, logger=self.logger):
            self.logger.warning("Failed to load symbols from active.set, loading from Market Watch")
            # Load from Market Watch if active.set doesn't exist
            if not config.load_symbols_from_market_watch(self.connector):
                self.logger.error("Failed to load symbols from Market Watch")
                self.stop()
                return False
            self.logger.info(f"Loaded {len(config.symbols)} symbols from Market Watch")

            # Save to active.set for future use (will be prioritized on next load)
            from pathlib import Path
            from src.utils.active_set_manager import get_active_set_manager

            active_set_manager = get_active_set_manager(connector=self.connector)
            active_set_manager.save_symbols(config.symbols)
            self.logger.info(f"Saved {len(config.symbols)} symbols to active.set")
        else:
            self.logger.info(f"Loaded {len(config.symbols)} symbols from active.set (after prioritization)")

        # Validate that we have symbols
        try:
            config.validate(check_symbols=True)
        except ValueError as e:
            self.logger.error(f"Configuration error: {e}")
            self.stop()
            return False

        # Log configuration
        self._log_configuration()

        # Initialize symbol strategies
        self._initialize_symbols()
        
        # Start main loop
        self.is_running = True
        self.logger.info("Trading bot started successfully")
        self.logger.separator()
        
        try:
            self._main_loop()
        except Exception as e:
            self.logger.error(f"Fatal error in main loop: {e}")
            self.stop()
    

    
    def _log_configuration(self):
        """Log current configuration"""
        self.logger.info("=== Configuration ===")
        self.logger.info(f"Symbols: {', '.join(config.symbols)}")
        self.logger.info(f"Magic Number: {config.advanced.magic_number}")
        self.logger.info(f"Risk Per Trade: {config.risk.risk_percent_per_trade}%")
        self.logger.info(f"Risk/Reward Ratio: 1:{config.strategy.risk_reward_ratio}")
        self.logger.info(f"Use Breakeven: {config.advanced.use_breakeven}")
        if config.advanced.use_breakeven:
            self.logger.info(f"  Breakeven Trigger: {config.advanced.breakeven_trigger_rr} R:R")
        self.logger.info(f"Use Trailing Stop: {config.trailing_stop.use_trailing_stop}")
        if config.trailing_stop.use_trailing_stop:
            self.logger.info(f"  Trailing Trigger: {config.trailing_stop.trailing_stop_trigger_rr} R:R")
            self.logger.info(f"  Trailing Distance: {config.trailing_stop.trailing_stop_distance} points")
        self.logger.info(f"Multi-Range Mode: Enabled (default)")
        self.logger.info(f"Adaptive Filters: {config.adaptive_filters.use_adaptive_filters}")
        self.logger.info(f"Symbol Adaptation: {config.symbol_adaptation.use_symbol_adaptation}")
        self.logger.separator()
    
    def _initialize_symbols(self):
        """Initialize strategy for each symbol"""
        self.logger.info("Initializing symbol strategies...")

        # Initialize controller with all symbols
        if not self.controller.initialize(config.symbols):
            self.logger.error("Failed to initialize trading controller")
            self.stop()
            return

        self.logger.separator()
    
    def _main_loop(self):
        """Main trading loop"""
        self.logger.info("Entering main trading loop...")

        # Start the controller (this starts all symbol threads)
        self.controller.start()

        # Keep main thread alive while bot is running
        try:
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.warning("Keyboard interrupt received")
            self.stop()

    def stop(self):
        """Stop the trading bot"""
        self.logger.info("Stopping trading bot...")
        self.is_running = False

        # Stop the controller
        if hasattr(self, 'controller'):
            self.controller.stop()

        # Disconnect from MT5
        self.connector.disconnect()

        self.logger.info("Trading bot stopped")
        sys.exit(0)


def main():
    """Main entry point"""
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║                                                            ║
    ║                    Ougha Multi Strategy                    ║
    ║                                                            ║
    ╚════════════════════════════════════════════════════════════╝
    """)
    
    # Create and start bot
    bot = TradingBot()
    bot.start()


if __name__ == "__main__":
    main()

