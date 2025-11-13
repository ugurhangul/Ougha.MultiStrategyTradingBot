"""
Enumeration types for the trading system.
"""
from enum import Enum


class SymbolCategory(Enum):
    """Symbol category enumeration"""
    MAJOR_FOREX = "major_forex"
    MINOR_FOREX = "minor_forex"
    EXOTIC_FOREX = "exotic_forex"
    METALS = "metals"
    INDICES = "indices"
    CRYPTO = "crypto"
    COMMODITIES = "commodities"
    STOCKS = "stocks"
    UNKNOWN = "unknown"


class PositionType(Enum):
    """Position type enumeration"""
    BUY = "buy"
    SELL = "sell"

