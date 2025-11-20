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
        # Compute start time OUTSIDE lock to avoid potential lock inversion with broker locks
        computed_start_time: Optional[datetime] = start_time
        if computed_start_time is None:
            try:
                computed_start_time = time_getter() or datetime.now(timezone.utc)
            except Exception:
                # In case time_getter raises (e.g., during early init), fallback to now
                computed_start_time = datetime.now(timezone.utc)

        # Now set mode and fields atomically
        with self._lock:
            self._mode = "backtest"
            self._simulated_time_getter = time_getter
            self._backtest_start_time = computed_start_time

        # Notify logger to recreate file handlers for new log directory
        self._notify_mode_change()
    
    def get_current_time(self) -> datetime:
        """
        Get current time based on mode.
        
        Returns:
            Current time (real or simulated)
        """
        # Snapshot mode and getter to avoid holding provider lock while invoking callback
        with self._lock:
            mode = self._mode
            getter = self._simulated_time_getter

        if mode == "backtest" and getter is not None:
            try:
                simulated_time = getter()
                if simulated_time is not None:
                    return simulated_time
            except Exception:
                # Ignore getter errors and fall back to real time
                pass

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
        # Snapshot state to avoid holding provider lock while invoking callback
        with self._lock:
            mode = self._mode
            getter = self._simulated_time_getter
            start_time_snapshot = self._backtest_start_time

        # Determine current time based on mode without holding TimeProvider lock
        if mode == "backtest":
            current_time: datetime
            if getter is not None:
                try:
                    simulated_time = getter()
                except Exception:
                    simulated_time = None
                if simulated_time is not None:
                    current_time = simulated_time
                elif start_time_snapshot is not None:
                    # Backtest hasn't started yet, use backtest start time
                    current_time = start_time_snapshot
                else:
                    # Fallback to current time (shouldn't happen)
                    current_time = datetime.now(timezone.utc)
            elif start_time_snapshot is not None:
                # No time getter, use backtest start time
                current_time = start_time_snapshot
            else:
                # Fallback to current time (shouldn't happen)
                current_time = datetime.now(timezone.utc)

            # Format date and return backtest log directory
            date_str = current_time.strftime("%Y-%m-%d")
            return Path("logs") / "backtest" / date_str
        else:
            # Live mode: use real time
            current_time = datetime.now(timezone.utc)
            date_str = current_time.strftime("%Y-%m-%d")
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

