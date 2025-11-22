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
from typing import Optional, Dict, Tuple, List
import MetaTrader5 as mt5

from src.utils.logger import get_logger
from src.backtesting.engine.cache_index import CacheIndex


class DataCache:
    """
    Manages caching of historical market data and symbol information.

    Cache structure (NEW - Date Hierarchy):
        data/cache/
            YYYY/
                MM/
                    DD/
                        candles/
                            {SYMBOL}_{TIMEFRAME}.parquet  # OHLC data for this day
                        ticks/
                            {SYMBOL}_{TICK_TYPE}.parquet  # Tick data for this day
                        symbol_info/
                            {SYMBOL}.json                 # Symbol metadata

    Benefits:
        - Easier to manage and delete old data (just remove old date directories)
        - Better organization for long-term backtests
        - Easier to identify which days have cached data
        - Simpler cache invalidation (per day instead of per date range)
    """

    def __init__(self, cache_dir: str = "data/cache", cache_ttl_days: int = 7,
                 use_index: bool = True):
        """
        Initialize data cache.

        Args:
            cache_dir: Root directory for cached data (default: data/cache)
            cache_ttl_days: Cache time-to-live in days (default: 7)
            use_index: Use cache index for fast validation (default: True)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_ttl_days = cache_ttl_days
        self.use_index = use_index
        self.logger = get_logger()

        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize cache index
        self.index = CacheIndex(str(self.cache_dir)) if use_index else None

    def _read_cache_metadata(self, cache_path: Path) -> Optional[Dict[str, str]]:
        """
        Read metadata from cached parquet file.

        Args:
            cache_path: Path to the cache file

        Returns:
            Dictionary with our custom metadata fields or None if no custom metadata/error
        """
        if not cache_path.exists():
            return None

        try:
            import pyarrow.parquet as pq
            pf = pq.ParquetFile(cache_path)
            metadata = pf.schema_arrow.metadata

            if not metadata:
                return None

            # Decode bytes to strings
            decoded_metadata = {k.decode(): v.decode() for k, v in metadata.items()}

            # Check if this has our custom metadata (cache_version key)
            # Pandas adds its own 'pandas' metadata, so we need to check for our specific keys
            if 'cache_version' not in decoded_metadata:
                return None  # Old cache without our metadata

            return decoded_metadata
        except Exception as e:
            self.logger.warning(f"Error reading cache metadata from {cache_path}: {e}")
            return None

    def validate_cache_coverage(self, symbol: str, timeframe: str,
                                start_date: datetime, end_date: datetime) -> Tuple[bool, Optional[str]]:
        """
        Validate that cached data covers requested range without gaps.

        Checks for:
        1. Missing cache files for any day in the range
        2. Cache files without metadata (old/broken cache)
        3. Gaps >1 day at the start of the data
        4. Cache freshness (TTL-based expiration)

        Args:
            symbol: Symbol name
            timeframe: Timeframe
            start_date: Start date
            end_date: End date

        Returns:
            Tuple of (is_valid, reason):
            - is_valid: True if cache is valid, False otherwise
            - reason: None if valid, error message if invalid
        """
        self.logger.debug(
            f"Validating cache coverage: {symbol} {timeframe} "
            f"from {start_date.date()} to {end_date.date()}"
        )

        days = self._get_date_range_days(start_date, end_date)

        if len(days) == 0:
            self.logger.debug(f"  Validation failed: No days in range")
            return False, "No days in range"

        now = datetime.now(timezone.utc)

        # OPTIMIZATION: For sparse timeframes (H4, D1) with many days, use sampling validation
        # Instead of checking ALL 325+ days, check first/last/sample to save time
        if timeframe in ['H4', 'D1'] and len(days) > 30:
            # Sample-based validation: check first, last, and a few in between
            sample_indices = [0, len(days)//4, len(days)//2, 3*len(days)//4, len(days)-1]
            days_to_check = [days[i] for i in sample_indices if i < len(days)]
            self.logger.debug(f"  Using fast validation: checking {len(days_to_check)}/{len(days)} days (sparse timeframe optimization)")
        else:
            days_to_check = days

        # Check each day for existence and metadata
        for i, day in enumerate(days_to_check):
            cache_path = self._get_day_cache_path(day, symbol, timeframe)

            if not cache_path.exists():
                self.logger.debug(f"  Validation failed: Missing cache file for {day.date()}")
                self.logger.debug(f"    Expected path: {cache_path}")
                return False, f"Missing cache for day {day.date()}"

            # Read metadata
            metadata = self._read_cache_metadata(cache_path)

            if not metadata:
                # No metadata - invalidate (old/broken cache)
                self.logger.debug(f"  Validation failed: Missing metadata for {day.date()}")
                return False, f"No metadata for day {day.date()} - cache will be rebuilt"

            # Check cache freshness (TTL)
            if 'cached_at' in metadata:
                try:
                    cached_at = datetime.fromisoformat(metadata['cached_at'])
                    age_days = (now - cached_at).total_seconds() / 86400

                    if age_days > self.cache_ttl_days:
                        self.logger.info(
                            f"Cache expired for {symbol} {timeframe} on {day.date()}: "
                            f"{age_days:.1f} days old (TTL: {self.cache_ttl_days} days)"
                        )
                        return False, f"Cache expired ({age_days:.1f} days old, TTL: {self.cache_ttl_days} days)"
                except Exception as e:
                    self.logger.warning(f"Error parsing cached_at metadata: {e}")
                    # Continue validation - don't fail on metadata parse error

            # For the first day, check for gap at start
            if i == 0 and 'first_data_time' in metadata:
                try:
                    first_data_time = datetime.fromisoformat(metadata['first_data_time'])
                    gap_seconds = (first_data_time - start_date).total_seconds()
                    gap_days = gap_seconds / 86400

                    if gap_days > 1:
                        self.logger.warning(
                            f"Cache gap detected for {symbol} {timeframe}: "
                            f"{gap_days:.1f} days between requested start and first data"
                        )
                        self.logger.debug(
                            f"    Requested start: {start_date}, First data: {first_data_time}"
                        )
                        return False, f"Gap of {gap_days:.1f} days at start"
                except Exception as e:
                    self.logger.warning(f"Error parsing first_data_time metadata: {e}")
                    # Continue validation - don't fail on metadata parse error

        self.logger.debug(f"  Validation passed: All {len(days)} days present and valid")
        return True, None

    def _get_day_cache_path(self, date: datetime, symbol: str, timeframe: str) -> Path:
        """
        Get the cache file path for a symbol/timeframe on a specific day.

        Args:
            date: Date for the cache file
            symbol: Symbol name
            timeframe: Timeframe (e.g., 'M1', 'M5', 'M15', 'H4')

        Returns:
            Path to cache file (YYYY/MM/DD/candles/SYMBOL_TIMEFRAME.parquet)
        """
        # Create date hierarchy: YYYY/MM/DD/candles/
        year = date.strftime('%Y')
        month = date.strftime('%m')
        day = date.strftime('%d')

        day_dir = self.cache_dir / year / month / day / "candles"
        day_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{symbol}_{timeframe}.parquet"
        return day_dir / filename

    def _get_symbol_info_path(self, date: datetime, symbol: str) -> Path:
        """
        Get path to symbol info JSON file for a specific day.

        Args:
            date: Date for the symbol info
            symbol: Symbol name

        Returns:
            Path to symbol info file (YYYY/MM/DD/symbol_info/SYMBOL.json)
        """
        year = date.strftime('%Y')
        month = date.strftime('%m')
        day = date.strftime('%d')

        info_dir = self.cache_dir / year / month / day / "symbol_info"
        info_dir.mkdir(parents=True, exist_ok=True)
        return info_dir / f"{symbol}.json"

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
            True if ALL days in the date range have cached data
        """
        days = self._get_date_range_days(start_date, end_date)

        # Check if all days have cached data
        for day in days:
            cache_path = self._get_day_cache_path(day, symbol, timeframe)
            if not cache_path.exists():
                return False

        return True
    
    def load_from_cache_partial(self, symbol: str, timeframe: str,
                                start_date: datetime, end_date: datetime) -> Tuple[Optional[pd.DataFrame], List[datetime], Dict]:
        """
        Load data from cache, supporting partial cache hits.

        Returns cached data for available days and a list of missing days.
        This enables incremental loading - only missing days need to be fetched.

        Args:
            symbol: Symbol name
            timeframe: Timeframe
            start_date: Start date
            end_date: End date

        Returns:
            Tuple of (cached_df, missing_days, symbol_info):
            - cached_df: DataFrame with cached data (None if no cache available)
            - missing_days: List of datetime objects for days that need to be fetched
            - symbol_info: Symbol info dict (empty if not cached)
        """
        self.logger.debug(
            f"Partial cache load: {symbol} {timeframe} "
            f"from {start_date.date()} to {end_date.date()}"
        )

        days = self._get_date_range_days(start_date, end_date)

        if len(days) == 0:
            self.logger.debug(f"  No days in range")
            return None, [], {}

        daily_dfs = []
        missing_days = []
        symbol_info = {}

        self.logger.debug(f"  Checking {len(days)} days for cached data...")

        # Check each day
        for day in days:
            cache_path = self._get_day_cache_path(day, symbol, timeframe)

            if not cache_path.exists():
                missing_days.append(day)
                continue

            # Read metadata to validate
            metadata = self._read_cache_metadata(cache_path)

            if not metadata:
                # No metadata - treat as missing (will be rebuilt)
                self.logger.debug(f"  No metadata for {symbol} {timeframe} on {day.date()}, will re-fetch")
                missing_days.append(day)
                continue

            # Check freshness
            if 'cached_at' in metadata:
                try:
                    cached_at = datetime.fromisoformat(metadata['cached_at'])
                    age_days = (datetime.now(timezone.utc) - cached_at).total_seconds() / 86400

                    if age_days > self.cache_ttl_days:
                        self.logger.debug(f"  Cache expired for {symbol} {timeframe} on {day.date()} ({age_days:.1f} days old)")
                        missing_days.append(day)
                        continue
                except Exception as e:
                    self.logger.warning(f"  Error parsing cached_at metadata: {e}")
                    # Treat as missing if we can't validate freshness
                    missing_days.append(day)
                    continue

            # Load this day's data
            try:
                df = pd.read_parquet(cache_path, engine='pyarrow')

                # Ensure time column is datetime with UTC timezone
                if 'time' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['time']):
                    df['time'] = pd.to_datetime(df['time'], utc=True)

                daily_dfs.append(df)

                # Load symbol info from the first cached day
                if not symbol_info:
                    symbol_info_path = self._get_symbol_info_path(day, symbol)
                    if symbol_info_path.exists():
                        try:
                            if symbol_info_path.stat().st_size > 0:
                                with open(symbol_info_path, 'r') as f:
                                    symbol_info = json.load(f)
                        except json.JSONDecodeError:
                            self.logger.warning(f"  Corrupted symbol info file for {symbol} on {day.date()}")
                            # Continue - we can still use the cached data

            except Exception as e:
                self.logger.warning(f"  Error loading cache for {symbol} {timeframe} on {day.date()}: {e}")
                # Treat as missing if we can't load it
                missing_days.append(day)
                continue

        # Merge cached data if any
        cached_df = None
        if daily_dfs:
            if len(daily_dfs) == 1:
                cached_df = daily_dfs[0]
            else:
                cached_df = pd.concat(daily_dfs, ignore_index=True)
                cached_df = cached_df.sort_values('time').reset_index(drop=True)
                cached_df = cached_df.drop_duplicates(subset=['time'], keep='first')

            # Filter to requested date range
            cached_df = cached_df[(cached_df['time'] >= start_date) & (cached_df['time'] <= end_date)].copy()

            self.logger.info(f"  ✓ Partial cache hit: {symbol} {timeframe} ({len(cached_df)} bars from {len(daily_dfs)} days, {len(missing_days)} days missing)")
        else:
            self.logger.info(f"  ✗ No cache available for {symbol} {timeframe} ({len(missing_days)} days need to be fetched)")

        return cached_df, missing_days, symbol_info

    def load_from_cache(self, symbol: str, timeframe: str,
                        start_date: datetime, end_date: datetime) -> Optional[Tuple[pd.DataFrame, Dict]]:
        """
        Load data from cache by merging daily cache files.

        This method requires ALL days to be cached and valid. If any day is missing
        or invalid, returns None to trigger a full reload.

        For incremental loading (partial cache hits), use load_from_cache_partial() instead.

        Args:
            symbol: Symbol name
            timeframe: Timeframe
            start_date: Start date
            end_date: End date

        Returns:
            Tuple of (DataFrame, symbol_info dict) or None if not found
        """
        # Validate cache coverage first
        is_valid, reason = self.validate_cache_coverage(symbol, timeframe, start_date, end_date)

        if not is_valid:
            self.logger.info(f"  Cache validation failed for {symbol} {timeframe}: {reason}")
            return None

        days = self._get_date_range_days(start_date, end_date)

        # Load data from each day
        daily_dfs = []
        symbol_info = {}

        for day in days:
            cache_path = self._get_day_cache_path(day, symbol, timeframe)

            if not cache_path.exists():
                # Missing data for this day - return None to trigger full reload
                return None

            try:
                # Load OHLC data using PyArrow engine (2-3x faster than default)
                df = pd.read_parquet(cache_path, engine='pyarrow')

                # Ensure time column is datetime with UTC timezone
                if 'time' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['time']):
                    df['time'] = pd.to_datetime(df['time'], utc=True)

                daily_dfs.append(df)

                # Load symbol info from the first day (it should be the same for all days)
                if not symbol_info:
                    symbol_info_path = self._get_symbol_info_path(day, symbol)
                    if symbol_info_path.exists():
                        try:
                            # Check if file is not empty before trying to parse
                            if symbol_info_path.stat().st_size > 0:
                                with open(symbol_info_path, 'r') as f:
                                    symbol_info = json.load(f)
                            else:
                                self.logger.warning(f"  ⚠ Empty symbol info file for {symbol} on {day.date()}, will re-fetch")
                                # Delete the corrupted file
                                symbol_info_path.unlink()
                                return None
                        except json.JSONDecodeError as je:
                            self.logger.warning(f"  ⚠ Corrupted symbol info file for {symbol} on {day.date()}: {je}, will re-fetch")
                            # Delete the corrupted file
                            symbol_info_path.unlink()
                            return None

            except Exception as e:
                self.logger.error(f"  ✗ Error loading cache for {symbol} {timeframe} on {day.date()}: {e}")
                return None

        if not daily_dfs:
            return None

        # Merge all daily DataFrames
        if len(daily_dfs) == 1:
            merged_df = daily_dfs[0]
        else:
            merged_df = pd.concat(daily_dfs, ignore_index=True)
            # Sort by time to ensure chronological order
            merged_df = merged_df.sort_values('time').reset_index(drop=True)
            # Remove any duplicate timestamps (shouldn't happen, but just in case)
            merged_df = merged_df.drop_duplicates(subset=['time'], keep='first')

        # Filter to requested date range
        merged_df = merged_df[(merged_df['time'] >= start_date) & (merged_df['time'] <= end_date)].copy()

        self.logger.info(f"  ✓ Loaded from cache: {symbol} {timeframe} ({len(merged_df)} bars from {len(daily_dfs)} days)")
        return merged_df, symbol_info
    
    def save_to_cache(self, symbol: str, timeframe: str,
                      start_date: datetime, end_date: datetime,
                      df: pd.DataFrame, symbol_info: Dict):
        """
        Save data to cache by splitting into daily files.

        Args:
            symbol: Symbol name
            timeframe: Timeframe
            start_date: Start date
            end_date: End date
            df: DataFrame with OHLC data
            symbol_info: Symbol information dictionary
        """
        if df is None or len(df) == 0:
            self.logger.warning(f"  ⚠ No data to save for {symbol} {timeframe}")
            return

        self.logger.debug(
            f"Saving to cache: {symbol} {timeframe} - {len(df)} bars "
            f"from {start_date.date()} to {end_date.date()}"
        )

        try:
            # Ensure time column is datetime
            if 'time' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['time']):
                df['time'] = pd.to_datetime(df['time'], utc=True)

            # Group data by day
            df['date'] = df['time'].dt.date
            grouped = df.groupby('date')

            days_saved = 0
            total_bars = 0
            saved_dates = []  # Track dates for index update

            self.logger.debug(f"  Grouped into {len(grouped)} days")

            for date, day_df in grouped:
                # Convert date back to datetime for path construction
                day_datetime = datetime.combine(date, datetime.min.time()).replace(tzinfo=timezone.utc)

                # Remove the temporary 'date' column
                day_df = day_df.drop(columns=['date']).copy()

                # Save this day's data with metadata
                cache_path = self._get_day_cache_path(day_datetime, symbol, timeframe)

                # Create metadata
                import pyarrow as pa
                import pyarrow.parquet as pq

                metadata = {
                    'cached_at': datetime.now(timezone.utc).isoformat(),
                    'source': 'mt5',  # Default source, can be overridden
                    'first_data_time': day_df['time'].iloc[0].isoformat() if len(day_df) > 0 else '',
                    'last_data_time': day_df['time'].iloc[-1].isoformat() if len(day_df) > 0 else '',
                    'row_count': str(len(day_df)),
                    'cache_version': '1.0'
                }

                # Convert to bytes for parquet metadata
                metadata_bytes = {k.encode(): v.encode() for k, v in metadata.items()}

                # Convert DataFrame to Arrow Table
                table = pa.Table.from_pandas(day_df, preserve_index=False)

                # Add metadata to table schema
                table = table.replace_schema_metadata(metadata_bytes)

                # Write with metadata
                pq.write_table(table, cache_path, compression='snappy')

                # Log cache save details
                file_size_mb = cache_path.stat().st_size / (1024 * 1024)
                self.logger.debug(
                    f"    Saved {day_datetime.date()}: {len(day_df)} bars, "
                    f"{file_size_mb:.2f} MB → {cache_path}"
                )

                # Save symbol info for this day (only if we have valid data)
                if symbol_info:
                    symbol_info_path = self._get_symbol_info_path(day_datetime, symbol)
                    try:
                        with open(symbol_info_path, 'w') as f:
                            json.dump(symbol_info, f, indent=2)
                    except Exception as e:
                        self.logger.warning(f"  ⚠ Failed to save symbol info for {symbol} on {day_datetime.date()}: {e}")
                        # If we failed to write, delete the potentially corrupted file
                        if symbol_info_path.exists():
                            symbol_info_path.unlink()

                days_saved += 1
                total_bars += len(day_df)
                saved_dates.append(date)

            # Update cache index
            if self.index and saved_dates:
                self.index.add_cached_days(symbol, timeframe, saved_dates)

            self.logger.info(f"  ✓ Saved to cache: {symbol} {timeframe} ({total_bars} bars across {days_saved} days)")

        except Exception as e:
            self.logger.error(f"  ✗ Error saving cache for {symbol} {timeframe}: {e}")

    def clear_cache(self, symbol: Optional[str] = None, date: Optional[datetime] = None):
        """
        Clear cached data.

        Args:
            symbol: If specified, only clear cache for this symbol.
                   If None, clear entire cache.
            date: If specified, only clear cache for this specific date.
                 If None, clear all dates.
        """
        import shutil

        if date:
            # Clear specific date
            year = date.strftime('%Y')
            month = date.strftime('%m')
            day = date.strftime('%d')
            date_dir = self.cache_dir / year / month / day

            if date_dir.exists():
                if symbol:
                    # Clear specific symbol for this date
                    candles_file = date_dir / "candles" / f"{symbol}_*.parquet"
                    ticks_file = date_dir / "ticks" / f"{symbol}_*.parquet"
                    info_file = date_dir / "symbol_info" / f"{symbol}.json"

                    for pattern in [candles_file, ticks_file, info_file]:
                        for file in date_dir.rglob(pattern.name):
                            if file.exists():
                                file.unlink()

                    # Update index - remove this day for this symbol
                    if self.index:
                        # Remove from all timeframes
                        for timeframe in ['M1', 'M5', 'M15', 'H1', 'H4', 'ticks']:
                            self.index.remove_cached_day(symbol, timeframe, date.date())

                    self.logger.info(f"Cleared cache for {symbol} on {date.date()}")
                else:
                    # Clear entire date
                    shutil.rmtree(date_dir)

                    # Update index - rebuild since we cleared entire date
                    if self.index:
                        self.index.rebuild_index()

                    self.logger.info(f"Cleared cache for {date.date()}")
        elif symbol:
            # Clear all dates for a specific symbol (search through all date directories)
            files_removed = 0
            for year_dir in self.cache_dir.iterdir():
                if not year_dir.is_dir():
                    continue
                for month_dir in year_dir.iterdir():
                    if not month_dir.is_dir():
                        continue
                    for day_dir in month_dir.iterdir():
                        if not day_dir.is_dir():
                            continue

                        # Remove symbol files from this day
                        for subdir in ['candles', 'ticks', 'symbol_info']:
                            subdir_path = day_dir / subdir
                            if subdir_path.exists():
                                for file in subdir_path.glob(f"{symbol}*"):
                                    file.unlink()
                                    files_removed += 1

            # Update index - clear this symbol
            if self.index:
                self.index.clear_symbol(symbol)

            self.logger.info(f"Cleared {files_removed} cache files for {symbol}")
        else:
            # Clear entire cache
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                self.cache_dir.mkdir(parents=True, exist_ok=True)

                # Update index - clear all
                if self.index:
                    self.index.clear_all()

                self.logger.info("Cleared entire cache")

    def get_cache_stats(self) -> Dict:
        """
        Get statistics about cached data.

        Returns:
            Dictionary with cache statistics including:
            - total_days: Number of days with cached data
            - total_files: Total number of cache files
            - total_size_mb: Total size in MB
            - symbols: Per-symbol statistics
            - days: Per-day statistics
        """
        stats = {
            'total_days': 0,
            'total_files': 0,
            'total_size_mb': 0.0,
            'symbols': {},
            'days': {}
        }

        if not self.cache_dir.exists():
            return stats

        # Track which symbols appear in which days
        symbol_days = {}  # symbol -> set of day_keys

        # Traverse date hierarchy: YYYY/MM/DD/
        for year_dir in self.cache_dir.iterdir():
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue

            for month_dir in year_dir.iterdir():
                if not month_dir.is_dir() or not month_dir.name.isdigit():
                    continue

                for day_dir in month_dir.iterdir():
                    if not day_dir.is_dir() or not day_dir.name.isdigit():
                        continue

                    # This is a valid day directory
                    day_key = f"{year_dir.name}-{month_dir.name}-{day_dir.name}"
                    stats['total_days'] += 1
                    stats['days'][day_key] = {
                        'files': 0,
                        'size_mb': 0.0,
                        'symbols': set()
                    }

                    # Count files in candles, ticks, and symbol_info subdirectories
                    for subdir_name in ['candles', 'ticks', 'symbol_info']:
                        subdir = day_dir / subdir_name
                        if not subdir.exists():
                            continue

                        for file_path in subdir.iterdir():
                            if not file_path.is_file():
                                continue

                            stats['total_files'] += 1
                            stats['days'][day_key]['files'] += 1

                            size_mb = file_path.stat().st_size / (1024 * 1024)
                            stats['total_size_mb'] += size_mb
                            stats['days'][day_key]['size_mb'] += size_mb

                            # Extract symbol from filename
                            # Candles: SYMBOL_TIMEFRAME.parquet
                            # Ticks: SYMBOL_TICKTYPE.parquet
                            # Symbol info: SYMBOL.json
                            symbol = file_path.stem.split('_')[0]
                            stats['days'][day_key]['symbols'].add(symbol)

                            # Track this symbol-day combination
                            if symbol not in symbol_days:
                                symbol_days[symbol] = set()
                            symbol_days[symbol].add(day_key)

                            # Update per-symbol stats
                            if symbol not in stats['symbols']:
                                stats['symbols'][symbol] = {
                                    'files': 0,
                                    'size_mb': 0.0,
                                    'days': 0
                                }
                            stats['symbols'][symbol]['files'] += 1
                            stats['symbols'][symbol]['size_mb'] += size_mb

                    # Convert set to count for JSON serialization
                    stats['days'][day_key]['symbols'] = len(stats['days'][day_key]['symbols'])

        # Count unique days per symbol using the tracked symbol_days
        for symbol in stats['symbols']:
            stats['symbols'][symbol]['days'] = len(symbol_days.get(symbol, set()))

        return stats

