"""
Custom formatters for the logging system.
"""
import logging
from datetime import datetime, timezone


class UTCFormatter(logging.Formatter):
    """Custom formatter that uses UTC time for all log messages"""

    def formatTime(self, record, datefmt=None):
        """Override formatTime to use UTC"""
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            s = dt.isoformat(timespec='seconds')
        return s

