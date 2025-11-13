"""
Breakout strategy configuration.

General configuration for breakout strategies (True/False breakout).
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class BreakoutStrategyConfig:
    """Configuration for breakout strategies (True/False breakout)"""
    
    # === Strategy Enable/Disable ===
    enabled: bool = True
    
    # === Multi-Range Configuration ===
    # Handled by RangeConfigSettings in trading_config.py
    
    # === Entry/Exit Parameters ===
    entry_offset_percent: float = 0.0
    stop_loss_offset_points: int = 100
    use_point_based_sl: bool = False
    risk_reward_ratio: float = 2.0
    
    # === Breakout Timeout ===
    breakout_timeout_candles: int = 24  # 2 hours for 5M candles
    
    @classmethod
    def from_env(cls) -> 'BreakoutStrategyConfig':
        """Load configuration from environment variables"""
        return cls(
            enabled=os.getenv('BREAKOUT_STRATEGY_ENABLED', 'true').lower() == 'true',
            entry_offset_percent=float(os.getenv('ENTRY_OFFSET_PERCENT', '0.0')),
            stop_loss_offset_points=int(os.getenv('STOP_LOSS_OFFSET_POINTS', '100')),
            use_point_based_sl=os.getenv('USE_POINT_BASED_SL', 'false').lower() == 'true',
            risk_reward_ratio=float(os.getenv('RISK_REWARD_RATIO', '2.0')),
            breakout_timeout_candles=int(os.getenv('BREAKOUT_TIMEOUT_CANDLES', '24'))
        )

