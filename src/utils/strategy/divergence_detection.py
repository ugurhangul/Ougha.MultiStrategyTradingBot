"""
Divergence detection utilities.

Provides utilities for detecting RSI and MACD divergence patterns
to confirm trading signals.

Note: This is a utility wrapper. The actual divergence detection logic
is implemented in TechnicalIndicators class (src/indicators/technical_indicators.py).
"""
from typing import Optional
import pandas as pd


class DivergenceDetector:
    """
    Divergence detection utilities for breakout strategies.

    This class provides static helper methods for divergence detection.
    The actual implementation is in TechnicalIndicators class which uses
    TA-Lib for RSI calculation and swing point detection.

    Usage:
        from src.indicators.technical_indicators import TechnicalIndicators

        indicators = TechnicalIndicators(connector)

        # For bullish divergence (BUY signals)
        bullish_div = indicators.detect_bullish_rsi_divergence(
            df, rsi_period=14, lookback=20, symbol='EURUSD'
        )

        # For bearish divergence (SELL signals)
        bearish_div = indicators.detect_bearish_rsi_divergence(
            df, rsi_period=14, lookback=20, symbol='EURUSD'
        )
    """

    @staticmethod
    def check_rsi_divergence(df: pd.DataFrame, indicators: 'TechnicalIndicators',
                            direction: str, rsi_period: int = 14,
                            lookback: int = 20, symbol: str = '') -> bool:
        """
        Check for RSI divergence using TechnicalIndicators.

        Args:
            df: DataFrame with OHLC data
            indicators: TechnicalIndicators instance
            direction: 'BUY' for bullish divergence, 'SELL' for bearish
            rsi_period: RSI period (default: 14)
            lookback: Lookback period for divergence detection (default: 20)
            symbol: Symbol name for logging

        Returns:
            True if divergence detected
        """
        if direction == 'BUY':
            return indicators.detect_bullish_rsi_divergence(
                df, rsi_period, lookback, symbol
            )
        elif direction == 'SELL':
            return indicators.detect_bearish_rsi_divergence(
                df, rsi_period, lookback, symbol
            )
        else:
            return False

    @staticmethod
    def check_macd_divergence(df: pd.DataFrame, indicators: 'TechnicalIndicators',
                             direction: str, lookback: int = 20,
                             symbol: str = '') -> bool:
        """
        Check for MACD divergence.

        Args:
            df: DataFrame with OHLC data
            indicators: TechnicalIndicators instance
            direction: 'BUY' for bullish divergence, 'SELL' for bearish
            lookback: Lookback period for divergence detection
            symbol: Symbol name for logging

        Returns:
            True if divergence detected

        Note:
            MACD divergence detection is not yet implemented in TechnicalIndicators.
            This is a placeholder for future implementation.
        """
        # TODO: Implement MACD divergence detection in TechnicalIndicators
        return False

    @staticmethod
    def is_divergence_confirmed(rsi_divergence: bool, macd_divergence: bool,
                               require_both: bool = False) -> bool:
        """
        Validate divergence strength.

        Args:
            rsi_divergence: RSI divergence detected
            macd_divergence: MACD divergence detected
            require_both: If True, both must be present

        Returns:
            True if divergence is confirmed
        """
        if require_both:
            return rsi_divergence and macd_divergence
        return rsi_divergence or macd_divergence

