"""
Configuration management for the trading system.
Ported from FMS_Config.mqh
"""
import os
from typing import List
from dotenv import load_dotenv

# Import all configuration dataclasses from the configs package
from src.config.configs import (
    MT5Config,
    StrategyConfig,
    StrategyEnableConfig,
    RiskConfig,
    TrailingStopConfig,
    TradingHoursConfig,
    AdvancedConfig,
    RangeConfigSettings,
    LoggingConfig,
    AdaptiveFilterConfig,
    SymbolAdaptationConfig,
    VolumeConfig,
    DivergenceConfig,
    HFTMomentumConfig,
    TickArchiveConfig,
)


# Load environment variables
load_dotenv()


class TradingConfig:
    """Main configuration class"""
    
    def __init__(self):
        # MT5 Configuration
        self.mt5 = MT5Config(
            login=int(os.getenv('MT5_LOGIN', '0')),
            password=os.getenv('MT5_PASSWORD', ''),
            server=os.getenv('MT5_SERVER', '')
        )

        # Symbols to trade - will be populated from Market Watch after MT5 connection
        self.symbols: List[str] = []
        
        # Strategy settings
        self.strategy = StrategyConfig(
            entry_offset_percent=float(os.getenv('ENTRY_OFFSET_PERCENT', '0.01')),
            stop_loss_offset_percent=float(os.getenv('STOP_LOSS_OFFSET_PERCENT', '0.02')),
            stop_loss_offset_points=int(os.getenv('STOP_LOSS_OFFSET_POINTS', '100')),
            use_point_based_sl=os.getenv('USE_POINT_BASED_SL', 'true').lower() == 'true',
            risk_reward_ratio=float(os.getenv('RISK_REWARD_RATIO', '2.0'))
        )
        
        # Risk management
        # Parse MIN_LOT_SIZE: if "MIN", use 0 to signal using symbol's minimum
        min_lot_str = os.getenv('MIN_LOT_SIZE', '0.01').strip().upper()
        min_lot_value = 0.0 if min_lot_str == 'MIN' else float(min_lot_str)

        # Parse MAX_LOT_SIZE: if "MAX", use 0 to signal using symbol's maximum; if "MIN", use symbol's minimum
        max_lot_str = os.getenv('MAX_LOT_SIZE', '0.01').strip().upper()
        if max_lot_str in ('MAX', 'MIN'):
            max_lot_value = 0.0
        else:
            max_lot_value = float(max_lot_str)

        self.risk = RiskConfig(
            risk_percent_per_trade=float(os.getenv('RISK_PERCENT_PER_TRADE', '1.0')),
            max_lot_size=max_lot_value,
            min_lot_size=min_lot_value,
            max_positions=int(os.getenv('MAX_POSITIONS', '1000')),
            max_portfolio_risk_percent=float(os.getenv('MAX_PORTFOLIO_RISK_PERCENT', '20.0'))
        )
        
        # Trailing stop
        self.trailing_stop = TrailingStopConfig(
            use_trailing_stop=os.getenv('USE_TRAILING_STOP', 'false').lower() == 'true',
            trailing_stop_trigger_rr=float(os.getenv('TRAILING_STOP_TRIGGER_RR', '1.5')),
            trailing_stop_distance=float(os.getenv('TRAILING_STOP_DISTANCE', '50.0')),
            use_atr_trailing=os.getenv('USE_ATR_TRAILING', 'false').lower() == 'true',
            atr_period=int(os.getenv('ATR_PERIOD', '14')),
            atr_multiplier=float(os.getenv('ATR_MULTIPLIER', '1.5')),
            atr_timeframe=os.getenv('ATR_TIMEFRAME', 'H4')
        )
        
        # Trading hours
        self.trading_hours = TradingHoursConfig(
            use_trading_hours=os.getenv('USE_TRADING_HOURS', 'false').lower() == 'true',
            start_hour=int(os.getenv('START_HOUR', '0')),
            end_hour=int(os.getenv('END_HOUR', '23')),
            check_symbol_session=os.getenv('CHECK_SYMBOL_SESSION', 'true').lower() == 'true',
            wait_for_session=os.getenv('WAIT_FOR_SESSION', 'false').lower() == 'true',
            session_wait_timeout_minutes=int(os.getenv('SESSION_WAIT_TIMEOUT_MINUTES', '30')),
            session_check_interval_seconds=int(os.getenv('SESSION_CHECK_INTERVAL_SECONDS', '60')),
            close_positions_before_session_end=os.getenv('CLOSE_POSITIONS_BEFORE_SESSION_END', 'false').lower() == 'true',
            close_positions_minutes_before_end=int(os.getenv('CLOSE_POSITIONS_MINUTES_BEFORE_END', '10'))
        )

        # Advanced settings
        self.advanced = AdvancedConfig(
            use_breakeven=os.getenv('USE_BREAKEVEN', 'true').lower() == 'true',
            breakeven_trigger_rr=float(os.getenv('BREAKEVEN_TRIGGER_RR', '1.0')),
            magic_number=int(os.getenv('MAGIC_NUMBER', '123456')),
            trade_comment=os.getenv('TRADE_COMMENT', '5MinScalper'),
            enable_order_prevalidation=os.getenv('ENABLE_ORDER_PREVALIDATION', 'true').lower() == 'true'
        )

        # Range configurations for multi-range mode
        self.range_config = RangeConfigSettings(
            enabled=os.getenv('MULTI_RANGE_ENABLED', 'true').lower() == 'true'
        )

        # Strategy enable/disable configuration
        self.strategy_enable = StrategyEnableConfig(
            true_breakout_enabled=os.getenv('TRUE_BREAKOUT_ENABLED', 'true').lower() == 'true',
            fakeout_enabled=os.getenv('FAKEOUT_ENABLED', 'true').lower() == 'true',
            hft_momentum_enabled=os.getenv('HFT_MOMENTUM_ENABLED', 'false').lower() == 'true',
            range_4h5m_enabled=os.getenv('RANGE_4H5M_ENABLED', 'true').lower() == 'true',
            range_15m1m_enabled=os.getenv('RANGE_15M1M_ENABLED', 'true').lower() == 'true',
            true_breakout_position_sizer=os.getenv('TRUE_BREAKOUT_POSITION_SIZER', 'fixed').lower(),
            fakeout_position_sizer=os.getenv('FAKEOUT_POSITION_SIZER', 'fixed').lower(),
            hft_momentum_position_sizer=os.getenv('HFT_MOMENTUM_POSITION_SIZER', 'martingale').lower()
        )

        # Logging
        self.logging = LoggingConfig(
            enable_detailed_logging=os.getenv('ENABLE_DETAILED_LOGGING', 'true').lower() == 'true',
            log_to_file=os.getenv('LOG_TO_FILE', 'true').lower() == 'true',
            log_to_console=os.getenv('LOG_TO_CONSOLE', 'true').lower() == 'true',
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            log_active_trades_every_5min=os.getenv('LOG_ACTIVE_TRADES_EVERY_5MIN', 'true').lower() == 'true'
        )
        
        # Adaptive filters
        # NOTE: Defaults changed for dual strategy system - confirmations must stay enabled
        self.adaptive_filters = AdaptiveFilterConfig(
            use_adaptive_filters=os.getenv('USE_ADAPTIVE_FILTERS', 'false').lower() == 'true',  # Changed default to 'false'
            adaptive_loss_trigger=int(os.getenv('ADAPTIVE_LOSS_TRIGGER', '3')),
            adaptive_win_recovery=int(os.getenv('ADAPTIVE_WIN_RECOVERY', '2')),
            start_with_filters_enabled=os.getenv('START_WITH_FILTERS_ENABLED', 'true').lower() == 'true'  # Changed default to 'true'
        )
        
        # Symbol adaptation
        self.symbol_adaptation = SymbolAdaptationConfig(
            use_symbol_adaptation=os.getenv('USE_SYMBOL_ADAPTATION', 'true').lower() == 'true',
            min_trades_for_evaluation=int(os.getenv('SYMBOL_MIN_TRADES', '10')),
            min_win_rate=float(os.getenv('SYMBOL_MIN_WIN_RATE', '30.0')),
            max_total_loss=float(os.getenv('SYMBOL_MAX_TOTAL_LOSS', '100.0')),
            max_consecutive_losses=int(os.getenv('SYMBOL_MAX_CONSECUTIVE_LOSSES', '3')),
            max_drawdown_percent=float(os.getenv('SYMBOL_MAX_DRAWDOWN_PERCENT', '15.0')),
            cooling_period_hours=int(os.getenv('SYMBOL_COOLING_PERIOD_HOURS', '168')),
            reset_weekly=os.getenv('SYMBOL_RESET_WEEKLY', 'true').lower() == 'true',
            weekly_reset_day=int(os.getenv('SYMBOL_WEEKLY_RESET_DAY', '0')),
            weekly_reset_hour=int(os.getenv('SYMBOL_WEEKLY_RESET_HOUR', '0'))
        )
        
        # Volume confirmation
        self.volume = VolumeConfig(
            breakout_volume_max_multiplier=float(os.getenv('BREAKOUT_VOLUME_MAX_MULTIPLIER', '1.0')),
            reversal_volume_min_multiplier=float(os.getenv('REVERSAL_VOLUME_MIN_MULTIPLIER', '1.5')),
            volume_average_period=int(os.getenv('VOLUME_AVERAGE_PERIOD', '20'))
        )
        
        # Divergence confirmation
        self.divergence = DivergenceConfig(
            require_both_indicators=os.getenv('REQUIRE_BOTH_INDICATORS', 'false').lower() == 'true',
            rsi_period=int(os.getenv('RSI_PERIOD', '14')),
            macd_fast=int(os.getenv('MACD_FAST', '12')),
            macd_slow=int(os.getenv('MACD_SLOW', '26')),
            macd_signal=int(os.getenv('MACD_SIGNAL', '9')),
            divergence_lookback=int(os.getenv('DIVERGENCE_LOOKBACK', '20'))
        )

        # HFT Momentum Strategy (with martingale position sizing parameters)
        from src.config.strategies import MartingaleType

        # Parse martingale type
        martingale_type_str = os.getenv('MP_MARTINGALE_TYPE', 'classic_multiplier').lower()
        martingale_type_map = {
            'classic_multiplier': MartingaleType.CLASSIC_MULTIPLIER,
            'multiplier_with_sum': MartingaleType.MULTIPLIER_WITH_SUM,
            'sum_with_initial': MartingaleType.SUM_WITH_INITIAL
        }
        martingale_type = martingale_type_map.get(martingale_type_str, MartingaleType.CLASSIC_MULTIPLIER)

        self.hft_momentum = HFTMomentumConfig(
            enabled=os.getenv('HFT_MOMENTUM_ENABLED', 'false').lower() == 'true',
            tick_momentum_count=int(os.getenv('MP_TICK_MOMENTUM_COUNT', '2')),
            trade_cooldown_seconds=int(os.getenv('MP_TRADE_COOLDOWN_SECONDS', '3')),
            enable_signal_validation=os.getenv('MP_ENABLE_SIGNAL_VALIDATION', 'true').lower() == 'true',
            use_auto_optimization=os.getenv('MP_USE_AUTO_OPTIMIZATION', 'true').lower() == 'true',
            min_momentum_strength=float(os.getenv('MP_MIN_MOMENTUM_STRENGTH', '0.0001')),
            min_volume_multiplier=float(os.getenv('MP_MIN_VOLUME_MULTIPLIER', '1.2')),
            volume_lookback=int(os.getenv('MP_VOLUME_LOOKBACK', '20')),
            enable_volatility_filter=os.getenv('MP_ENABLE_VOLATILITY_FILTER', 'true').lower() == 'true',
            min_atr_multiplier=float(os.getenv('MP_MIN_ATR_MULTIPLIER', '0.5')),
            max_atr_multiplier=float(os.getenv('MP_MAX_ATR_MULTIPLIER', '2.0')),
            atr_period=int(os.getenv('MP_ATR_PERIOD', '14')),
            atr_timeframe=os.getenv('MP_ATR_TIMEFRAME', 'M5'),
            atr_lookback=int(os.getenv('MP_ATR_LOOKBACK', '20')),
            enable_trend_filter=os.getenv('MP_ENABLE_TREND_FILTER', 'true').lower() == 'true',
            trend_ema_period=int(os.getenv('MP_TREND_EMA_PERIOD', '50')),
            trend_ema_timeframe=os.getenv('MP_TREND_EMA_TIMEFRAME', 'M5'),
            max_spread_multiplier=float(os.getenv('MP_MAX_SPREAD_MULTIPLIER', '2.0')),
            spread_lookback=int(os.getenv('MP_SPREAD_LOOKBACK', '20')),
            martingale_type=martingale_type,
            martingale_multiplier=float(os.getenv('MP_MARTINGALE_MULTIPLIER', '1.5')),
            max_orders_per_round=int(os.getenv('MP_MAX_ORDERS_PER_ROUND', '3')),
            max_lot_size=float(os.getenv('MP_MAX_LOT_SIZE', '5.0')),
            use_dynamic_stop_loss=os.getenv('MP_USE_DYNAMIC_STOP_LOSS', 'true').lower() == 'true',
            use_atr_multiplier=os.getenv('MP_USE_ATR_MULTIPLIER', 'true').lower() == 'true',
            atr_multiplier_for_sl=float(os.getenv('MP_ATR_MULTIPLIER_FOR_SL', '2.0')),
            risk_reward_ratio=float(os.getenv('MP_RISK_REWARD_RATIO', '2.0')),
            enable_consecutive_loss_protection=os.getenv('MP_ENABLE_CONSECUTIVE_LOSS_PROTECTION', 'true').lower() == 'true',
            max_consecutive_losses=int(os.getenv('MP_MAX_CONSECUTIVE_LOSSES', '5'))
        )

        # Symbol-specific optimization enabled
        self.use_symbol_specific_settings: bool = os.getenv('USE_SYMBOL_SPECIFIC_SETTINGS', 'true').lower() == 'true'

        # Tick archive configuration (for backtesting)
        self.tick_archive = TickArchiveConfig(
            enabled=os.getenv('TICK_ARCHIVE_ENABLED', 'false').lower() == 'true',
            archive_url_pattern=os.getenv('TICK_ARCHIVE_URL_PATTERN',
                'https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{BROKER}_{SYMBOL}_{YEAR}.zip'),
            download_timeout_seconds=int(os.getenv('TICK_ARCHIVE_TIMEOUT', '300')),
            max_retries=int(os.getenv('TICK_ARCHIVE_MAX_RETRIES', '3')),
            save_downloaded_archives=os.getenv('TICK_ARCHIVE_SAVE', 'true').lower() == 'true',
            archive_cache_dir=os.getenv('TICK_ARCHIVE_CACHE_DIR', 'data/tick_archives')
        )

    def load_symbols_from_active_set(self, file_path: str = "data/active.set", connector=None, logger=None) -> bool:
        """
        Load symbols from active.set file with automatic prioritization and deduplication.

        Args:
            file_path: Path to active.set file
            connector: MT5Connector instance for symbol validation (optional)
            logger: Logger instance (optional)

        Returns:
            True if symbols loaded successfully
        """
        from pathlib import Path
        from ..utils.active_set_manager import get_active_set_manager

        active_set_path = Path(file_path)
        if not active_set_path.exists():
            return False

        try:
            # Use ActiveSetManager with prioritization
            manager = get_active_set_manager(file_path, connector, enable_prioritization=True)
            symbols = manager.load_symbols(logger)

            if not symbols:
                return False

            self.symbols = symbols
            return True

        except Exception:
            return False

    def load_symbols_from_market_watch(self, connector) -> bool:
        """
        Load symbols from MetaTrader's Market Watch list.

        Args:
            connector: MT5Connector instance (must be connected)

        Returns:
            True if symbols loaded successfully
        """
        symbols = connector.get_market_watch_symbols()
        if not symbols:
            return False

        self.symbols = symbols
        return True

    def validate(self, check_symbols: bool = True) -> bool:
        """
        Validate configuration.

        Args:
            check_symbols: Whether to validate symbols (False during initial validation)
        """
        if not self.mt5.login or not self.mt5.password or not self.mt5.server:
            raise ValueError("MT5 credentials not configured")

        if self.risk.risk_percent_per_trade <= 0 or self.risk.risk_percent_per_trade > 100:
            raise ValueError("Risk percent must be between 0 and 100")

        if self.strategy.risk_reward_ratio <= 0:
            raise ValueError("Risk/Reward ratio must be positive")

        if check_symbols and not self.symbols:
            raise ValueError("No symbols configured")

        return True


# Global configuration instance
config = TradingConfig()

