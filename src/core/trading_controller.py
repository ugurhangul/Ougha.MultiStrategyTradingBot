"""
Multi-symbol trading controller.
Orchestrates concurrent trading across multiple symbols.
"""
import os
import threading
import time
from typing import Dict, List, Set, Optional
from datetime import datetime, timezone, timedelta

from src.core.mt5_connector import MT5Connector
from src.core.symbol_session_monitor import SymbolSessionMonitor
from src.execution.order_manager import OrderManager
from src.execution.trade_manager import TradeManager
from src.indicators.technical_indicators import TechnicalIndicators
from src.risk.risk_manager import RiskManager
from src.strategy.multi_strategy_orchestrator import MultiStrategyOrchestrator
from src.strategy.symbol_performance_persistence import SymbolPerformancePersistence
from src.models.data_models import PositionInfo, PositionType
from src.config import config
from src.utils.logger import get_logger


class TradingController:
    """Controls multi-symbol trading operations"""

    def __init__(self, connector: MT5Connector, order_manager: OrderManager,
                 risk_manager: RiskManager, trade_manager: TradeManager,
                 indicators: TechnicalIndicators,
                 symbol_persistence: Optional[SymbolPerformancePersistence] = None):
        """
        Initialize trading controller.

        Args:
            connector: MT5 connector instance
            order_manager: Order manager instance
            risk_manager: Risk manager instance
            trade_manager: Trade manager instance
            indicators: Technical indicators instance
            symbol_persistence: Symbol performance persistence instance (optional)
        """
        self.connector = connector
        self.order_manager = order_manager
        self.risk_manager = risk_manager
        self.trade_manager = trade_manager
        self.indicators = indicators
        self.logger = get_logger()

        # Symbol performance persistence (shared across all symbols)
        self.symbol_persistence = symbol_persistence if symbol_persistence is not None else SymbolPerformancePersistence()

        # Symbol session monitor
        check_interval = config.trading_hours.session_check_interval_seconds
        self.session_monitor = SymbolSessionMonitor(connector=connector, check_interval_seconds=check_interval)

        # Symbol strategies (MultiStrategyOrchestrator per symbol)
        self.strategies: Dict[str, MultiStrategyOrchestrator] = {}

        # Threading
        self.threads: Dict[str, threading.Thread] = {}
        self.running = False
        self.lock = threading.Lock()

        # Monitoring
        self.last_position_check = datetime.now(timezone.utc)

    def initialize(self, symbols: List[str]) -> bool:
        """
        Initialize strategies for all symbols.

        Args:
            symbols: List of symbol names

        Returns:
            True if all strategies initialized successfully
        """
        self.logger.info("=" * 60)
        self.logger.info("Initializing Trading Controller")
        self.logger.info(f"Symbols: {', '.join(symbols)}")
        self.logger.info("=" * 60)

        # Reconcile persisted positions with MT5 on startup
        self._reconcile_positions()

        success_count = 0

        # Display enabled strategies
        self.logger.info("=" * 60)
        self.logger.info("*** PLUGIN-BASED ARCHITECTURE ***")
        self.logger.info("Using MultiStrategyOrchestrator with dynamic strategy loading")
        self.logger.info("=" * 60)

        # List enabled strategies
        enabled = []
        if config.strategy_enable.true_breakout_enabled:
            enabled.append("TrueBreakout")
        if config.strategy_enable.fakeout_enabled:
            enabled.append("Fakeout")
        if config.strategy_enable.hft_momentum_enabled:
            enabled.append("HFTMomentum")

        if enabled:
            self.logger.info(f"Enabled strategies: {', '.join(enabled)}")
        else:
            self.logger.warning("No strategies enabled! Check configuration.")

        # List enabled ranges
        ranges = []
        if config.strategy_enable.range_4h5m_enabled:
            ranges.append("4H_5M")
        if config.strategy_enable.range_15m1m_enabled:
            ranges.append("15M_1M")

        if ranges:
            self.logger.info(f"Enabled ranges: {', '.join(ranges)}")
        else:
            self.logger.warning("No ranges enabled! Breakout strategies will not run.")

        self.logger.info("=" * 60)

        # Check if session checking is enabled
        if config.trading_hours.check_symbol_session:
            # Check trading session status for all symbols
            active_symbols, inactive_symbols = self.session_monitor.filter_active_symbols(symbols)

            # Initialize active symbols immediately
            for symbol in active_symbols:
                success_count += self._initialize_symbol(symbol)

            # Handle inactive symbols - wait for their trading sessions if enabled
            if inactive_symbols and config.trading_hours.wait_for_session:
                self.logger.info("=" * 60)
                self.logger.info("Some symbols are not in active trading sessions")
                self.logger.info("Waiting for trading sessions to become active...")
                self.logger.info("=" * 60)

                # Get timeout from config (0 means wait indefinitely)
                timeout = config.trading_hours.session_wait_timeout_minutes
                timeout = None if timeout == 0 else timeout

                # Wait for each inactive symbol
                for symbol in inactive_symbols:
                    if self.session_monitor.wait_for_trading_session(symbol, max_wait_minutes=timeout):
                        # Symbol is now active, initialize it
                        success_count += self._initialize_symbol(symbol)
                    else:
                        self.logger.warning(
                            f"Skipping {symbol} - trading session did not become active within timeout",
                            symbol
                        )
            elif inactive_symbols:
                # Session checking enabled but waiting disabled - skip inactive symbols
                self.logger.warning("=" * 60)
                self.logger.warning("Skipping inactive symbols (WAIT_FOR_SESSION is disabled)")
                self.logger.warning(f"Skipped symbols: {', '.join(inactive_symbols)}")
                self.logger.warning("=" * 60)
        else:
            # Session checking disabled - initialize all symbols without checking
            self.logger.info("Session checking is disabled - initializing all symbols")
            for symbol in symbols:
                success_count += self._initialize_symbol(symbol)

        self.logger.info("=" * 60)
        self.logger.info(f"Initialized {success_count}/{len(symbols)} symbols")
        self.logger.info("=" * 60)

        return success_count > 0

    def _initialize_symbol(self, symbol: str) -> int:
        """
        Initialize a single symbol.

        Args:
            symbol: Symbol name

        Returns:
            1 if initialization successful, 0 otherwise
        """
        try:
            # Create multi-strategy orchestrator for symbol
            strategy = MultiStrategyOrchestrator(
                symbol=symbol,
                connector=self.connector,
                order_manager=self.order_manager,
                risk_manager=self.risk_manager,
                trade_manager=self.trade_manager,
                indicators=self.indicators,
                symbol_persistence=self.symbol_persistence
            )

            # Initialize strategy
            if strategy.initialize():
                self.strategies[symbol] = strategy
                self.logger.info(f"✓ {symbol} initialized", symbol)
                return 1
            else:
                self.logger.trade_error(
                    symbol=symbol,
                    error_type="Initialization",
                    error_message="Strategy initialization failed",
                    context={"action": "Symbol will not be traded"}
                )
                return 0

        except Exception as e:
            self.logger.trade_error(
                symbol=symbol,
                error_type="Initialization",
                error_message=f"Exception during initialization: {str(e)}",
                context={
                    "exception_type": type(e).__name__,
                    "action": "Symbol will not be traded"
                }
            )
            return 0

    def start(self):
        """Start trading for all symbols"""
        if not self.strategies:
            self.logger.error("No strategies initialized")
            return

        # Check if AutoTrading is enabled before starting
        if not self.connector.is_autotrading_enabled():
            self.logger.error("=" * 60)
            self.logger.error("AutoTrading is DISABLED in MT5 terminal")
            self.logger.error("Please enable AutoTrading and restart the bot")
            self.logger.error("=" * 60)
            return

        self.running = True

        self.logger.info("=" * 60)
        self.logger.info("Starting Multi-Symbol Trading")
        self.logger.info(f"Active symbols: {len(self.strategies)}")
        self.logger.info("=" * 60)

        # Start a thread for each symbol
        started_count = 0
        skipped_count = 0

        for symbol, strategy in self.strategies.items():
            # Check if symbol is actively trading before starting thread
            if not self.connector.is_trading_enabled(symbol):
                self.logger.warning(f"Trading is DISABLED for {symbol} - Skipping thread creation", symbol)
                skipped_count += 1
                continue

            thread = threading.Thread(
                target=self._symbol_worker,
                args=(symbol, strategy),
                name=f"Strategy-{symbol}",
                daemon=True
            )
            thread.start()
            self.threads[symbol] = thread
            started_count += 1

            # Log initial trading session state if session checking is enabled
            if config.trading_hours.check_symbol_session:
                in_session = self.session_monitor.check_symbol_session(symbol)
                if in_session:
                    self.logger.info(
                        f"{symbol}: In active trading session - worker will start trading immediately",
                        symbol
                    )
                else:
                    self.logger.info(
                        f"{symbol}: NOT in active trading session - worker will start in sleep mode until session opens",
                        symbol
                    )

        if started_count == 0:
            self.logger.error("No symbol threads were started - all symbols have trading disabled")
            self.running = False
            return

        # Start position monitoring thread
        monitor_thread = threading.Thread(
            target=self._position_monitor,
            name="PositionMonitor",
            daemon=True
        )
        monitor_thread.start()
        self.logger.info("Started position monitor thread")

        self.logger.info("=" * 60)
        self.logger.info(f"Thread Summary: {started_count} started, {skipped_count} skipped")
        if skipped_count > 0:
            self.logger.warning(f"{skipped_count} symbol(s) skipped due to trading disabled")
        self.logger.info("=" * 60)

    def _symbol_worker(self, symbol: str, strategy: MultiStrategyOrchestrator):
        """
        Worker thread for a single symbol.

        Args:
            symbol: Symbol name
            strategy: MultiStrategyOrchestrator instance for this symbol
        """
        self.logger.info(f"Worker thread started for {symbol}", symbol)

        while self.running:
            try:
                # Check if AutoTrading is still enabled
                if not self.connector.is_autotrading_enabled():
                    self.logger.error(f"AutoTrading DISABLED - Stopping worker thread", symbol)
                    self.running = False
                    break

                # Check if symbol trading is still enabled
                if not self.connector.is_trading_enabled(symbol):
                    self.logger.warning(f"Trading DISABLED for symbol - Stopping worker thread", symbol)
                    break

                # Check if symbol is in an active trading session
                if not self._is_symbol_in_active_session(symbol):
                    # Put the worker thread to sleep until the next active session
                    if not self._sleep_until_next_session(symbol):
                        # Sleep was aborted because controller is stopping
                        break
                    # After waking up, re-validate all conditions
                    continue

                # Process tick
                strategy.on_tick()
                time.sleep(1)  # Sleep for 1 second (adjust as needed)
            except Exception as e:
                self.logger.trade_error(
                    symbol=symbol,
                    error_type="Worker Thread",
                    error_message=f"Exception in symbol worker thread: {str(e)}",
                    context={
                        "exception_type": type(e).__name__,
                        "action": "Retrying in 5 seconds"
                    }
                )
                time.sleep(5)  # Wait before retrying

        self.logger.info(f"Worker thread stopped for {symbol}", symbol)

    def _is_symbol_in_active_session(self, symbol: str) -> bool:
        """Determine if a symbol is currently in an active trading session.

        This combines broker / MT5 session status with optional configured
        trading hours to support pre/post-market filtering.
        """
        trading_hours_config = config.trading_hours

        # Optionally skip MT5-based session checks if disabled in config
        if trading_hours_config.check_symbol_session:
            # First rely on the MT5-based session detection, which already
            # understands holidays, early closes, etc.
            in_session = self.session_monitor.check_symbol_session(symbol)
            if not in_session:
                return False

        # If explicit trading hours filtering is disabled, MT5 status alone is enough
        if not trading_hours_config.use_trading_hours:
            return True

        # Apply configured trading window (assumed to be in UTC)
        now = datetime.now(timezone.utc)
        start_hour = trading_hours_config.start_hour
        end_hour = trading_hours_config.end_hour
        current_hour = now.hour

        if start_hour == end_hour:
            # 24-hour session
            return True

        if start_hour < end_hour:
            # Simple window within same day
            return start_hour <= current_hour < end_hour

        # Window crosses midnight, e.g. 22 -> 2
        return current_hour >= start_hour or current_hour < end_hour

    def _calculate_next_session_start(self) -> datetime:
        """Estimate the start time of the next trading session in UTC.

        Uses TradingHoursConfig when enabled; otherwise falls back to using
        the session check interval as a conservative polling delay.
        """
        now = datetime.now(timezone.utc)
        trading_hours_config = config.trading_hours

        if not trading_hours_config.use_trading_hours:
            # No explicit hours configured - poll again after check interval
            return now + timedelta(seconds=trading_hours_config.session_check_interval_seconds)

        start_hour = trading_hours_config.start_hour
        end_hour = trading_hours_config.end_hour

        # Assume a simple daily window [start_hour, end_hour) in UTC
        today_start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=end_hour, minute=0, second=0, microsecond=0)

        if now < today_start:
            candidate = today_start
        elif now >= today_end:
            candidate = today_start + timedelta(days=1)
        else:
            # Within configured hours but MT5 reports no trading session
            # (holiday, early close, etc.) - poll again after interval.
            return now + timedelta(seconds=trading_hours_config.session_check_interval_seconds)

        # Skip weekends (Saturday=5, Sunday=6)
        while candidate.weekday() >= 5:
            candidate = candidate + timedelta(days=1)
            candidate = candidate.replace(hour=start_hour, minute=0, second=0, microsecond=0)

        return candidate

    def _sleep_until_next_session(self, symbol: str) -> bool:
        """Put the worker thread for a symbol to sleep until the next trading session.

        Returns:
            True if the worker should continue once the session is active,
            False if trading should stop because the controller is shutting down.
        """
        trading_hours_config = config.trading_hours
        now = datetime.now(timezone.utc)
        next_session_start = self._calculate_next_session_start()

        # Compute expected sleep duration (in seconds)
        sleep_seconds = max(
            trading_hours_config.session_check_interval_seconds,
            int((next_session_start - now).total_seconds())
        )

        # Guard against non-positive durations
        if sleep_seconds <= 0:
            sleep_seconds = trading_hours_config.session_check_interval_seconds

        message = (
            f"{symbol}: Outside active trading session. "
            f"Next session expected at {next_session_start.strftime('%Y-%m-%d %H:%M:%S %Z')} "
            f"(sleeping for ~{sleep_seconds // 60} minutes, "
            f"checking every {trading_hours_config.session_check_interval_seconds} seconds)."
        )
        self.logger.info(message, symbol)

        remaining = float(sleep_seconds)
        check_interval = max(1, trading_hours_config.session_check_interval_seconds)
        elapsed_since_check = 0.0

        while self.running and remaining > 0:
            step = min(remaining, 1.0)
            time.sleep(step)
            remaining -= step
            elapsed_since_check += step

            if not self.running:
                # Controller is shutting down
                return False

            if elapsed_since_check >= check_interval:
                elapsed_since_check = 0.0

                # Wake up early if the session became active sooner than expected
                if self._is_symbol_in_active_session(symbol):
                    self.logger.info(
                        f"{symbol}: Trading session became active earlier than expected - Resuming.",
                        symbol
                    )
                    return True


    def _should_close_positions_for_session_end(self, symbol: str) -> bool:
        """Determine if positions for a symbol should be closed before session end.

        Primary signal comes from MT5's *actual* trading mode (CLOSEONLY),
        which reflects the broker's real session calendar including holidays
        and early closes. Optionally falls back to static TradingHoursConfig
        window when enabled.
        """
        trading_hours_config = config.trading_hours

        if not trading_hours_config.close_positions_before_session_end:
            return False

        # --- 1) Prefer MT5's actual session state via trade_mode (CLOSEONLY) ---
        # Force a fresh symbol_info fetch so trade_mode changes are seen promptly
        try:
            self.connector.clear_symbol_info_cache(symbol)
            symbol_info = self.connector.get_symbol_info(symbol)
        except Exception:
            symbol_info = None

        if symbol_info is not None:
            # trade_mode values (see TradingStatusChecker and MT5 docs):
            # 0 = DISABLED, 1 = LONGONLY, 2 = SHORTONLY,
            # 3 = CLOSEONLY (only closing allowed), 4 = FULL
            trade_mode = symbol_info.get("trade_mode", 0)

            # When broker switches symbol to CLOSEONLY, the session is about to end
            # but closing trades is still allowed. Close positions immediately.
            if trade_mode == 3:
                return True

        # --- 2) Optional fallback: static trading hours window (if configured) ---
        if not trading_hours_config.use_trading_hours:
            return False

        now = datetime.now(timezone.utc)
        start_hour = trading_hours_config.start_hour
        end_hour = trading_hours_config.end_hour

        # 24-hour window - no specific session end where forced closure is needed
        if start_hour == end_hour:
            return False

        # Determine the current session start/end that contains "now"
        session_start = None
        session_end = None

        if start_hour < end_hour:
            # Simple intraday window [start_hour, end_hour)
            session_start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            session_end = now.replace(hour=end_hour, minute=0, second=0, microsecond=0)

            if not (session_start <= now < session_end):
                return False
        else:
            # Window crosses midnight, e.g. 22 -> 2
            # Two segments: [start_hour, 24) and [0, end_hour)
            if now.hour >= start_hour:
                # Evening segment (today -> tomorrow)
                session_start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
                session_end = (session_start + timedelta(days=1)).replace(
                    hour=end_hour, minute=0, second=0, microsecond=0
                )
            elif now.hour < end_hour:
                # Morning segment (continuation of previous day's session)
                session_end = now.replace(hour=end_hour, minute=0, second=0, microsecond=0)
                session_start = (session_end - timedelta(days=1)).replace(
                    hour=start_hour, minute=0, second=0, microsecond=0
                )
            else:
                # Outside the configured session window
                return False

            if not (session_start <= now < session_end):
                return False

        minutes_to_end = (session_end - now).total_seconds() / 60.0
        return minutes_to_end <= trading_hours_config.close_positions_minutes_before_end

    def _close_positions_before_session_end(self, positions: List[PositionInfo]):
        """Close open positions for symbols whose session is about to end.

        This is intended to reduce the risk of holding positions into a closed
        market. It respects TradingHoursConfig and only acts when both:
        - close_positions_before_session_end is enabled
        - the symbol is still in an active trading session
        """
        if not positions:
            return

        trading_hours_config = config.trading_hours
        if not trading_hours_config.close_positions_before_session_end:
            return

        # Group positions by symbol to log and act per symbol
        positions_by_symbol: Dict[str, List[PositionInfo]] = {}
        for pos in positions:
            positions_by_symbol.setdefault(pos.symbol, []).append(pos)

        for symbol, symbol_positions in positions_by_symbol.items():
            # Only attempt to close while we still consider the session active
            if not self._is_symbol_in_active_session(symbol):
                continue

            if not self._should_close_positions_for_session_end(symbol):
                continue

            self.logger.info(
                f"{symbol}: Trading session ending soon - closing {len(symbol_positions)} open position(s) before session end.",
                symbol
            )

            for pos in symbol_positions:
                success = self.order_manager.close_position(pos.ticket)
                if not success:
                    self.logger.warning(
                        f"{symbol}: Failed to close position {pos.ticket} before session end.",
                        symbol
                    )



    def _position_monitor(self):
        """Monitor all positions and check for closed trades"""
        self.logger.info("Position monitor thread started")

        # Track known positions
        known_positions = set()

        # Track last statistics log time
        last_stats_log = datetime.now(timezone.utc)

        while self.running:
            try:
                # Check if AutoTrading is still enabled
                if not self.connector.is_autotrading_enabled():
                    self.logger.error("AutoTrading DISABLED - Stopping position monitor")
                    self.running = False
                    break

                # Get all positions
                positions = self.connector.get_positions(
                    magic_number=config.advanced.magic_number
                )

                # Current position tickets
                current_tickets = {pos.ticket for pos in positions}

                # Check for closed positions
                closed_tickets = known_positions - current_tickets

                for ticket in closed_tickets:
                    # Position was closed, need to find which symbol it was
                    # We'll check history to get the profit
                    self._handle_closed_position(ticket)

                # Update known positions
                known_positions = current_tickets

                if positions:
                    # Close positions if the session is about to end
                    self._close_positions_before_session_end(positions)

                    # Manage positions (breakeven and trailing stops)
                    self.trade_manager.manage_positions(positions)

                # Log statistics every 10 seconds
                if (datetime.now(timezone.utc) - last_stats_log).total_seconds() >= 10:
                    self._log_position_statistics(positions)
                    last_stats_log = datetime.now(timezone.utc)

                # Sleep for 5 seconds
                time.sleep(5)

            except Exception as e:
                self.logger.error(f"Error in position monitor: {e}")
                time.sleep(10)

        self.logger.info("Position monitor thread stopped")

    def _log_position_statistics(self, positions: List[PositionInfo]):
        """
        Log statistics about open positions.

        Args:
            positions: List of open positions
        """
        if not positions:
            return

        # Calculate statistics
        total_positions = len(positions)
        buy_positions = sum(1 for p in positions if p.position_type == PositionType.BUY)
        sell_positions = total_positions - buy_positions

        total_profit = sum(p.profit for p in positions)
        winning_positions = sum(1 for p in positions if p.profit > 0)
        losing_positions = sum(1 for p in positions if p.profit < 0)

        # Get account info
        balance = self.connector.get_account_balance()
        equity = self.connector.get_account_equity()

        # Group positions by symbol
        positions_by_symbol = {}
        for pos in positions:
            if pos.symbol not in positions_by_symbol:
                positions_by_symbol[pos.symbol] = []
            positions_by_symbol[pos.symbol].append(pos)

        # Log summary
        self.logger.info("=" * 60)
        self.logger.info("POSITION MONITOR - STATISTICS")
        self.logger.info("=" * 60)
        self.logger.info(f"Account Balance: ${balance:.2f}")
        self.logger.info(f"Account Equity: ${equity:.2f}")
        self.logger.info(f"Floating P&L: ${total_profit:.2f}")
        self.logger.info("-" * 60)
        self.logger.info(f"Total Positions: {total_positions}")
        self.logger.info(f"  BUY: {buy_positions} | SELL: {sell_positions}")
        self.logger.info(f"  Winning: {winning_positions} | Losing: {losing_positions}")
        self.logger.info("-" * 60)

        # Log positions by symbol
        for symbol, symbol_positions in sorted(positions_by_symbol.items()):
            symbol_profit = sum(p.profit for p in symbol_positions)
            self.logger.info(f"{symbol}: {len(symbol_positions)} position(s) | P&L: ${symbol_profit:.2f}")

            for pos in symbol_positions:
                pos_type = "BUY" if pos.position_type == PositionType.BUY else "SELL"
                self.logger.info(
                    f"  #{pos.ticket} {pos_type} {pos.volume:.2f} @ {pos.open_price:.5f} | "
                    f"Current: {pos.current_price:.5f} | P&L: ${pos.profit:.2f}"
                )

        self.logger.info("=" * 60)

    def _handle_closed_position(self, ticket: int):
        """
        Handle a closed position.

        Args:
            ticket: Position ticket
        """
        # Query MT5 history to get symbol, profit, volume, and comment
        position_info = self.connector.get_closed_position_info(ticket)

        if position_info is None:
            self.logger.warning(f"Could not find closed position info for ticket {ticket}")
            return

        symbol, profit, volume, comment = position_info

        self.logger.info(f"Position {ticket} closed: {symbol} | Profit: ${profit:.2f} | Volume: {volume:.2f}")

        # Notify trade manager to clean up tracking data
        self.trade_manager.on_position_closed(ticket)

        # Find the strategy orchestrator for this symbol and notify it
        if symbol in self.strategies:
            strategy = self.strategies[symbol]
            # MultiStrategyOrchestrator handles position closure routing
            strategy.on_position_closed(symbol, profit, volume, comment)
        else:
            self.logger.warning(f"No strategy found for symbol {symbol} (ticket {ticket})")

    def stop(self):
        """Stop all trading"""
        self.logger.info("Stopping trading controller...")

        self.running = False

        # Wait for all threads to finish
        for symbol, thread in self.threads.items():
            self.logger.info(f"Waiting for {symbol} thread to stop...", symbol)
            thread.join(timeout=5)

        # Shutdown all strategies
        for symbol, strategy in self.strategies.items():
            strategy.shutdown()

        self.logger.info("Trading controller stopped")

    def get_status(self) -> dict:
        """
        Get status of all strategies.

        Returns:
            Dictionary with status for each symbol
        """
        with self.lock:
            return {
                symbol: strategy.get_status()
                for symbol, strategy in self.strategies.items()
            }



    def _reconcile_positions(self):
        """
        Reconcile persisted positions with actual MT5 positions on startup.

        This prevents duplicate position creation after bot restart by:
        1. Loading positions from persistence file
        2. Comparing with actual MT5 positions
        3. Syncing the two sources of truth
        """
        self.logger.info("=" * 60)
        self.logger.info("RECONCILING POSITIONS WITH MT5")
        self.logger.info("=" * 60)

        try:
            # Get all MT5 positions with our magic number
            mt5_positions = self.connector.get_positions(
                magic_number=config.advanced.magic_number
            )

            self.logger.info(f"Found {len(mt5_positions)} positions in MT5")

            # Reconcile with persistence
            results = self.order_manager.persistence.reconcile_with_mt5(mt5_positions)

            # Log results
            if results['added'] or results['removed'] or results['updated']:
                self.logger.info("Reconciliation Summary:")
                self.logger.info(f"  Added to tracking: {len(results['added'])}")
                self.logger.info(f"  Removed from tracking: {len(results['removed'])}")
                self.logger.info(f"  Updated: {len(results['updated'])}")
            else:
                self.logger.info("All positions already in sync")

            self.logger.info("=" * 60)

        except Exception as e:
            self.logger.error(f"Error during position reconciliation: {e}")
            self.logger.warning("Continuing with initialization...")

        self.logger.info("=" * 60)

