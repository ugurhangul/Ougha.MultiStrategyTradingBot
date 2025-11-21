"""
Broker Archive Downloader for Historical Tick Data.

Downloads historical tick data from external broker archives when MT5
doesn't have the requested data available.
"""
import requests
import zipfile
import io
import time
import re
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse
import pandas as pd
import MetaTrader5 as mt5

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
    
    def construct_archive_url(self, symbol: str, year: int, broker: str) -> str:
        """
        Construct archive download URL from template.
        
        Args:
            symbol: Normalized symbol name
            year: Year for tick data
            broker: Broker name
            
        Returns:
            Complete archive download URL
        """
        url = self.config.archive_url_pattern.format(
            SYMBOL=symbol,
            YEAR=year,
            BROKER=broker
        )
        return url
    
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
    
    def parse_archive(self, archive_content: bytes, symbol: str, year: int) -> Optional[pd.DataFrame]:
        """
        Parse tick data from downloaded archive.
        
        Supports common tick data formats:
        - CSV files with columns: time, bid, ask, volume
        - Binary formats (to be implemented)
        
        Args:
            archive_content: Archive file content
            symbol: Symbol name
            year: Year
            
        Returns:
            DataFrame with tick data in MT5 format, or None if parsing failed
        """
        self.logger.info(f"  Parsing tick archive for {symbol} {year}")
        
        try:
            # Extract ZIP archive
            with zipfile.ZipFile(io.BytesIO(archive_content)) as zf:
                # List files in archive
                file_list = zf.namelist()
                self.logger.info(f"    Archive contains {len(file_list)} file(s)")
                
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
                
                self.logger.info(f"    Parsing file: {data_file}")
                
                # Read and parse CSV
                with zf.open(data_file) as f:
                    # Try to detect format and parse
                    df = self._parse_tick_csv(f, symbol)
                    
                    if df is not None and len(df) > 0:
                        self.logger.info(f"  ✓ Parsed {len(df):,} ticks from archive")
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
        Parse tick data from CSV file.
        
        Supports various CSV formats and auto-detects column structure.
        
        Args:
            file_obj: File object to read from
            symbol: Symbol name
            
        Returns:
            DataFrame with columns: time, bid, ask, volume (optional)
        """
        try:
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

    def fetch_tick_data(self, symbol: str, start_date: datetime, end_date: datetime,
                       server_name: str) -> Optional[pd.DataFrame]:
        """
        Fetch tick data from external broker archive.

        Main entry point for downloading historical tick data.

        Args:
            symbol: MT5 symbol name
            start_date: Start date for tick data
            end_date: End date for tick data
            server_name: MT5 server name (for broker detection)

        Returns:
            DataFrame with tick data, or None if fetch failed
        """
        if not self.config.enabled:
            self.logger.info(f"  External archive downloads are disabled")
            return None

        # Get broker name
        broker = self.get_broker_name(server_name)
        if not broker:
            self.logger.warning(f"  Could not determine broker name from server: {server_name}")
            return None

        # Normalize symbol name
        normalized_symbol = self.normalize_symbol_name(symbol)

        self.logger.info(f"  Attempting to fetch tick data from external archive")
        self.logger.info(f"    Symbol: {symbol} -> {normalized_symbol}")
        self.logger.info(f"    Broker: {broker}")
        self.logger.info(f"    Date range: {start_date.date()} to {end_date.date()}")

        # Determine years to download
        years = list(range(start_date.year, end_date.year + 1))

        all_ticks = []

        for year in years:
            self.logger.info(f"  Fetching data for year {year}...")

            # Construct archive URL
            url = self.construct_archive_url(normalized_symbol, year, broker)

            # Validate source
            if not self.validate_archive_source(url):
                self.logger.warning(f"  Untrusted archive source: {url}")
                continue

            # Check local cache first
            cached_archive = None
            if self.config.save_downloaded_archives:
                cache_file = self.archive_cache_path / f"{broker}_{normalized_symbol}_{year}.zip"
                if cache_file.exists():
                    self.logger.info(f"  Using cached archive: {cache_file.name}")
                    try:
                        cached_archive = cache_file.read_bytes()
                    except Exception as e:
                        self.logger.warning(f"  Error reading cached archive: {e}")

            # Download if not cached
            archive_content = cached_archive
            if archive_content is None:
                archive_content = self.download_archive(url, normalized_symbol, year)

                # Save to cache if successful
                if archive_content and self.config.save_downloaded_archives:
                    try:
                        cache_file = self.archive_cache_path / f"{broker}_{normalized_symbol}_{year}.zip"
                        cache_file.write_bytes(archive_content)
                        self.logger.info(f"  Saved archive to cache: {cache_file.name}")
                    except Exception as e:
                        self.logger.warning(f"  Error saving archive to cache: {e}")

            if archive_content is None:
                self.logger.info(f"  No archive available for {year}")
                continue

            # Parse archive
            df = self.parse_archive(archive_content, normalized_symbol, year)

            if df is not None and len(df) > 0:
                # Filter to requested date range
                df = df[(df['time'] >= start_date) & (df['time'] <= end_date)].copy()

                if len(df) > 0:
                    all_ticks.append(df)
                    self.logger.info(f"  ✓ Got {len(df):,} ticks for {year}")

        # Combine all years
        if not all_ticks:
            self.logger.info(f"  No tick data found in external archives")
            return None

        combined_df = pd.concat(all_ticks, ignore_index=True)
        combined_df = combined_df.sort_values('time').reset_index(drop=True)

        # Validate combined data
        if self.config.validate_tick_format:
            if not self.validate_tick_data(combined_df, symbol, start_date, end_date):
                self.logger.warning(f"  Downloaded data failed validation")
                return None

        self.logger.info(f"  ✓ Successfully fetched {len(combined_df):,} ticks from external archive")

        return combined_df

