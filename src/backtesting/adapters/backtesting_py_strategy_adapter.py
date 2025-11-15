"""
Strategy adapter for backtesting.py library.

Converts our trading strategies to backtesting.py Strategy format.
"""
from typing import Optional
from backtesting import Strategy
from backtesting.lib import crossover
import pandas as pd

from src.utils.logger import get_logger


class BacktestingPyStrategyAdapter(Strategy):
    """
    Base adapter for converting our strategies to backtesting.py format.
    
    backtesting.py requires:
    - Inherit from backtesting.Strategy
    - Implement init() method for indicators
    - Implement next() method for trading logic
    """
    
    # Strategy parameters (can be optimized)
    risk_reward_ratio = 2.0
    sl_buffer_pips = 5
    
    def __init__(self, broker, data, params):
        """Initialize strategy (called by backtesting.py)."""
        super().__init__(broker, data, params)
        self.logger = get_logger()
        
    def init(self):
        """
        Initialize indicators and setup.
        
        This is called once at the start of backtesting.
        Override this in subclasses to add indicators.
        """
        self.logger.info(f"Initializing {self.__class__.__name__}")
    
    def next(self):
        """
        Main trading logic - called for each candle.
        
        Override this in subclasses to implement strategy logic.
        """
        pass


class FakeoutStrategyAdapter(BacktestingPyStrategyAdapter):
    """
    Fakeout strategy adapter for backtesting.py.
    
    Simplified version of FakeoutStrategy for backtesting.
    """
    
    # Strategy parameters
    reference_lookback = 4  # Number of candles to look back for range
    max_breakout_volume_multiplier = 0.8
    min_reversal_volume_multiplier = 1.5
    risk_reward_ratio = 2.0
    sl_buffer_pips = 5
    
    def init(self):
        """Initialize indicators."""
        super().init()
        
        # Calculate rolling high/low for range detection
        self.range_high = self.I(
            lambda: pd.Series(self.data.High).rolling(self.reference_lookback).max(),
            name='Range High'
        )
        self.range_low = self.I(
            lambda: pd.Series(self.data.Low).rolling(self.reference_lookback).min(),
            name='Range Low'
        )
        
        # Calculate average volume
        self.avg_volume = self.I(
            lambda: pd.Series(self.data.Volume).rolling(20).mean(),
            name='Avg Volume'
        )
        
        self.logger.info("Fakeout strategy initialized")
    
    def next(self):
        """
        Trading logic for each candle.
        
        Fakeout logic:
        1. Detect breakout above/below range
        2. Check if breakout volume is LOW (weak breakout)
        3. Wait for reversal back into range
        4. Enter trade in reversal direction
        """
        # Skip if we don't have enough data
        if len(self.data) < self.reference_lookback + 20:
            return
        
        # Skip if already in position
        if self.position:
            return
        
        # Get current values
        current_high = self.data.High[-1]
        current_low = self.data.Low[-1]
        current_close = self.data.Close[-1]
        current_volume = self.data.Volume[-1]
        
        range_high = self.range_high[-1]
        range_low = self.range_low[-1]
        avg_vol = self.avg_volume[-1]
        
        # Check for valid range
        if pd.isna(range_high) or pd.isna(range_low) or pd.isna(avg_vol):
            return
        
        # === FALSE BREAKOUT SELL (breakout above, then reversal down) ===
        # Check if previous candle broke above range with low volume
        if len(self.data) >= 2:
            prev_close = self.data.Close[-2]
            prev_volume = self.data.Volume[-2]
            
            # Breakout above with low volume
            if (prev_close > range_high and 
                prev_volume < avg_vol * self.max_breakout_volume_multiplier):
                
                # Current candle reversed back into range with high volume
                if (current_close < range_high and
                    current_volume > avg_vol * self.min_reversal_volume_multiplier):
                    
                    # Enter SELL
                    sl = range_high + (self.sl_buffer_pips * 0.0001)  # Assuming forex
                    tp = current_close - (sl - current_close) * self.risk_reward_ratio
                    
                    self.sell(sl=sl, tp=tp)
                    self.logger.info(f"FALSE SELL at {current_close:.5f}, SL={sl:.5f}, TP={tp:.5f}")
        
        # === FALSE BREAKOUT BUY (breakout below, then reversal up) ===
        if len(self.data) >= 2:
            prev_close = self.data.Close[-2]
            prev_volume = self.data.Volume[-2]
            
            # Breakout below with low volume
            if (prev_close < range_low and 
                prev_volume < avg_vol * self.max_breakout_volume_multiplier):
                
                # Current candle reversed back into range with high volume
                if (current_close > range_low and
                    current_volume > avg_vol * self.min_reversal_volume_multiplier):
                    
                    # Enter BUY
                    sl = range_low - (self.sl_buffer_pips * 0.0001)  # Assuming forex
                    tp = current_close + (current_close - sl) * self.risk_reward_ratio
                    
                    self.buy(sl=sl, tp=tp)
                    self.logger.info(f"FALSE BUY at {current_close:.5f}, SL={sl:.5f}, TP={tp:.5f}")

