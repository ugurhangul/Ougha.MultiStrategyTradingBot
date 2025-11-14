"""
Symbol Parameters Repository

Stores and retrieves optimized parameters for different symbol categories.

This service follows the Single Responsibility Principle (SRP) by
focusing solely on parameter storage and retrieval.
"""
from typing import Dict
from src.models.data_models import SymbolCategory, SymbolParameters


class SymbolParametersRepository:
    """
    Repository for symbol category parameters.
    
    Stores optimized parameters for each symbol category based on
    historical performance analysis and data-driven optimization.
    """
    
    # Optimized parameters for each category
    # Updated based on log analysis (2025-11-05) to eliminate "both strategies rejected" gaps
    CATEGORY_PARAMETERS: Dict[SymbolCategory, SymbolParameters] = {
        SymbolCategory.MAJOR_FOREX: SymbolParameters(
            enable_false_breakout_strategy=True,
            enable_true_breakout_strategy=True,
            # Data-driven: Avg gap 0.50-0.82x, widened to capture more opportunities
            breakout_volume_max=0.85,  # Was 0.8, increased to capture 0.82x breakouts
            reversal_volume_min=1.5,   # Was 1.8, lowered for better signal generation
            true_breakout_volume_min=1.5,  # Was 2.0, lowered to reduce rejections
            continuation_volume_min=1.3,   # Was 1.5, lowered for consistency
            retest_range_percent=0.0015,  # 0.15% - Major pairs moderate volatility
            retest_range_points=0.0,  # Use percentage for forex
            retest_tolerance_mode='percent',  # Force percentage-based for forex
            volume_average_period=20,
            rsi_period=14,
            macd_fast=12,
            macd_slow=26,
            macd_signal=9,
            divergence_lookback=20,
            adaptive_loss_trigger=1,
            adaptive_win_recovery=3,
            max_spread_percent=0.05,  # Major pairs: 0.05% (tight spreads)
            # HFT Momentum validation thresholds
            min_momentum_strength=2.5,  # Multiplier for spread
            min_volume_multiplier=1.2,
            min_atr_multiplier=0.6,
            max_atr_multiplier=2.5,
            trend_ema_period=50,
            max_spread_multiplier=2.0,
            # Stop loss parameters
            base_stop_loss_points=300,  # 30 pips
            atr_multiplier_for_sl=1.5
        ),
        SymbolCategory.MINOR_FOREX: SymbolParameters(
            enable_false_breakout_strategy=True,
            enable_true_breakout_strategy=True,
            # Data-driven: Avg gap 0.57-0.78x, widened to eliminate gaps
            breakout_volume_max=0.90,  # Was 0.7, increased significantly
            reversal_volume_min=1.5,   # Was 2.0, lowered
            true_breakout_volume_min=1.5,  # Was 2.2, lowered significantly
            continuation_volume_min=1.3,   # Was 1.6, lowered
            retest_range_percent=0.0020,  # 0.20% - Minor pairs higher volatility
            retest_range_points=0.0,  # Use percentage for forex
            retest_tolerance_mode='percent',  # Force percentage-based for forex
            volume_average_period=25,
            rsi_period=14,
            macd_fast=12,
            macd_slow=26,
            macd_signal=9,
            divergence_lookback=25,
            adaptive_loss_trigger=1,
            adaptive_win_recovery=3,
            max_spread_percent=0.05,  # Minor pairs: 0.05% (slightly wider spreads)
            # HFT Momentum validation thresholds
            min_momentum_strength=3.0,
            min_volume_multiplier=1.3,
            min_atr_multiplier=0.7,
            max_atr_multiplier=3.5,
            trend_ema_period=50,
            max_spread_multiplier=2.5,
            # Stop loss parameters
            base_stop_loss_points=400,  # 40 pips
            atr_multiplier_for_sl=2.0
        ),
        SymbolCategory.EXOTIC_FOREX: SymbolParameters(
            enable_false_breakout_strategy=True,
            enable_true_breakout_strategy=True,
            # Data-driven: Avg gap 0.60-0.85x, widened significantly
            breakout_volume_max=1.0,   # Was 0.6, increased significantly
            reversal_volume_min=1.4,   # Was 2.5, lowered significantly
            true_breakout_volume_min=1.4,  # Was 2.8, lowered significantly
            continuation_volume_min=1.2,   # Was 1.8, lowered
            retest_range_percent=0.0030,  # 0.30% - Exotic pairs very high volatility
            retest_range_points=0.0,  # Use percentage for forex
            retest_tolerance_mode='percent',  # Force percentage-based for forex
            volume_average_period=30,
            rsi_period=14,
            macd_fast=12,
            macd_slow=26,
            macd_signal=9,
            divergence_lookback=30,
            adaptive_loss_trigger=1,
            adaptive_win_recovery=3,
            max_spread_percent=0.02,  # Exotic pairs: 0.10% (wider spreads)
            # HFT Momentum validation thresholds
            min_momentum_strength=4.0,
            min_volume_multiplier=1.4,
            min_atr_multiplier=0.8,
            max_atr_multiplier=4.5,
            trend_ema_period=50,
            max_spread_multiplier=3.0,
            # Stop loss parameters
            base_stop_loss_points=1000,  # 100 pips
            atr_multiplier_for_sl=2.5
        ),
        SymbolCategory.METALS: SymbolParameters(
            enable_false_breakout_strategy=True,
            enable_true_breakout_strategy=True,
            # Data-driven: Avg gap 0.55-0.80x, widened to eliminate gaps
            breakout_volume_max=0.90,  # Was 0.75, increased
            reversal_volume_min=1.5,   # Was 2.0, lowered
            true_breakout_volume_min=1.5,  # Was 2.5, lowered significantly
            continuation_volume_min=1.3,   # Was 1.7, lowered
            retest_range_percent=0.0025,  # 0.25% - Metals high volatility
            retest_range_points=0.0,  # Use auto mode (will choose based on price scale)
            retest_tolerance_mode='auto',  # Auto-detect best mode
            volume_average_period=20,
            rsi_period=14,
            macd_fast=12,
            macd_slow=26,
            macd_signal=9,
            divergence_lookback=20,
            adaptive_loss_trigger=1,
            adaptive_win_recovery=3,
            max_spread_percent=0.02,  # Metals: 0.05% (tight spreads for gold/silver)
            # HFT Momentum validation thresholds
            min_momentum_strength=4.0,
            min_volume_multiplier=1.4,
            min_atr_multiplier=0.8,
            max_atr_multiplier=4.0,
            trend_ema_period=100,
            max_spread_multiplier=3.0,
            # Stop loss parameters
            base_stop_loss_points=900,  # Average of Gold(800) and Silver(1000)
            atr_multiplier_for_sl=2.5
        ),
        SymbolCategory.INDICES: SymbolParameters(
            enable_false_breakout_strategy=True,
            enable_true_breakout_strategy=True,
            # Data-driven: Avg gap 0.60-0.85x, widened to eliminate gaps
            breakout_volume_max=0.95,  # Was 0.7, increased significantly
            reversal_volume_min=1.5,   # Was 2.2, lowered
            true_breakout_volume_min=1.5,  # Was 2.5, lowered significantly
            continuation_volume_min=1.3,   # Was 1.8, lowered
            retest_range_percent=0.0020,  # 0.20% - Indices moderate-high volatility
            retest_range_points=500.0,  # 500 points - Appropriate for indices (e.g., SPX ~4000)
            retest_tolerance_mode='auto',  # Auto-detect best mode
            volume_average_period=25,
            rsi_period=14,
            macd_fast=12,
            macd_slow=26,
            macd_signal=9,
            divergence_lookback=25,
            adaptive_loss_trigger=1,
            adaptive_win_recovery=3,
            max_spread_percent=0.01,  # Indices: 0.08% (moderate spreads)
            # HFT Momentum validation thresholds
            min_momentum_strength=3.5,
            min_volume_multiplier=1.3,
            min_atr_multiplier=0.7,
            max_atr_multiplier=3.5,
            trend_ema_period=50,
            max_spread_multiplier=2.5,
            # Stop loss parameters
            base_stop_loss_points=2000,  # 200 points
            atr_multiplier_for_sl=2.0
        ),
        SymbolCategory.CRYPTO: SymbolParameters(
            enable_false_breakout_strategy=True,
            enable_true_breakout_strategy=True,
            # Data-driven: Avg gap 0.65-0.90x, widened significantly
            breakout_volume_max=1.0,   # Was 0.6, increased significantly
            reversal_volume_min=1.4,   # Was 3.0, lowered significantly
            true_breakout_volume_min=1.4,  # Was 3.5, lowered significantly
            continuation_volume_min=1.2,   # Was 2.0, lowered
            retest_range_percent=0.0015,  # 0.15% - Used for low-value crypto (XRPUSD, etc.)
            retest_range_points=20000.0,  # 20,000 points - Used for high-value crypto (BTCJPY ~14M)
            retest_tolerance_mode='auto',  # Auto-detect: price>1000 uses points, else uses %
            volume_average_period=30,
            rsi_period=14,
            macd_fast=12,
            macd_slow=26,
            macd_signal=9,
            divergence_lookback=30,
            adaptive_loss_trigger=1,
            adaptive_win_recovery=3,
            max_spread_percent=0.15,  # Crypto: 0.15% (very wide spreads)
            # HFT Momentum validation thresholds
            min_momentum_strength=5.0,
            min_volume_multiplier=1.6,
            min_atr_multiplier=1.0,
            max_atr_multiplier=8.0,
            trend_ema_period=50,
            max_spread_multiplier=4.0,
            # Stop loss parameters
            base_stop_loss_points=7000,  # 700 pips
            atr_multiplier_for_sl=3.0
        ),
        SymbolCategory.COMMODITIES: SymbolParameters(
            enable_false_breakout_strategy=True,
            enable_true_breakout_strategy=True,
            # Data-driven: Avg gap 0.60-0.85x, widened to eliminate gaps
            breakout_volume_max=0.95,  # Was 0.7, increased significantly
            reversal_volume_min=1.5,   # Was 2.3, lowered
            true_breakout_volume_min=1.5,  # Was 2.6, lowered significantly
            continuation_volume_min=1.3,   # Was 1.8, lowered
            retest_range_percent=0.0030,  # 0.30% - Commodities high volatility
            retest_range_points=0.0,  # Use auto mode (will choose based on price scale)
            retest_tolerance_mode='auto',  # Auto-detect best mode
            volume_average_period=25,
            rsi_period=14,
            macd_fast=12,
            macd_slow=26,
            macd_signal=9,
            divergence_lookback=25,
            adaptive_loss_trigger=1,
            adaptive_win_recovery=3,
            max_spread_percent=0.08,  # Commodities: 0.08% (moderate spreads)
            # HFT Momentum validation thresholds
            min_momentum_strength=3.5,
            min_volume_multiplier=1.3,
            min_atr_multiplier=0.7,
            max_atr_multiplier=3.5,
            trend_ema_period=50,
            max_spread_multiplier=2.5,
            # Stop loss parameters
            base_stop_loss_points=1000,  # 100 pips
            atr_multiplier_for_sl=2.0
        ),
        SymbolCategory.STOCKS: SymbolParameters(
            enable_false_breakout_strategy=True,
            enable_true_breakout_strategy=True,
            # Data-driven: Avg gap 0.60-0.85x, widened to eliminate gaps
            breakout_volume_max=0.95,  # Was 0.7, increased significantly
            reversal_volume_min=1.5,   # Was 2.2, lowered
            true_breakout_volume_min=1.5,  # Was 2.5, lowered significantly
            continuation_volume_min=1.3,   # Was 1.8, lowered
            retest_range_percent=0.0025,  # 0.25% - Stocks moderate-high volatility
            retest_range_points=0.0,  # Use auto mode (will choose based on price scale)
            retest_tolerance_mode='auto',  # Auto-detect best mode
            volume_average_period=25,
            rsi_period=14,
            macd_fast=12,
            macd_slow=26,
            macd_signal=9,
            divergence_lookback=25,
            adaptive_loss_trigger=1,
            adaptive_win_recovery=3,
            max_spread_percent=0.10,  # Stocks: 0.10% (wider spreads)
            # HFT Momentum validation thresholds
            min_momentum_strength=3.0,
            min_volume_multiplier=1.3,
            min_atr_multiplier=0.7,
            max_atr_multiplier=3.0,
            trend_ema_period=50,
            max_spread_multiplier=2.5,
            # Stop loss parameters
            base_stop_loss_points=500,
            atr_multiplier_for_sl=2.0
        )
    }
    
    @classmethod
    def get_parameters(cls, category: SymbolCategory, default_params: SymbolParameters) -> SymbolParameters:
        """
        Get optimized parameters for symbol category.
        
        Args:
            category: Symbol category
            default_params: Default parameters to use if category is unknown
            
        Returns:
            SymbolParameters for the category
        """
        if category == SymbolCategory.UNKNOWN:
            return default_params
        
        return cls.CATEGORY_PARAMETERS.get(category, default_params)

