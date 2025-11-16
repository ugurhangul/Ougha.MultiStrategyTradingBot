"""
Custom formatters for the logging system.
"""
import logging
from datetime import datetime, timezone

from src.utils.logging.time_provider import get_current_time


class UTCFormatter(logging.Formatter):
    """
    Custom formatter that uses UTC time for all log messages.

    In live trading mode: Uses real system time
    In backtest mode: Uses simulated time from SimulatedBroker
    """

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

