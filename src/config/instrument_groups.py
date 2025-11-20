"""
Instrument group configuration for portfolio risk management.

Groups instruments by correlation to prevent over-concentration in correlated positions.
"""

from typing import Dict, List
from enum import Enum


class InstrumentGroup(Enum):
    """Instrument groups for correlation-based risk management."""
    BTC = "BTC"           # All Bitcoin pairs
    ETH = "ETH"           # All Ethereum pairs
    CRYPTO_OTHER = "CRYPTO_OTHER"  # Other crypto
    FX_MAJOR = "FX_MAJOR"  # Major FX pairs (EUR, GBP, USD, JPY, CHF, CAD, AUD, NZD)
    FX_MINOR = "FX_MINOR"  # Minor FX pairs and crosses
    FX_EXOTIC = "FX_EXOTIC"  # Exotic FX pairs
    INDICES = "INDICES"    # Stock indices (US30, SPX500, etc.)
    COMMODITIES = "COMMODITIES"  # Gold, Silver, Oil
    STOCKS = "STOCKS"      # Individual stocks
    UNKNOWN = "UNKNOWN"    # Uncategorized


# Maximum risk per instrument group (as percentage of account balance)
# This prevents over-concentration in correlated instruments
DEFAULT_GROUP_RISK_LIMITS: Dict[InstrumentGroup, float] = {
    InstrumentGroup.BTC: 5.0,           # Max 5% total risk across all BTC pairs
    InstrumentGroup.ETH: 5.0,           # Max 5% total risk across all ETH pairs
    InstrumentGroup.CRYPTO_OTHER: 5.0,  # Max 5% total risk across other crypto
    InstrumentGroup.FX_MAJOR: 15.0,     # Max 15% total risk across major FX
    InstrumentGroup.FX_MINOR: 10.0,     # Max 10% total risk across minor FX
    InstrumentGroup.FX_EXOTIC: 5.0,     # Max 5% total risk across exotic FX
    InstrumentGroup.INDICES: 10.0,      # Max 10% total risk across indices
    InstrumentGroup.COMMODITIES: 10.0,  # Max 10% total risk across commodities
    InstrumentGroup.STOCKS: 10.0,       # Max 10% total risk across stocks
    InstrumentGroup.UNKNOWN: 5.0,       # Max 5% for unknown instruments
}


def get_instrument_group(symbol: str) -> InstrumentGroup:
    """
    Determine the instrument group for a given symbol.
    
    Args:
        symbol: Symbol name (e.g., "BTCUSD", "EURUSD", "AAPL")
        
    Returns:
        InstrumentGroup enum value
    """
    symbol_upper = symbol.upper()
    
    # Bitcoin pairs
    if 'BTC' in symbol_upper:
        return InstrumentGroup.BTC
    
    # Ethereum pairs
    if 'ETH' in symbol_upper:
        return InstrumentGroup.ETH
    
    # Other crypto
    crypto_prefixes = ['XRP', 'LTC', 'ADA', 'DOT', 'DOGE', 'SOL', 'MATIC', 'AVAX']
    if any(prefix in symbol_upper for prefix in crypto_prefixes):
        return InstrumentGroup.CRYPTO_OTHER
    
    # Major FX pairs (8 major currencies)
    major_currencies = ['EUR', 'GBP', 'USD', 'JPY', 'CHF', 'CAD', 'AUD', 'NZD']
    major_pairs = [
        'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD',
        'EURGBP', 'EURJPY', 'GBPJPY', 'AUDJPY', 'NZDJPY', 'EURAUD', 'EURNZD',
        'GBPAUD', 'GBPNZD', 'AUDCAD', 'AUDNZD', 'CADJPY', 'CHFJPY', 'NZDCAD'
    ]
    
    if symbol_upper in major_pairs:
        return InstrumentGroup.FX_MAJOR
    
    # Check if it's a cross of major currencies (minor FX)
    if all(any(curr in symbol_upper for curr in major_currencies) for _ in range(2)):
        # Both base and quote are major currencies but not in major pairs list
        return InstrumentGroup.FX_MINOR
    
    # Exotic FX (one major currency + one exotic)
    exotic_currencies = ['ZAR', 'TRY', 'MXN', 'BRL', 'RUB', 'INR', 'CNH', 'SGD', 'HKD', 'THB']
    if any(curr in symbol_upper for curr in exotic_currencies):
        return InstrumentGroup.FX_EXOTIC
    
    # Indices
    index_symbols = ['US30', 'SPX500', 'NAS100', 'DJ30', 'GER30', 'UK100', 'FRA40', 'ESP35', 'JPN225', 'AUS200']
    if any(idx in symbol_upper for idx in index_symbols):
        return InstrumentGroup.INDICES
    
    # Commodities
    commodity_symbols = ['XAU', 'XAG', 'XPT', 'XPD', 'GOLD', 'SILVER', 'OIL', 'USOIL', 'UKOIL', 'BRENT']
    if any(comm in symbol_upper for comm in commodity_symbols):
        return InstrumentGroup.COMMODITIES
    
    # Stocks (typically 2-5 letter symbols without common FX/crypto patterns)
    if len(symbol_upper) <= 5 and symbol_upper.isalpha():
        # Check if it's not a currency pair
        if not any(curr in symbol_upper for curr in major_currencies + exotic_currencies):
            return InstrumentGroup.STOCKS
    
    # Unknown
    return InstrumentGroup.UNKNOWN


def get_group_risk_limit(group: InstrumentGroup) -> float:
    """
    Get the maximum risk limit for an instrument group.
    
    Args:
        group: InstrumentGroup enum value
        
    Returns:
        Maximum risk percentage for the group
    """
    return DEFAULT_GROUP_RISK_LIMITS.get(group, 5.0)

