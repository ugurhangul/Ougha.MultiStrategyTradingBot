"""
Trading System Constants

This module centralizes all magic numbers, hard-coded strings, and constant values
used throughout the trading system to improve maintainability and reduce duplication.
"""
import MetaTrader5 as mt5
from typing import Dict, Final


# ============================================================================
# DIRECTORY AND FILE PATHS
# ============================================================================

DATA_DIR: Final[str] = "data"
LOGS_DIR: Final[str] = "logs"
POSITIONS_FILE: Final[str] = "positions.json"
SYMBOL_STATS_FILE: Final[str] = "symbol_stats.json"
ACTIVE_SET_FILE: Final[str] = "active.set"


# ============================================================================
# ORDER EXECUTION CONSTANTS
# ============================================================================

# Price deviation in points for order execution
DEFAULT_PRICE_DEVIATION: Final[int] = 10

# Order time type
ORDER_TIME_TYPE: Final[int] = mt5.ORDER_TIME_GTC  # Good Till Cancelled

# Default Risk/Reward ratio for trade signals
DEFAULT_RISK_REWARD_RATIO: Final[float] = 2.0


# ============================================================================
# TIMEFRAME MAPPINGS
# ============================================================================

# Map timeframe strings to MT5 constants
TIMEFRAME_MAP: Final[Dict[str, int]] = {
    'M1': mt5.TIMEFRAME_M1,
    'M5': mt5.TIMEFRAME_M5,
    'M15': mt5.TIMEFRAME_M15,
    'M30': mt5.TIMEFRAME_M30,
    'H1': mt5.TIMEFRAME_H1,
    'H4': mt5.TIMEFRAME_H4,
    'D1': mt5.TIMEFRAME_D1,
    'W1': mt5.TIMEFRAME_W1,
    'MN1': mt5.TIMEFRAME_MN1,
}

# Reverse mapping for MT5 constants to strings
TIMEFRAME_REVERSE_MAP: Final[Dict[int, str]] = {
    v: k for k, v in TIMEFRAME_MAP.items()
}


# ============================================================================
# FILLING MODE CONSTANTS
# ============================================================================

# Filling mode bit flags (from MT5 symbol_info.filling_mode)
FILLING_MODE_FOK: Final[int] = 1   # Fill or Kill (bit 0)
FILLING_MODE_IOC: Final[int] = 2   # Immediate or Cancel (bit 1)
FILLING_MODE_RETURN: Final[int] = 4  # Can remain in order book (bit 2)

# MT5 order filling mode constants (hardcoded to avoid import-time dependency on MT5)
# These match the MT5 constants but are defined here to work in backtest mode
ORDER_FILLING_FOK: Final[int] = 1      # Fill or Kill
ORDER_FILLING_IOC: Final[int] = 2      # Immediate or Cancel
ORDER_FILLING_RETURN: Final[int] = 4   # Return (partial fills allowed)

# Filling mode preference order (most restrictive to least)
# Uses our constants instead of mt5.ORDER_FILLING_* to avoid import-time issues
FILLING_MODE_PREFERENCE: Final[list] = [
    (FILLING_MODE_FOK, ORDER_FILLING_FOK, "FOK"),
    (FILLING_MODE_IOC, ORDER_FILLING_IOC, "IOC"),
    (FILLING_MODE_RETURN, ORDER_FILLING_RETURN, "RETURN"),
]


# ============================================================================
# THREADING CONSTANTS
# ============================================================================

# Thread join timeout in seconds
THREAD_JOIN_TIMEOUT: Final[int] = 5

# Position monitor check interval in seconds
POSITION_MONITOR_INTERVAL: Final[int] = 1

# Symbol worker tick interval in seconds
SYMBOL_WORKER_TICK_INTERVAL: Final[int] = 1


# ============================================================================
# TECHNICAL INDICATOR DEFAULTS
# ============================================================================

# ATR (Average True Range)
DEFAULT_ATR_PERIOD: Final[int] = 14

# Volume Average
DEFAULT_VOLUME_PERIOD: Final[int] = 20

# RSI (Relative Strength Index)
DEFAULT_RSI_PERIOD: Final[int] = 14

# MACD (Moving Average Convergence Divergence)
DEFAULT_MACD_FAST: Final[int] = 12
DEFAULT_MACD_SLOW: Final[int] = 26
DEFAULT_MACD_SIGNAL: Final[int] = 9

# Divergence Lookback
DEFAULT_DIVERGENCE_LOOKBACK: Final[int] = 20


# ============================================================================
# TIME CONSTANTS
# ============================================================================

# Minutes in a day
MINUTES_PER_DAY: Final[int] = 1440

# Seconds in a minute
SECONDS_PER_MINUTE: Final[int] = 60

# History lookback period in days
HISTORY_LOOKBACK_DAYS: Final[int] = 7


# ============================================================================
# LOGGING CONSTANTS
# ============================================================================

# Log separator character
LOG_SEPARATOR_CHAR: Final[str] = "="
LOG_SEPARATOR_LENGTH: Final[int] = 60

# Log level names
LOG_LEVEL_DEBUG: Final[str] = "DEBUG"
LOG_LEVEL_INFO: Final[str] = "INFO"
LOG_LEVEL_WARNING: Final[str] = "WARNING"
LOG_LEVEL_ERROR: Final[str] = "ERROR"
LOG_LEVEL_CRITICAL: Final[str] = "CRITICAL"


# ============================================================================
# TRADE COMMENT TEMPLATES
# ============================================================================

# Default trade comment prefix
DEFAULT_TRADE_COMMENT: Final[str] = "5MinScalper"

# Trade comment format: "{prefix}_{strategy_type}_{range_id}"
# Example: "5MinScalper_FB_4H_5M" (False Breakout, 4H/5M range)
# Example: "5MinScalper_TB_15M_1M" (True Breakout, 15M/1M range)


# ============================================================================
# STRATEGY TYPE IDENTIFIERS
# ============================================================================

STRATEGY_TYPE_FALSE_BREAKOUT: Final[str] = "FB"  # False Breakout (reversal)
STRATEGY_TYPE_TRUE_BREAKOUT: Final[str] = "TB"   # True Breakout (continuation)
STRATEGY_TYPE_HFT_MOMENTUM: Final[str] = "HFT"   # HFT Momentum (tick-level)


# ============================================================================
# STRATEGY PARAMETERS
# ============================================================================

# Retest range percentage for true breakout strategy
# Used to detect when price pulls back to test the breakout level
# DEPRECATED: Use SymbolParameters.retest_range_percent from SymbolParametersRepository instead
# This constant is kept for backward compatibility only
RETEST_RANGE_PERCENT: Final[float] = 0.0005  # 0.05% range for retest detection (legacy default)


# ============================================================================
# RANGE IDENTIFIERS
# ============================================================================

# Default range ID for legacy single-range mode
DEFAULT_RANGE_ID: Final[str] = "default"

# Common range IDs for multi-range mode
RANGE_ID_4H_5M: Final[str] = "4H_5M"   # 4H reference, 5M breakout
RANGE_ID_15M_1M: Final[str] = "15M_1M"  # 15M reference, 1M breakout


# ============================================================================
# CURRENCY CONVERSION
# ============================================================================

# Common currency pair separators to try
CURRENCY_SEPARATORS: Final[list] = ['/', '.', '_', '']


# ============================================================================
# SYMBOL SUFFIX PRIORITY
# ============================================================================

# Symbol suffix priority for deduplication (higher = better)
# Example: EURUSDr > EURUSD > EURUSDm
SYMBOL_SUFFIX_PRIORITY: Final[Dict[str, int]] = {
    'r': 3,      # Raw spread (best)
    '': 2,       # Standard (good)
    'm': 1,      # Market (acceptable)
}


# ============================================================================
# MT5 RETCODE CONSTANTS
# ============================================================================

# MT5 Trade Server Return Codes
RETCODE_MARKET_CLOSED: Final[int] = 10018  # Market is closed
RETCODE_AUTOTRADING_DISABLED: Final[int] = 10026  # AutoTrading disabled by server
RETCODE_ONLY_CLOSE_ALLOWED: Final[int] = 10044  # Only position closing allowed


# ============================================================================
# ERROR MESSAGES
# ============================================================================

ERROR_MT5_NOT_CONNECTED: Final[str] = "Not connected to MT5"
ERROR_INVALID_TIMEFRAME: Final[str] = "Invalid timeframe"
ERROR_SYMBOL_NOT_FOUND: Final[str] = "Symbol not found in MT5"
ERROR_INVALID_BALANCE: Final[str] = "Invalid account balance"
ERROR_INVALID_SL_DISTANCE: Final[str] = "Invalid stop loss distance"
ERROR_PRICE_RETRIEVAL_FAILED: Final[str] = "Failed to get current market price"
ERROR_ORDER_SEND_FAILED: Final[str] = "order_send failed, no result returned from MT5"
ERROR_AUTOTRADING_DISABLED: Final[str] = "AutoTrading is DISABLED in MT5 terminal"


# ============================================================================
# SUCCESS MESSAGES
# ============================================================================

SUCCESS_MT5_CONNECTED: Final[str] = "MT5 Connection Successful"
SUCCESS_POSITION_OPENED: Final[str] = "Position opened successfully"
SUCCESS_POSITION_MODIFIED: Final[str] = "Position modified successfully"
SUCCESS_POSITION_CLOSED: Final[str] = "Position closed successfully"


# ============================================================================
# VALIDATION CONSTANTS
# ============================================================================

# Minimum data points required for calculations
MIN_DATA_POINTS_ATR: Final[int] = 15  # ATR period + 1
MIN_DATA_POINTS_VOLUME: Final[int] = 21  # Volume period + 1

# Risk tolerance multiplier for max risk check
RISK_TOLERANCE_MULTIPLIER: Final[float] = 1.5  # Allow 50% over configured risk


# ============================================================================
# POSITION MANAGEMENT
# ============================================================================

# Maximum number of retries for position operations
MAX_POSITION_OPERATION_RETRIES: Final[int] = 3

# Delay between retries in seconds
POSITION_OPERATION_RETRY_DELAY: Final[float] = 0.5


# ============================================================================
# FILE OPERATION CONSTANTS
# ============================================================================

# File encoding
FILE_ENCODING: Final[str] = 'utf-8'

# JSON indent for pretty printing
JSON_INDENT: Final[int] = 2

# Backup file suffix
BACKUP_FILE_SUFFIX: Final[str] = '.backup'


# ============================================================================
# DISPLAY CONSTANTS
# ============================================================================

# Banner width for console output
BANNER_WIDTH: Final[int] = 80

# Table column widths
COLUMN_WIDTH_SYMBOL: Final[int] = 15
COLUMN_WIDTH_CATEGORY: Final[int] = 18
COLUMN_WIDTH_SPREAD: Final[int] = 10

