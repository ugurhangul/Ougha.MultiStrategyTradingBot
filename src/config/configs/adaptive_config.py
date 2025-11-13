"""
Adaptive filter and symbol adaptation configuration.
"""
from dataclasses import dataclass


@dataclass
class AdaptiveFilterConfig:
    """Adaptive filter system settings

    NOTE: With dual strategy system (false + true breakout), volume confirmation
    is CRITICAL for strategy selection and should always remain enabled.
    Adaptive filters are disabled by default.
    """
    use_adaptive_filters: bool = False  # Disabled - confirmations required for dual strategy
    adaptive_loss_trigger: int = 3
    adaptive_win_recovery: int = 2
    start_with_filters_enabled: bool = True  # Always start with filters enabled


@dataclass
class SymbolAdaptationConfig:
    """Symbol-level adaptation settings"""
    use_symbol_adaptation: bool = True
    min_trades_for_evaluation: int = 10  # Renamed for clarity
    min_win_rate: float = 30.0  # Minimum win rate percentage
    max_total_loss: float = 100.0  # Maximum total loss (positive value)
    max_consecutive_losses: int = 3  # Maximum consecutive losses before disable
    max_drawdown_percent: float = 15.0  # Maximum drawdown percentage before disable
    cooling_period_hours: int = 168  # Cooling period in hours (168 = 7 days)
    reset_weekly: bool = True  # Reset stats at start of each trading week
    weekly_reset_day: int = 0  # Day of week to reset (0=Monday, 6=Sunday)
    weekly_reset_hour: int = 0  # Hour (UTC) to reset on reset day

