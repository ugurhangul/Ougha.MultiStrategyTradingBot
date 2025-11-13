"""
Timeframe Conversion Utility

Provides utilities for converting between timeframe string representations
and MT5 timeframe constants, as well as calculating timeframe durations.
"""
from typing import Optional
from datetime import timedelta
from src.constants import TIMEFRAME_MAP, TIMEFRAME_REVERSE_MAP, ERROR_INVALID_TIMEFRAME


class TimeframeConverter:
    """
    Utility class for timeframe conversions and calculations.
    
    This class provides static methods for:
    - Converting timeframe strings to MT5 constants
    - Converting MT5 constants back to strings
    - Calculating timeframe durations
    - Validating timeframe strings
    """
    
    @staticmethod
    def to_mt5_constant(timeframe: str) -> Optional[int]:
        """
        Convert timeframe string to MT5 constant.
        
        Args:
            timeframe: Timeframe string (e.g., 'M5', 'H4', 'D1')
            
        Returns:
            MT5 timeframe constant or None if invalid
            
        Examples:
            >>> TimeframeConverter.to_mt5_constant('M5')
            5  # mt5.TIMEFRAME_M5
            >>> TimeframeConverter.to_mt5_constant('H4')
            16388  # mt5.TIMEFRAME_H4
        """
        return TIMEFRAME_MAP.get(timeframe)
    
    @staticmethod
    def to_string(mt5_constant: int) -> Optional[str]:
        """
        Convert MT5 timeframe constant to string.
        
        Args:
            mt5_constant: MT5 timeframe constant
            
        Returns:
            Timeframe string or None if invalid
            
        Examples:
            >>> TimeframeConverter.to_string(5)
            'M5'
            >>> TimeframeConverter.to_string(16388)
            'H4'
        """
        return TIMEFRAME_REVERSE_MAP.get(mt5_constant)
    
    @staticmethod
    def is_valid(timeframe: str) -> bool:
        """
        Check if timeframe string is valid.
        
        Args:
            timeframe: Timeframe string to validate
            
        Returns:
            True if valid, False otherwise
            
        Examples:
            >>> TimeframeConverter.is_valid('M5')
            True
            >>> TimeframeConverter.is_valid('M7')
            False
        """
        return timeframe in TIMEFRAME_MAP
    
    @staticmethod
    def get_duration_minutes(timeframe: str) -> Optional[int]:
        """
        Get timeframe duration in minutes.
        
        Args:
            timeframe: Timeframe string (e.g., 'M5', 'H4', 'D1')
            
        Returns:
            Duration in minutes or None if invalid
            
        Examples:
            >>> TimeframeConverter.get_duration_minutes('M5')
            5
            >>> TimeframeConverter.get_duration_minutes('H4')
            240
            >>> TimeframeConverter.get_duration_minutes('D1')
            1440
        """
        if not TimeframeConverter.is_valid(timeframe):
            return None
        
        # Parse timeframe string
        if timeframe.startswith('M'):
            # Minutes
            try:
                return int(timeframe[1:])
            except ValueError:
                return None
        elif timeframe.startswith('H'):
            # Hours
            try:
                hours = int(timeframe[1:])
                return hours * 60
            except ValueError:
                return None
        elif timeframe.startswith('D'):
            # Days
            try:
                days = int(timeframe[1:])
                return days * 1440  # 24 * 60
            except ValueError:
                return None
        elif timeframe.startswith('W'):
            # Weeks
            try:
                weeks = int(timeframe[1:])
                return weeks * 10080  # 7 * 24 * 60
            except ValueError:
                return None
        elif timeframe.startswith('MN'):
            # Months (approximate as 30 days)
            try:
                months = int(timeframe[2:])
                return months * 43200  # 30 * 24 * 60
            except ValueError:
                return None
        
        return None

    @staticmethod
    def get_minutes_per_candle(timeframe: str, default: int = 5) -> int:
        """
        Get the number of minutes per candle for a given timeframe.

        This is an alias for get_duration_minutes() with a default fallback value.
        Useful for timeout calculations and candle-based time calculations.

        Args:
            timeframe: Timeframe string (e.g., 'M5', 'H4', 'D1')
            default: Default value to return if timeframe is invalid (default: 5)

        Returns:
            Duration in minutes, or default value if invalid

        Examples:
            >>> TimeframeConverter.get_minutes_per_candle('M5')
            5
            >>> TimeframeConverter.get_minutes_per_candle('H4')
            240
            >>> TimeframeConverter.get_minutes_per_candle('INVALID')
            5  # Returns default
        """
        minutes = TimeframeConverter.get_duration_minutes(timeframe)
        return minutes if minutes is not None else default

    @staticmethod
    def get_duration_timedelta(timeframe: str) -> Optional[timedelta]:
        """
        Get timeframe duration as timedelta object.
        
        Args:
            timeframe: Timeframe string (e.g., 'M5', 'H4', 'D1')
            
        Returns:
            timedelta object or None if invalid
            
        Examples:
            >>> TimeframeConverter.get_duration_timedelta('M5')
            timedelta(minutes=5)
            >>> TimeframeConverter.get_duration_timedelta('H4')
            timedelta(hours=4)
        """
        minutes = TimeframeConverter.get_duration_minutes(timeframe)
        if minutes is None:
            return None
        
        return timedelta(minutes=minutes)
    
    @staticmethod
    def get_all_supported_timeframes() -> list:
        """
        Get list of all supported timeframe strings.
        
        Returns:
            List of timeframe strings
            
        Examples:
            >>> TimeframeConverter.get_all_supported_timeframes()
            ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1', 'MN1']
        """
        return list(TIMEFRAME_MAP.keys())
    
    @staticmethod
    def validate_or_raise(timeframe: str) -> int:
        """
        Validate timeframe and return MT5 constant, or raise ValueError.
        
        Args:
            timeframe: Timeframe string to validate
            
        Returns:
            MT5 timeframe constant
            
        Raises:
            ValueError: If timeframe is invalid
            
        Examples:
            >>> TimeframeConverter.validate_or_raise('M5')
            5
            >>> TimeframeConverter.validate_or_raise('INVALID')
            ValueError: Invalid timeframe: INVALID
        """
        mt5_constant = TimeframeConverter.to_mt5_constant(timeframe)
        if mt5_constant is None:
            raise ValueError(f"{ERROR_INVALID_TIMEFRAME}: {timeframe}")
        return mt5_constant
    
    @staticmethod
    def compare_timeframes(tf1: str, tf2: str) -> int:
        """
        Compare two timeframes by duration.
        
        Args:
            tf1: First timeframe string
            tf2: Second timeframe string
            
        Returns:
            -1 if tf1 < tf2, 0 if tf1 == tf2, 1 if tf1 > tf2
            None if either timeframe is invalid
            
        Examples:
            >>> TimeframeConverter.compare_timeframes('M5', 'H4')
            -1  # M5 is shorter than H4
            >>> TimeframeConverter.compare_timeframes('H4', 'M5')
            1   # H4 is longer than M5
            >>> TimeframeConverter.compare_timeframes('M5', 'M5')
            0   # Equal
        """
        duration1 = TimeframeConverter.get_duration_minutes(tf1)
        duration2 = TimeframeConverter.get_duration_minutes(tf2)
        
        if duration1 is None or duration2 is None:
            return None
        
        if duration1 < duration2:
            return -1
        elif duration1 > duration2:
            return 1
        else:
            return 0
    
    @staticmethod
    def get_smaller_timeframe(tf1: str, tf2: str) -> Optional[str]:
        """
        Get the smaller (shorter duration) of two timeframes.
        
        Args:
            tf1: First timeframe string
            tf2: Second timeframe string
            
        Returns:
            The smaller timeframe string or None if either is invalid
            
        Examples:
            >>> TimeframeConverter.get_smaller_timeframe('M5', 'H4')
            'M5'
            >>> TimeframeConverter.get_smaller_timeframe('H4', 'M1')
            'M1'
        """
        comparison = TimeframeConverter.compare_timeframes(tf1, tf2)
        if comparison is None:
            return None
        elif comparison <= 0:
            return tf1
        else:
            return tf2
    
    @staticmethod
    def get_larger_timeframe(tf1: str, tf2: str) -> Optional[str]:
        """
        Get the larger (longer duration) of two timeframes.
        
        Args:
            tf1: First timeframe string
            tf2: Second timeframe string
            
        Returns:
            The larger timeframe string or None if either is invalid
            
        Examples:
            >>> TimeframeConverter.get_larger_timeframe('M5', 'H4')
            'H4'
            >>> TimeframeConverter.get_larger_timeframe('H4', 'M1')
            'H4'
        """
        comparison = TimeframeConverter.compare_timeframes(tf1, tf2)
        if comparison is None:
            return None
        elif comparison >= 0:
            return tf1
        else:
            return tf2

