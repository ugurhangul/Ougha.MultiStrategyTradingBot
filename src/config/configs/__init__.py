"""
Configuration modules for the trading system.

This package contains domain-specific configuration dataclasses
organized by responsibility for better maintainability.
"""

# Re-export all configuration classes for convenient imports
from src.config.configs.mt5_config import MT5Config
from src.config.configs.strategy_config import StrategyConfig, StrategyEnableConfig
from src.config.configs.risk_config import RiskConfig, TrailingStopConfig
from src.config.configs.trading_hours_config import TradingHoursConfig
from src.config.configs.advanced_config import AdvancedConfig
from src.config.configs.range_config import RangeConfigSettings
from src.config.configs.logging_config import LoggingConfig
from src.config.configs.adaptive_config import AdaptiveFilterConfig, SymbolAdaptationConfig
from src.config.configs.volume_divergence_config import VolumeConfig, DivergenceConfig
from src.config.configs.hft_momentum_config import HFTMomentumConfig
from src.config.configs.tick_archive_config import TickArchiveConfig

__all__ = [
    # MT5 Configuration
    'MT5Config',

    # Strategy Configuration
    'StrategyConfig',
    'StrategyEnableConfig',

    # Risk Management
    'RiskConfig',
    'TrailingStopConfig',

    # Trading Hours
    'TradingHoursConfig',

    # Advanced Settings
    'AdvancedConfig',

    # Range Configuration
    'RangeConfigSettings',

    # Logging
    'LoggingConfig',

    # Adaptive Filters
    'AdaptiveFilterConfig',
    'SymbolAdaptationConfig',

    # Volume & Divergence
    'VolumeConfig',
    'DivergenceConfig',

    # HFT Momentum
    'HFTMomentumConfig',

    # Tick Archive
    'TickArchiveConfig',
]

