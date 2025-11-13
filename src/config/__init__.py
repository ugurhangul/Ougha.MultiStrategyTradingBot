"""
Configuration management for the trading system.

This package provides a hierarchical configuration system:
- Global configuration (TradingConfig)
- Strategy-specific configurations (strategies/)
- Symbol-specific optimization (symbols/)
- General settings (configs/)
"""

# Re-export main configuration class and singleton
from src.config.trading_config import TradingConfig, config

__all__ = [
    'TradingConfig',
    'config',
]
