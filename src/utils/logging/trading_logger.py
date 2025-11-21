"""
Main trading logger class.
"""
import logging
import logging.handlers
import threading
import queue
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict
import colorlog

from src.utils.logging.formatters import UTCFormatter
from src.utils.logging.time_provider import get_current_time, get_log_directory


class TradingLogger:
    """Custom logger for trading operations"""

    def __init__(self, name: str = "TradingBot", log_to_file: bool = True,
                 log_to_console: bool = True, log_level: str = "INFO",
                 enable_detailed: bool = True, backtest_date: Optional[datetime] = None,
                 use_async_logging: bool = True):
        """
        Initialize the trading logger.

        Args:
            name: Logger name
            log_to_file: Enable file logging
            log_to_console: Enable console logging
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            enable_detailed: Enable detailed logging
            backtest_date: Optional datetime for backtesting (uses this date instead of current date for log files)
            use_async_logging: Enable async logging (background thread for I/O) - PERFORMANCE OPTIMIZATION
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, log_level.upper()))
        self.logger.handlers.clear()  # Clear existing handlers

        self.enable_detailed = enable_detailed
        self.symbol_handlers: Dict[str, logging.FileHandler] = {}
        self.disable_log_handler: Optional[logging.FileHandler] = None
        self.disabled_symbols: set = set()  # Track disabled symbols to avoid duplicates
        self.backtest_date = backtest_date  # Store backtest date for log file naming (deprecated, use time_provider)
        self._log_to_file = log_to_file  # Store flag for later use
        self._log_to_console = log_to_console  # Store flag for later use
        self._log_level = log_level  # Store log level for later use
        self._current_log_dir: Optional[Path] = None  # Track current log directory
        self._master_file_handler: Optional[logging.FileHandler] = None  # Track master file handler
        self._console_handler: Optional[logging.Handler] = None  # Track console handler
        self._lock = threading.RLock()  # Protect handler (re)creation against races

        # PERFORMANCE OPTIMIZATION: Async logging support
        self._use_async_logging = use_async_logging
        self._log_queue: Optional[queue.Queue] = None
        self._queue_handler: Optional[logging.handlers.QueueHandler] = None
        self._queue_listener: Optional[logging.handlers.QueueListener] = None
        self._actual_handlers: list = []  # Store actual handlers for queue listener

        # Disable propagation to avoid duplicate logs from parent loggers
        self.logger.propagate = False

        # Create custom colored formatter with UTC (or simulated time in backtest mode)
        class UTCColoredFormatter(colorlog.ColoredFormatter):
            def formatTime(self, record, datefmt=None):
                """
                Override formatTime to use time from global time provider.

                This allows logs to show simulated time during backtesting
                instead of the current system time.
                """
                # Get time from global time provider (real or simulated)
                dt = get_current_time()

                if datefmt:
                    s = dt.strftime(datefmt)
                else:
                    s = dt.isoformat(timespec='seconds')
                return s

        # Store the formatter class for later use
        self._UTCColoredFormatter = UTCColoredFormatter

        # PERFORMANCE OPTIMIZATION: Setup async logging if enabled
        if self._use_async_logging:
            self._setup_async_logging()

        # Setup console handler
        self._setup_console_handler()

        # Create logs directory and file handlers if file logging is enabled
        if log_to_file:
            self._setup_file_handlers()


    @property
    def log_dir(self) -> Path:
        """
        Get the current log directory dynamically.

        This property evaluates the log directory at access time, allowing it to
        change when switching between live and backtest modes, or when the date
        changes (midnight crossing). If the directory changes, file handlers are
        recreated automatically.

        Returns:
            Path: Current log directory (logs/live/YYYY-MM-DD/ or logs/backtest/YYYY-MM-DD/)
        """
        current_dir = get_log_directory()

        # Check if log directory has changed (e.g., switched modes or date changed)
        if self._log_to_file and self._current_log_dir != current_dir:
            # Log directory changed - recreate file handlers
            self._setup_file_handlers()

        return current_dir

    def _setup_async_logging(self):
        """
        Setup async logging using QueueHandler and QueueListener.

        PERFORMANCE OPTIMIZATION: This moves all I/O operations to a background thread,
        preventing logging from blocking the main tick processing loop.

        Expected speedup: 1.13x-1.25x (13-25% faster) by eliminating I/O blocking.
        """
        with self._lock:
            # Create queue for log records (unbounded for safety)
            self._log_queue = queue.Queue(-1)

            # Create QueueHandler that will be added to the logger
            # This handler just puts log records into the queue (very fast, no I/O)
            self._queue_handler = logging.handlers.QueueHandler(self._log_queue)
            self._queue_handler.setLevel(logging.DEBUG)  # Accept all levels

            # Add queue handler to logger
            # All log calls will now go through this handler first
            self.logger.addHandler(self._queue_handler)

    def _start_queue_listener(self):
        """
        Start the queue listener with actual handlers.

        This should be called AFTER all actual handlers (file, console) are created.
        The listener runs in a background thread and processes log records from the queue.
        """
        with self._lock:
            # Stop existing listener if any
            if self._queue_listener is not None:
                self._queue_listener.stop()
                self._queue_listener = None

            # Only start if we have handlers and async logging is enabled
            if not self._use_async_logging or not self._actual_handlers:
                return

            # Create and start queue listener with all actual handlers
            # The listener will run in a background thread and write to these handlers
            self._queue_listener = logging.handlers.QueueListener(
                self._log_queue,
                *self._actual_handlers,
                respect_handler_level=True  # Respect each handler's level
            )
            self._queue_listener.start()

    def _setup_console_handler(self):
        """
        Setup or recreate console handler.

        This method is called during initialization.
        """
        with self._lock:
            # Remove old console handler from actual handlers list
            if self._console_handler:
                if self._console_handler in self._actual_handlers:
                    self._actual_handlers.remove(self._console_handler)
                # Only remove from logger if NOT using async logging
                if not self._use_async_logging:
                    try:
                        self.logger.removeHandler(self._console_handler)
                    except:
                        pass
                self._console_handler = None

            # Create console handler with colors (still using UTC)
            if self._log_to_console:
                # Full console logging - all levels
                console_handler = colorlog.StreamHandler()
                console_handler.setLevel(getattr(logging, self._log_level.upper()))

                console_formatter = self._UTCColoredFormatter(
                    '%(log_color)s%(asctime)s UTC | %(levelname)-8s | %(message)s',
                    datefmt='%H:%M:%S',
                    log_colors={
                        'DEBUG': 'cyan',
                        'INFO': 'white',
                        'WARNING': 'yellow',
                        'ERROR': 'red',
                        'CRITICAL': 'red,bg_white',
                    }
                )
                console_handler.setFormatter(console_formatter)

                # PERFORMANCE OPTIMIZATION: Add to actual handlers for async logging
                if self._use_async_logging:
                    self._actual_handlers.append(console_handler)
                else:
                    self.logger.addHandler(console_handler)

                self._console_handler = console_handler
            else:
                # Console logging disabled, but ALWAYS show errors and critical
                console_handler = colorlog.StreamHandler()
                console_handler.setLevel(logging.ERROR)  # Only ERROR and CRITICAL

                console_formatter = self._UTCColoredFormatter(
                    '%(log_color)s%(asctime)s UTC | %(levelname)-8s | %(message)s',
                    datefmt='%H:%M:%S',
                    log_colors={
                        'ERROR': 'red',
                        'CRITICAL': 'red,bg_white',
                    }
                )
                console_handler.setFormatter(console_formatter)

                # PERFORMANCE OPTIMIZATION: Add to actual handlers for async logging
                if self._use_async_logging:
                    self._actual_handlers.append(console_handler)
                else:
                    self.logger.addHandler(console_handler)

                self._console_handler = console_handler

    def _setup_file_handlers(self):
        """
        Setup or recreate file handlers for the current log directory.

        This method is called:
        1. During initialization
        2. When the log directory changes (e.g., switching from live to backtest mode)
        """
        with self._lock:
            # Get current log directory
            log_dir = get_log_directory()

            # If directory hasn't changed, no need to recreate handlers
            if self._current_log_dir == log_dir:
                return

            # Update current log directory
            self._current_log_dir = log_dir

            # Create log directory if it doesn't exist
            log_dir.mkdir(parents=True, exist_ok=True)

            # Remove old master file handler if it exists
            if self._master_file_handler:
                # Remove from actual handlers list
                if self._master_file_handler in self._actual_handlers:
                    self._actual_handlers.remove(self._master_file_handler)
                # Only remove from logger if NOT using async logging
                if not self._use_async_logging:
                    try:
                        self.logger.removeHandler(self._master_file_handler)
                    except:
                        pass
                try:
                    self._master_file_handler.close()
                except:
                    pass
                self._master_file_handler = None

            # Create new master log file handler: logs/<mode>/main.log
            master_log_file = log_dir / "main.log"

            # Proactively remove any existing handler targeting the same file (safety against races)
            if not self._use_async_logging:
                for h in list(self.logger.handlers):
                    try:
                        if isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', None):
                            if Path(h.baseFilename) == master_log_file.resolve():
                                self.logger.removeHandler(h)
                                try:
                                    h.close()
                                except Exception:
                                    pass
                    except Exception:
                        # Be robust; ignore issues inspecting handlers
                        pass

            # PERFORMANCE OPTIMIZATION: Use buffered I/O for 2-3x speedup
            self._master_file_handler = logging.FileHandler(master_log_file, encoding='utf-8')
            self._master_file_handler.stream = open(master_log_file, 'a', encoding='utf-8', buffering=8192)
            self._master_file_handler.setLevel(logging.DEBUG)

            # Use UTC formatter for file logs
            file_formatter = UTCFormatter(
                '%(asctime)s UTC | %(levelname)-8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            self._master_file_handler.setFormatter(file_formatter)

            # PERFORMANCE OPTIMIZATION: Add to actual handlers for async logging
            if self._use_async_logging:
                self._actual_handlers.append(self._master_file_handler)
            else:
                self.logger.addHandler(self._master_file_handler)

            # Remove old disable log handler if it exists
            if self.disable_log_handler:
                try:
                    self.disable_log_handler.close()
                except:
                    pass
                self.disable_log_handler = None

            # Create new disable log file: logs/<mode>/disable.log
            disable_log_file = log_dir / "disable.log"
            # PERFORMANCE OPTIMIZATION: Use buffered I/O
            self.disable_log_handler = logging.FileHandler(disable_log_file, encoding='utf-8')
            self.disable_log_handler.stream = open(disable_log_file, 'a', encoding='utf-8', buffering=8192)
            self.disable_log_handler.setLevel(logging.INFO)
            self.disable_log_handler.setFormatter(file_formatter)
            # Note: disable_log_handler is NOT added to logger or actual_handlers
            # It's used directly in disable_symbol() method

            # Clear symbol handlers (they will be recreated on demand with new paths)
            for handler in self.symbol_handlers.values():
                try:
                    handler.close()
                except Exception:
                    pass
            self.symbol_handlers.clear()

            # PERFORMANCE OPTIMIZATION: Start queue listener with updated handlers
            if self._use_async_logging:
                self._start_queue_listener()

    def _check_date_change(self):
        """
        Check if the log directory has changed (e.g., date changed at midnight).

        This method should be called before each log operation to ensure that
        file handlers are recreated when the date changes.
        """
        # Access log_dir property to trigger date change detection
        _ = self.log_dir

    def _get_symbol_handler(self, symbol: str) -> Optional[logging.FileHandler]:
        """
        Get or create a file handler for a specific symbol.

        Args:
            symbol: Trading symbol name

        Returns:
            File handler for the symbol, or None if file logging is disabled
        """
        with self._lock:
            # Check if handler already exists
            existing = self.symbol_handlers.get(symbol)
            if existing is not None:
                return existing

            # Create new handler for this symbol
            try:
                # Get log directory from time provider (logs/live/YYYY-MM-DD/ or logs/backtest/YYYY-MM-DD/)
                log_dir = get_log_directory()
                log_dir.mkdir(parents=True, exist_ok=True)

                # Create symbol-specific log file: logs/<mode>/YYYY-MM-DD/SYMBOL.log
                log_file = log_dir / f"{symbol}.log"

                # PERFORMANCE OPTIMIZATION: Use buffered I/O for 2-3x speedup
                # Buffer size: 8KB (default is unbuffered for FileHandler)
                handler = logging.FileHandler(log_file, encoding='utf-8')
                handler.stream = open(log_file, 'a', encoding='utf-8', buffering=8192)
                handler.setLevel(logging.DEBUG)

                # Use UTC formatter
                formatter = UTCFormatter(
                    '%(asctime)s UTC | %(levelname)-8s | %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                handler.setFormatter(formatter)

                # Store handler
                self.symbol_handlers[symbol] = handler

                return handler
            except Exception as e:
                self.logger.error(f"Failed to create log handler for {symbol}: {e}")
                return None

    def _log_to_symbol_file(self, level: int, message: str, symbol: str):
        """
        Log a message to a symbol-specific file.

        Args:
            level: Logging level
            message: Log message
            symbol: Trading symbol
        """
        handler = self._get_symbol_handler(symbol)
        if handler:
            # Create a log record
            record = self.logger.makeRecord(
                self.logger.name,
                level,
                "(symbol_log)",
                0,
                message,
                (),
                None
            )
            handler.emit(record)

    def info(self, message: str, symbol: Optional[str] = None, strategy_key: Optional[str] = None):
        """Log info message"""
        self._check_date_change()
        if symbol:
            # Log to symbol-specific file
            self._log_to_symbol_file(logging.INFO, message, symbol)
            # Add symbol prefix for master log
            if strategy_key:
                message = f"[{symbol}] [{strategy_key}] {message}"
            else:
                message = f"[{symbol}] {message}"
        elif strategy_key:
            # Add strategy key prefix even without symbol
            message = f"[{strategy_key}] {message}"
        self.logger.info(message)

    def debug(self, message: str, symbol: Optional[str] = None, strategy_key: Optional[str] = None):
        """Log debug message (only if detailed logging enabled)"""
        self._check_date_change()
        if self.enable_detailed:
            if symbol:
                # Log to symbol-specific file
                self._log_to_symbol_file(logging.DEBUG, message, symbol)
                # Add symbol prefix for master log
                if strategy_key:
                    message = f"[{symbol}] [{strategy_key}] {message}"
                else:
                    message = f"[{symbol}] {message}"
            elif strategy_key:
                # Add strategy key prefix even without symbol
                message = f"[{strategy_key}] {message}"
            self.logger.debug(message)

    def warning(self, message: str, symbol: Optional[str] = None, strategy_key: Optional[str] = None):
        """Log warning message"""
        self._check_date_change()
        if symbol:
            # Log to symbol-specific file
            self._log_to_symbol_file(logging.WARNING, message, symbol)
            # Add symbol prefix for master log
            if strategy_key:
                message = f"[{symbol}] [{strategy_key}] {message}"
            else:
                message = f"[{symbol}] {message}"
        elif strategy_key:
            # Add strategy key prefix even without symbol
            message = f"[{strategy_key}] {message}"
        self.logger.warning(message)

    def error(self, message: str, symbol: Optional[str] = None, strategy_key: Optional[str] = None):
        """Log error message"""
        self._check_date_change()
        if symbol:
            # Log to symbol-specific file
            self._log_to_symbol_file(logging.ERROR, message, symbol)
            # Add symbol prefix for master log
            if strategy_key:
                message = f"[{symbol}] [{strategy_key}] {message}"
            else:
                message = f"[{symbol}] {message}"
        elif strategy_key:
            # Add strategy key prefix even without symbol
            message = f"[{strategy_key}] {message}"
        self.logger.error(message)

    def critical(self, message: str, symbol: Optional[str] = None, strategy_key: Optional[str] = None):
        """Log critical message"""
        self._check_date_change()
        if symbol:
            # Log to symbol-specific file
            self._log_to_symbol_file(logging.CRITICAL, message, symbol)
            # Add symbol prefix for master log
            if strategy_key:
                message = f"[{symbol}] [{strategy_key}] {message}"
            else:
                message = f"[{symbol}] {message}"
        elif strategy_key:
            # Add strategy key prefix even without symbol
            message = f"[{strategy_key}] {message}"
        self.logger.critical(message)

    def separator(self, char: str = "=", length: int = 60):
        """Log a separator line"""
        self.logger.info(char * length)

    def header(self, title: str, width: int = 60):
        """Log a formatted header"""
        self.separator("=", width)
        padding = (width - len(title) - 2) // 2
        self.logger.info(f"{'=' * padding} {title} {'=' * padding}")
        self.separator("=", width)

    def box(self, title: str, lines: list[str], width: int = 60):
        """Log a formatted box with title and content"""
        self.logger.info("╔" + "═" * (width - 2) + "╗")

        # Title
        title_padding = width - len(title) - 4
        self.logger.info(f"║  {title}{' ' * title_padding}║")

        self.logger.info("╚" + "═" * (width - 2) + "╝")

        # Content
        for line in lines:
            self.logger.info(line)

    def trade_signal(self, signal_type: str, symbol: str, entry: float,
                    sl: float, tp: float, lot_size: float):
        """Log a trade signal"""
        self.header(f"{signal_type} SIGNAL - {symbol}")
        self.info(f"Entry Price: {entry:.5f}")
        self.info(f"Stop Loss: {sl:.5f}")
        self.info(f"Take Profit: {tp:.5f}")
        self.info(f"Lot Size: {lot_size:.2f}")
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = reward / risk if risk > 0 else 0
        self.info(f"Risk: {risk:.5f} | Reward: {reward:.5f} | R:R: {rr:.2f}")
        self.separator()

    def position_opened(self, ticket: int, symbol: str, position_type: str,
                       volume: float, price: float, sl: float, tp: float):
        """Log position opened"""
        self.header(f"POSITION OPENED - {symbol}")
        self.info(f"Ticket: {ticket}")
        self.info(f"Type: {position_type}")
        self.info(f"Volume: {volume:.2f}")
        self.info(f"Price: {price:.5f}")
        self.info(f"SL: {sl:.5f} | TP: {tp:.5f}")
        self.separator()

    def position_closed(self, ticket: int, symbol: str, profit: float,
                       is_win: bool, rr_achieved: float):
        """Log position closed"""
        result = "WIN" if is_win else "LOSS"
        self.header(f"POSITION CLOSED - {result}")
        self.info(f"Ticket: {ticket} | Symbol: {symbol}")
        self.info(f"Profit: ${profit:.2f}")
        self.info(f"R:R Achieved: {rr_achieved:.2f}")
        self.separator()

    def symbol_disabled(self, symbol: str, reason: str, stats: Optional[dict] = None):
        """
        Log symbol disabled event.

        Args:
            symbol: Symbol name
            reason: Reason for disabling
            stats: Optional statistics dictionary
        """
        # Check if symbol is already in disabled set (avoid duplicate logging)
        if symbol in self.disabled_symbols:
            return

        # Add to disabled set
        self.disabled_symbols.add(symbol)

        # Prepare log message
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        message = f"[{symbol}] DISABLED | Reason: {reason}"

        # Log to main log
        self.info(f"Symbol disabled: {reason}", symbol)

        # Log to disable.log
        if self.disable_log_handler:
            record = self.logger.makeRecord(
                self.logger.name,
                logging.INFO,
                "(disable_log)",
                0,
                message,
                (),
                None
            )
            self.disable_log_handler.emit(record)

        # Log detailed box if stats provided
        if stats:
            lines = [
                f"Reason: {reason}",
                "",
                "Statistics:",
                f"  Total Trades: {stats.get('total_trades', 0)}",
                f"  Wins: {stats.get('wins', 0)} ({stats.get('win_rate', 0):.1f}%)",
                f"  Losses: {stats.get('losses', 0)}",
                f"  Net P&L: ${stats.get('net_pnl', 0):.2f}",
                f"  Consecutive Losses: {stats.get('consecutive_losses', 0)}",
                f"  Current Drawdown: {stats.get('current_drawdown', 0):.2f}%",
                f"  Max Drawdown: {stats.get('max_drawdown', 0):.2f}%",
                "",
                f"Re-enable Date: {stats.get('reenable_date', 'N/A')}"
            ]
            self.box(f"SYMBOL DISABLED: {symbol}", lines)

    def symbol_reenabled(self, symbol: str, old_stats: Optional[dict] = None):
        """
        Log symbol re-enabled event.

        Args:
            symbol: Symbol name
            old_stats: Optional previous statistics dictionary
        """
        # Remove from disabled set
        self.disabled_symbols.discard(symbol)

        # Prepare log message
        message = f"[{symbol}] RE-ENABLED | Cooling period expired"

        # Log to main log
        self.info("Symbol re-enabled after cooling period", symbol)

        # Log to disable.log
        if self.disable_log_handler:
            record = self.logger.makeRecord(
                self.logger.name,
                logging.INFO,
                "(disable_log)",
                0,
                message,
                (),
                None
            )
            self.disable_log_handler.emit(record)

        # Log detailed box if stats provided
        if old_stats:
            lines = [
                "Reason: Cooling period expired",
                "",
                "Previous Performance:",
                f"  Total Trades: {old_stats.get('total_trades', 0)}",
                f"  Net P&L: ${old_stats.get('net_pnl', 0):.2f}",
                f"  Disable Reason: {old_stats.get('disable_reason', 'N/A')}",
                "",
                "Statistics: RESET",
                "Status: Ready to trade"
            ]
            self.box(f"SYMBOL RE-ENABLED: {symbol}", lines)

    def trade_error(self, symbol: str, error_type: str, error_message: str,
                   context: Optional[dict] = None, remove_from_active_set: bool = True):
        """
        Log trade execution or data retrieval error with comprehensive details.
        Optionally removes symbol from active.set if error is persistent.

        Args:
            symbol: Symbol name
            error_type: Type of error (e.g., "Trade Execution", "Data Retrieval", "Spread Check")
            error_message: Specific error message or exception
            context: Optional context dictionary with additional details
            remove_from_active_set: Whether to check if symbol should be removed from active.set
        """
        # Build error message
        message = f"{error_type} Error: {error_message}"

        # Log to main error log
        self.error(message, symbol)

        # Log detailed context if provided
        if context:
            for key, value in context.items():
                self.error(f"  {key}: {value}", symbol)

        # Check if symbol should be removed from active.set
        if remove_from_active_set:
            try:
                from src.utils.active_set_manager import get_active_set_manager

                manager = get_active_set_manager()
                if manager.should_remove_symbol(error_message):
                    # Remove from active.set
                    if manager.remove_symbol(symbol, f"{error_type}: {error_message}", self):
                        self.warning(
                            f"Symbol removed from active.set due to persistent error: {error_message}",
                            symbol
                        )
            except Exception:
                # Don't crash if active set manager fails
                pass

    def spread_warning(self, symbol: str, current_spread_percent: float,
                      current_spread_points: float, threshold_percent: float,
                      is_rejected: bool = False, remove_from_active_set: bool = True):
        """
        Log spread-related warnings.
        Optionally removes symbol from active.set if spread is consistently too high.

        Args:
            symbol: Symbol name
            current_spread_percent: Current spread as percentage
            current_spread_points: Current spread in points
            threshold_percent: Maximum allowed spread percentage
            is_rejected: Whether trade was rejected due to spread
            remove_from_active_set: Whether to check if symbol should be removed from active.set
        """
        status = "REJECTED" if is_rejected else "WARNING"
        message = (
            f"Spread {status}: {current_spread_percent:.3f}% ({current_spread_points:.1f} points) "
            f"| Threshold: {threshold_percent:.3f}%"
        )

        if is_rejected:
            self.warning(message, symbol)

            # Remove from active.set if spread is rejected
            if remove_from_active_set:
                try:
                    from src.utils.active_set_manager import get_active_set_manager

                    manager = get_active_set_manager()
                    error_msg = f"Spread too high: {current_spread_percent:.3f}% (max: {threshold_percent:.3f}%)"

                    if manager.remove_symbol(symbol, error_msg, self):
                        self.warning(
                            f"Symbol removed from active.set due to excessive spread",
                            symbol
                        )
                except Exception:
                    # Don't crash if active set manager fails
                    pass
        else:
            self.warning(f"Elevated spread: {message}", symbol)

    def liquidity_warning(self, symbol: str, volume: float, avg_volume: float,
                         reason: str):
        """
        Log liquidity or volume warnings.

        Args:
            symbol: Symbol name
            volume: Current volume
            avg_volume: Average volume
            reason: Reason for warning
        """
        message = (
            f"Liquidity Warning: {reason} | "
            f"Current Volume: {volume:.0f} | Average: {avg_volume:.0f}"
        )
        self.warning(message, symbol)

    def symbol_condition_warning(self, symbol: str, condition: str, details: str,
                                remove_from_active_set: bool = True):
        """
        Log general symbol-specific condition warnings.
        Optionally removes symbol from active.set for persistent conditions.

        Args:
            symbol: Symbol name
            condition: Condition type (e.g., "Market Hours", "Trading Disabled")
            details: Additional details about the condition
            remove_from_active_set: Whether to check if symbol should be removed from active.set
        """
        message = f"{condition}: {details}"
        self.warning(message, symbol)

        # Remove from active.set if trading is disabled
        if remove_from_active_set and "Trading Disabled" in condition:
            try:
                from src.utils.active_set_manager import get_active_set_manager

                manager = get_active_set_manager()
                error_msg = f"{condition}: {details}"

                if manager.remove_symbol(symbol, error_msg, self):
                    self.warning(
                        f"Symbol removed from active.set: {condition}",
                        symbol
                    )
            except Exception:
                # Don't crash if active set manager fails
                pass

    def shutdown(self):
        """
        Shutdown the logger and cleanup resources.

        PERFORMANCE OPTIMIZATION: Properly stop the queue listener to ensure
        all pending log records are flushed before shutdown.
        """
        with self._lock:
            # Stop queue listener if running
            if self._queue_listener is not None:
                self._queue_listener.stop()
                self._queue_listener = None

            # Close all file handlers
            if self._master_file_handler:
                try:
                    self._master_file_handler.close()
                except:
                    pass
                self._master_file_handler = None

            if self.disable_log_handler:
                try:
                    self.disable_log_handler.close()
                except:
                    pass
                self.disable_log_handler = None

            for handler in self.symbol_handlers.values():
                try:
                    handler.close()
                except:
                    pass
            self.symbol_handlers.clear()

            # Clear actual handlers list
            self._actual_handlers.clear()

    def __del__(self):
        """Destructor to ensure cleanup on garbage collection."""
        try:
            self.shutdown()
        except:
            pass

