"""
Symbol Session Monitor

Monitors symbols and waits for their trading sessions to become active before initialization.
"""
import time
from typing import List, Set, Optional
from datetime import datetime, timezone

from src.core.mt5_connector import MT5Connector
from src.utils.logger import get_logger


class SymbolSessionMonitor:
    """
    Monitors symbols and waits for their trading sessions to become active.
    
    This class is responsible for:
    - Checking if symbols are in active trading sessions
    - Waiting for symbols to enter their trading sessions
    - Providing status updates during the waiting period
    """
    
    def __init__(self, connector: MT5Connector, check_interval_seconds: int = 60):
        """
        Initialize symbol session monitor.
        
        Args:
            connector: MT5 connector instance
            check_interval_seconds: How often to check session status (default: 60 seconds)
        """
        self.connector = connector
        self.check_interval_seconds = check_interval_seconds
        self.logger = get_logger()
        
    def check_symbol_session(self, symbol: str) -> bool:
        """
        Check if a symbol is currently in its active trading session.
        
        Args:
            symbol: Symbol name
            
        Returns:
            True if symbol is in active trading session, False otherwise
        """
        return self.connector.is_in_trading_session(symbol)
    
    def wait_for_trading_session(self, symbol: str, max_wait_minutes: Optional[int] = None) -> bool:
        """
        Wait for a symbol to enter its active trading session.
        
        Args:
            symbol: Symbol name
            max_wait_minutes: Maximum time to wait in minutes (None = wait indefinitely)
            
        Returns:
            True if symbol entered trading session, False if timeout or error
        """
        self.logger.info(f"Waiting for {symbol} to enter active trading session...", symbol)
        
        start_time = datetime.now(timezone.utc)
        check_count = 0
        
        while True:
            # Check if symbol is now in trading session
            if self.check_symbol_session(symbol):
                elapsed_minutes = (datetime.now(timezone.utc) - start_time).total_seconds() / 60
                self.logger.info(
                    f"✓ {symbol} is now in active trading session (waited {elapsed_minutes:.1f} minutes)",
                    symbol
                )
                return True
            
            # Check if we've exceeded max wait time
            if max_wait_minutes is not None:
                elapsed_minutes = (datetime.now(timezone.utc) - start_time).total_seconds() / 60
                if elapsed_minutes >= max_wait_minutes:
                    self.logger.warning(
                        f"Timeout waiting for {symbol} trading session (waited {elapsed_minutes:.1f} minutes)",
                        symbol
                    )
                    return False
            
            # Log status every 5 checks (5 minutes by default)
            check_count += 1
            if check_count % 5 == 0:
                elapsed_minutes = (datetime.now(timezone.utc) - start_time).total_seconds() / 60
                self.logger.info(
                    f"Still waiting for {symbol} trading session... (elapsed: {elapsed_minutes:.1f} minutes)",
                    symbol
                )
            
            # Wait before next check
            time.sleep(self.check_interval_seconds)
    
    def filter_active_symbols(self, symbols: List[str]) -> tuple[List[str], List[str]]:
        """
        Filter symbols into active and inactive based on trading session status.
        
        Args:
            symbols: List of symbol names to check
            
        Returns:
            Tuple of (active_symbols, inactive_symbols)
        """
        active_symbols = []
        inactive_symbols = []
        
        self.logger.info("=" * 60)
        self.logger.info("Checking trading session status for all symbols...")
        self.logger.info("=" * 60)
        
        for symbol in symbols:
            if self.check_symbol_session(symbol):
                active_symbols.append(symbol)
                self.logger.info(f"✓ {symbol}: In active trading session", symbol)
            else:
                inactive_symbols.append(symbol)
                self.logger.warning(f"✗ {symbol}: NOT in active trading session", symbol)
        
        self.logger.info("=" * 60)
        self.logger.info(f"Active symbols: {len(active_symbols)}/{len(symbols)}")
        if inactive_symbols:
            self.logger.info(f"Inactive symbols: {', '.join(inactive_symbols)}")
        self.logger.info("=" * 60)
        
        return active_symbols, inactive_symbols
    
    def wait_for_all_symbols(self, symbols: List[str], max_wait_minutes: Optional[int] = None) -> List[str]:
        """
        Wait for all symbols to enter their active trading sessions.
        
        Args:
            symbols: List of symbol names
            max_wait_minutes: Maximum time to wait for each symbol (None = wait indefinitely)
            
        Returns:
            List of symbols that successfully entered trading session
        """
        ready_symbols = []
        
        for symbol in symbols:
            if self.wait_for_trading_session(symbol, max_wait_minutes):
                ready_symbols.append(symbol)
            else:
                self.logger.warning(f"Skipping {symbol} - trading session not available", symbol)
        
        return ready_symbols

