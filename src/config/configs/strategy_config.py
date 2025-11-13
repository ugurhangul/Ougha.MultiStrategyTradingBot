"""
Strategy configuration settings.
"""
from dataclasses import dataclass


@dataclass
class StrategyConfig:
    """Strategy settings"""
    entry_offset_percent: float = 0
    stop_loss_offset_percent: float = 0  # Deprecated: use stop_loss_offset_points instead
    stop_loss_offset_points: int = 100  # Stop loss offset in points (recommended)
    use_point_based_sl: bool = False  # Use point-based SL calculation instead of percentage
    risk_reward_ratio: float = 2.0


@dataclass
class StrategyEnableConfig:
    """
    Strategy enable/disable configuration.

    Controls which strategies are active for each symbol.
    Multiple strategies can run simultaneously on the same symbol.
    """
    # === Breakout Strategies ===
    true_breakout_enabled: bool = True  # True breakout with retest confirmation
    fakeout_enabled: bool = True  # Fakeout/reversal strategy

    # === HFT Strategies ===
    hft_momentum_enabled: bool = False  # HFT Momentum strategy (disabled by default)

    # === Multi-Range Support ===
    # Enable/disable specific range configurations for breakout strategies
    range_4h5m_enabled: bool = True  # 4H reference, 5M confirmation
    range_15m1m_enabled: bool = True  # 15M reference, 1M confirmation

    # === Position Sizing Configuration ===
    # Choose position sizing method for each strategy
    # Options: "fixed" (default), "martingale" (high risk)
    true_breakout_position_sizer: str = "fixed"  # Position sizing for true breakout
    fakeout_position_sizer: str = "fixed"  # Position sizing for fakeout
    hft_momentum_position_sizer: str = "martingale"  # Position sizing for HFT Momentum (uses martingale by default)

