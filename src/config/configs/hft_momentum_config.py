"""
HFT Momentum Strategy configuration.
"""
import os
from dataclasses import dataclass, field
from typing import Dict
from src.config.strategies import MartingaleType


@dataclass
class HFTMomentumConfig:
    """
    HFT Momentum Strategy Configuration

    High-frequency trading strategy with tick-level momentum detection
    and martingale position sizing for loss recovery.

    WARNING: Martingale strategies carry high risk. Use conservative settings
    and allocate only 5-10% of account capital to this strategy.
    """
    # === Strategy Enable/Disable ===
    enabled: bool = True  # Disabled by default - must be explicitly enabled

    # === HFT Signal Detection ===
    tick_momentum_count: int = 2  # Number of consecutive ticks to analyze
    trade_cooldown_seconds: int = 3  # Minimum seconds between trades

    # === Signal Validation ===
    enable_signal_validation: bool = True  # Enable multi-layer filtering
    use_auto_optimization: bool = True  # Use symbol-specific parameters

    # Momentum strength filter
    min_momentum_strength: float = 0.0001  # Minimum price movement (auto-optimized)

    # Volume confirmation filter
    min_volume_multiplier: float = 1.2  # Min volume vs average (auto-optimized)
    volume_lookback: int = 20  # M1 candles for volume average (uses tick_volume from candles)

    # Volatility filter (ATR-based)
    enable_volatility_filter: bool = True
    min_atr_multiplier: float = 0.5  # Min ATR ratio (auto-optimized)
    max_atr_multiplier: float = 2.0  # Max ATR ratio (auto-optimized)
    atr_period: int = 14
    atr_timeframe: str = "M1"  # Timeframe for ATR calculation
    atr_lookback: int = 20  # Number of periods for ATR average

    # Trend alignment filter
    enable_trend_filter: bool = True
    trend_ema_period: int = 50  # EMA period (auto-optimized)
    trend_ema_timeframe: str = "M5"

    # Spread filter
    max_spread_multiplier: float = 2.0  # Max spread vs average (auto-optimized)
    spread_lookback: int = 20  # Ticks for spread average

    # === Martingale Position Sizing ===
    # CONSERVATIVE DEFAULTS - DO NOT INCREASE WITHOUT EXTENSIVE BACKTESTING
    martingale_type: MartingaleType = MartingaleType.CLASSIC_MULTIPLIER
    martingale_multiplier: float = 1.5  # Conservative (was 2.0 in MQL5)
    max_orders_per_round: int = 3  # Limit progression (was 5 in MQL5)
    max_lot_size: float = 5.0  # Absolute maximum lot size

    # === Risk Management ===
    use_dynamic_stop_loss: bool = True  # Category-based SL
    use_atr_multiplier: bool = True  # ATR-based SL adjustment
    atr_multiplier_for_sl: float = 2.0  # ATR multiplier for SL
    risk_reward_ratio: float = 2.0  # TP/SL ratio

    # Consecutive loss protection
    enable_consecutive_loss_protection: bool = True
    max_consecutive_losses: int = 5  # Stop after N consecutive losses

    # === Per-Symbol Overrides ===
    # Dictionary of symbol-specific parameter overrides
    # Example: {"EURUSD": {"tick_momentum_count": 10, "martingale_multiplier": 1.3}}
    symbol_overrides: Dict[str, Dict] = field(default_factory=dict)

    @classmethod
    def from_env(cls, range_id: str = "HFT") -> 'HFTMomentumConfig':
        """
        Load HFT Momentum configuration from environment variables.

        Args:
            range_id: Range identifier (default: "HFT")

        Returns:
            HFTMomentumConfig instance
        """
        # Parse martingale type from environment
        martingale_type_str = os.getenv('HFT_MARTINGALE_TYPE', 'classic_multiplier').lower()
        martingale_type_map = {
            'classic_multiplier': MartingaleType.CLASSIC_MULTIPLIER,
            'multiplier_with_sum': MartingaleType.MULTIPLIER_WITH_SUM,
            'sum_with_initial': MartingaleType.SUM_WITH_INITIAL
        }
        martingale_type = martingale_type_map.get(martingale_type_str, MartingaleType.CLASSIC_MULTIPLIER)

        return cls(
            # Strategy Enable/Disable
            enabled=os.getenv('HFT_ENABLED', 'false').lower() == 'true',

            # HFT Signal Detection
            tick_momentum_count=int(os.getenv('HFT_TICK_MOMENTUM_COUNT', '2')),
            trade_cooldown_seconds=int(os.getenv('HFT_TRADE_COOLDOWN_SECONDS', '3')),

            # Signal Validation
            enable_signal_validation=os.getenv('HFT_ENABLE_SIGNAL_VALIDATION', 'true').lower() == 'true',
            use_auto_optimization=os.getenv('HFT_USE_AUTO_OPTIMIZATION', 'true').lower() == 'true',

            # Momentum strength filter
            min_momentum_strength=float(os.getenv('HFT_MIN_MOMENTUM_STRENGTH', '0.0001')),

            # Volume confirmation filter
            min_volume_multiplier=float(os.getenv('HFT_MIN_VOLUME_MULTIPLIER', '1.2')),
            volume_lookback=int(os.getenv('HFT_VOLUME_LOOKBACK', '20')),

            # Volatility filter
            enable_volatility_filter=os.getenv('HFT_ENABLE_VOLATILITY_FILTER', 'true').lower() == 'true',
            min_atr_multiplier=float(os.getenv('HFT_MIN_ATR_MULTIPLIER', '0.5')),
            max_atr_multiplier=float(os.getenv('HFT_MAX_ATR_MULTIPLIER', '2.0')),
            atr_period=int(os.getenv('HFT_ATR_PERIOD', '14')),
            atr_timeframe=os.getenv('HFT_ATR_TIMEFRAME', 'M5'),
            atr_lookback=int(os.getenv('HFT_ATR_LOOKBACK', '20')),

            # Trend alignment filter
            enable_trend_filter=os.getenv('HFT_ENABLE_TREND_FILTER', 'true').lower() == 'true',
            trend_ema_period=int(os.getenv('HFT_TREND_EMA_PERIOD', '50')),
            trend_ema_timeframe=os.getenv('HFT_TREND_EMA_TIMEFRAME', 'M5'),

            # Spread filter
            max_spread_multiplier=float(os.getenv('HFT_MAX_SPREAD_MULTIPLIER', '2.0')),
            spread_lookback=int(os.getenv('HFT_SPREAD_LOOKBACK', '20')),

            # Martingale Position Sizing
            martingale_type=martingale_type,
            martingale_multiplier=float(os.getenv('HFT_MARTINGALE_MULTIPLIER', '1.5')),
            max_orders_per_round=int(os.getenv('HFT_MAX_ORDERS_PER_ROUND', '3')),
            max_lot_size=float(os.getenv('HFT_MAX_LOT_SIZE', '5.0')),

            # Risk Management
            use_dynamic_stop_loss=os.getenv('HFT_USE_DYNAMIC_STOP_LOSS', 'true').lower() == 'true',
            use_atr_multiplier=os.getenv('HFT_USE_ATR_MULTIPLIER', 'true').lower() == 'true',
            atr_multiplier_for_sl=float(os.getenv('HFT_ATR_MULTIPLIER_FOR_SL', '2.0')),
            risk_reward_ratio=float(os.getenv('HFT_RISK_REWARD_RATIO', '2.0')),

            # Consecutive loss protection
            enable_consecutive_loss_protection=os.getenv('HFT_ENABLE_CONSECUTIVE_LOSS_PROTECTION', 'true').lower() == 'true',
            max_consecutive_losses=int(os.getenv('HFT_MAX_CONSECUTIVE_LOSSES', '5')),

            # Symbol overrides (empty by default)
            symbol_overrides={}
        )
