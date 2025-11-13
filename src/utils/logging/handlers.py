"""
Custom handlers for the logging system.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path


class SymbolFileHandler(logging.FileHandler):
    """File handler for symbol-specific logs"""

    def __init__(self, symbol: str, log_dir: Path):
        """
        Initialize symbol-specific file handler.

        Args:
            symbol: Trading symbol name
            log_dir: Base log directory
        """
        self.symbol = symbol
        self.log_dir = log_dir

        # Create date-based directory structure: logs/YYYY-MM-DD/
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = log_dir / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        # Create symbol-specific log file: logs/YYYY-MM-DD/SYMBOL.log
        log_file = date_dir / f"{symbol}.log"

        super().__init__(log_file, encoding='utf-8')

