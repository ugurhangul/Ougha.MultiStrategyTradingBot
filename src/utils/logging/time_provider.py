"""
Time provider for logging system.

Provides a global time source that can be switched between real-time (for live trading)
and simulated time (for backtesting). This allows log messages to show the correct
historical timestamp during backtesting.
"""
from datetime import datetime, timezone
from typing import Optional, Callable
from pathlib import Path
import threading


class TimeProvider:
    """
    Global time provider for logging system.

    In live trading mode: Returns current system time and uses logs/live/ directory
    In backtest mode: Returns simulated time from SimulatedBroker and uses logs/backtest/<timestamp>/ directory
    """

    def __init__(self):
        """Initialize time provider in live mode."""
        self._mode = "live"
        self._simulated_time_getter: Optional[Callable[[], Optional[datetime]]] = None
        self._backtest_start_time: Optional[datetime] = None
        self._lock = threading.Lock()
    
    def set_live_mode(self):
        """Set time provider to live mode (uses system time and logs/live/ directory)."""
        with self._lock:
            self._mode = "live"
            self._simulated_time_getter = None
            self._backtest_start_time = None

        # Notify logger to recreate file handlers for new log directory
        self._notify_mode_change()

    def set_backtest_mode(self, time_getter: Callable[[], Optional[datetime]], start_time: Optional[datetime] = None):
        """
        Set time provider to backtest mode (uses simulated time and logs/backtest/<timestamp>/ directory).

        Args:
            time_getter: Callable that returns the current simulated time (e.g., SimulatedBroker.get_current_time)
            start_time: Backtest start time (used for log directory naming). If None, uses current simulated time.
        """
        with self._lock:
            self._mode = "backtest"
            self._simulated_time_getter = time_getter
            # Use provided start_time or get from time_getter or fallback to current time
            if start_time:
                self._backtest_start_time = start_time
            else:
                # Try to get from time_getter
                simulated_time = time_getter()
                if simulated_time:
                    self._backtest_start_time = simulated_time
                else:
                    self._backtest_start_time = datetime.now(timezone.utc)

        # Notify logger to recreate file handlers for new log directory
        self._notify_mode_change()
    
    def get_current_time(self) -> datetime:
        """
        Get current time based on mode.
        
        Returns:
            Current time (real or simulated)
        """
        with self._lock:
            if self._mode == "backtest" and self._simulated_time_getter is not None:
                simulated_time = self._simulated_time_getter()
                if simulated_time is not None:
                    return simulated_time
            
            # Fallback to real time
            return datetime.now(timezone.utc)
    
    def is_backtest_mode(self) -> bool:
        """Check if currently in backtest mode."""
        with self._lock:
            return self._mode == "backtest"

    def get_log_directory(self) -> Path:
        """
        Get the appropriate log directory based on mode.

        Returns:
            Path: logs/live/YYYY-MM-DD/ for live mode, logs/backtest/YYYY-MM-DD/ for backtest mode
        """
        with self._lock:
            # Get current time (real or simulated) - must be done inside lock
            if self._mode == "backtest":
                # In backtest mode, use simulated time if available, otherwise use backtest start time
                if self._simulated_time_getter is not None:
                    simulated_time = self._simulated_time_getter()
                    if simulated_time is not None:
                        current_time = simulated_time
                    elif self._backtest_start_time is not None:
                        # Backtest hasn't started yet, use backtest start time
                        current_time = self._backtest_start_time
                    else:
                        # Fallback to current time (shouldn't happen)
                        current_time = datetime.now(timezone.utc)
                elif self._backtest_start_time is not None:
                    # No time getter, use backtest start time
                    current_time = self._backtest_start_time
                else:
                    # Fallback to current time (shouldn't happen)
                    current_time = datetime.now(timezone.utc)
            else:
                # Live mode: use real time
                current_time = datetime.now(timezone.utc)

            # Format date as YYYY-MM-DD
            date_str = current_time.strftime("%Y-%m-%d")

            if self._mode == "backtest":
                # Backtest mode: logs/backtest/YYYY-MM-DD/
                return Path("logs") / "backtest" / date_str
            else:
                # Live mode: logs/live/YYYY-MM-DD/
                return Path("logs") / "live" / date_str

    def _notify_mode_change(self):
        """
        Notify the global logger that the mode has changed.

        This triggers recreation of file handlers to use the new log directory.
        """
        # Import here to avoid circular dependency
        from src.utils.logging.logger_factory import get_logger

        try:
            logger = get_logger()
            # Access the log_dir property to trigger recreation of file handlers
            _ = logger.log_dir
        except Exception:
            # Logger might not be initialized yet, which is fine
            pass


# Global time provider instance
_time_provider = TimeProvider()


def get_time_provider() -> TimeProvider:
    """Get the global time provider instance."""
    return _time_provider


def set_live_mode():
    """Set global time provider to live mode."""
    _time_provider.set_live_mode()


def set_backtest_mode(time_getter: Callable[[], Optional[datetime]], start_time: Optional[datetime] = None):
    """
    Set global time provider to backtest mode.

    Args:
        time_getter: Callable that returns the current simulated time
        start_time: Backtest start time (used for log directory naming). If None, uses current simulated time.
    """
    _time_provider.set_backtest_mode(time_getter, start_time)


def get_current_time() -> datetime:
    """
    Get current time from global time provider.

    Returns:
        Current time (real or simulated based on mode)
    """
    return _time_provider.get_current_time()


def get_log_directory() -> Path:
    """
    Get the appropriate log directory from global time provider.

    Returns:
        Path: logs/live/YYYY-MM-DD/ for live mode, logs/backtest/YYYY-MM-DD/ for backtest mode
    """
    return _time_provider.get_log_directory()


def is_backtest_mode() -> bool:
    """
    Check if global time provider is in backtest mode.

    Returns:
        bool: True if in backtest mode, False otherwise
    """
    return _time_provider.is_backtest_mode()

