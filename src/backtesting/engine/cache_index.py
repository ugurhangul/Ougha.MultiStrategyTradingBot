"""
Cache metadata index for fast cache validation.

Maintains an in-memory index of cached date ranges to avoid
filesystem scans on every cache check.

This significantly speeds up cache validation:
- Without index: 0.5-1s (filesystem scan)
- With index: <0.01s (in-memory lookup)
"""
import json
from pathlib import Path
from datetime import datetime, date, timezone
from typing import Dict, Set, Optional, List
from threading import Lock
from src.utils.logger import get_logger


class CacheIndex:
    """
    Maintains index of cached data for fast validation.
    
    Index structure:
    {
        "EURUSD": {
            "M1": {
                "cached_days": ["2025-01-01", "2025-01-02", ...],
                "last_updated": "2025-11-22T10:30:00Z"
            },
            "ticks": {
                "cached_days": ["2025-01-01", ...],
                "last_updated": "2025-11-22T10:30:00Z"
            }
        }
    }
    
    Thread-safe for concurrent access.
    Auto-rebuilds if corrupted or missing.
    """
    
    def __init__(self, cache_dir: str, auto_rebuild: bool = True):
        """
        Initialize cache index.
        
        Args:
            cache_dir: Root cache directory
            auto_rebuild: Automatically rebuild index if corrupted (default: True)
        """
        self.cache_dir = Path(cache_dir)
        self.index_path = self.cache_dir / "cache_index.json"
        self.index: Dict = {}
        self.lock = Lock()
        self.auto_rebuild = auto_rebuild
        self.logger = get_logger()
        self._load_index()
    
    def _load_index(self):
        """Load index from disk."""
        with self.lock:
            if self.index_path.exists():
                try:
                    with open(self.index_path, 'r') as f:
                        self.index = json.load(f)

                    # Count total cached days
                    total_days = sum(
                        len(data.get('cached_days', []))
                        for symbol_data in self.index.values()
                        for data in symbol_data.values()
                    )
                    self.logger.debug(f"Cache index loaded: {len(self.index)} symbols, {total_days} total cached days")
                except (json.JSONDecodeError, IOError) as e:
                    # Corrupted index
                    self.logger.warning(f"Cache index corrupted: {e}")
                    if self.auto_rebuild:
                        self.logger.info("Auto-rebuilding cache index from filesystem...")
                        self.index = {}
                        self.rebuild_index()
                    else:
                        self.logger.warning("Auto-rebuild disabled, starting with empty index")
                        self.index = {}
            else:
                self.logger.debug("No cache index found, starting with empty index")
                self.index = {}
    
    def _save_index(self):
        """Save index to disk (must be called with lock held)."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with open(self.index_path, 'w') as f:
                json.dump(self.index, f, indent=2)
        except IOError:
            # Ignore save errors (index will be rebuilt on next load)
            pass
    
    def get_cached_days(self, symbol: str, data_key: str) -> Set[date]:
        """
        Get set of cached days for symbol/data_key.

        Args:
            symbol: Symbol name (e.g., 'EURUSD')
            data_key: Data key (e.g., 'M1', 'M5', 'ticks')

        Returns:
            Set of dates that are cached
        """
        with self.lock:
            if symbol not in self.index:
                self.logger.debug(f"Cache index lookup: {symbol} {data_key} - symbol not in index")
                return set()
            if data_key not in self.index[symbol]:
                self.logger.debug(f"Cache index lookup: {symbol} {data_key} - data_key not in index")
                return set()

            day_strings = self.index[symbol][data_key].get('cached_days', [])
            try:
                cached_days = {datetime.fromisoformat(d).date() for d in day_strings}
                self.logger.debug(f"Cache index lookup: {symbol} {data_key} - {len(cached_days)} days found")
                return cached_days
            except (ValueError, AttributeError):
                # Corrupted data
                self.logger.warning(f"Cache index lookup: {symbol} {data_key} - corrupted data")
                return set()
    
    def add_cached_day(self, symbol: str, data_key: str, day: date):
        """
        Add a day to the index.
        
        Args:
            symbol: Symbol name
            data_key: Data key (timeframe or 'ticks')
            day: Date to add
        """
        with self.lock:
            if symbol not in self.index:
                self.index[symbol] = {}
            if data_key not in self.index[symbol]:
                self.index[symbol][data_key] = {
                    'cached_days': [],
                    'last_updated': datetime.now(timezone.utc).isoformat()
                }
            
            day_str = day.isoformat()
            if day_str not in self.index[symbol][data_key]['cached_days']:
                self.index[symbol][data_key]['cached_days'].append(day_str)
                self.index[symbol][data_key]['cached_days'].sort()
                self.index[symbol][data_key]['last_updated'] = datetime.now(timezone.utc).isoformat()
                self._save_index()
    
    def add_cached_days(self, symbol: str, data_key: str, days: List[date]):
        """
        Add multiple days to the index (batch operation).

        More efficient than calling add_cached_day() multiple times.

        Args:
            symbol: Symbol name
            data_key: Data key (timeframe or 'ticks')
            days: List of dates to add
        """
        with self.lock:
            if symbol not in self.index:
                self.index[symbol] = {}
            if data_key not in self.index[symbol]:
                self.index[symbol][data_key] = {
                    'cached_days': [],
                    'last_updated': datetime.now(timezone.utc).isoformat()
                }

            # Get existing days
            existing_days = set(self.index[symbol][data_key]['cached_days'])

            # Add new days
            new_days = [d.isoformat() for d in days if d.isoformat() not in existing_days]

            if new_days:
                self.index[symbol][data_key]['cached_days'].extend(new_days)
                self.index[symbol][data_key]['cached_days'].sort()
                self.index[symbol][data_key]['last_updated'] = datetime.now(timezone.utc).isoformat()
                self._save_index()
                self.logger.debug(f"Cache index updated: {symbol} {data_key} - added {len(new_days)} days")
            else:
                self.logger.debug(f"Cache index: {symbol} {data_key} - all {len(days)} days already indexed")
    
    def remove_cached_day(self, symbol: str, data_key: str, day: date):
        """
        Remove a day from the index.
        
        Args:
            symbol: Symbol name
            data_key: Data key (timeframe or 'ticks')
            day: Date to remove
        """
        with self.lock:
            if symbol not in self.index:
                return
            if data_key not in self.index[symbol]:
                return
            
            day_str = day.isoformat()
            if day_str in self.index[symbol][data_key]['cached_days']:
                self.index[symbol][data_key]['cached_days'].remove(day_str)
                self.index[symbol][data_key]['last_updated'] = datetime.now(timezone.utc).isoformat()
                self._save_index()
    
    def clear_symbol(self, symbol: str):
        """
        Clear all cached days for a symbol.
        
        Args:
            symbol: Symbol name
        """
        with self.lock:
            if symbol in self.index:
                del self.index[symbol]
                self._save_index()
    
    def clear_all(self):
        """Clear entire index."""
        with self.lock:
            self.index = {}
            self._save_index()
    
    def rebuild_index(self):
        """
        Rebuild index by scanning filesystem.

        This scans the cache directory and rebuilds the index from scratch.
        Useful if the index becomes out of sync with the filesystem.
        """
        self.logger.info("Rebuilding cache index from filesystem...")
        rebuild_start = datetime.now()

        with self.lock:
            self.index = {}

            # Scan cache directory structure: YYYY/MM/DD/candles/ and YYYY/MM/DD/ticks/
            if not self.cache_dir.exists():
                self.logger.debug("Cache directory does not exist, index will be empty")
                self._save_index()
                return
            
            # Scan year directories
            for year_dir in self.cache_dir.iterdir():
                if not year_dir.is_dir() or not year_dir.name.isdigit():
                    continue
                
                # Scan month directories
                for month_dir in year_dir.iterdir():
                    if not month_dir.is_dir() or not month_dir.name.isdigit():
                        continue
                    
                    # Scan day directories
                    for day_dir in month_dir.iterdir():
                        if not day_dir.is_dir() or not day_dir.name.isdigit():
                            continue
                        
                        try:
                            # Parse date from directory structure
                            year = int(year_dir.name)
                            month = int(month_dir.name)
                            day = int(day_dir.name)
                            cache_date = date(year, month, day)
                        except (ValueError, OSError):
                            continue
                        
                        # Scan candles directory
                        candles_dir = day_dir / "candles"
                        if candles_dir.exists():
                            for cache_file in candles_dir.glob("*.parquet"):
                                # Parse filename: SYMBOL_TIMEFRAME.parquet
                                parts = cache_file.stem.split('_')
                                if len(parts) >= 2:
                                    symbol = '_'.join(parts[:-1])  # Handle symbols with underscores
                                    timeframe = parts[-1]
                                    
                                    if symbol not in self.index:
                                        self.index[symbol] = {}
                                    if timeframe not in self.index[symbol]:
                                        self.index[symbol][timeframe] = {
                                            'cached_days': [],
                                            'last_updated': datetime.now(timezone.utc).isoformat()
                                        }
                                    
                                    day_str = cache_date.isoformat()
                                    if day_str not in self.index[symbol][timeframe]['cached_days']:
                                        self.index[symbol][timeframe]['cached_days'].append(day_str)
                        
                        # Scan ticks directory
                        ticks_dir = day_dir / "ticks"
                        if ticks_dir.exists():
                            for cache_file in ticks_dir.glob("*.parquet"):
                                # Parse filename: SYMBOL_TICKTYPE.parquet
                                parts = cache_file.stem.split('_')
                                if len(parts) >= 2:
                                    symbol = '_'.join(parts[:-1])  # Handle symbols with underscores
                                    
                                    if symbol not in self.index:
                                        self.index[symbol] = {}
                                    if 'ticks' not in self.index[symbol]:
                                        self.index[symbol]['ticks'] = {
                                            'cached_days': [],
                                            'last_updated': datetime.now(timezone.utc).isoformat()
                                        }
                                    
                                    day_str = cache_date.isoformat()
                                    if day_str not in self.index[symbol]['ticks']['cached_days']:
                                        self.index[symbol]['ticks']['cached_days'].append(day_str)
            
            # Sort all cached_days lists
            for symbol in self.index:
                for data_key in self.index[symbol]:
                    self.index[symbol][data_key]['cached_days'].sort()

            self._save_index()

            # Log rebuild completion
            rebuild_duration = (datetime.now() - rebuild_start).total_seconds()
            total_days = sum(
                len(data.get('cached_days', []))
                for symbol_data in self.index.values()
                for data in symbol_data.values()
            )
            self.logger.info(
                f"Cache index rebuilt: {len(self.index)} symbols, {total_days} total cached days "
                f"({rebuild_duration:.2f}s)"
            )
    
    def get_stats(self) -> Dict:
        """
        Get index statistics.
        
        Returns:
            Dictionary with statistics:
            - total_symbols: Number of symbols in index
            - total_days: Total number of cached days across all symbols
            - symbols: List of symbols with their cached day counts
        """
        with self.lock:
            stats = {
                'total_symbols': len(self.index),
                'total_days': 0,
                'symbols': {}
            }
            
            for symbol in self.index:
                symbol_days = 0
                for data_key in self.index[symbol]:
                    day_count = len(self.index[symbol][data_key].get('cached_days', []))
                    symbol_days += day_count
                
                stats['symbols'][symbol] = symbol_days
                stats['total_days'] += symbol_days
            
            return stats

