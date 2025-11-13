"""
Trading hours filter configuration.
"""
from dataclasses import dataclass


@dataclass
class TradingHoursConfig:
    """Trading hours filter settings"""
    use_trading_hours: bool = False
    start_hour: int = 0
    end_hour: int = 23

    # Session checking settings
    check_symbol_session: bool = True  # Check if symbol is in active trading session before initialization
    wait_for_session: bool = False  # Wait for symbols to enter trading session (False = skip inactive symbols)
    session_wait_timeout_minutes: int = 30  # Max time to wait for each symbol's session (0 = wait indefinitely)
    session_check_interval_seconds: int = 60  # How often to check session status while waiting

