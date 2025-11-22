"""
Broker Archive Downloader for Historical Tick Data.

Downloads historical tick data from external broker archives when MT5
doesn't have the requested data available.

PERFORMANCE OPTIMIZATION:
- In-memory archive cache: Parsed archives are cached to avoid redundant parsing
- Automatic day-by-day Parquet caching: Archives are split into daily files for fast subsequent access
- Thread-safe: Supports parallel day loading with proper locking
- Polars CSV parser: 2-3x faster than pandas for large CSV files (if available)
- Parquet pre-conversion: Automatically converts archives to Parquet for 10-50x faster subsequent loads
"""
import requests
import zipfile
import io
import time
import re
import threading
from pathlib import Path
from typing import Optional, Tuple, Dict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import pandas as pd
import MetaTrader5 as mt5

# Try to import polars for faster CSV parsing
try:
    import polars as pl
    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False

from src.config.configs.tick_archive_config import TickArchiveConfig
from src.utils.logger import get_logger


class BrokerArchiveDownloader:
    """
    Downloads and processes historical tick data from external broker archives.

    Supports multi-tier fallback:
    1. Check local archive cache
    2. Download from external archive source
    3. Parse and validate tick data
    4. Convert to MT5-compatible format

    PERFORMANCE FEATURES:
    - In-memory parsed archive cache (avoids re-parsing same archive 324 times)
    - Automatic day-by-day Parquet caching (fast subsequent backtest runs)
    - Thread-safe for parallel day loading
    """

    def __init__(self, config: TickArchiveConfig):
        """
        Initialize broker archive downloader.

        Args:
            config: Tick archive configuration
        """
        self.config = config
        self.logger = get_logger()

        # Create archive cache directory if it doesn't exist
        if self.config.save_downloaded_archives:
            self.archive_cache_path = Path(self.config.archive_cache_dir)
            self.archive_cache_path.mkdir(parents=True, exist_ok=True)

        # In-memory parsed archive cache
        # Key: (broker, symbol, year) -> Value: parsed DataFrame
        # DISABLED by default to prevent excessive memory usage (40GB+ for 4 symbols)
        # Parquet cache is fast enough (0.6s vs 43s) and doesn't consume RAM
        self._use_memory_cache = False  # Set to True to enable (not recommended)
        self._parsed_archive_cache: Dict[Tuple[str, str, int], pd.DataFrame] = {}
        self._cache_lock = threading.Lock()
        self._cache_stats = {'hits': 0, 'misses': 0, 'memory_mb': 0}

        # Parsing lock to prevent duplicate parsing of same archive
        # Multiple threads requesting same year will wait for first thread to finish
        self._parsing_locks: Dict[Tuple[str, str, int], threading.Lock] = {}
        self._parsing_locks_lock = threading.Lock()

        # Parquet pre-conversion cache directory
        # Stores pre-converted Parquet files for 10-50x faster subsequent loads
        self._parquet_cache_dir = Path(self.config.archive_cache_dir) / "parquet"
        if self.config.save_downloaded_archives:
            self._parquet_cache_dir.mkdir(parents=True, exist_ok=True)
    
    def get_broker_name(self, server_name: str) -> Optional[str]:
        """
        Extract broker name from MT5 server name.
        
        Args:
            server_name: MT5 server name (e.g., "Exness-MT5Trial15")
            
        Returns:
            Broker name for archive URLs (e.g., "Exness") or None if not mapped
        """
        # Check explicit mapping first
        if server_name in self.config.broker_name_mapping:
            return self.config.broker_name_mapping[server_name]
        
        # Try to extract broker name from server name
        # Common patterns: "BrokerName-MT5...", "BrokerName-Server...", etc.
        match = re.match(r'^([A-Za-z]+)', server_name)
        if match:
            return match.group(1)
        
        return None
    
    def normalize_symbol_name(self, symbol: str) -> str:
        """
        Normalize symbol name for archive URLs.
        
        Args:
            symbol: MT5 symbol name (e.g., "XAUUSD.a")
            
        Returns:
            Normalized symbol name (e.g., "XAUUSD")
        """
        # Check explicit mapping first
        if symbol in self.config.symbol_name_mapping:
            return self.config.symbol_name_mapping[symbol]
        
        # Remove common suffixes (.a, .b, .raw, etc.)
        normalized = re.sub(r'\.[a-z]+$', '', symbol, flags=re.IGNORECASE)
        return normalized
    
    def validate_archive_source(self, url: str) -> bool:
        """
        Validate that the archive URL is from a trusted source.
        
        Args:
            url: Archive download URL
            
        Returns:
            True if source is trusted, False otherwise
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Check if domain is in trusted sources
            for trusted_source in self.config.trusted_sources:
                if domain == trusted_source.lower() or domain.endswith('.' + trusted_source.lower()):
                    return True
            
            return False
        except Exception as e:
            self.logger.warning(f"  Error validating archive source: {e}")
            return False
    
    def construct_archive_url(self, symbol: str, year: int, broker: str,
                              month: int = None, day: int = None) -> str:
        """
        Construct day-based archive download URL from template.

        SIMPLIFIED: Only supports day-based archives.

        Args:
            symbol: Normalized symbol name
            year: Year for tick data
            broker: Broker name
            month: Month for tick data (required for day-based archives)
            day: Day for tick data (required for day-based archives)

        Returns:
            Complete archive download URL for the specified day
        """
        # Only day-based archives are supported
        if day is not None and month is not None:
            url = self.config.archive_url_pattern_day.format(
                SYMBOL=symbol,
                YEAR=year,
                MONTH=f"{month:02d}",
                DAY=f"{day:02d}",
                BROKER=broker
            )
            return url
        else:
            # Month/year-based archives are no longer supported
            raise ValueError(
                f"Day-based archives only: month and day parameters are required. "
                f"Got month={month}, day={day}"
            )
    
    def download_archive(self, url: str, symbol: str, year: int) -> Optional[bytes]:
        """
        Download tick data archive from URL with retry logic.
        
        Args:
            url: Archive download URL
            symbol: Symbol name (for logging)
            year: Year (for logging)
            
        Returns:
            Archive file content as bytes, or None if download failed
        """
        self.logger.info(f"  Downloading tick archive: {symbol} {year}")
        self.logger.info(f"    URL: {url}")
        
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    timeout=self.config.download_timeout_seconds,
                    stream=True
                )
                
                if response.status_code == 200:
                    # Get total size if available
                    total_size = int(response.headers.get('content-length', 0))
                    if total_size > 0:
                        self.logger.info(f"    Archive size: {total_size / 1024 / 1024:.1f} MB")
                    
                    # Download content
                    content = response.content
                    self.logger.info(f"  ✓ Download successful ({len(content) / 1024 / 1024:.1f} MB)")
                    return content
                    
                elif response.status_code == 404:
                    self.logger.info(f"  Archive not found (HTTP 404)")
                    return None
                    
                else:
                    self.logger.warning(f"  Download failed: HTTP {response.status_code}")
                    
            except requests.exceptions.Timeout:
                self.logger.warning(f"  Download timeout (attempt {attempt}/{self.config.max_retries})")
                
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"  Download error (attempt {attempt}/{self.config.max_retries}): {e}")
            
            # Retry delay (except on last attempt)
            if attempt < self.config.max_retries:
                self.logger.info(f"  Retrying in {self.config.retry_delay_seconds} seconds...")
                time.sleep(self.config.retry_delay_seconds)
        
        self.logger.warning(f"  Failed to download archive after {self.config.max_retries} attempts")
        return None
    


    def parse_archive(self, archive_content: bytes, symbol: str, year: int,
                     broker: str = None) -> Optional[pd.DataFrame]:
        """
        Parse tick data from downloaded day-based archive.

        Simplified for day-only archives - no intermediate Parquet caching needed
        since day archives are small and already cached at the day level.

        Uses Polars for CSV parsing if available (2-3x faster than pandas).

        Supports common tick data formats:
        - CSV files with columns: time, bid, ask, volume
        - Binary formats (to be implemented)

        Args:
            archive_content: Archive file content (ZIP)
            symbol: Symbol name
            year: Year (for logging only)
            broker: Broker name (unused in simplified version)

        Returns:
            DataFrame with tick data in MT5 format, or None if parsing failed
        """
        self.logger.debug(f"  Parsing day archive for {symbol}...")

        try:
            # Extract ZIP archive
            with zipfile.ZipFile(io.BytesIO(archive_content)) as zf:
                # List files in archive
                file_list = zf.namelist()
                self.logger.debug(f"    Archive contains {len(file_list)} file(s)")

                # Find CSV or data files
                data_files = [f for f in file_list if f.endswith('.csv') or f.endswith('.txt')]

                if not data_files:
                    self.logger.warning(f"  No CSV/TXT files found in archive")
                    return None

                # Use the first data file (or largest if multiple)
                data_file = data_files[0]
                if len(data_files) > 1:
                    # Find largest file
                    data_file = max(data_files, key=lambda f: zf.getinfo(f).file_size)

                self.logger.debug(f"    Parsing file: {data_file}")

                # Read and parse CSV
                with zf.open(data_file) as f:
                    # Try to detect format and parse
                    df = self._parse_tick_csv(f, symbol)

                    if df is not None and len(df) > 0:
                        self.logger.debug(f"  ✓ Parsed {len(df):,} ticks from archive")
                        return df
                    else:
                        self.logger.warning(f"  Failed to parse tick data from archive")
                        return None

        except zipfile.BadZipFile:
            self.logger.warning(f"  Invalid ZIP archive")
            return None

        except Exception as e:
            self.logger.warning(f"  Error parsing archive: {e}")
            return None
    
    def _parse_tick_csv(self, file_obj, symbol: str) -> Optional[pd.DataFrame]:
        """
        Parse tick data from CSV file using the fastest available method.

        PERFORMANCE: Uses Polars (Rust-based) if available for 2-3x speedup,
        otherwise falls back to pandas.

        Supports various CSV formats and auto-detects column structure.

        Args:
            file_obj: File object to read from
            symbol: Symbol name

        Returns:
            DataFrame with columns: time, bid, ask, volume (optional)
        """
        try:
            # Try Polars first (2-3x faster for large CSVs)
            if POLARS_AVAILABLE:
                try:
                    file_obj.seek(0)
                    # Read entire file content for polars
                    csv_content = file_obj.read()

                    # Parse with polars (much faster than pandas)
                    df_polars = pl.read_csv(io.BytesIO(csv_content))

                    # Convert to pandas for compatibility
                    df = df_polars.to_pandas()

                    self.logger.info(f"    ✓ Parsed with Polars (fast mode)")

                except Exception as e:
                    self.logger.debug(f"    Polars parsing failed, falling back to pandas: {e}")
                    # Fall back to pandas
                    file_obj.seek(0)
                    df = pd.read_csv(file_obj, delimiter=',', low_memory=False)
            else:
                # Use pandas (slower but always available)
                # Try to read CSV with various delimiters
                for delimiter in [',', ';', '\t', ' ']:
                    try:
                        file_obj.seek(0)  # Reset file position
                        df = pd.read_csv(file_obj, delimiter=delimiter, low_memory=False)

                        if len(df.columns) >= 3:  # Need at least time, bid, ask
                            break
                    except:
                        continue
                else:
                    self.logger.warning(f"  Could not parse CSV with any delimiter")
                    return None
            
            # Detect and rename columns
            df = self._normalize_tick_columns(df)
            
            if df is None:
                return None
            
            # Validate required columns
            if 'time' not in df.columns or 'bid' not in df.columns or 'ask' not in df.columns:
                self.logger.warning(f"  CSV missing required columns (time, bid, ask)")
                return None

            # Convert time to datetime (handle both string and numeric timestamps)
            try:
                # Try parsing as datetime string first
                df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
            except:
                try:
                    # Try parsing as Unix timestamp
                    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True, errors='coerce')
                except:
                    self.logger.warning(f"  Could not parse time column")
                    return None

            # Convert bid and ask to numeric
            df['bid'] = pd.to_numeric(df['bid'], errors='coerce')
            df['ask'] = pd.to_numeric(df['ask'], errors='coerce')

            # Filter out invalid rows
            df = df.dropna(subset=['time', 'bid', 'ask'])
            df = df[(df['bid'] > 0) & (df['ask'] > 0) & (df['ask'] >= df['bid'])].copy()

            if len(df) == 0:
                self.logger.warning(f"  No valid tick data after filtering")
                return None

            # Add volume column if missing (use 0 as placeholder)
            if 'volume' not in df.columns:
                df['volume'] = 0
            else:
                df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0)

            # Sort by time
            df = df.sort_values('time').reset_index(drop=True)

            # Return only the required columns
            return df[['time', 'bid', 'ask', 'volume']]
            
        except Exception as e:
            self.logger.warning(f"  Error parsing CSV: {e}")
            return None

    def _normalize_tick_columns(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        Normalize column names to standard format.

        Detects common column name variations and renames to: time, bid, ask, volume

        Args:
            df: Raw DataFrame from CSV

        Returns:
            DataFrame with normalized column names, or None if columns can't be detected
        """
        # Common column name variations (exact matches first, then partial matches)
        time_cols_exact = ['time', 'timestamp', 'datetime', 'date', 'dt']
        bid_cols_exact = ['bid', 'bid_price', 'bidprice']
        ask_cols_exact = ['ask', 'ask_price', 'askprice']
        volume_cols_exact = ['volume', 'vol', 'size']

        # Create column mapping
        column_map = {}

        # Find time column (exact match first)
        for col in df.columns:
            col_lower = col.lower().strip()
            if col_lower in time_cols_exact:
                column_map[col] = 'time'
                break

        # If not found, try partial match
        if 'time' not in column_map.values():
            for col in df.columns:
                col_lower = col.lower().strip()
                if any(tc in col_lower for tc in time_cols_exact):
                    column_map[col] = 'time'
                    break

        # Find bid column (exact match first)
        for col in df.columns:
            col_lower = col.lower().strip()
            if col_lower in bid_cols_exact:
                column_map[col] = 'bid'
                break

        # If not found, try partial match (but exclude already mapped columns)
        if 'bid' not in column_map.values():
            for col in df.columns:
                if col in column_map:  # Skip already mapped columns
                    continue
                col_lower = col.lower().strip()
                # Check for 'bid' or 'b' but not in other contexts
                if col_lower == 'b' or 'bid' in col_lower:
                    column_map[col] = 'bid'
                    break

        # Find ask column (exact match first)
        for col in df.columns:
            col_lower = col.lower().strip()
            if col_lower in ask_cols_exact:
                column_map[col] = 'ask'
                break

        # If not found, try partial match (but exclude already mapped columns)
        if 'ask' not in column_map.values():
            for col in df.columns:
                if col in column_map:  # Skip already mapped columns
                    continue
                col_lower = col.lower().strip()
                # Check for 'ask' or 'a' but not in other contexts
                if col_lower == 'a' or 'ask' in col_lower:
                    column_map[col] = 'ask'
                    break

        # Find volume column (optional, exact match first)
        for col in df.columns:
            col_lower = col.lower().strip()
            if col_lower in volume_cols_exact:
                column_map[col] = 'volume'
                break

        # If not found, try partial match
        if 'volume' not in column_map.values():
            for col in df.columns:
                if col in column_map:  # Skip already mapped columns
                    continue
                col_lower = col.lower().strip()
                if col_lower == 'v' or any(vc in col_lower for vc in volume_cols_exact):
                    column_map[col] = 'volume'
                    break

        # Check if we found the required columns
        if 'time' not in column_map.values() or 'bid' not in column_map.values() or 'ask' not in column_map.values():
            self.logger.warning(f"  Could not detect required columns in CSV")
            self.logger.warning(f"    Available columns: {list(df.columns)}")
            self.logger.warning(f"    Detected mapping: {column_map}")
            return None

        # Rename columns
        df = df.rename(columns=column_map)

        return df

    def validate_tick_data(self, df: pd.DataFrame, symbol: str, start_date: datetime, end_date: datetime) -> bool:
        """
        Validate downloaded tick data.

        Args:
            df: Tick data DataFrame
            symbol: Symbol name
            start_date: Requested start date
            end_date: Requested end date

        Returns:
            True if data is valid, False otherwise
        """
        if df is None or len(df) == 0:
            self.logger.warning(f"  Validation failed: Empty DataFrame")
            return False

        # Check minimum ticks threshold
        if len(df) < self.config.min_ticks_threshold:
            self.logger.warning(f"  Validation failed: Only {len(df)} ticks (minimum: {self.config.min_ticks_threshold})")
            return False

        # Check required columns
        required_cols = ['time', 'bid', 'ask']
        if not all(col in df.columns for col in required_cols):
            self.logger.warning(f"  Validation failed: Missing required columns")
            return False

        # Check for valid prices
        if (df['bid'] <= 0).any() or (df['ask'] <= 0).any():
            self.logger.warning(f"  Validation failed: Invalid prices (bid/ask <= 0)")
            return False

        # Check bid/ask spread
        if (df['ask'] < df['bid']).any():
            self.logger.warning(f"  Validation failed: Ask < Bid in some rows")
            return False

        # Check time range
        actual_start = df['time'].iloc[0]
        actual_end = df['time'].iloc[-1]

        self.logger.info(f"  Validation: {len(df):,} ticks from {actual_start.date()} to {actual_end.date()}")

        return True

    def _get_tick_cache_path(self, symbol: str, date: datetime, tick_type: int, cache_dir: str) -> Path:
        """
        Get the cache file path for a specific day's tick data.

        Args:
            symbol: Symbol name
            date: Date for the tick data
            tick_type: MT5 tick type constant
            cache_dir: Base cache directory

        Returns:
            Path to the cache file
        """
        # Create date hierarchy: cache_dir/YYYY/MM/DD/ticks/
        year_dir = Path(cache_dir) / str(date.year)
        month_dir = year_dir / f"{date.month:02d}"
        day_dir = month_dir / f"{date.day:02d}"
        tick_dir = day_dir / "ticks"

        # Create cache filename
        tick_type_name = {
            mt5.COPY_TICKS_ALL: 'ALL',
            mt5.COPY_TICKS_INFO: 'INFO',
            mt5.COPY_TICKS_TRADE: 'TRADE'
        }.get(tick_type, 'INFO')

        cache_file = tick_dir / f"{symbol}_{tick_type_name}.parquet"
        return cache_file

    def _save_day_to_cache(self, df: pd.DataFrame, symbol: str, date: datetime,
                          tick_type: int, cache_dir: str) -> bool:
        """
        Save a single day's tick data to Parquet cache with metadata.

        Args:
            df: Tick data for the day
            symbol: Symbol name
            date: Date for the tick data
            tick_type: MT5 tick type constant
            cache_dir: Base cache directory

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            from datetime import timezone
            import pyarrow as pa
            import pyarrow.parquet as pq

            cache_path = self._get_tick_cache_path(symbol, date, tick_type, cache_dir)

            # Check if already cached - skip if exists to avoid unnecessary overwrites
            if cache_path.exists():
                self.logger.debug(f"  ⏭️  Day cache already exists, skipping: {cache_path.name}")
                return True

            # Create directory if it doesn't exist
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            # Create metadata
            metadata = {
                'cached_at': datetime.now(timezone.utc).isoformat(),
                'source': 'archive',  # From broker archive
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

            return True
        except Exception as e:
            self.logger.warning(f"  Error saving day cache for {date.date()}: {e}")
            return False



    def fetch_tick_data_for_day(self, symbol: str, date: datetime, server_name: str,
                                tick_type: int = mt5.COPY_TICKS_INFO,
                                cache_dir: Optional[str] = None,
                                progress_callback: Optional[callable] = None) -> Optional[pd.DataFrame]:
        """
        Fetch tick data for a single day from day-based archive.

        Simplified strategy: Only downloads day-based archives (single day).
        No fallback to month or year archives for predictable behavior.

        Args:
            symbol: MT5 symbol name
            date: Date to fetch (single day)
            server_name: MT5 server name (for broker detection)
            tick_type: MT5 tick type constant
            cache_dir: Base cache directory for day-level Parquet files
            progress_callback: Optional callback for progress updates (unused in day-only mode)

        Returns:
            DataFrame with tick data for the requested day, or None if fetch failed
        """
        if not self.config.enabled:
            return None

        # Get broker name
        broker = self.get_broker_name(server_name)
        if not broker:
            self.logger.debug(f"    Could not determine broker name from server: {server_name}")
            return None

        # Normalize symbol name
        normalized_symbol = self.normalize_symbol_name(symbol)

        year = date.year
        month = date.month
        day = date.day

        # Define day boundaries
        day_start = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
        day_end = datetime(year, month, day, 23, 59, 59, 999999, tzinfo=timezone.utc)

        # Try day-based archive only
        if self.config.use_granular_downloads:
            self.logger.debug(f"    Trying day-based archive for {date.date()}...")

            url = self.construct_archive_url(normalized_symbol, year, broker, month, day)

            if self.validate_archive_source(url):
                # Try to download day archive
                archive_content = self._try_download_archive(url, normalized_symbol, year, month, day, 'day')

                if archive_content:
                    # Parse and extract the day
                    df = self.parse_archive(archive_content, normalized_symbol, year, broker)
                    if df is not None and len(df) > 0:
                        # Filter to exact day
                        df = df[(df['time'] >= day_start) & (df['time'] <= day_end)].copy()
                        if len(df) > 0:
                            self.logger.info(f"    ✓ Fetched {len(df):,} ticks from day-based archive")

                            # Cache this day
                            if cache_dir:
                                self._save_day_to_cache(df, symbol, date, tick_type, cache_dir)

                            return df

        # No data available - day archive doesn't exist or download failed
        self.logger.debug(f"    No day-based archive available for {date.date()}")
        return None

    def _try_download_archive(self, url: str, symbol: str, year: int,
                              month: Optional[int], day: Optional[int],
                              granularity: str) -> Optional[bytes]:
        """
        Try to download an archive with caching support.

        Args:
            url: Archive URL
            symbol: Symbol name
            year: Year
            month: Month (optional)
            day: Day (optional)
            granularity: 'day', 'month', or 'year'

        Returns:
            Archive content as bytes, or None if download failed
        """
        # Construct cache filename
        if day is not None and month is not None:
            cache_filename = f"{symbol}_{year}_{month:02d}_{day:02d}.zip"
        elif month is not None:
            cache_filename = f"{symbol}_{year}_{month:02d}.zip"
        else:
            cache_filename = f"{symbol}_{year}.zip"

        # Check local ZIP cache first
        if self.config.save_downloaded_archives:
            cache_file = self.archive_cache_path / cache_filename
            if cache_file.exists():
                self.logger.debug(f"    Found cached {granularity} archive: {cache_file.name}")
                try:
                    return cache_file.read_bytes()
                except Exception as e:
                    self.logger.debug(f"    Error reading cached archive: {e}")

        # Download from URL
        archive_content = self.download_archive(url, symbol, year)

        # Save to cache if successful
        if archive_content and self.config.save_downloaded_archives:
            try:
                cache_file = self.archive_cache_path / cache_filename
                cache_file.write_bytes(archive_content)
                self.logger.debug(f"    Saved {granularity} archive to cache: {cache_file.name}")
            except Exception as e:
                self.logger.debug(f"    Error saving archive to cache: {e}")

        return archive_content



