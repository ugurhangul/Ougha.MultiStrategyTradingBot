"""
Signal Generator Service

Consolidates trade signal generation logic for the multi-range strategy engine.

This service handles:
- Pattern detection (highest high, lowest low)
- SL/TP calculation
- TradeSignal construction
"""
from typing import Optional, TYPE_CHECKING
from datetime import datetime
import pandas as pd
from src.models.data_models import (
    TradeSignal, PositionType, SymbolParameters, CandleData
)
from src.constants import DEFAULT_RISK_REWARD_RATIO

if TYPE_CHECKING:
    from src.utils.logger import TradingLogger


class SignalGenerator:
    """
    Service for generating trade signals with consistent SL/TP calculation.
    
    This class provides methods to:
    - Find pattern extremes (highest high, lowest low)
    - Calculate stop loss and take profit levels
    - Generate TradeSignal objects with proper parameters
    """
    
    def __init__(self, symbol: str, symbol_params: SymbolParameters, 
                 logger: 'TradingLogger', connector=None):
        """
        Initialize signal generator.
        
        Args:
            symbol: Symbol name
            symbol_params: Symbol-specific parameters
            logger: Logger instance
            connector: MT5 connector for symbol info (optional, for point-based SL)
        """
        self.symbol = symbol
        self.symbol_params = symbol_params
        self.logger = logger
        self.connector = connector
    
    def find_highest_high_in_pattern(self, candles_df: pd.DataFrame, 
                                     reference_high: float) -> Optional[float]:
        """
        Find the HIGHEST HIGH among the last 10 candles.
        
        Args:
            candles_df: DataFrame with candle data (must have 'high' column)
            reference_high: The reference level's high price (for logging only)
            
        Returns:
            Highest high price, or None if no valid candles found
        """
        if candles_df is None or len(candles_df) == 0:
            return None
        
        # Get last 10 candles
        last_10 = candles_df.tail(10)
        
        if len(last_10) == 0:
            return None
        
        # Find the highest high among all candles
        highest_high = last_10['high'].max()
        
        self.logger.debug(
            f"Pattern detection: Found highest high = {highest_high:.5f} "
            f"(reference high = {reference_high:.5f}) among {len(last_10)} candles",
            self.symbol
        )
        
        return highest_high
    
    def find_lowest_low_in_pattern(self, candles_df: pd.DataFrame, 
                                   reference_low: float) -> Optional[float]:
        """
        Find the LOWEST LOW among the last 10 candles.
        
        Args:
            candles_df: DataFrame with candle data (must have 'low' column)
            reference_low: The reference level's low price (for logging only)
            
        Returns:
            Lowest low price, or None if no valid candles found
        """
        if candles_df is None or len(candles_df) == 0:
            return None
        
        # Get last 10 candles
        last_10 = candles_df.tail(10)
        
        if len(last_10) == 0:
            return None
        
        # Find the lowest low among all candles
        lowest_low = last_10['low'].min()
        
        self.logger.debug(
            f"Pattern detection: Found lowest low = {lowest_low:.5f} "
            f"(reference low = {reference_low:.5f}) among {len(last_10)} candles",
            self.symbol
        )
        
        return lowest_low
    
    def generate_buy_signal(self, reference_low: float, candle_breakout: CandleData,
                           candles_df: pd.DataFrame, is_true_breakout: bool = False,
                           volume_confirmed: bool = False, divergence_confirmed: bool = False,
                           range_id: str = "default") -> TradeSignal:
        """
        Generate BUY trade signal.
        
        Args:
            reference_low: Reference level's low price
            candle_breakout: Current breakout candle
            candles_df: DataFrame with recent candles for pattern detection
            is_true_breakout: True if this is a true breakout (continuation)
            volume_confirmed: Whether volume confirmation passed
            divergence_confirmed: Whether divergence confirmation passed
            range_id: Range identifier (e.g., "4H_5M", "15M_1M")
            
        Returns:
            TradeSignal for BUY
        """
        # Find the LOWEST LOW among the last 10 candles
        lowest_low = self.find_lowest_low_in_pattern(candles_df, reference_low)
        
        if lowest_low is None:
            self.logger.warning(f"No valid lowest low found for BUY signal [{range_id}]", self.symbol, strategy_key=range_id)
            lowest_low = reference_low  # Fallback to reference low
        
        # Calculate entry, SL, and TP
        entry = candle_breakout.close
        sl = lowest_low
        
        # Calculate TP based on configured R:R ratio
        risk = abs(entry - sl)
        reward = risk * DEFAULT_RISK_REWARD_RATIO
        tp = entry + reward
        
        self.logger.info(f"BUY Signal Generated [{range_id}]:", self.symbol, strategy_key=range_id)
        self.logger.info(f"  Entry: {entry:.5f}", self.symbol, strategy_key=range_id)
        self.logger.info(f"  SL: {sl:.5f} (Lowest Low: {lowest_low:.5f})", self.symbol, strategy_key=range_id)
        self.logger.info(f"  TP: {tp:.5f}", self.symbol, strategy_key=range_id)
        self.logger.info(f"  Risk: {risk:.5f}, Reward: {reward:.5f}, R:R: {DEFAULT_RISK_REWARD_RATIO}", self.symbol, strategy_key=range_id)
        
        return TradeSignal(
            symbol=self.symbol,
            signal_type=PositionType.BUY,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            lot_size=0.0,  # Will be calculated by risk manager
            timestamp=candle_breakout.time,
            range_id=range_id,
            reason=f"{'True' if is_true_breakout else 'False'} breakout strategy - Range: {range_id}",
            max_spread_percent=self.symbol_params.max_spread_percent,
            is_true_breakout=is_true_breakout,
            volume_confirmed=volume_confirmed,
            divergence_confirmed=divergence_confirmed
        )
    
    def generate_sell_signal(self, reference_high: float, candle_breakout: CandleData,
                            candles_df: pd.DataFrame, is_true_breakout: bool = False,
                            volume_confirmed: bool = False, divergence_confirmed: bool = False,
                            range_id: str = "default") -> TradeSignal:
        """
        Generate SELL trade signal.
        
        Args:
            reference_high: Reference level's high price
            candle_breakout: Current breakout candle
            candles_df: DataFrame with recent candles for pattern detection
            is_true_breakout: True if this is a true breakout (continuation)
            volume_confirmed: Whether volume confirmation passed
            divergence_confirmed: Whether divergence confirmation passed
            range_id: Range identifier (e.g., "4H_5M", "15M_1M")
            
        Returns:
            TradeSignal for SELL
        """
        # Find the HIGHEST HIGH among the last 10 candles
        highest_high = self.find_highest_high_in_pattern(candles_df, reference_high)
        
        if highest_high is None:
            self.logger.warning(f"No valid highest high found for SELL signal [{range_id}]", self.symbol, strategy_key=range_id)
            highest_high = reference_high  # Fallback to reference high
        
        # Calculate entry, SL, and TP
        entry = candle_breakout.close
        sl = highest_high
        
        # Calculate TP based on configured R:R ratio
        risk = abs(sl - entry)
        reward = risk * DEFAULT_RISK_REWARD_RATIO
        tp = entry - reward
        
        self.logger.info(f"SELL Signal Generated [{range_id}]:", self.symbol, strategy_key=range_id)
        self.logger.info(f"  Entry: {entry:.5f}", self.symbol, strategy_key=range_id)
        self.logger.info(f"  SL: {sl:.5f} (Highest High: {highest_high:.5f})", self.symbol, strategy_key=range_id)
        self.logger.info(f"  TP: {tp:.5f}", self.symbol, strategy_key=range_id)
        self.logger.info(f"  Risk: {risk:.5f}, Reward: {reward:.5f}, R:R: {DEFAULT_RISK_REWARD_RATIO}", self.symbol, strategy_key=range_id)
        
        return TradeSignal(
            symbol=self.symbol,
            signal_type=PositionType.SELL,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            lot_size=0.0,  # Will be calculated by risk manager
            timestamp=candle_breakout.time,
            range_id=range_id,
            reason=f"{'True' if is_true_breakout else 'False'} breakout strategy - Range: {range_id}",
            max_spread_percent=self.symbol_params.max_spread_percent,
            is_true_breakout=is_true_breakout,
            volume_confirmed=volume_confirmed,
            divergence_confirmed=divergence_confirmed
        )

