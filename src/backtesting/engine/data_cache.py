"""
Data Cache for Backtesting.

Caches historical OHLC data and symbol information to disk to avoid
repeated downloads from MT5 and enable offline backtesting.
"""
import os
import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple
import MetaTrader5 as mt5

from src.utils.logger import get_logger


class DataCache:
    """
    Manages caching of historical market data and symbol information.
    
    Cache structure:
        data/
            {symbol}/
                {timeframe}_{start_date}_{end_date}.parquet  # OHLC data
                symbol_info.json                              # Symbol metadata
    """
    
    def __init__(self, cache_dir: str = "data"):
        """
        Initialize data cache.
        
        Args:
            cache_dir: Root directory for cached data
        """
        self.cache_dir = Path(cache_dir)
        self.logger = get_logger()
        
        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_cache_path(self, symbol: str, timeframe: str, 
                        start_date: datetime, end_date: datetime) -> Path:
        """
        Get the cache file path for a symbol/timeframe/date range.
        
        Args:
            symbol: Symbol name
            timeframe: Timeframe (e.g., 'M1', 'M5', 'M15', 'H4')
            start_date: Start date
            end_date: End date
            
        Returns:
            Path to cache file
        """
        symbol_dir = self.cache_dir / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)
        
        # Format dates as YYYY-MM-DD for filename
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        
        filename = f"{timeframe}_{start_str}_{end_str}.parquet"
        return symbol_dir / filename
    
    def _get_symbol_info_path(self, symbol: str) -> Path:
        """Get path to symbol info JSON file."""
        symbol_dir = self.cache_dir / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)
        return symbol_dir / "symbol_info.json"
    
    def has_cached_data(self, symbol: str, timeframe: str,
                        start_date: datetime, end_date: datetime) -> bool:
        """
        Check if cached data exists for the given parameters.
        
        Args:
            symbol: Symbol name
            timeframe: Timeframe
            start_date: Start date
            end_date: End date
            
        Returns:
            True if cache file exists
        """
        cache_path = self._get_cache_path(symbol, timeframe, start_date, end_date)
        return cache_path.exists()
    
    def load_from_cache(self, symbol: str, timeframe: str,
                        start_date: datetime, end_date: datetime) -> Optional[Tuple[pd.DataFrame, Dict]]:
        """
        Load data from cache.
        
        Args:
            symbol: Symbol name
            timeframe: Timeframe
            start_date: Start date
            end_date: End date
            
        Returns:
            Tuple of (DataFrame, symbol_info dict) or None if not found
        """
        cache_path = self._get_cache_path(symbol, timeframe, start_date, end_date)
        symbol_info_path = self._get_symbol_info_path(symbol)
        
        if not cache_path.exists():
            return None
        
        try:
            # Load OHLC data using PyArrow engine (2-3x faster than default)
            df = pd.read_parquet(cache_path, engine='pyarrow')

            # Ensure time column is datetime with UTC timezone
            # Only convert if not already datetime (avoid expensive re-conversion)
            if 'time' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['time']):
                df['time'] = pd.to_datetime(df['time'], utc=True)

            # Load symbol info
            symbol_info = {}
            if symbol_info_path.exists():
                with open(symbol_info_path, 'r') as f:
                    symbol_info = json.load(f)

            self.logger.info(f"  ✓ Loaded from cache: {symbol} {timeframe} ({len(df)} bars)")
            return df, symbol_info

        except Exception as e:
            self.logger.error(f"  ✗ Error loading cache for {symbol} {timeframe}: {e}")
            return None
    
    def save_to_cache(self, symbol: str, timeframe: str,
                      start_date: datetime, end_date: datetime,
                      df: pd.DataFrame, symbol_info: Dict):
        """
        Save data to cache.
        
        Args:
            symbol: Symbol name
            timeframe: Timeframe
            start_date: Start date
            end_date: End date
            df: DataFrame with OHLC data
            symbol_info: Symbol information dictionary
        """
        try:
            # Save OHLC data using PyArrow engine with compression (faster + smaller files)
            cache_path = self._get_cache_path(symbol, timeframe, start_date, end_date)
            df.to_parquet(cache_path, index=False, engine='pyarrow', compression='snappy')

            # Save symbol info (only once per symbol)
            symbol_info_path = self._get_symbol_info_path(symbol)
            with open(symbol_info_path, 'w') as f:
                json.dump(symbol_info, f, indent=2)

            self.logger.info(f"  ✓ Saved to cache: {symbol} {timeframe} ({len(df)} bars)")

        except Exception as e:
            self.logger.error(f"  ✗ Error saving cache for {symbol} {timeframe}: {e}")

    def clear_cache(self, symbol: Optional[str] = None):
        """
        Clear cached data.

        Args:
            symbol: If specified, only clear cache for this symbol.
                   If None, clear entire cache.
        """
        if symbol:
            symbol_dir = self.cache_dir / symbol
            if symbol_dir.exists():
                import shutil
                shutil.rmtree(symbol_dir)
                self.logger.info(f"Cleared cache for {symbol}")
        else:
            import shutil
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self.logger.info("Cleared entire cache")

    def get_cache_stats(self) -> Dict:
        """
        Get statistics about cached data.

        Returns:
            Dictionary with cache statistics
        """
        stats = {
            'total_symbols': 0,
            'total_files': 0,
            'total_size_mb': 0.0,
            'symbols': {}
        }

        if not self.cache_dir.exists():
            return stats

        for symbol_dir in self.cache_dir.iterdir():
            if not symbol_dir.is_dir():
                continue

            symbol = symbol_dir.name
            stats['total_symbols'] += 1
            stats['symbols'][symbol] = {
                'files': 0,
                'size_mb': 0.0
            }

            for file_path in symbol_dir.iterdir():
                if file_path.is_file():
                    stats['total_files'] += 1
                    stats['symbols'][symbol]['files'] += 1

                    size_mb = file_path.stat().st_size / (1024 * 1024)
                    stats['total_size_mb'] += size_mb
                    stats['symbols'][symbol]['size_mb'] += size_mb

        return stats

