"""
Signal validation helpers.

Provides helper functions for validating trading signals based on
volume, ATR, trend alignment, and spread conditions.
"""


class SignalValidationHelpers:
    """Helper functions for signal validation"""

    @staticmethod
    def check_volume_confirmation(recent_volume: float, avg_volume: float,
                                  min_multiplier: float) -> bool:
        """
        Check if volume confirms the signal.

        Args:
            recent_volume: Recent volume (average or single tick)
            avg_volume: Average volume over lookback period
            min_multiplier: Minimum volume multiplier threshold

        Returns:
            True if volume confirms signal
        """
        if avg_volume <= 0:
            return False

        volume_ratio = recent_volume / avg_volume
        return volume_ratio >= min_multiplier

    @staticmethod
    def check_atr_filter(current_atr: float, avg_atr: float,
                        min_multiplier: float, max_multiplier: float) -> bool:
        """
        Check if current ATR is within acceptable range.

        Args:
            current_atr: Current ATR value
            avg_atr: Average ATR over lookback period
            min_multiplier: Minimum ATR multiplier
            max_multiplier: Maximum ATR multiplier

        Returns:
            True if ATR is within range
        """
        if avg_atr <= 0:
            return True  # Skip check if no data

        atr_ratio = current_atr / avg_atr
        return min_multiplier <= atr_ratio <= max_multiplier

    @staticmethod
    def check_trend_alignment(current_price: float, trend_ema: float,
                             is_buy_signal: bool) -> bool:
        """
        Check if price aligns with trend direction.

        Args:
            current_price: Current price (mid-price)
            trend_ema: Trend EMA value
            is_buy_signal: True for BUY signal, False for SELL

        Returns:
            True if trend aligns with signal
        """
        if is_buy_signal:
            return current_price > trend_ema
        else:
            return current_price < trend_ema

    @staticmethod
    def check_spread_filter(current_spread: float, avg_spread: float,
                           max_multiplier: float) -> bool:
        """
        Check if current spread is acceptable.

        Args:
            current_spread: Current spread
            avg_spread: Average spread over lookback period
            max_multiplier: Maximum spread multiplier

        Returns:
            True if spread is acceptable
        """
        if avg_spread <= 0:
            return True  # Skip check if no data

        spread_ratio = current_spread / avg_spread
        return spread_ratio <= max_multiplier

