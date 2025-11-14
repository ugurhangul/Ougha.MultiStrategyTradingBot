"""
Symbol-related data models.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class SymbolParameters:
    """Symbol-specific parameter set"""
    # Strategy selection
    enable_false_breakout_strategy: bool = True  # Trade reversals (weak breakouts)
    enable_true_breakout_strategy: bool = True   # Trade continuations (strong breakouts)

    # Confirmation flags
    # CRITICAL: Volume confirmation MUST be enabled for dual strategy system
    # It determines which strategy to use: LOW volume = false breakout, HIGH volume = true breakout
    volume_confirmation_enabled: bool = True
    divergence_confirmation_enabled: bool = True  # Used for false breakout strategy only

    # False breakout volume parameters
    breakout_volume_max: float = 1.0  # Max volume for weak breakout (false breakout)
    reversal_volume_min: float = 1.5  # Min volume for strong reversal (false breakout)
    volume_average_period: int = 20

    # True breakout volume parameters
    true_breakout_volume_min: float = 2.0  # Min volume for strong breakout (true breakout)
    continuation_volume_min: float = 1.5   # Min volume for continuation confirmation (true breakout)

    # True breakout retest parameters
    retest_range_percent: float = 0.0015  # Retest tolerance as percentage (0.15% default)
    retest_range_points: float = 0.0  # Retest tolerance in absolute points (0 = use percentage)
    # Tolerance mode: 'auto' (intelligent selection), 'percent' (force %), 'points' (force absolute)
    retest_tolerance_mode: str = 'auto'

    # Divergence parameters
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    divergence_lookback: int = 20

    # Adaptive trigger parameters
    adaptive_loss_trigger: int = 3
    adaptive_win_recovery: int = 2

    # Breakout timeout (in number of 5M candles)
    # Prevents trading on stale breakouts that have lost momentum
    # Default: 24 candles = 2 hours
    breakout_timeout_candles: int = 24

    # Spread limit (as percentage of price, e.g., 0.1 = 0.1%)
    max_spread_percent: float = 0.1

    # HFT Momentum validation thresholds (from ValidationThresholdsCalculator)
    min_momentum_strength: float = 3.0  # Multiplier for spread
    min_volume_multiplier: float = 1.3  # Min volume vs average
    min_atr_multiplier: float = 0.7  # Min ATR ratio
    max_atr_multiplier: float = 3.0  # Max ATR ratio
    trend_ema_period: int = 50  # EMA period for trend alignment
    max_spread_multiplier: float = 2.5  # Max spread vs average

    # Stop loss parameters (from StopLossCalculator)
    base_stop_loss_points: int = 500  # Base stop loss in points
    atr_multiplier_for_sl: float = 2.0  # ATR multiplier for stop loss calculation


@dataclass
class SymbolStats:
    """Symbol-level performance statistics"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    is_enabled: bool = True
    disabled_time: Optional[datetime] = None
    disable_reason: str = ""

    # Drawdown tracking
    peak_equity: float = 0.0  # Highest equity reached
    current_drawdown: float = 0.0  # Current drawdown from peak
    max_drawdown: float = 0.0  # Maximum drawdown ever reached

    # Weekly reset tracking
    week_start_time: Optional[datetime] = None  # When current week started

    @property
    def win_rate(self) -> float:
        """Calculate win rate percentage"""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100.0

    @property
    def net_profit(self) -> float:
        """Calculate net profit/loss"""
        return self.total_profit - self.total_loss

    @property
    def current_drawdown_percent(self) -> float:
        """Calculate current drawdown as percentage of peak equity"""
        if self.peak_equity == 0:
            return 0.0
        return (self.current_drawdown / self.peak_equity) * 100.0

    @property
    def max_drawdown_percent(self) -> float:
        """Calculate maximum drawdown as percentage of peak equity"""
        if self.peak_equity == 0:
            return 0.0
        return (self.max_drawdown / self.peak_equity) * 100.0

