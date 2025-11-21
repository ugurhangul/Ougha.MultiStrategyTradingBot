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
from src.backtesting.engine.broker_archive_downloader import BrokerArchiveDownloader
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

        # Initialize broker archive downloader
        from src.config import config
        self.archive_downloader = BrokerArchiveDownloader(config.tick_archive)
    
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
                self.logger.warning(
                    f"No {timeframe} data retrieved for {symbol} - "
                    f"MT5 Error: ({error_code}) {error_msg}"
                )

                # FALLBACK: Try to build candles from ticks for any timeframe
                self.logger.info(f"  ⚡ Attempting to build {timeframe} candles from tick data for {symbol}...")
                df = self._build_candles_from_ticks(symbol, timeframe, start_date, end_date)

                if df is not None and len(df) > 0:
                    self.logger.info(f"  ✓ Successfully built {len(df)} {timeframe} candles from ticks")

                    # Get symbol info
                    symbol_info = self.connector.get_symbol_info(symbol)
                    if not symbol_info:
                        self.logger.error(f"Failed to get symbol info for {symbol}")
                        return None

                    # IMPORTANT: Save to cache so we don't rebuild next time
                    if self.use_cache:
                        self.logger.info(f"  💾 Saving built {timeframe} candles to cache...")
                        self.cache.save_to_cache(symbol, timeframe, start_date, end_date, df, symbol_info)

                    return df, symbol_info
                else:
                    self.logger.error(f"  ✗ Failed to build {timeframe} candles from ticks")

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

    def _build_candles_from_ticks(self, symbol: str, timeframe: str,
                                   start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """
        Build candles of any timeframe from tick data.

        This is a fallback when candles are not available from the broker.
        Supports: M1, M5, M15, M30, H1, H4, D1

        Args:
            symbol: Symbol name
            timeframe: Timeframe (e.g., 'M1', 'M5', 'H1', 'H4', 'D1')
            start_date: Start date (UTC)
            end_date: End date (UTC)

        Returns:
            DataFrame with OHLC data (same format as copy_rates_range) or None
        """
        try:
            # Map timeframe to pandas resample frequency
            timeframe_map = {
                'M1': '1min',
                'M5': '5min',
                'M15': '15min',
                'M30': '30min',
                'H1': '1H',
                'H4': '4H',
                'D1': '1D'
            }

            if timeframe not in timeframe_map:
                self.logger.error(f"Unsupported timeframe for building from ticks: {timeframe}")
                return None

            resample_freq = timeframe_map[timeframe]

            # Load tick data
            self.logger.info(f"  Loading tick data for {symbol}...")
            ticks = mt5.copy_ticks_range(symbol, start_date, end_date, mt5.COPY_TICKS_INFO)

            if ticks is None or len(ticks) == 0:
                error_code, error_msg = mt5.last_error()
                self.logger.error(f"  No tick data available for {symbol}: ({error_code}) {error_msg}")
                return None

            self.logger.info(f"  Loaded {len(ticks):,} ticks, building {timeframe} candles...")

            # Convert to DataFrame
            df_ticks = pd.DataFrame(ticks)
            df_ticks['time'] = pd.to_datetime(df_ticks['time'], unit='s', utc=True)

            # Use bid price for candle building (standard for forex)
            df_ticks['price'] = df_ticks['bid']

            # Set time as index for resampling
            df_ticks.set_index('time', inplace=True)

            # Build OHLC candles by resampling
            candles = df_ticks['price'].resample(resample_freq).agg(['first', 'max', 'min', 'last'])
            candles.columns = ['open', 'high', 'low', 'close']

            # Add tick volume (count of ticks in each period)
            candles['tick_volume'] = df_ticks['volume'].resample(resample_freq).sum()

            # Remove NaN rows (periods with no ticks)
            candles = candles.dropna()

            # Reset index to get time as column
            candles = candles.reset_index()

            # Add required columns to match MT5 format
            candles['spread'] = 0  # Will be calculated from actual spreads if needed
            candles['real_volume'] = 0  # Not available from ticks

            self.logger.info(f"  Built {len(candles)} {timeframe} candles from {len(df_ticks):,} ticks")

            return candles

        except Exception as e:
            self.logger.error(f"Error building {timeframe} candles from ticks: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
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

    def load_ticks_from_mt5(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        tick_type: int = mt5.COPY_TICKS_INFO,
        cache_dir: Optional[str] = None
    ) -> Optional[pd.DataFrame]:
        """
        Load tick data from MT5 using copy_ticks_range().

        Supports caching: If cache_dir is provided, saves ticks to parquet files
        and loads from cache on subsequent runs.

        Args:
            symbol: Symbol name
            start_date: Start date (UTC)
            end_date: End date (UTC)
            tick_type: Type of ticks to load (default: COPY_TICKS_INFO for bid/ask changes)
                - mt5.COPY_TICKS_ALL: All ticks
                - mt5.COPY_TICKS_INFO: Bid/ask changes (recommended)
                - mt5.COPY_TICKS_TRADE: Trade ticks only
            cache_dir: Directory to cache tick data (optional). If provided, ticks are
                saved to/loaded from parquet files for faster subsequent runs.

        Returns:
            DataFrame with columns: time, bid, ask, last, volume, time_msc, flags
            or None if failed
        """
        from pathlib import Path

        # Check cache first if cache_dir provided
        if cache_dir:
            cache_path = Path(cache_dir)
            cache_path.mkdir(parents=True, exist_ok=True)

            # Create cache filename based on symbol, dates, and tick type
            tick_type_name = {
                mt5.COPY_TICKS_INFO: "INFO",
                mt5.COPY_TICKS_ALL: "ALL",
                mt5.COPY_TICKS_TRADE: "TRADE"
            }.get(tick_type, "UNKNOWN")

            start_str = start_date.strftime("%Y%m%d")
            end_str = end_date.strftime("%Y%m%d")
            cache_file = cache_path / f"{symbol}_{start_str}_{end_str}_{tick_type_name}.parquet"

            # Try to load from cache
            # First try the exact requested filename
            cache_file_to_load = None
            if cache_file.exists():
                cache_file_to_load = cache_file
            else:
                # If exact match doesn't exist, look for any cache file for this symbol and tick type
                # This handles the case where we previously cached with actual dates instead of requested dates
                pattern = f"{symbol}_*_{tick_type_name}.parquet"
                matching_files = list(cache_path.glob(pattern))
                if matching_files:
                    # Use the most recent cache file
                    cache_file_to_load = max(matching_files, key=lambda p: p.stat().st_mtime)
                    self.logger.info(f"Found alternative cache file: {cache_file_to_load.name}")

            if cache_file_to_load:
                try:
                    self.logger.info(f"Loading {symbol} ticks from cache: {cache_file_to_load.name}")
                    df = pd.read_parquet(cache_file_to_load)

                    # Ensure time column is datetime with UTC timezone
                    if 'time' in df.columns:
                        df['time'] = pd.to_datetime(df['time'], utc=True)

                    self.logger.info(f"  ✓ Loaded {len(df):,} ticks from cache")

                    # Validate that cached data covers the requested date range
                    if len(df) > 0:
                        cached_start = df['time'].iloc[0]
                        cached_end = df['time'].iloc[-1]

                        # Calculate date differences
                        start_gap_days = (cached_start.to_pydatetime() - start_date).total_seconds() / 86400
                        end_gap_days = (end_date - cached_end.to_pydatetime()).total_seconds() / 86400

                        # Check if there's a significant gap at the start (cached data starts much later than requested)
                        if start_gap_days > 1:  # More than 1 day gap at start
                            self.logger.info(f"  Cache validation: Cached data starts {start_gap_days:.1f} days after requested start")
                            self.logger.info(f"    Requested start: {start_date.date()}")
                            self.logger.info(f"    Cached start:    {cached_start.date()}")
                            self.logger.info(f"  Checking MT5 for additional historical data...")

                            # Attempt to fetch missing data from MT5
                            # This handles the case where MT5's historical data availability has improved
                            try:
                                # Connect if needed
                                if self._owns_connector and not self.connector.is_connected:
                                    if not self.connector.connect():
                                        self.logger.warning("  Failed to connect to MT5 for cache validation")
                                        return df  # Use cached data as-is

                                # Ensure symbol is selected
                                if not mt5.symbol_select(symbol, True):
                                    self.logger.warning(f"  Could not select {symbol} for cache validation")
                                    return df  # Use cached data as-is

                                # Try to fetch ticks for the missing period (requested start to cached start)
                                missing_period_end = cached_start.to_pydatetime()
                                self.logger.info(f"  Attempting to fetch missing period: {start_date.date()} to {missing_period_end.date()}")

                                missing_ticks = mt5.copy_ticks_range(symbol, start_date, missing_period_end, tick_type)

                                if missing_ticks is not None and len(missing_ticks) > 0:
                                    # Convert to DataFrame
                                    missing_df = pd.DataFrame(missing_ticks)
                                    missing_df['time'] = pd.to_datetime(missing_df['time'], unit='s', utc=True)

                                    # Filter out invalid ticks
                                    missing_df = missing_df[(missing_df['bid'] > 0) & (missing_df['ask'] > 0)].copy()

                                    if len(missing_df) > 0:
                                        new_start = missing_df['time'].iloc[0]
                                        self.logger.info(f"  ✓ Found {len(missing_df):,} additional ticks from MT5!")
                                        self.logger.info(f"    New data starts: {new_start.date()}")

                                        # Merge with cached data (remove any overlap)
                                        # Keep only missing_df ticks that are before cached_start
                                        missing_df = missing_df[missing_df['time'] < cached_start].copy()

                                        if len(missing_df) > 0:
                                            # Concatenate and sort
                                            df = pd.concat([missing_df, df], ignore_index=True)
                                            df = df.sort_values('time').reset_index(drop=True)

                                            self.logger.info(f"  ✓ Extended cache with {len(missing_df):,} earlier ticks")
                                            self.logger.info(f"  Total ticks: {len(df):,}")

                                            # Update the cache file with extended data
                                            try:
                                                new_start_str = df['time'].iloc[0].strftime("%Y%m%d")
                                                new_end_str = df['time'].iloc[-1].strftime("%Y%m%d")

                                                tick_type_name = {
                                                    mt5.COPY_TICKS_INFO: "INFO",
                                                    mt5.COPY_TICKS_ALL: "ALL",
                                                    mt5.COPY_TICKS_TRADE: "TRADE"
                                                }.get(tick_type, "UNKNOWN")

                                                new_cache_file = cache_path / f"{symbol}_{new_start_str}_{new_end_str}_{tick_type_name}.parquet"

                                                self.logger.info(f"  Updating cache file: {new_cache_file.name}")
                                                df.to_parquet(new_cache_file, compression='snappy', index=False)

                                                # Remove old cache file if different
                                                if new_cache_file != cache_file_to_load:
                                                    try:
                                                        cache_file_to_load.unlink()
                                                        self.logger.info(f"  Removed old cache file: {cache_file_to_load.name}")
                                                    except Exception as e:
                                                        self.logger.warning(f"  Could not remove old cache file: {e}")

                                                file_size_mb = new_cache_file.stat().st_size / 1024 / 1024
                                                self.logger.info(f"  ✓ Updated cache ({file_size_mb:.1f} MB)")
                                            except Exception as e:
                                                self.logger.warning(f"  Failed to update cache: {e}")

                                            return df
                                        else:
                                            # No new ticks after filtering overlap
                                            self.logger.info(f"  No additional ticks after removing overlap")
                                            return df
                                    else:
                                        self.logger.info(f"  No additional valid ticks found in MT5 for missing period")
                                        return df
                                else:
                                    self.logger.info(f"  MT5 still does not have data for the missing period")

                                    # Tier 3: Try to fetch from external broker archives
                                    archive_df = self._try_fetch_from_archive(
                                        symbol, start_date, missing_period_end, tick_type
                                    )

                                    if archive_df is not None and len(archive_df) > 0:
                                        # Successfully fetched from archive, merge with cached data
                                        self.logger.info(f"  ✓ Found {len(archive_df):,} ticks from external archive!")

                                        # Filter to avoid overlap
                                        archive_df = archive_df[archive_df['time'] < cached_start].copy()

                                        if len(archive_df) > 0:
                                            # Concatenate and sort
                                            df = pd.concat([archive_df, df], ignore_index=True)
                                            df = df.sort_values('time').reset_index(drop=True)

                                            self.logger.info(f"  ✓ Extended cache with {len(archive_df):,} ticks from archive")
                                            self.logger.info(f"  Total ticks: {len(df):,}")

                                            # Update the cache file with extended data
                                            try:
                                                new_start_str = df['time'].iloc[0].strftime("%Y%m%d")
                                                new_end_str = df['time'].iloc[-1].strftime("%Y%m%d")

                                                tick_type_name = {
                                                    mt5.COPY_TICKS_INFO: "INFO",
                                                    mt5.COPY_TICKS_ALL: "ALL",
                                                    mt5.COPY_TICKS_TRADE: "TRADE"
                                                }.get(tick_type, "UNKNOWN")

                                                new_cache_file = cache_path / f"{symbol}_{new_start_str}_{new_end_str}_{tick_type_name}.parquet"

                                                self.logger.info(f"  Updating cache file: {new_cache_file.name}")
                                                df.to_parquet(new_cache_file, compression='snappy', index=False)

                                                # Remove old cache file if different
                                                if new_cache_file != cache_file_to_load:
                                                    try:
                                                        cache_file_to_load.unlink()
                                                        self.logger.info(f"  Removed old cache file: {cache_file_to_load.name}")
                                                    except Exception as e:
                                                        self.logger.warning(f"  Could not remove old cache file: {e}")

                                                file_size_mb = new_cache_file.stat().st_size / 1024 / 1024
                                                self.logger.info(f"  ✓ Updated cache ({file_size_mb:.1f} MB)")
                                            except Exception as e:
                                                self.logger.warning(f"  Failed to update cache: {e}")

                                            return df

                                    # Tier 4: Use partial cached data with warnings
                                    self.logger.info(f"  Using cached data starting from {cached_start.date()}")
                                    return df

                            except Exception as e:
                                self.logger.warning(f"  Error checking MT5 for additional data: {e}")
                                self.logger.info(f"  Using cached data as-is")
                                return df

                        # Check if cached data ends significantly before requested end
                        elif end_gap_days > 7:  # More than 7 days gap at end
                            self.logger.warning(f"  Cached data ends {end_gap_days:.1f} days before requested end")
                            self.logger.warning(f"    Requested: {start_date.date()} to {end_date.date()}")
                            self.logger.warning(f"    Cached:    {cached_start.date()} to {cached_end.date()}")
                            self.logger.warning(f"    Will reload from MT5 to get latest data")
                            # Don't return, fall through to reload from MT5
                        else:
                            # Cache is good, use it
                            return df
                    else:
                        return df

                except Exception as e:
                    self.logger.warning(f"Failed to load from cache: {e}, will reload from MT5")

        try:
            # Connect if needed
            if self._owns_connector and not self.connector.is_connected:
                if not self.connector.connect():
                    self.logger.error("Failed to connect to MT5")
                    return None

            # Ensure symbol is selected in Market Watch
            if not mt5.symbol_select(symbol, True):
                self.logger.warning(f"Could not select {symbol} in Market Watch")

            # Check if symbol is available
            symbol_info_check = mt5.symbol_info(symbol)
            if symbol_info_check is None:
                self.logger.error(f"Symbol {symbol} not found in MT5")
                return None

            if not symbol_info_check.visible:
                self.logger.warning(f"Symbol {symbol} not visible, attempting to enable...")
                if not mt5.symbol_select(symbol, True):
                    self.logger.error(f"Failed to enable {symbol} in Market Watch")
                    return None

            # Load ticks from MT5
            self.logger.info(f"Loading tick data for {symbol} from {start_date} to {end_date}")
            self.logger.info(f"  Tick type: {tick_type} (INFO=bid/ask, ALL=all ticks, TRADE=trades only)")

            ticks = mt5.copy_ticks_range(symbol, start_date, end_date, tick_type)

            if ticks is None or len(ticks) == 0:
                error_code, error_msg = mt5.last_error()
                self.logger.error(
                    f"No tick data retrieved for {symbol} - "
                    f"MT5 Error: ({error_code}) {error_msg}"
                )
                self.logger.error(
                    f"Date range: {start_date.strftime('%Y-%m-%d %H:%M:%S')} to "
                    f"{end_date.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                return None

            # Convert to DataFrame
            df = pd.DataFrame(ticks)

            # Convert time from Unix timestamp to datetime
            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)

            # Ensure all required columns exist
            required_cols = ['time', 'bid', 'ask', 'last', 'volume']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                self.logger.error(f"Tick data missing required columns: {missing_cols}")
                return None

            # Filter out ticks with zero bid/ask (invalid ticks)
            initial_count = len(df)
            df = df[(df['bid'] > 0) & (df['ask'] > 0)].copy()
            filtered_count = initial_count - len(df)

            if filtered_count > 0:
                self.logger.warning(f"  Filtered out {filtered_count} invalid ticks (zero bid/ask)")

            self.logger.info(f"  Loaded {len(df):,} ticks for {symbol}")

            # Log tick data statistics and validate date range
            if len(df) > 0:
                actual_start = df['time'].iloc[0]
                actual_end = df['time'].iloc[-1]
                time_span = (actual_end - actual_start).total_seconds()
                ticks_per_second = len(df) / time_span if time_span > 0 else 0

                self.logger.info(f"  Time span: {time_span/3600:.1f} hours")
                self.logger.info(f"  Average: {ticks_per_second:.1f} ticks/second")
                self.logger.info(f"  Actual date range: {actual_start.strftime('%Y-%m-%d %H:%M:%S')} to {actual_end.strftime('%Y-%m-%d %H:%M:%S')}")

                # Check if actual data matches requested date range
                # Allow 1 day tolerance for start date (weekends, holidays)
                start_diff = (actual_start - start_date).total_seconds() / 86400  # days
                end_diff = (end_date - actual_end).total_seconds() / 86400  # days

                if start_diff > 1:  # Actual start is more than 1 day after requested start
                    self.logger.warning("")
                    self.logger.warning("=" * 80)
                    self.logger.warning(f"⚠️  TICK DATA AVAILABILITY WARNING for {symbol}")
                    self.logger.warning("=" * 80)
                    self.logger.warning(f"  Requested start date: {start_date.strftime('%Y-%m-%d %H:%M:%S')}")
                    self.logger.warning(f"  Actual first tick:    {actual_start.strftime('%Y-%m-%d %H:%M:%S')}")
                    self.logger.warning(f"  Missing data:         {start_diff:.1f} days")
                    self.logger.warning("")
                    self.logger.warning("  MT5 does not have tick data available before the actual first tick.")
                    self.logger.warning("  The backtest will start from the first available tick, not the configured START_DATE.")
                    self.logger.warning("")
                    self.logger.warning("  Options:")
                    self.logger.warning("  1. Accept the later start date (backtest will start from first available tick)")
                    self.logger.warning("  2. Disable tick mode (USE_TICK_DATA = False) to use candle-based backtesting")
                    self.logger.warning("  3. Reduce the backtest date range to match available tick data")
                    self.logger.warning("=" * 80)
                    self.logger.warning("")

            # Save to cache if cache_dir provided
            if cache_dir and len(df) > 0:
                try:
                    # Use ACTUAL date range in filename (not requested range)
                    # This makes it clear what data is actually in the cache
                    actual_start_str = df['time'].iloc[0].strftime("%Y%m%d")
                    actual_end_str = df['time'].iloc[-1].strftime("%Y%m%d")

                    # Create cache filename with actual date range
                    tick_type_name = {
                        mt5.COPY_TICKS_INFO: "INFO",
                        mt5.COPY_TICKS_ALL: "ALL",
                        mt5.COPY_TICKS_TRADE: "TRADE"
                    }.get(tick_type, "UNKNOWN")

                    actual_cache_file = cache_path / f"{symbol}_{actual_start_str}_{actual_end_str}_{tick_type_name}.parquet"

                    # If the actual cache file is different from the requested one, use the actual one
                    # This prevents confusion when MT5 doesn't have data for the full requested range
                    if actual_cache_file != cache_file:
                        self.logger.info(f"  Note: Using actual date range in cache filename")
                        self.logger.info(f"    Requested: {cache_file.name}")
                        self.logger.info(f"    Actual:    {actual_cache_file.name}")
                        cache_file = actual_cache_file

                    self.logger.info(f"  Saving ticks to cache: {cache_file.name}")
                    df.to_parquet(cache_file, compression='snappy', index=False)
                    file_size_mb = cache_file.stat().st_size / 1024 / 1024
                    self.logger.info(f"  ✓ Cached {len(df):,} ticks ({file_size_mb:.1f} MB)")
                except Exception as e:
                    self.logger.warning(f"  Failed to save cache: {e}")

            return df

        except Exception as e:
            self.logger.error(f"Error loading tick data for {symbol}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
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

    def _try_fetch_from_archive(self, symbol: str, start_date: datetime,
                                end_date: datetime, tick_type: int) -> Optional[pd.DataFrame]:
        """
        Try to fetch tick data from external broker archives.

        This is Tier 3 in the fallback mechanism:
        - Tier 1: Use existing cache
        - Tier 2: Fetch missing data from MT5
        - Tier 3: Download from broker archives (THIS METHOD)
        - Tier 4: Use partial cached data with warnings

        Args:
            symbol: Symbol name
            start_date: Start date for missing data
            end_date: End date for missing data
            tick_type: MT5 tick type (INFO, ALL, or TRADE)

        Returns:
            DataFrame with tick data from archive, or None if fetch failed
        """
        try:
            # Get MT5 server name for broker detection
            account_info = mt5.account_info()
            if not account_info:
                self.logger.info(f"  Cannot fetch from archive: No MT5 account info")
                return None

            server_name = account_info.server

            # Fetch from archive
            archive_df = self.archive_downloader.fetch_tick_data(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                server_name=server_name
            )

            if archive_df is not None and len(archive_df) > 0:
                # Ensure columns match MT5 format
                # Archive data has: time, bid, ask, volume
                # We may need to add additional columns for compatibility

                # Add flags column if missing (0 = no flags)
                if 'flags' not in archive_df.columns:
                    archive_df['flags'] = 0

                # Add volume_real column if missing (use volume or 0)
                if 'volume_real' not in archive_df.columns:
                    if 'volume' in archive_df.columns:
                        archive_df['volume_real'] = archive_df['volume'].astype(float)
                    else:
                        archive_df['volume_real'] = 0.0

                # Ensure time is datetime with UTC timezone
                archive_df['time'] = pd.to_datetime(archive_df['time'], utc=True)

                return archive_df

            return None

        except Exception as e:
            self.logger.warning(f"  Error fetching from archive: {e}")
            return None

