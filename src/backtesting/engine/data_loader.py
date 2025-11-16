"""
Data Loader for Custom Backtesting Engine.

Loads historical OHLC data for multiple symbols with time alignment.
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import MetaTrader5 as mt5

from src.core.mt5_connector import MT5Connector
from src.backtesting.engine.data_cache import DataCache
from src.utils.logger import get_logger


class BacktestDataLoader:
    """
    Load and prepare historical data for backtesting.
    
    Handles:
    - Loading data from MT5 or CSV files
    - Time alignment across multiple symbols
    - Symbol info extraction
    """
    
    def __init__(self, connector: Optional[MT5Connector] = None,
                 use_cache: bool = True, cache_dir: str = "data"):
        """
        Initialize data loader.

        Args:
            connector: MT5Connector instance (optional, for loading from MT5)
            use_cache: Whether to use data caching (default: True)
            cache_dir: Directory for cached data (default: "data")
        """
        self.logger = get_logger()
        self.connector = connector
        self._owns_connector = False

        if connector is None:
            # Create our own connector
            from src.config import config
            self.connector = MT5Connector(config.mt5)
            self._owns_connector = True

        # Initialize cache
        self.use_cache = use_cache
        self.cache = DataCache(cache_dir) if use_cache else None
    
    def load_from_mt5(self, symbol: str, timeframe: str,
                     start_date: datetime, end_date: datetime,
                     force_refresh: bool = False) -> Optional[Tuple[pd.DataFrame, Dict]]:
        """
        Load historical data from MT5 with caching support.

        First checks cache, then falls back to MT5 if needed.

        Args:
            symbol: Symbol name
            timeframe: Timeframe (e.g., 'M1', 'M5', 'M15', 'H4')
            start_date: Start date (UTC)
            end_date: End date (UTC)
            force_refresh: If True, bypass cache and download from MT5

        Returns:
            Tuple of (DataFrame, symbol_info dict) or None if failed
        """
        # Try to load from cache first (unless force_refresh is True)
        if self.use_cache and not force_refresh:
            cached_data = self.cache.load_from_cache(symbol, timeframe, start_date, end_date)
            if cached_data is not None:
                return cached_data

            self.logger.info(f"  ⚠ Cache miss: {symbol} {timeframe} - downloading from MT5...")

        # Load from MT5
        result = self._download_from_mt5(symbol, timeframe, start_date, end_date)

        # Save to cache if successful
        if result is not None and self.use_cache:
            df, symbol_info = result
            self.cache.save_to_cache(symbol, timeframe, start_date, end_date, df, symbol_info)

        return result

    def _download_from_mt5(self, symbol: str, timeframe: str,
                          start_date: datetime, end_date: datetime) -> Optional[Tuple[pd.DataFrame, Dict]]:
        """
        Download historical data from MT5 (internal method).

        Args:
            symbol: Symbol name
            timeframe: Timeframe (e.g., "M1", "M5", "H1")
            start_date: Start date
            end_date: End date
            
        Returns:
            Tuple of (DataFrame with OHLC data, symbol_info dict) or None
        """
        try:
            # Connect if needed
            if self._owns_connector and not self.connector.is_connected:
                if not self.connector.connect():
                    self.logger.error("Failed to connect to MT5")
                    return None
            
            # Convert timeframe string to MT5 constant
            mt5_timeframe = self._convert_timeframe(timeframe)
            if mt5_timeframe is None:
                return None

            # Ensure symbol is selected in Market Watch (required for some brokers)
            if not mt5.symbol_select(symbol, True):
                self.logger.warning(f"Could not select {symbol} in Market Watch")

            # Get data from MT5
            self.logger.info(f"Loading {symbol} {timeframe} data from {start_date} to {end_date}")

            # Check if symbol is available
            symbol_info_check = mt5.symbol_info(symbol)
            if symbol_info_check is None:
                self.logger.error(f"Symbol {symbol} not found in MT5")
                return None

            if not symbol_info_check.visible:
                self.logger.warning(f"Symbol {symbol} not visible in Market Watch, attempting to enable...")
                if not mt5.symbol_select(symbol, True):
                    self.logger.error(f"Failed to enable {symbol} in Market Watch")
                    return None

            rates = mt5.copy_rates_range(symbol, mt5_timeframe, start_date, end_date)

            if rates is None or len(rates) == 0:
                # Get MT5 error details
                error_code, error_msg = mt5.last_error()
                self.logger.error(
                    f"No data retrieved for {symbol} {timeframe} - "
                    f"MT5 Error: ({error_code}) {error_msg}"
                )
                self.logger.error(
                    f"Date range: {start_date.strftime('%Y-%m-%d %H:%M:%S')} to {end_date.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                self.logger.error(f"Timeframe: {timeframe} (MT5 constant: {mt5_timeframe})")
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
            
            # Get symbol info
            symbol_info = self.connector.get_symbol_info(symbol)
            if not symbol_info:
                self.logger.error(f"Failed to get symbol info for {symbol}")
                return None
            
            self.logger.info(f"Loaded {len(df)} bars for {symbol}")
            
            return df, symbol_info
            
        except Exception as e:
            self.logger.error(f"Error loading data from MT5: {e}")
            return None

    def clear_cache(self, symbol: Optional[str] = None):
        """
        Clear cached data.

        Args:
            symbol: If specified, only clear cache for this symbol.
                   If None, clear entire cache.
        """
        if self.cache:
            self.cache.clear_cache(symbol)
        else:
            self.logger.warning("Cache is not enabled")

    def get_cache_stats(self) -> Dict:
        """
        Get statistics about cached data.

        Returns:
            Dictionary with cache statistics
        """
        if self.cache:
            return self.cache.get_cache_stats()
        else:
            return {'error': 'Cache is not enabled'}

    def load_from_csv(self, csv_path: str, symbol_info: Dict) -> Optional[Tuple[pd.DataFrame, Dict]]:
        """
        Load historical data from CSV file.
        
        CSV must have columns: time, open, high, low, close, volume (or tick_volume)
        
        Args:
            csv_path: Path to CSV file
            symbol_info: Dictionary with symbol information
            
        Returns:
            Tuple of (DataFrame with OHLC data, symbol_info dict) or None
        """
        try:
            self.logger.info(f"Loading data from CSV: {csv_path}")
            
            df = pd.read_csv(csv_path)
            
            # Ensure required columns exist
            required_cols = ['time', 'open', 'high', 'low', 'close']
            if not all(col in df.columns for col in required_cols):
                self.logger.error(f"CSV missing required columns: {required_cols}")
                return None
            
            # Convert time to datetime
            df['time'] = pd.to_datetime(df['time'])
            if df['time'].dt.tz is None:
                df['time'] = df['time'].dt.tz_localize('UTC')
            
            # Handle volume column
            if 'volume' not in df.columns and 'tick_volume' in df.columns:
                df['volume'] = df['tick_volume']
            elif 'volume' not in df.columns:
                df['volume'] = 0
            
            self.logger.info(f"Loaded {len(df)} bars from CSV")
            
            return df, symbol_info
            
        except Exception as e:
            self.logger.error(f"Error loading data from CSV: {e}")
            return None
    
    def get_available_date_range(self, symbol: str, timeframe: str = 'M1',
                                  num_bars: int = 1000) -> Optional[Tuple[datetime, datetime]]:
        """
        Get the available date range for a symbol by fetching recent bars.

        Useful for determining what historical data is actually available.

        Args:
            symbol: Symbol name
            timeframe: Timeframe to check (default: M1)
            num_bars: Number of bars to fetch (default: 1000)

        Returns:
            Tuple of (start_date, end_date) or None if no data available
        """
        try:
            # Connect if needed
            if self._owns_connector and not self.connector.is_connected:
                if not self.connector.connect():
                    return None

            # Convert timeframe
            mt5_timeframe = self._convert_timeframe(timeframe)
            if mt5_timeframe is None:
                return None

            # Select symbol
            mt5.symbol_select(symbol, True)

            # Get recent bars
            rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, num_bars)

            if rates is None or len(rates) == 0:
                return None

            # Convert timestamps to datetime
            start_time = pd.to_datetime(rates[0]['time'], unit='s', utc=True).to_pydatetime()
            end_time = pd.to_datetime(rates[-1]['time'], unit='s', utc=True).to_pydatetime()

            return start_time, end_time

        except Exception as e:
            self.logger.error(f"Error getting date range for {symbol}: {e}")
            return None

    def _convert_timeframe(self, timeframe: str) -> Optional[int]:
        """Convert timeframe string to MT5 constant."""
        timeframe_map = {
            'M1': mt5.TIMEFRAME_M1,
            'M5': mt5.TIMEFRAME_M5,
            'M15': mt5.TIMEFRAME_M15,
            'M30': mt5.TIMEFRAME_M30,
            'H1': mt5.TIMEFRAME_H1,
            'H4': mt5.TIMEFRAME_H4,
            'D1': mt5.TIMEFRAME_D1,
        }

        return timeframe_map.get(timeframe)

