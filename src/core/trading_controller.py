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
                 symbol_persistence: Optional[SymbolPerformancePersistence] = None,
                 time_controller: Optional['TimeController'] = None):
        """
        Initialize trading controller.

        Args:
            connector: MT5 connector instance (or SimulatedBroker for backtesting)
            order_manager: Order manager instance
            risk_manager: Risk manager instance
            trade_manager: Trade manager instance
            indicators: Technical indicators instance
            symbol_persistence: Symbol performance persistence instance (optional)
            time_controller: Time controller for backtest synchronization (optional, backtest only)
        """
        self.connector = connector
        self.order_manager = order_manager
        self.risk_manager = risk_manager
        self.trade_manager = trade_manager
        self.indicators = indicators
        self.logger = get_logger()

        # Backtest mode detection and time controller
        self.time_controller = time_controller
        self.is_backtest_mode = time_controller is not None

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

        # Background symbol monitoring for inactive symbols
        self.pending_symbols: Set[str] = set()  # Symbols waiting for their trading sessions
        self.background_monitor_threads: Dict[str, threading.Thread] = {}

        # Monitoring
        self.last_position_check = datetime.now(timezone.utc)

        if self.is_backtest_mode:
            self.logger.info("TradingController initialized in BACKTEST mode with TimeController")

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

        # In backtest mode, always initialize all symbols regardless of session status
        # because we're simulating historical time, not real-time
        if self.is_backtest_mode:
            self.logger.info("BACKTEST MODE: Initializing all symbols (session checking skipped)")
            for symbol in symbols:
                success_count += self._initialize_symbol(symbol)
        # Check if session checking is enabled (live trading only)
        elif config.trading_hours.check_symbol_session:
            # Check trading session status for all symbols
            active_symbols, inactive_symbols = self.session_monitor.filter_active_symbols(symbols)

            # Initialize active symbols immediately
            for symbol in active_symbols:
                success_count += self._initialize_symbol(symbol)

            # Handle inactive symbols - start background monitoring if enabled
            if inactive_symbols and config.trading_hours.wait_for_session:
                self.logger.info("=" * 60)
                self.logger.info("Some symbols are not in active trading sessions")
                self.logger.info("Starting background monitoring for inactive symbols...")
                self.logger.info("These symbols will be automatically initialized when their sessions start")
                self.logger.info("=" * 60)

                # Get timeout from config (0 means wait indefinitely)
                timeout = config.trading_hours.session_wait_timeout_minutes
                timeout = None if timeout == 0 else timeout

                # Start background monitoring for each inactive symbol
                for symbol in inactive_symbols:
                    self._start_background_symbol_monitor(symbol, timeout)

                self.logger.info(f"Started background monitoring for {len(inactive_symbols)} inactive symbols")
                self.logger.info(f"Monitoring symbols: {', '.join(inactive_symbols)}")
                self.logger.info("=" * 60)
            elif inactive_symbols:
                # Session checking enabled but waiting disabled - skip inactive symbols
                self.logger.warning("=" * 60)
                self.logger.warning("Skipping inactive symbols (WAIT_FOR_SESSION is disabled)")
                self.logger.warning(f"Skipped symbols: {', '.join(inactive_symbols)}")
                self.logger.warning("To enable background monitoring, set WAIT_FOR_SESSION=true")
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
                with self.lock:
                    self.strategies[symbol] = strategy
                    # Remove from pending symbols if it was there
                    self.pending_symbols.discard(symbol)
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

    def _start_background_symbol_monitor(self, symbol: str, max_wait_minutes: Optional[int] = None):
        """
        Start a background thread to monitor an inactive symbol and initialize it when its session starts.

        Args:
            symbol: Symbol name
            max_wait_minutes: Maximum time to wait for session (None = wait indefinitely)
        """
        with self.lock:
            # Add to pending symbols
            self.pending_symbols.add(symbol)

        # Create and start background monitoring thread
        thread = threading.Thread(
            target=self._background_symbol_monitor_worker,
            args=(symbol, max_wait_minutes),
            name=f"SessionMonitor-{symbol}",
            daemon=True
        )
        thread.start()

        with self.lock:
            self.background_monitor_threads[symbol] = thread

        self.logger.info(f"Started background session monitor for {symbol}", symbol)

    def _background_symbol_monitor_worker(self, symbol: str, max_wait_minutes: Optional[int] = None):
        """
        Background worker that waits for a symbol's trading session to start and then initializes it.

        Args:
            symbol: Symbol name
            max_wait_minutes: Maximum time to wait for session (None = wait indefinitely)
        """
        self.logger.info(f"Background monitor: Waiting for {symbol} trading session to start...", symbol)

        start_time = datetime.now(timezone.utc)
        check_interval = config.trading_hours.session_check_interval_seconds
        check_count = 0

        while self.running:
            try:
                # Check if symbol is now in trading session
                if self.session_monitor.check_symbol_session(symbol):
                    elapsed_minutes = (datetime.now(timezone.utc) - start_time).total_seconds() / 60
                    self.logger.info(
                        f"✓ {symbol} trading session is now active (waited {elapsed_minutes:.1f} minutes)",
                        symbol
                    )

                    # Initialize the symbol
                    if self._initialize_symbol(symbol) > 0:
                        # If bot is already running, start the trading thread for this symbol
                        if self.running:
                            with self.lock:
                                strategy = self.strategies.get(symbol)

                            if strategy:
                                # Check if trading is enabled for this symbol
                                if self.connector.is_trading_enabled(symbol):
                                    thread = threading.Thread(
                                        target=self._symbol_worker,
                                        args=(symbol, strategy),
                                        name=f"Strategy-{symbol}",
                                        daemon=True
                                    )
                                    thread.start()

                                    with self.lock:
                                        self.threads[symbol] = thread

                                    self.logger.info(
                                        f"✓ {symbol} trading thread started - now actively trading",
                                        symbol
                                    )
                                else:
                                    self.logger.warning(
                                        f"{symbol} initialized but trading is disabled - thread not started",
                                        symbol
                                    )
                    break

                # Check if we've exceeded max wait time
                if max_wait_minutes is not None:
                    elapsed_minutes = (datetime.now(timezone.utc) - start_time).total_seconds() / 60
                    if elapsed_minutes >= max_wait_minutes:
                        self.logger.warning(
                            f"Timeout waiting for {symbol} trading session (waited {elapsed_minutes:.1f} minutes)",
                            symbol
                        )
                        with self.lock:
                            self.pending_symbols.discard(symbol)
                        break

                # Log status every 5 checks
                check_count += 1
                if check_count % 5 == 0:
                    elapsed_minutes = (datetime.now(timezone.utc) - start_time).total_seconds() / 60
                    self.logger.info(
                        f"Still waiting for {symbol} trading session... (elapsed: {elapsed_minutes:.1f} minutes)",
                        symbol
                    )

                # Wait before next check
                time.sleep(check_interval)

            except Exception as e:
                self.logger.error(
                    f"Error in background monitor for {symbol}: {str(e)}",
                    symbol
                )
                time.sleep(check_interval)

        # Clean up
        with self.lock:
            self.background_monitor_threads.pop(symbol, None)
            self.pending_symbols.discard(symbol)

        self.logger.info(f"Background monitor stopped for {symbol}", symbol)

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

        In LIVE mode: Runs continuously with time.sleep(1) between ticks
        In BACKTEST mode: Uses TimeController barrier synchronization

        Args:
            symbol: Symbol name
            strategy: MultiStrategyOrchestrator instance for this symbol
        """
        self.logger.info(f"Worker thread started for {symbol}", symbol)

        while self.running:
            try:
                # BACKTEST MODE: Check if we should continue
                if self.is_backtest_mode:
                    # Check if data is still available for this symbol
                    if not self.connector.is_data_available(symbol):
                        self.logger.info(f"{symbol}: No more data available - stopping worker", symbol)
                        break

                # LIVE MODE: Check AutoTrading and symbol trading status
                if not self.is_backtest_mode:
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
                    in_session = self._is_symbol_in_active_session(symbol)
                    if not in_session:
                        self.logger.info(f"{symbol}: Not in active trading session - entering sleep mode", symbol)
                        # Put the worker thread to sleep until the next active session
                        if not self._sleep_until_next_session(symbol):
                            # Sleep was aborted because controller is stopping
                            break
                        # After waking up, re-validate all conditions
                        continue

                # BACKTEST MODE: Check if symbol has data at current global time
                if self.is_backtest_mode:
                    # Check if this symbol has data at the current global time
                    has_data = self.connector.has_data_at_current_time(symbol)

                    if has_data:
                        # Process tick only if symbol has data at current time
                        strategy.on_tick()
                    # else: Symbol has no data at this minute, skip processing

                    # All symbols wait at barrier (whether they processed or not)
                    if not self.time_controller.wait_for_next_step(symbol):
                        # TimeController stopped
                        break

                    # Check if symbol has reached end of all data
                    if not self.connector.has_more_data(symbol):
                        # No more data for this symbol
                        self.logger.info(f"{symbol}: Reached end of data", symbol)
                        break

                # LIVE MODE: Process tick and sleep
                else:
                    strategy.on_tick()
                    time.sleep(1)  # Sleep for 1 second (adjust as needed)

            except Exception as e:
                self.logger.trade_error(
                    symbol=symbol,
                    error_type="Worker Thread",
                    error_message=f"Exception in symbol worker thread: {str(e)}",
                    context={
                        "exception_type": type(e).__name__,
                        "action": "Checking session status before retrying"
                    }
                )

                # LIVE MODE: Check session status before retrying
                if not self.is_backtest_mode:
                    # Before retrying, check if the exception was due to session being closed
                    # This prevents rapid retry loops when market is closed
                    if not self._is_symbol_in_active_session(symbol):
                        self.logger.info(
                            f"{symbol}: Exception occurred and session is now closed - entering sleep mode",
                            symbol
                        )
                        # Don't retry immediately - go to sleep mode instead
                        continue

                    # Session is still active, wait before retrying
                    time.sleep(5)
                else:
                    # BACKTEST MODE: Log error and continue
                    self.logger.warning(f"{symbol}: Error in backtest, continuing...", symbol)
                    time.sleep(0.1)

        self.logger.info(f"Worker thread stopped for {symbol}", symbol)

        # BACKTEST MODE: Remove this participant from the barrier
        if self.is_backtest_mode:
            self.time_controller.remove_participant(symbol)

    def _is_symbol_in_active_session(self, symbol: str, suppress_logs: bool = False) -> bool:
        """Determine if a symbol is currently in an active trading session.

        Uses broker's actual market hours from MT5 (CHECK_SYMBOL_SESSION).

        Args:
            symbol: Symbol name
            suppress_logs: If True, suppress repetitive stale tick warnings during sleep mode checks
        """
        trading_hours_config = config.trading_hours

        # Check MT5-based session status if enabled in config
        if trading_hours_config.check_symbol_session:
            in_session = self.session_monitor.check_symbol_session(symbol, suppress_logs)
            if not in_session:
                return False

        return True

    def _calculate_next_session_start(self) -> datetime:
        """Estimate the start time of the next trading session in UTC.

        Returns the next check time based on session check interval.
        Actual session start is determined by MT5's real-time session status.
        """
        now = datetime.now(timezone.utc)
        trading_hours_config = config.trading_hours

        # Poll again after check interval
        return now + timedelta(seconds=trading_hours_config.session_check_interval_seconds)

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
                # Suppress logs during sleep mode to avoid repetitive stale tick warnings
                if self._is_symbol_in_active_session(symbol, suppress_logs=True):
                    self.logger.info(
                        f"{symbol}: Trading session became active earlier than expected - Resuming.",
                        symbol
                    )
                    return True


    def _should_close_positions_for_session_end(self, symbol: str) -> bool:
        """Determine if positions for a symbol should be closed before session end.

        Uses MT5's actual trading mode (CLOSEONLY) which reflects the broker's
        real session calendar including holidays and early closes.

        Note: Cache is only invalidated every 60 seconds to reduce unnecessary
        MT5 API calls while still detecting session end promptly.
        """
        trading_hours_config = config.trading_hours

        if not trading_hours_config.close_positions_before_session_end:
            return False

        # Check MT5's actual session state via trade_mode (CLOSEONLY)
        # Only invalidate cache if it's older than 60 seconds to reduce API calls
        cache_age = self.connector.symbol_cache.get_cache_age(symbol)
        if cache_age is None or cache_age > 60:
            # Cache is stale or doesn't exist, invalidate and fetch fresh
            try:
                self.connector.clear_symbol_info_cache(symbol)
                symbol_info = self.connector.get_symbol_info(symbol)
            except Exception:
                symbol_info = None
        else:
            # Use cached value (less than 60 seconds old)
            try:
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

        return False

    def _close_positions_before_session_end(self, positions: List[PositionInfo]):
        """Close open positions for symbols whose session is about to end.

        This is intended to reduce the risk of holding positions into a closed
        market. It respects TradingHoursConfig and only acts when both:
        - close_positions_before_session_end is enabled
        - the symbol is still in an active trading session

        Optimization: Skips all checks (including cache operations) for symbols
        not in active trading session to reduce unnecessary MT5 API calls.
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
            # OPTIMIZATION: Skip all session-end checks for symbols not in active session
            # This avoids unnecessary cache operations and MT5 API calls for closed markets
            if not self._is_symbol_in_active_session(symbol):
                # Symbol is not in active trading session, skip session-end check entirely
                # No need to check for CLOSEONLY mode if market is already closed
                continue

            # Symbol is in active session, check if it's about to close (CLOSEONLY mode)
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
        """
        Monitor all positions and check for closed trades.

        In LIVE mode: Runs every 5 seconds with time.sleep(5)
        In BACKTEST mode: Runs on every time step synchronized with symbol threads
        """
        self.logger.info("Position monitor thread started")

        # Track known positions
        known_positions = set()

        # Track last statistics log time (only needed in live mode)
        if not self.is_backtest_mode:
            last_stats_log = datetime.now(timezone.utc)

        # Backtest: Track steps to run position monitor less frequently
        step_counter = 0

        while self.running:
            try:
                # LIVE MODE: Check AutoTrading
                if not self.is_backtest_mode:
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

                # BACKTEST MODE: Update positions with current prices and check SL/TP
                # ONLY in CANDLE mode - TICK mode already checks SL/TP in advance_global_time_tick_by_tick
                if self.is_backtest_mode and not getattr(self.connector, 'use_tick_data', False):
                    # Call SimulatedBroker's update_positions to:
                    # 1. Update all position profits with current prices
                    # 2. Check for SL/TP hits and close positions automatically
                    # NOTE: In tick mode, this is handled by _check_sl_tp_for_tick() during time advancement
                    self.connector.update_positions()

                    # Get fresh position list after update_positions() may have closed some
                    positions = self.connector.get_positions(
                        magic_number=config.advanced.magic_number
                    )

                # Manage positions (breakeven and trailing stops) - works in both live and backtest
                if positions:
                    self.trade_manager.manage_positions(positions)

                # LIVE MODE ONLY: Close positions before session end
                if positions and not self.is_backtest_mode:
                    # Close positions if the session is about to end
                    self._close_positions_before_session_end(positions)

                # Log statistics periodically (only in live mode)
                if not self.is_backtest_mode:
                    current_time = datetime.now(timezone.utc)
                    if current_time and last_stats_log and (current_time - last_stats_log).total_seconds() >= 10:
                        self._log_position_statistics(positions)
                        last_stats_log = current_time

                # BACKTEST MODE: Wait at barrier
                if self.is_backtest_mode:
                    # Position monitor participates in barrier synchronization
                    # Use a special "position_monitor" identifier
                    if not self.time_controller.wait_for_next_step("position_monitor"):
                        # TimeController stopped
                        break

                    step_counter += 1

                # LIVE MODE: Sleep for 5 seconds
                else:
                    time.sleep(5)

            except Exception as e:
                self.logger.error(f"Error in position monitor: {e}")
                if not self.is_backtest_mode:
                    time.sleep(10)
                else:
                    # In backtest, just log and continue
                    pass

        self.logger.info("Position monitor thread stopped")

        # BACKTEST MODE: Remove position monitor from the barrier
        if self.is_backtest_mode:
            self.time_controller.remove_participant("position_monitor")

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

        # Wait for all trading threads to finish
        for symbol, thread in self.threads.items():
            self.logger.info(f"Waiting for {symbol} thread to stop...", symbol)
            thread.join(timeout=5)

        # Wait for all background monitor threads to finish
        with self.lock:
            monitor_threads = list(self.background_monitor_threads.items())

        for symbol, thread in monitor_threads:
            self.logger.info(f"Waiting for {symbol} background monitor to stop...", symbol)
            thread.join(timeout=5)

        # Shutdown all strategies
        for symbol, strategy in self.strategies.items():
            strategy.shutdown()

        self.logger.info("Trading controller stopped")

    def get_status(self) -> dict:
        """
        Get status of all strategies.

        Returns:
            Dictionary with status for each symbol and pending symbols
        """
        with self.lock:
            status = {
                'active_symbols': {
                    symbol: strategy.get_status()
                    for symbol, strategy in self.strategies.items()
                },
                'pending_symbols': list(self.pending_symbols),
                'total_active': len(self.strategies),
                'total_pending': len(self.pending_symbols)
            }
            return status



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

