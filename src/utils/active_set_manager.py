"""
Active Set Manager - Manages the active.set file and removes problematic symbols.

This module handles:
1. Loading symbols from active.set
2. Removing symbols that encounter errors (except insufficient margin and market closed)
3. Removing symbols with trading disabled
4. Removing symbols with excessive spread
5. Logging removed symbols to disable.log
6. Prioritizing and deduplicating symbols (r > standard > m)
"""
from pathlib import Path
from typing import List, Optional
import threading
from datetime import datetime, timezone
from .symbol_prioritizer import SymbolPrioritizer


class ActiveSetManager:
    """Manages the active.set file and automatic symbol removal"""

    def __init__(self, file_path: str = "data/active.set", connector=None, enable_prioritization: bool = True):
        """
        Initialize the active set manager.

        Args:
            file_path: Path to the active.set file (relative to python_trader directory)
            connector: MT5Connector instance for symbol validation (optional)
            enable_prioritization: Enable automatic symbol prioritization and deduplication
        """
        # Convert to absolute path relative to this file's location
        if not Path(file_path).is_absolute():
            # Get the python_trader directory (3 levels up from this file)
            python_trader_dir = Path(__file__).parent.parent.parent
            self.file_path = python_trader_dir / file_path
        else:
            self.file_path = Path(file_path)

        self.lock = threading.Lock()
        self.symbols: List[str] = []
        self.connector = connector
        self.enable_prioritization = enable_prioritization
        self.prioritizer = SymbolPrioritizer(connector) if enable_prioritization else None
        
    def _load_symbols_internal(self) -> List[str]:
        """
        Internal method to load symbols without locking.

        Returns:
            List of symbol names
        """
        if not self.file_path.exists():
            return []

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # First line is count, rest are symbols
            symbols = [
                line.strip()
                for line in lines[1:]
                if line.strip()
            ]

            return symbols

        except Exception:
            return []

    def load_symbols(self, logger=None) -> List[str]:
        """
        Load symbols from active.set file.
        Handles both UTF-8 and UTF-16 encodings.
        Automatically filters duplicates and prioritizes raw spread symbols.

        Args:
            logger: Logger instance (optional)

        Returns:
            List of symbol names (deduplicated and prioritized)
        """
        with self.lock:
            raw_symbols = self._load_symbols_internal()

            # Apply prioritization and deduplication if enabled
            if self.enable_prioritization and self.prioritizer and raw_symbols:
                filtered_symbols = self.prioritizer.filter_symbols(raw_symbols, logger)

                # If symbols were filtered, save the updated list
                if len(filtered_symbols) != len(raw_symbols):
                    if logger:
                        logger.info(f"Symbol filtering: {len(raw_symbols)} -> {len(filtered_symbols)} symbols")
                    self.symbols = filtered_symbols
                    # Save the filtered list back to active.set
                    self._save_symbols_internal()
                else:
                    self.symbols = filtered_symbols
            else:
                self.symbols = raw_symbols

            return self.symbols.copy()
    
    def _save_symbols_internal(self):
        """
        Internal method to save symbols without locking.
        """
        # Ensure directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                # Write count on first line
                f.write(f"{len(self.symbols)}\n")

                # Write symbols
                for symbol in self.symbols:
                    f.write(f"{symbol}\n")

        except Exception:
            # Silently fail - error will be caught by caller
            pass

    def save_symbols(self, symbols: Optional[List[str]] = None):
        """
        Save symbols to active.set file in UTF-8 encoding.

        Args:
            symbols: List of symbols to save (uses internal list if None)
        """
        with self.lock:
            if symbols is not None:
                self.symbols = symbols

            self._save_symbols_internal()
    
    def remove_symbol(self, symbol: str, reason: str, logger=None) -> bool:
        """
        Remove a symbol from active.set and log to disable.log.

        Args:
            symbol: Symbol to remove
            reason: Reason for removal
            logger: Logger instance (optional)

        Returns:
            True if symbol was removed, False if not found
        """
        with self.lock:
            # Reload symbols from file to ensure we have the latest list
            self.symbols = self._load_symbols_internal()

            if symbol not in self.symbols:
                return False

            # Remove from list
            self.symbols.remove(symbol)

            # Save updated list immediately
            if self.symbols is not None:
                # Ensure directory exists
                self.file_path.parent.mkdir(parents=True, exist_ok=True)

                try:
                    with open(self.file_path, 'w', encoding='utf-8') as f:
                        # Write count on first line
                        f.write(f"{len(self.symbols)}\n")

                        # Write symbols
                        for sym in self.symbols:
                            f.write(f"{sym}\n")

                except Exception:
                    # Silently fail - error will be caught by caller
                    pass

            # Log to disable.log if logger provided
            if logger:
                stats = {
                    'removed_from': 'active.set',
                    'reason': reason,
                    'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                }
                logger.symbol_disabled(symbol, reason, stats)

            return True
    
    def should_remove_symbol(self, error_message: str) -> bool:
        """
        Determine if a symbol should be removed based on error message.

        Symbols are NOT removed for:
        - Insufficient margin / No money errors
        - Market closed errors
        - Position opening restrictions (retcode 10044)

        Symbols ARE removed for:
        - Trading disabled
        - Spread too high
        - Symbol not found
        - Invalid symbol
        - Other persistent errors

        Args:
            error_message: The error message to check

        Returns:
            True if symbol should be removed
        """
        error_lower = error_message.lower()

        # Don't remove for these errors (temporary conditions)
        if any(phrase in error_lower for phrase in [
            'insufficient margin',
            'no money',
            'not enough money',
            'margin',
            'market is closed',
            'market closed',
            'retcode 10018',  # Market closed error code
            'off quotes',
            'no prices',
            'requote',
            'only position closing allowed',  # retcode 10044 - temporary broker restriction
            'position opening restricted',
            'retcode 10044'
        ]):
            return False
        
        # Remove for these errors (persistent issues)
        if any(phrase in error_lower for phrase in [
            'trading is disabled',
            'trade is disabled',
            'symbol is disabled',
            'spread too high',
            'spread rejected',
            'excessive spread',
            'symbol not found',
            'invalid symbol',
            'unknown symbol',
            'symbol does not exist',
            'failed to get symbol info',
            'failed to get spread',
            'failed to get candles',
            'failed to get current price',
            'failed to get 4h candles',
            'failed to get latest candle',
            'failed to get 5m candles',
            'failed to get m5 candles',
            'failed to get 4h candle',
            'failed to get 5m candle',
            'failed to get 4h candle data',
            'failed to get 5m candle data',
            'failed to get latest candle data',
            'data retrieval error'
        ]):
            return True
        
        return False


# Global instance
_active_set_manager: Optional[ActiveSetManager] = None


def get_active_set_manager(file_path: str = "data/active.set", connector=None, enable_prioritization: bool = True) -> ActiveSetManager:
    """
    Get the global active set manager instance.

    Args:
        file_path: Path to active.set file
        connector: MT5Connector instance for symbol validation (optional)
        enable_prioritization: Enable automatic symbol prioritization and deduplication

    Returns:
        ActiveSetManager instance
    """
    global _active_set_manager
    if _active_set_manager is None:
        _active_set_manager = ActiveSetManager(file_path, connector, enable_prioritization)
    elif connector is not None and _active_set_manager.connector is None:
        # Update connector if it wasn't set initially
        _active_set_manager.connector = connector
        if _active_set_manager.prioritizer:
            _active_set_manager.prioritizer.connector = connector
    return _active_set_manager

