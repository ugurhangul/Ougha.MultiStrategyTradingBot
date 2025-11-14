"""
MT5 trading status checker.
"""

import MetaTrader5 as mt5
from typing import Optional, Dict, Tuple
from datetime import datetime, timezone

from src.utils.logging import TradingLogger


class TradingStatusChecker:
    """Checks trading status in MT5"""

    def __init__(self, connection_manager, symbol_cache, logger: TradingLogger):
        """
        Initialize trading status checker.

        Args:
            connection_manager: ConnectionManager instance
            symbol_cache: SymbolInfoCache instance
            logger: Logger instance
        """
        self.connection_manager = connection_manager
        self.symbol_cache = symbol_cache
        self.logger = logger

        # Session state cache: symbol -> (is_in_session, last_check_time, consecutive_closed_count)
        # This reduces repeated logging for symbols that are consistently closed
        self._session_state_cache: Dict[str, Tuple[bool, datetime, int]] = {}

    def is_autotrading_enabled(self) -> bool:
        """
        Check if AutoTrading is enabled in MT5 terminal.

        Returns:
            True if AutoTrading is enabled, False otherwise
        """
        try:
            if not self.connection_manager.is_connected:
                return False

            terminal_info = mt5.terminal_info()
            if terminal_info is None:
                self.logger.error("Failed to get terminal info")
                return False

            # Check if trade is allowed in terminal
            return terminal_info.trade_allowed

        except Exception as e:
            self.logger.error(f"Error checking AutoTrading status: {e}")
            return False

    def is_trading_enabled(self, symbol: str) -> bool:
        """
        Check if trading is enabled for a symbol.

        Args:
            symbol: Symbol name

        Returns:
            True if trading is enabled, False otherwise
        """
        try:
            symbol_info = self.symbol_cache.get(symbol)
            if symbol_info is None:
                return False

            # trade_mode values:
            # 0 = SYMBOL_TRADE_MODE_DISABLED - trading disabled
            # 1 = SYMBOL_TRADE_MODE_LONGONLY - only long positions allowed
            # 2 = SYMBOL_TRADE_MODE_SHORTONLY - only short positions allowed
            # 3 = SYMBOL_TRADE_MODE_CLOSEONLY - only position closing allowed
            # 4 = SYMBOL_TRADE_MODE_FULL - no restrictions
            trade_mode = symbol_info.get('trade_mode', 0)

            # Trading is enabled if mode is not DISABLED (0)
            return trade_mode != 0

        except Exception as e:
            self.logger.error(f"Error checking if trading enabled for {symbol}: {e}")
            return False

    def is_market_open(self, symbol: str) -> bool:
        """
        Check if the market is currently open for a symbol.

        This checks if we can get current tick data, which indicates the market is active.

        Args:
            symbol: Symbol name

        Returns:
            True if market appears to be open, False otherwise
        """
        try:
            # Try to get current tick - if market is closed, this may fail or return stale data
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return False

            # Check if we can get symbol info
            symbol_info = self.symbol_cache.get(symbol)
            if symbol_info is None:
                return False

            # Check trade mode - if it's DISABLED (0), market is not available
            trade_mode = symbol_info.get('trade_mode', 0)
            if trade_mode == 0:
                return False

            # If we got here, market appears to be accessible
            return True

        except Exception as e:
            self.logger.debug(f"Error checking market status for {symbol}: {e}")
            return False

    def is_in_trading_session(self, symbol: str) -> bool:
        """
        Check if the symbol is currently within its active trading session.

        This performs a comprehensive check including:
        - Symbol trading mode (not disabled)
        - Recent tick data availability (market activity)
        - Tick freshness (not stale data)

        Uses session state caching to reduce logging verbosity for symbols
        that are consistently closed.

        Args:
            symbol: Symbol name

        Returns:
            True if symbol is in active trading session, False otherwise
        """
        try:
            # First check if trading is enabled for this symbol
            if not self.is_trading_enabled(symbol):
                self._update_session_cache(symbol, False, "Trading is disabled")
                return False

            # Get current tick to check market activity
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                self._update_session_cache(symbol, False, "No tick data available")
                return False

            # Check if tick data is fresh (within last 60 seconds)
            # tick.time is in Unix timestamp format
            current_time = datetime.now(timezone.utc).timestamp()
            tick_age_seconds = current_time - tick.time

            # If tick is older than 60 seconds, market is likely closed
            if tick_age_seconds > 60:
                self._update_session_cache(
                    symbol,
                    False,
                    f"Tick data is stale (age: {tick_age_seconds:.0f}s)"
                )
                return False

            # Check if bid and ask prices are valid (non-zero)
            if tick.bid <= 0 or tick.ask <= 0:
                self._update_session_cache(
                    symbol,
                    False,
                    f"Invalid prices (bid: {tick.bid}, ask: {tick.ask})"
                )
                return False

            # All checks passed - symbol is in active trading session
            self._update_session_cache(symbol, True, "Session active")
            return True

        except Exception as e:
            self._update_session_cache(symbol, False, f"Error: {e}")
            return False

    def _update_session_cache(self, symbol: str, is_in_session: bool, reason: str):
        """
        Update session state cache and log appropriately.

        This method reduces logging verbosity by only logging:
        - When session state changes (open -> closed or closed -> open)
        - Every 10th consecutive check when market is closed

        Args:
            symbol: Symbol name
            is_in_session: Whether symbol is in active trading session
            reason: Reason for the session state
        """
        now = datetime.now(timezone.utc)

        # Get previous state
        if symbol in self._session_state_cache:
            prev_in_session, last_check, consecutive_closed = self._session_state_cache[symbol]
        else:
            prev_in_session = None
            last_check = now
            consecutive_closed = 0

        # Update consecutive closed count
        if not is_in_session:
            consecutive_closed += 1
        else:
            consecutive_closed = 0

        # Update cache
        self._session_state_cache[symbol] = (is_in_session, now, consecutive_closed)

        # Determine if we should log
        should_log = False
        log_level = "debug"

        if prev_in_session is None:
            # First check for this symbol
            should_log = True
        elif prev_in_session != is_in_session:
            # State changed
            should_log = True
            if is_in_session:
                log_level = "info"  # Market opened - more important
        elif not is_in_session and consecutive_closed % 10 == 0:
            # Market still closed, log every 10th check to reduce spam
            should_log = True
            reason = f"{reason} (checked {consecutive_closed} times)"

        # Log if needed
        if should_log:
            if log_level == "info":
                self.logger.info(f"{symbol}: {reason}", symbol)
            else:
                self.logger.debug(f"{symbol}: {reason}", symbol)

