"""
Symbol Prioritizer - Manages symbol priority and deduplication.

This module handles:
1. Detecting duplicate symbols (same base pair with different suffixes)
2. Prioritizing symbols based on suffix (r > standard > m)
3. Validating symbols are tradeable in MT5
4. Filtering to keep only the best available version of each pair
"""
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
import re


class SymbolPrioritizer:
    """Manages symbol priority and deduplication"""
    
    # Priority order: lower number = higher priority
    SUFFIX_PRIORITY = {
        'r': 1,      # Raw spread (highest priority)
        '': 2,       # Standard (no suffix)
        'm': 3,      # Micro/Mini (lowest priority)
    }
    
    def __init__(self, connector=None):
        """
        Initialize the symbol prioritizer.
        
        Args:
            connector: MT5Connector instance for validation (optional)
        """
        self.connector = connector
    
    @staticmethod
    def extract_base_and_suffix(symbol: str) -> Tuple[str, str]:
        """
        Extract base symbol and suffix from a symbol name.
        
        Args:
            symbol: Symbol name (e.g., 'EURUSDr', 'EURUSD', 'EURUSDm')
            
        Returns:
            Tuple of (base_symbol, suffix)
            
        Examples:
            'EURUSDr' -> ('EURUSD', 'r')
            'EURUSD' -> ('EURUSD', '')
            'EURUSDm' -> ('EURUSD', 'm')
        """
        # Check for known suffixes at the end
        if symbol.endswith('r'):
            return symbol[:-1], 'r'
        elif symbol.endswith('m'):
            return symbol[:-1], 'm'
        else:
            return symbol, ''
    
    @staticmethod
    def group_symbols_by_base(symbols: List[str]) -> Dict[str, List[Tuple[str, str]]]:
        """
        Group symbols by their base pair.
        
        Args:
            symbols: List of symbol names
            
        Returns:
            Dictionary mapping base_symbol -> [(full_symbol, suffix), ...]
            
        Example:
            ['EURUSD', 'EURUSDr', 'EURUSDm'] -> 
            {'EURUSD': [('EURUSD', ''), ('EURUSDr', 'r'), ('EURUSDm', 'm')]}
        """
        groups = defaultdict(list)
        
        for symbol in symbols:
            base, suffix = SymbolPrioritizer.extract_base_and_suffix(symbol)
            groups[base].append((symbol, suffix))
        
        return dict(groups)
    
    def is_symbol_tradeable(self, symbol: str) -> bool:
        """
        Check if a symbol is tradeable in MT5.
        
        Args:
            symbol: Symbol name
            
        Returns:
            True if symbol is tradeable, False otherwise
        """
        if self.connector is None:
            # If no connector provided, assume all symbols are tradeable
            return True
        
        try:
            # Check if symbol exists and trading is enabled
            symbol_info = self.connector.get_symbol_info(symbol)
            if symbol_info is None:
                return False
            
            # Check if trading is enabled
            return self.connector.is_trading_enabled(symbol)
            
        except Exception:
            return False
    
    def select_best_symbol(self, symbol_group: List[Tuple[str, str]]) -> Optional[str]:
        """
        Select the best symbol from a group based on priority and tradeability.
        
        Args:
            symbol_group: List of (full_symbol, suffix) tuples
            
        Returns:
            Best symbol name or None if none are tradeable
        """
        # Sort by priority (lower priority number = higher priority)
        sorted_symbols = sorted(
            symbol_group,
            key=lambda x: self.SUFFIX_PRIORITY.get(x[1], 999)
        )
        
        # Try each symbol in priority order
        for full_symbol, suffix in sorted_symbols:
            if self.is_symbol_tradeable(full_symbol):
                return full_symbol
        
        # No tradeable symbols found
        return None
    
    def filter_symbols(self, symbols: List[str], logger=None) -> List[str]:
        """
        Filter symbols to keep only the best version of each base pair.
        
        Args:
            symbols: List of symbol names
            logger: Logger instance (optional)
            
        Returns:
            Filtered list of symbols with duplicates removed
        """
        # Group symbols by base pair
        groups = self.group_symbols_by_base(symbols)
        
        filtered_symbols = []
        removed_symbols = []
        
        for base_symbol, symbol_group in groups.items():
            if len(symbol_group) == 1:
                # Only one version exists, keep it if tradeable
                full_symbol = symbol_group[0][0]
                if self.is_symbol_tradeable(full_symbol):
                    filtered_symbols.append(full_symbol)
                else:
                    removed_symbols.append((full_symbol, "Not tradeable"))
            else:
                # Multiple versions exist, select best one
                best_symbol = self.select_best_symbol(symbol_group)
                
                if best_symbol:
                    filtered_symbols.append(best_symbol)
                    
                    # Log removed duplicates
                    for full_symbol, suffix in symbol_group:
                        if full_symbol != best_symbol:
                            removed_symbols.append((full_symbol, f"Duplicate of {best_symbol}"))
                else:
                    # No tradeable version found
                    for full_symbol, suffix in symbol_group:
                        removed_symbols.append((full_symbol, "No tradeable version available"))
        
        # Log results if logger provided
        if logger and removed_symbols:
            logger.info(f"Symbol Prioritization: Removed {len(removed_symbols)} duplicate/untradeable symbols")
            for symbol, reason in removed_symbols:
                logger.debug(f"  - {symbol}: {reason}")
        
        return filtered_symbols


# Global instance
_symbol_prioritizer: Optional[SymbolPrioritizer] = None


def get_symbol_prioritizer(connector=None) -> SymbolPrioritizer:
    """Get the global symbol prioritizer instance"""
    global _symbol_prioritizer
    if _symbol_prioritizer is None:
        _symbol_prioritizer = SymbolPrioritizer(connector)
    return _symbol_prioritizer

