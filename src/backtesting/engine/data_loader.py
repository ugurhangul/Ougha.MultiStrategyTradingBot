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
                 use_cache: bool = True, cache_dir: str = "data",
                 cache_ttl_days: int = 7):
        """
        Initialize data loader.

        Args:
            connector: MT5Connector instance (optional, for loading from MT5)
            use_cache: Whether to use data caching (default: True)
            cache_dir: Directory for cached data (default: "data")
            cache_ttl_days: Cache time-to-live in days (default: 7)
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
        self.cache = DataCache(cache_dir, cache_ttl_days) if use_cache else None

        # Initialize broker archive downloader
        from src.config import config
        self.archive_downloader = BrokerArchiveDownloader(config.tick_archive)

    def _get_tick_cache_path(self, cache_dir: str, date: datetime, symbol: str, tick_type_name: str) -> Path:
        """
        Get the cache file path for tick data on a specific day.

        Args:
            cache_dir: Root cache directory (e.g., 'data/cache')
            date: Date for the cache file
            symbol: Symbol name
            tick_type_name: Tick type name (e.g., 'INFO', 'ALL', 'TRADE')

        Returns:
            Path to cache file (data/cache/YYYY/MM/DD/ticks/SYMBOL_TICKTYPE.parquet)
        """
        cache_path = Path(cache_dir)

        # Create date hierarchy: YYYY/MM/DD/ticks/
        year = date.strftime('%Y')
        month = date.strftime('%m')
        day = date.strftime('%d')

        day_dir = cache_path / year / month / day / "ticks"
        day_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{symbol}_{tick_type_name}.parquet"
        return day_dir / filename

    def _get_date_range_days(self, start_date: datetime, end_date: datetime) -> list:
        """
        Get list of dates between start_date and end_date (inclusive).

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of datetime objects for each day in the range
        """
        from datetime import timedelta

        days = []
        current = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = end_date.replace(hour=0, minute=0, second=0, microsecond=0)

        while current <= end:
            days.append(current)
            current += timedelta(days=1)

        return days

    def _should_skip_day(self, symbol: str, day: datetime) -> bool:
        """
        Check if we should skip downloading data for this day based on market schedule.

        Forex and Metals markets are closed on weekends (Saturday/Sunday).
        Crypto markets trade 24/7 including weekends.
        Indices depend on the specific exchange.

        Args:
            symbol: Trading symbol
            day: Date to check

        Returns:
            True if day should be skipped (no market data available), False otherwise
        """
        from src.config.symbols.category_detector import SymbolCategoryDetector
        from src.models.data_models import SymbolCategory

        # Get symbol category
        # Note: We don't have mt5_category here, so we rely on pattern matching
        category = SymbolCategoryDetector.detect_category(symbol, mt5_category=None)

        # Check if it's a weekend (Saturday=5, Sunday=6)
        weekday = day.weekday()
        is_weekend = weekday in (5, 6)

        if not is_weekend:
            # Weekdays - data should be available for all markets
            return False

        # Weekend handling by category
        if category in (SymbolCategory.MAJOR_FOREX, SymbolCategory.MINOR_FOREX,
                       SymbolCategory.EXOTIC_FOREX, SymbolCategory.METALS):
            # Forex and Metals markets close on weekends
            return True
        elif category == SymbolCategory.CRYPTO:
            # Crypto trades 24/7
            return False
        elif category == SymbolCategory.INDICES:
            # Most indices are closed on weekends
            # Could be refined per-exchange in the future
            return True
        elif category == SymbolCategory.COMMODITIES:
            # Most commodities (oil, gas) are closed on weekends
            return True
        elif category == SymbolCategory.STOCKS:
            # Stock exchanges are closed on weekends
            return True
        else:
            # Unknown category - be conservative and attempt download
            return False

    def _download_day_ticks(self, symbol: str, day_start: datetime, day_end: datetime,
                           tick_type: int, tick_type_name: str, cache_path: Path = None,
                           cache_dir: str = None, progress_callback: callable = None,
                           full_progress_callback: callable = None) -> pd.DataFrame:
        """
        Download tick data for a single day with fallback: MT5 → Archive.

        Args:
            symbol: Trading symbol
            day_start: Start of day (00:00:00)
            day_end: End of day (23:59:59.999999)
            tick_type: MT5 tick type flag
            tick_type_name: Tick type name (INFO, ALL, TRADE)
            cache_path: Path to save cached data (optional)
            cache_dir: Base cache directory for day-level caching
            progress_callback: Optional callback for reporting download stages (simple)
            full_progress_callback: Optional callback for detailed progress (day_idx, total, date, status, count, msg, metadata)

        Returns:
            DataFrame with tick data for the day, or None if no data available
        """
        # Try MT5 first
        try:
            # Connect if needed
            if self._owns_connector and not self.connector.is_connected:
                if not self.connector.connect():
                    self.logger.error("Failed to connect to MT5")
                    return None

            # Ensure symbol is selected in Market Watch
            if not mt5.symbol_select(symbol, True):
                self.logger.error(f"Failed to select symbol {symbol}")
                return None

            # Try to get ticks from MT5 for this single day
            ticks = mt5.copy_ticks_range(symbol, day_start, day_end, tick_type)

            if ticks is not None and len(ticks) > 0:
                # Convert to DataFrame
                df = pd.DataFrame(ticks)
                df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)

                # Check if MT5 data covers this day (starts within 1 day of requested start)
                actual_start = df['time'].iloc[0]
                start_diff_days = (actual_start - day_start).total_seconds() / 86400

                if start_diff_days <= 1:
                    # MT5 has data for this day - cache it and return
                    if cache_path:
                        if progress_callback:
                            progress_callback('caching')
                        self._save_tick_cache(df, cache_path)
                    return df
                else:
                    # MT5 data doesn't cover this day - try archive
                    self.logger.debug(
                        f"    MT5 data starts at {actual_start.strftime('%Y-%m-%d %H:%M:%S')}, "
                        f"{start_diff_days:.1f} days after {day_start.strftime('%Y-%m-%d')}"
                    )

        except Exception as e:
            self.logger.debug(f"    MT5 download failed: {e}")

        # MT5 doesn't have data - try archive downloader
        if hasattr(self, 'archive_downloader') and self.archive_downloader:
            try:
                self.logger.debug(f"    Attempting to fetch from broker archives...")

                # Report fetching stage
                if progress_callback:
                    progress_callback('fetching')

                # Get MT5 server name for broker detection
                account_info = mt5.account_info()
                if not account_info:
                    self.logger.debug(f"    Cannot fetch from archive: No MT5 account info")
                    return None

                server_name = account_info.server

                # Download from archive for this single day
                # Pass cache_dir and progress callback to enable intelligent caching
                archive_df = self.archive_downloader.fetch_tick_data(
                    symbol=symbol,
                    start_date=day_start,
                    end_date=day_end,
                    server_name=server_name,
                    tick_type=tick_type,
                    cache_dir=cache_dir,
                    progress_callback=full_progress_callback
                )

                if archive_df is not None and len(archive_df) > 0:
                    # Archive has data - cache it and return
                    # Note: Archive downloader already cached it via _split_and_cache_by_day
                    # but we still save to cache_path for consistency
                    if cache_path:
                        if progress_callback:
                            progress_callback('caching')
                        self._save_tick_cache(archive_df, cache_path)
                    return archive_df
                else:
                    self.logger.debug(f"    Archive returned no data for {day_start.date()}")

            except Exception as e:
                self.logger.warning(f"    Archive download failed: {e}")

        # No data available from any source
        return None

    def _save_tick_cache(self, df: pd.DataFrame, cache_path: Path):
        """Save tick data to cache file with metadata."""
        try:
            from datetime import timezone
            import pyarrow as pa
            import pyarrow.parquet as pq

            cache_path.parent.mkdir(parents=True, exist_ok=True)

            # Create metadata
            metadata = {
                'cached_at': datetime.now(timezone.utc).isoformat(),
                'source': 'mt5',
                'first_data_time': df['time'].iloc[0].isoformat() if len(df) > 0 else '',
                'last_data_time': df['time'].iloc[-1].isoformat() if len(df) > 0 else '',
                'row_count': str(len(df)),
                'cache_version': '1.0'
            }

            # Convert to bytes for parquet metadata
            metadata_bytes = {k.encode(): v.encode() for k, v in metadata.items()}

            # Convert DataFrame to Arrow Table
            table = pa.Table.from_pandas(df, preserve_index=False)

            # Add metadata to table schema
            table = table.replace_schema_metadata(metadata_bytes)

            # Write with metadata
            pq.write_table(table, cache_path, compression='snappy')

            self.logger.debug(f"    Cached to {cache_path}")
        except Exception as e:
            self.logger.warning(f"    Failed to save cache: {e}")

    def load_from_mt5(self, symbol: str, timeframe: str,
                     start_date: datetime, end_date: datetime,
                     force_refresh: bool = False,
                     preloaded_ticks: Optional[pd.DataFrame] = None,
                     use_incremental_loading: bool = True) -> Optional[Tuple[pd.DataFrame, Dict]]:
        """
        Load historical data from MT5 with caching support.

        First checks cache, then falls back to MT5 if needed.
        Supports incremental loading - only downloads missing days instead of full range.

        Args:
            symbol: Symbol name
            timeframe: Timeframe (e.g., 'M1', 'M5', 'M15', 'H4')
            start_date: Start date (UTC)
            end_date: End date (UTC)
            force_refresh: If True, bypass cache and download from MT5
            preloaded_ticks: Optional pre-loaded tick DataFrame to use for building candles
                           if MT5 doesn't have candle data
            use_incremental_loading: If True, use partial cache hits and only download missing days

        Returns:
            Tuple of (DataFrame, symbol_info dict) or None if failed
        """
        # Try to load from cache first (unless force_refresh is True)
        if self.use_cache and not force_refresh:
            if use_incremental_loading:
                # Use partial cache loading - returns cached data + missing days
                import time
                cache_start = time.time()

                cached_df, missing_days, symbol_info = self.cache.load_from_cache_partial(
                    symbol, timeframe, start_date, end_date
                )

                cache_time = time.time() - cache_start

                if len(missing_days) == 0:
                    # Complete cache hit - return cached data
                    self.logger.debug(
                        f"  ✓ Complete cache hit: {symbol} {timeframe} - "
                        f"{len(cached_df)} bars loaded in {cache_time:.2f}s"
                    )
                    return cached_df, symbol_info

                if len(missing_days) > 0:
                    # Partial cache hit - download only missing days
                    cached_bars = len(cached_df) if cached_df is not None else 0
                    self.logger.info(
                        f"  ⚡ Incremental load: {symbol} {timeframe} - "
                        f"{cached_bars} bars cached, {len(missing_days)} days to download "
                        f"(cache load: {cache_time:.2f}s)"
                    )

                    # Log which specific days are missing
                    if len(missing_days) <= 10:
                        missing_dates_str = ', '.join([d.strftime('%Y-%m-%d') for d in missing_days])
                        self.logger.debug(f"    Missing days: {missing_dates_str}")
                    else:
                        self.logger.debug(
                            f"    Missing days: {missing_days[0].strftime('%Y-%m-%d')} to "
                            f"{missing_days[-1].strftime('%Y-%m-%d')} ({len(missing_days)} days)"
                        )

                    # Download missing days
                    download_start = time.time()
                    missing_dfs = []
                    total_downloaded_bars = 0

                    for idx, missing_day in enumerate(missing_days, 1):
                        # Check if we should skip this day (e.g., weekends for Forex/Metals)
                        if self._should_skip_day(symbol, missing_day):
                            day_name = missing_day.strftime('%A')
                            self.logger.debug(
                                f"    [{idx}/{len(missing_days)}] {missing_day.date()} ({day_name}): "
                                f"Skipping - market closed"
                            )
                            continue

                        # Download this day's data
                        day_end = missing_day.replace(hour=23, minute=59, second=59)

                        self.logger.debug(
                            f"    [{idx}/{len(missing_days)}] Downloading {missing_day.date()}..."
                        )

                        day_download_start = time.time()
                        day_result = self._download_from_mt5(
                            symbol, timeframe, missing_day, day_end, preloaded_ticks
                        )
                        day_download_time = time.time() - day_download_start

                        if day_result is not None:
                            day_df, day_symbol_info = day_result
                            missing_dfs.append(day_df)
                            total_downloaded_bars += len(day_df)

                            self.logger.debug(
                                f"      ✓ Downloaded {len(day_df)} bars for {missing_day.date()} "
                                f"({day_download_time:.2f}s)"
                            )

                            # Update symbol_info if we don't have it yet
                            if not symbol_info:
                                symbol_info = day_symbol_info

                            # Cache this day immediately
                            self.cache.save_to_cache(
                                symbol, timeframe, missing_day, day_end, day_df, day_symbol_info
                            )
                        else:
                            self.logger.warning(
                                f"  ⚠ Failed to download {symbol} {timeframe} for {missing_day.date()}"
                            )

                    download_time = time.time() - download_start
                    self.logger.debug(
                        f"  Download phase complete: {total_downloaded_bars} bars in {download_time:.2f}s"
                    )

                    # Merge cached data with newly downloaded data
                    merge_start = time.time()
                    all_dfs = []
                    if cached_df is not None:
                        all_dfs.append(cached_df)
                    all_dfs.extend(missing_dfs)

                    if len(all_dfs) == 0:
                        self.logger.error(f"  ✗ No data available for {symbol} {timeframe}")
                        return None

                    # Merge and sort
                    if len(all_dfs) == 1:
                        merged_df = all_dfs[0]
                    else:
                        merged_df = pd.concat(all_dfs, ignore_index=True)
                        merged_df = merged_df.sort_values('time').reset_index(drop=True)
                        merged_df = merged_df.drop_duplicates(subset=['time'], keep='first')

                    # Filter to requested range
                    merged_df = merged_df[(merged_df['time'] >= start_date) & (merged_df['time'] <= end_date)].copy()

                    merge_time = time.time() - merge_start
                    total_time = time.time() - cache_start

                    self.logger.info(
                        f"  ✓ Incremental load complete: {symbol} {timeframe} - "
                        f"{len(merged_df)} bars total ({len(missing_dfs)} days downloaded, "
                        f"total time: {total_time:.2f}s)"
                    )
                    self.logger.debug(
                        f"    Timing breakdown: cache={cache_time:.2f}s, "
                        f"download={download_time:.2f}s, merge={merge_time:.2f}s"
                    )

                    return merged_df, symbol_info
            else:
                # Use old behavior - all-or-nothing cache
                cached_data = self.cache.load_from_cache(symbol, timeframe, start_date, end_date)
                if cached_data is not None:
                    return cached_data

                self.logger.info(f"  ⚠ Cache miss: {symbol} {timeframe} - downloading from MT5...")

        # Load from MT5 (full range)
        result = self._download_from_mt5(symbol, timeframe, start_date, end_date, preloaded_ticks)

        # Save to cache if successful
        if result is not None and self.use_cache:
            df, symbol_info = result
            self.cache.save_to_cache(symbol, timeframe, start_date, end_date, df, symbol_info)

        return result

    def _download_from_mt5(self, symbol: str, timeframe: str,
                          start_date: datetime, end_date: datetime,
                          preloaded_ticks: Optional[pd.DataFrame] = None) -> Optional[Tuple[pd.DataFrame, Dict]]:
        """
        Download historical data from MT5 (internal method).

        Args:
            symbol: Symbol name
            timeframe: Timeframe (e.g., "M1", "M5", "H1")
            start_date: Start date
            end_date: End date
            preloaded_ticks: Optional pre-loaded tick DataFrame to use for building candles
                           if MT5 doesn't have candle data

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
                df = self._build_candles_from_ticks(symbol, timeframe, start_date, end_date, preloaded_ticks)

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
                                   start_date: datetime, end_date: datetime,
                                   preloaded_ticks: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
        """
        Build candles of any timeframe from tick data.

        This is a fallback when candles are not available from the broker.
        Supports: M1, M5, M15, M30, H1, H4, D1

        Args:
            symbol: Symbol name
            timeframe: Timeframe (e.g., 'M1', 'M5', 'H1', 'H4', 'D1')
            start_date: Start date (UTC)
            end_date: End date (UTC)
            preloaded_ticks: Optional pre-loaded tick DataFrame. If provided, use this instead
                           of loading from MT5 again.

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

            # Use pre-loaded ticks if available, otherwise load from MT5
            if preloaded_ticks is not None and len(preloaded_ticks) > 0:
                self.logger.info(f"  Using pre-loaded tick data ({len(preloaded_ticks):,} ticks)...")
                df_ticks = preloaded_ticks.copy()

                # Ensure time column is datetime
                if 'time' in df_ticks.columns and not pd.api.types.is_datetime64_any_dtype(df_ticks['time']):
                    df_ticks['time'] = pd.to_datetime(df_ticks['time'], unit='s', utc=True)
            else:
                # Load tick data from MT5
                self.logger.info(f"  Loading tick data from MT5 for {symbol}...")
                ticks = mt5.copy_ticks_range(symbol, start_date, end_date, mt5.COPY_TICKS_INFO)

                if ticks is None or len(ticks) == 0:
                    error_code, error_msg = mt5.last_error()
                    self.logger.error(f"  No tick data available for {symbol}: ({error_code}) {error_msg}")
                    return None

                self.logger.info(f"  Loaded {len(ticks):,} ticks from MT5...")

                # Convert to DataFrame
                df_ticks = pd.DataFrame(ticks)
                df_ticks['time'] = pd.to_datetime(df_ticks['time'], unit='s', utc=True)

            self.logger.info(f"  Building {timeframe} candles from {len(df_ticks):,} ticks...")

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
        cache_dir: Optional[str] = None,
        progress_callback: Optional[callable] = None,
        parallel_days: int = 1
    ) -> Optional[pd.DataFrame]:
        """
        Load tick data from MT5 using copy_ticks_range().

        NEW: Uses date hierarchy caching (YYYY/MM/DD/ticks/SYMBOL_TICKTYPE.parquet)
        Each day's ticks are cached separately for better organization and management.

        PARALLEL LOADING: Processes multiple days concurrently in batches for faster loading.

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
            progress_callback: Optional callback function(day_idx, total_days, day_date, status, ticks_count, message)
                Called after each day is processed to report progress.
            parallel_days: Number of days to process in parallel (default: 10)
                Higher values = faster but more memory usage

        Returns:
            DataFrame with columns: time, bid, ask, last, volume, time_msc, flags
            or None if failed
        """
        from pathlib import Path
        import concurrent.futures
        import threading

        tick_type_name = {
            mt5.COPY_TICKS_INFO: "INFO",
            mt5.COPY_TICKS_ALL: "ALL",
            mt5.COPY_TICKS_TRADE: "TRADE"
        }.get(tick_type, "UNKNOWN")

        self.logger.info(f"Loading {symbol} ticks for {start_date.date()} to {end_date.date()}")

        # Get list of days in the requested range
        days = self._get_date_range_days(start_date, end_date)
        self.logger.info(f"  Date range: {len(days)} days (parallel batches of {parallel_days})")

        # Process days in parallel batches
        daily_dfs = [None] * len(days)  # Pre-allocate list to maintain order

        if cache_dir:
            cache_path = Path(cache_dir)
            cache_path.mkdir(parents=True, exist_ok=True)
        else:
            cache_path = None

        # Thread-safe lock for progress callback
        callback_lock = threading.Lock()

        def process_single_day(day_idx, day):
            """Process a single day (load from cache or download)."""
            import time

            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)

            # Check if we should skip this day (e.g., weekends for Forex/Metals)
            if self._should_skip_day(symbol, day):
                day_name = day.strftime('%A')  # e.g., "Saturday"
                self.logger.debug(
                    f"  [{day_idx}/{len(days)}] {day.date()} ({day_name}): "
                    f"Skipping - market closed"
                )
                # Report progress - skipped (thread-safe)
                if progress_callback:
                    with callback_lock:
                        progress_callback(day_idx, len(days), day.date(), 'skipped', 0,
                                        f'Skipped - market closed ({day_name})', {'reason': 'weekend'})
                return None

            # Check if this day is cached
            day_cache_path = None
            if cache_path:
                day_cache_path = self._get_tick_cache_path(str(cache_path), day, symbol, tick_type_name)

            # Try to load from cache first
            if day_cache_path and day_cache_path.exists():
                try:
                    load_start = time.time()
                    file_size_mb = day_cache_path.stat().st_size / (1024 * 1024)

                    df = pd.read_parquet(day_cache_path)
                    if 'time' in df.columns:
                        df['time'] = pd.to_datetime(df['time'], utc=True)

                    # Filter to exact day range
                    df = df[(df['time'] >= day_start) & (df['time'] <= day_end)].copy()

                    if len(df) > 0:
                        load_time = time.time() - load_start
                        self.logger.info(f"  [{day_idx}/{len(days)}] {day.date()}: ✓ Loaded {len(df):,} ticks from cache ({file_size_mb:.1f} MB, {load_time:.2f}s)")

                        # Report progress (thread-safe)
                        if progress_callback:
                            with callback_lock:
                                progress_callback(day_idx, len(days), day.date(), 'cached', len(df),
                                                f'Loaded {len(df):,} ticks from cache ({file_size_mb:.1f} MB, {load_time:.2f}s)',
                                                {'file_size_mb': file_size_mb, 'load_time': load_time})
                        return df
                    else:
                        self.logger.warning(f"  [{day_idx}/{len(days)}] {day.date()}: Cache empty, will download")
                except Exception as e:
                    self.logger.warning(f"  [{day_idx}/{len(days)}] {day.date()}: Cache read failed ({e}), will download")

            # Cache miss - download this day's data
            download_start = time.time()
            self.logger.info(f"  [{day_idx}/{len(days)}] {day.date()}: Downloading from MT5/archive...")

            # Report progress - checking MT5 (thread-safe)
            if progress_callback:
                with callback_lock:
                    progress_callback(day_idx, len(days), day.date(), 'checking_mt5', 0,
                                    'Checking MT5...', {'stage': 'checking_mt5'})

            # Create a progress callback for archive download stages (simple)
            def archive_progress(stage, details=None):
                """Report archive download progress (simple callback)."""
                if progress_callback:
                    with callback_lock:
                        if stage == 'fetching':
                            progress_callback(day_idx, len(days), day.date(), 'fetching_archive', 0,
                                            'Fetching from archive...', {'stage': 'fetching_archive'})
                        elif stage == 'parsing':
                            pct = details.get('percent', 0) if details else 0
                            progress_callback(day_idx, len(days), day.date(), 'parsing_archive', 0,
                                            f'Parsing archive ({pct:.0f}% complete)...',
                                            {'stage': 'parsing_archive', 'percent': pct})
                        elif stage == 'caching':
                            progress_callback(day_idx, len(days), day.date(), 'caching', 0,
                                            'Caching to disk...', {'stage': 'caching'})

            # Create a full progress callback for archive downloader (detailed)
            def full_archive_progress(idx, total, date, status, count, msg, metadata=None):
                """Report detailed archive download progress (full callback)."""
                if progress_callback:
                    with callback_lock:
                        progress_callback(idx, total, date, status, count, msg, metadata)

            day_df = self._download_day_ticks(symbol, day_start, day_end, tick_type, tick_type_name,
                                             day_cache_path, str(cache_path) if cache_path else None,
                                             archive_progress, full_archive_progress)

            if day_df is not None and len(day_df) > 0:
                download_time = time.time() - download_start

                # Get file size if cached
                file_size_mb = 0
                source = "MT5"
                if day_cache_path and day_cache_path.exists():
                    file_size_mb = day_cache_path.stat().st_size / (1024 * 1024)
                    # Check if it came from archive (download time > 5s usually means archive)
                    if download_time > 5:
                        source = "archive"

                self.logger.info(f"  [{day_idx}/{len(days)}] {day.date()}: ✓ Downloaded {len(day_df):,} ticks from {source} ({file_size_mb:.1f} MB, {download_time:.1f}s)")

                # Report progress - downloaded (thread-safe)
                if progress_callback:
                    with callback_lock:
                        progress_callback(day_idx, len(days), day.date(), 'downloaded', len(day_df),
                                        f'Downloaded {len(day_df):,} ticks from {source} ({file_size_mb:.1f} MB, {download_time:.1f}s)',
                                        {'file_size_mb': file_size_mb, 'download_time': download_time, 'source': source})
                return day_df
            else:
                self.logger.warning(f"  [{day_idx}/{len(days)}] {day.date()}: ✗ No data available")

                # Report progress - no data (thread-safe)
                if progress_callback:
                    with callback_lock:
                        progress_callback(day_idx, len(days), day.date(), 'no_data', 0,
                                        'No data available', {})
                return None

        # Process days in parallel batches
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_days) as executor:
            # Submit all days for processing
            future_to_idx = {
                executor.submit(process_single_day, idx + 1, day): idx
                for idx, day in enumerate(days)
            }

            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    result = future.result()
                    daily_dfs[idx] = result
                except Exception as e:
                    self.logger.error(f"Error processing day {days[idx].date()}: {e}")
                    daily_dfs[idx] = None

        # Filter out None values
        daily_dfs = [df for df in daily_dfs if df is not None and len(df) > 0]

        # Merge all daily dataframes
        if not daily_dfs:
            self.logger.error(f"No tick data available for {symbol}")
            return None

        self.logger.info(f"Merging {len(daily_dfs)} days of tick data...")

        if len(daily_dfs) == 1:
            merged_df = daily_dfs[0]
        else:
            merged_df = pd.concat(daily_dfs, ignore_index=True)
            merged_df = merged_df.sort_values('time').reset_index(drop=True)

        # Filter to exact requested range
        # Ensure timezone-aware comparison
        start_tz = pd.Timestamp(start_date).tz_localize('UTC') if pd.Timestamp(start_date).tz is None else pd.Timestamp(start_date)
        end_tz = pd.Timestamp(end_date).tz_localize('UTC') if pd.Timestamp(end_date).tz is None else pd.Timestamp(end_date)
        merged_df = merged_df[(merged_df['time'] >= start_tz) & (merged_df['time'] <= end_tz)].copy()

        self.logger.info(f"✓ Total: {len(merged_df):,} ticks loaded for {symbol}")
        return merged_df

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

