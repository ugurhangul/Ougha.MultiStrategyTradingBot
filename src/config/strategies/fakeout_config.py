"""
Fakeout strategy configuration.

Configuration for Fakeout strategy (reversal after failed breakout).
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv
from src.models.data_models import RangeConfig
from src.config.configs.range_config import RangeConfigSettings

load_dotenv()


@dataclass
class FakeoutConfig:
    """Configuration for Fakeout strategy (reversal after failed breakout)"""

    # === Range Configuration ===
    # Use RangeConfig for range-related settings (reference timeframe, breakout timeframe, etc.)
    # This field is required and must come first (no default value)
    range_config: RangeConfig

    # === Strategy Enable/Disable ===
    enabled: bool = True

    # === Breakout Detection (Low Volume) ===
    max_breakout_volume_multiplier: float = 0.8  # Maximum volume for fakeout
    breakout_timeout_candles: int = 24  # Timeout in confirmation candles

    # === Reversal Confirmation ===
    min_reversal_volume_multiplier: float = 1.5  # Minimum reversal volume
    reversal_pattern_candles: int = 10  # Candles to analyze for reversal

    # === Divergence Validation ===
    check_divergence: bool = True  # Check for divergence
    require_divergence: bool = False  # Require divergence for entry
    rsi_period: int = 14  # RSI period for divergence
    divergence_lookback: int = 20  # Lookback for divergence detection

    # === Entry & Exit ===
    entry_offset_percent: float = 0.0  # Entry offset from current price
    stop_loss_offset_points: int = 100  # SL offset from pattern high/low
    use_point_based_sl: bool = False  # Use point-based SL calculation
    risk_reward_ratio: float = 2.0  # R:R ratio for TP
    risk_percent: float = 1.0  # Risk percentage per trade

    # === Trade Management ===
    enable_breakeven: bool = True  # Move SL to breakeven
    breakeven_trigger_ratio: float = 1.0  # R:R ratio to trigger breakeven
    enable_trailing_stop: bool = False  # Enable trailing stop
    trailing_distance_points: int = 50  # Trailing distance

    @classmethod
    def from_env(cls, range_id: str = "4H_5M") -> 'FakeoutConfig':
        """
        Load configuration from environment variables.

        Args:
            range_id: Range identifier (e.g., "4H_5M", "15M_1M")

        Returns:
            FakeoutConfig instance

        Raises:
            ValueError: If range_id is not found in predefined RangeConfigSettings
        """
        prefix = f"FAKEOUT_{range_id.replace('_', '')}_"

        # Get predefined RangeConfig from RangeConfigSettings
        range_config_settings = RangeConfigSettings()
        range_config = None
        for rc in range_config_settings.ranges:
            if rc.range_id == range_id:
                range_config = rc
                break

        if range_config is None:
            available_ranges = [rc.range_id for rc in range_config_settings.ranges]
            raise ValueError(
                f"Range ID '{range_id}' not found in predefined RangeConfigSettings. "
                f"Available ranges: {available_ranges}"
            )

        return cls(
            range_config=range_config,
            enabled=os.getenv(f'{prefix}ENABLED', 'true').lower() == 'true',
            max_breakout_volume_multiplier=float(os.getenv(f'{prefix}MAX_BREAKOUT_VOLUME', '0.8')),
            breakout_timeout_candles=int(os.getenv(f'{prefix}BREAKOUT_TIMEOUT', '24')),
            min_reversal_volume_multiplier=float(os.getenv(f'{prefix}MIN_REVERSAL_VOLUME', '1.5')),
            reversal_pattern_candles=int(os.getenv(f'{prefix}REVERSAL_CANDLES', '10')),
            check_divergence=os.getenv(f'{prefix}CHECK_DIVERGENCE', 'true').lower() == 'true',
            require_divergence=os.getenv(f'{prefix}REQUIRE_DIVERGENCE', 'false').lower() == 'true',
            rsi_period=int(os.getenv(f'{prefix}RSI_PERIOD', '14')),
            divergence_lookback=int(os.getenv(f'{prefix}DIVERGENCE_LOOKBACK', '20')),
            entry_offset_percent=float(os.getenv(f'{prefix}ENTRY_OFFSET_PERCENT', '0.0')),
            stop_loss_offset_points=int(os.getenv(f'{prefix}STOP_LOSS_OFFSET_POINTS', '100')),
            use_point_based_sl=os.getenv(f'{prefix}USE_POINT_BASED_SL', 'false').lower() == 'true',
            risk_reward_ratio=float(os.getenv(f'{prefix}RISK_REWARD_RATIO', '2.0')),
            risk_percent=float(os.getenv(f'{prefix}RISK_PERCENT', '1.0')),
            enable_breakeven=os.getenv(f'{prefix}ENABLE_BREAKEVEN', 'true').lower() == 'true',
            breakeven_trigger_ratio=float(os.getenv(f'{prefix}BREAKEVEN_TRIGGER_RATIO', '1.0')),
            enable_trailing_stop=os.getenv(f'{prefix}ENABLE_TRAILING_STOP', 'false').lower() == 'true',
            trailing_distance_points=int(os.getenv(f'{prefix}TRAILING_DISTANCE_POINTS', '50'))
        )

