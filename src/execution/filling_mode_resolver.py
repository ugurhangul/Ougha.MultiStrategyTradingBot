"""
Filling Mode Resolver

Provides utilities to determine the appropriate MT5 order filling mode
based on symbol capabilities.
"""
import MetaTrader5 as mt5
from typing import Optional, TYPE_CHECKING
from src.constants import FILLING_MODE_PREFERENCE, FILLING_MODE_FOK, ORDER_FILLING_FOK

if TYPE_CHECKING:
    from src.utils.logger import TradingLogger


class FillingModeResolver:
    """
    Service for resolving MT5 order filling modes.

    This class provides methods to:
    - Determine the best filling mode for a symbol
    - Check which filling modes are supported by a symbol
    - Get human-readable filling mode names
    - Handle fallback to default modes

    MT5 Filling Modes:
    - FOK (Fill or Kill): Order must be filled completely or not at all
    - IOC (Immediate or Cancel): Fill as much as possible, cancel the rest
    - RETURN: Can be filled partially with remaining volume as a limit order
    """

    def __init__(self, logger: 'TradingLogger'):
        """
        Initialize filling mode resolver.
        
        Args:
            logger: Logger instance for logging mode resolution
        """
        self.logger = logger
    
    def resolve_filling_mode(self, symbol_info: dict, symbol: str = "") -> int:
        """
        Determine the appropriate filling mode for a symbol.
        
        Checks symbol's supported filling modes and returns the most
        appropriate one based on preference order defined in constants.
        
        Args:
            symbol_info: Symbol information dictionary from MT5
            symbol: Symbol name for logging (optional)
            
        Returns:
            MT5 filling mode constant (e.g., mt5.ORDER_FILLING_FOK)
            
        Examples:
            >>> resolver.resolve_filling_mode(symbol_info, 'EURUSD')
            2  # mt5.ORDER_FILLING_FOK
        """
        # Get symbol's filling mode flags
        filling_mode_flags = symbol_info.get('filling_mode', 0)

        # If filling_mode is 0, it means it wasn't retrieved - default to FOK
        if filling_mode_flags == 0:
            self.logger.warning(
                f"Filling mode not available for {symbol}, defaulting to FOK"
            )
            return ORDER_FILLING_FOK  # Use constant instead of mt5.ORDER_FILLING_FOK
        
        # Check supported modes in order of preference (from constants)
        for bit_flag, mode_constant, mode_name in FILLING_MODE_PREFERENCE:
            if filling_mode_flags & bit_flag:
                self.logger.debug(
                    f"Selected filling mode for {symbol}: {mode_name} "
                    f"(flags: {filling_mode_flags})"
                )
                return mode_constant
        
        # Fallback to FOK if no mode is supported (shouldn't happen)
        self.logger.warning(
            f"No filling mode supported for {symbol} (flags: {filling_mode_flags}), "
            f"defaulting to FOK"
        )
        return ORDER_FILLING_FOK  # Use constant instead of mt5.ORDER_FILLING_FOK
    
    def get_filling_mode_name(self, mode_constant: int) -> str:
        """
        Get human-readable name for a filling mode constant.
        
        Args:
            mode_constant: MT5 filling mode constant
            
        Returns:
            Human-readable mode name (e.g., "FOK", "IOC", "RETURN")
            
        Examples:
            >>> resolver.get_filling_mode_name(mt5.ORDER_FILLING_FOK)
            'FOK'
        """
        for _, constant, name in FILLING_MODE_PREFERENCE:
            if mode_constant == constant:
                return name
        
        return "UNKNOWN"
    
    def is_filling_mode_supported(
        self,
        symbol_info: dict,
        mode_constant: int
    ) -> bool:
        """
        Check if a specific filling mode is supported by a symbol.
        
        Args:
            symbol_info: Symbol information dictionary from MT5
            mode_constant: MT5 filling mode constant to check
            
        Returns:
            True if the mode is supported, False otherwise
            
        Examples:
            >>> resolver.is_filling_mode_supported(symbol_info, mt5.ORDER_FILLING_FOK)
            True
        """
        filling_mode_flags = symbol_info.get('filling_mode', 0)
        
        if filling_mode_flags == 0:
            return False
        
        # Find the bit flag for this mode constant
        for bit_flag, constant, _ in FILLING_MODE_PREFERENCE:
            if constant == mode_constant:
                return bool(filling_mode_flags & bit_flag)
        
        return False
    
    def get_supported_modes(self, symbol_info: dict) -> list[str]:
        """
        Get list of all supported filling modes for a symbol.
        
        Args:
            symbol_info: Symbol information dictionary from MT5
            
        Returns:
            List of supported mode names (e.g., ['FOK', 'IOC'])
            
        Examples:
            >>> resolver.get_supported_modes(symbol_info)
            ['FOK', 'IOC', 'RETURN']
        """
        filling_mode_flags = symbol_info.get('filling_mode', 0)
        
        if filling_mode_flags == 0:
            return []
        
        supported = []
        for bit_flag, _, mode_name in FILLING_MODE_PREFERENCE:
            if filling_mode_flags & bit_flag:
                supported.append(mode_name)
        
        return supported
    
    def log_filling_mode_info(self, symbol_info: dict, symbol: str):
        """
        Log detailed information about symbol's filling mode support.
        
        Useful for debugging filling mode issues.
        
        Args:
            symbol_info: Symbol information dictionary from MT5
            symbol: Symbol name for logging
        """
        filling_mode_flags = symbol_info.get('filling_mode', 0)
        supported_modes = self.get_supported_modes(symbol_info)
        selected_mode = self.resolve_filling_mode(symbol_info, symbol)
        selected_mode_name = self.get_filling_mode_name(selected_mode)
        
        self.logger.info(
            f"Filling Mode Info for {symbol}:",
            symbol
        )
        self.logger.info(
            f"  Flags: {filling_mode_flags}",
            symbol
        )
        self.logger.info(
            f"  Supported: {', '.join(supported_modes) if supported_modes else 'None'}",
            symbol
        )
        self.logger.info(
            f"  Selected: {selected_mode_name}",
            symbol
        )

