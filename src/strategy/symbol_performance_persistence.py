"""
Symbol performance persistence mechanism.

This module provides:
1. JSON-based symbol stats storage with atomic writes
2. Thread-safe file access
3. Automatic backup of corrupted files
4. Per-symbol performance tracking across restarts
5. Stats reconstruction from MT5 history when empty
"""
import json
import os
import threading
from typing import Dict, Optional, TYPE_CHECKING
from datetime import datetime, timedelta
from pathlib import Path

from src.models.data_models import SymbolStats
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.core.mt5_connector import MT5Connector


class SymbolPerformancePersistence:
    """Manages symbol performance persistence across restarts"""
    
    def __init__(self, data_dir: str = "data"):
        """
        Initialize symbol performance persistence.
        
        Args:
            data_dir: Directory to store symbol_stats.json file
        """
        self.logger = get_logger()
        
        # Create data directory if it doesn't exist
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Stats file path
        self.stats_file = self.data_dir / "symbol_stats.json"
        
        # Thread lock for file access
        self.lock = threading.Lock()
        
        # In-memory cache of symbol stats
        self.stats_cache: Dict[str, Dict] = {}
        
        # Load existing stats on initialization
        self._load_stats()
    
    def _load_stats(self):
        """Load symbol stats from JSON file"""
        with self.lock:
            try:
                if self.stats_file.exists():
                    with open(self.stats_file, 'r') as f:
                        self.stats_cache = json.load(f)
                    
                    self.logger.info(f"Loaded stats for {len(self.stats_cache)} symbols from persistence file")
                else:
                    self.stats_cache = {}
                    self.logger.info("No existing symbol stats file found, starting fresh")
                    
            except json.JSONDecodeError as e:
                self.logger.error(f"Corrupted symbol stats file: {e}")
                self.logger.warning("Starting with empty stats cache")
                self.stats_cache = {}
                # Backup corrupted file with timestamp
                if self.stats_file.exists():
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    backup_path = self.stats_file.with_suffix(f'.json.corrupted.{timestamp}')
                    self.stats_file.rename(backup_path)
                    self.logger.info(f"Corrupted file backed up to: {backup_path}")
                    
            except Exception as e:
                self.logger.error(f"Error loading symbol stats: {e}")
                self.stats_cache = {}
    
    def _save_stats(self):
        """
        Save symbol stats to JSON file with atomic write.

        NOTE: This method does NOT acquire the lock - it must be called
        from a method that already holds the lock.
        """
        import time
        import sys

        try:
            # Write to temporary file first (atomic write)
            temp_file = self.stats_file.with_suffix('.json.tmp')

            with open(temp_file, 'w') as f:
                json.dump(self.stats_cache, f, indent=2, default=str)
            # File handle is now closed

            # Windows-compatible atomic rename with retry logic
            max_retries = 3
            retry_delay = 0.1  # 100ms

            for attempt in range(max_retries):
                try:
                    if sys.platform == 'win32':
                        # On Windows, we need to delete the target file first
                        # because replace() can fail with "Access is denied"
                        if self.stats_file.exists():
                            self.stats_file.unlink()
                        # Now rename temp file to target
                        temp_file.rename(self.stats_file)
                    else:
                        # On Unix-like systems, replace() is truly atomic
                        temp_file.replace(self.stats_file)

                    # Success
                    self.logger.debug(f"Saved stats for {len(self.stats_cache)} symbols to persistence file")
                    break

                except (PermissionError, OSError) as e:
                    if attempt < max_retries - 1:
                        # Retry after a short delay
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        # Final attempt failed
                        raise

        except Exception as e:
            self.logger.error(f"Error saving symbol stats: {e}")
            # Clean up temp file if it still exists
            try:
                temp_file = self.stats_file.with_suffix('.json.tmp')
                if temp_file.exists():
                    temp_file.unlink()
            except:
                pass
    
    def save_symbol_stats(self, symbol: str, stats: SymbolStats):
        """
        Save stats for a symbol.
        
        Args:
            symbol: Symbol name
            stats: SymbolStats object
        """
        with self.lock:
            stats_data = {
                'total_trades': stats.total_trades,
                'winning_trades': stats.winning_trades,
                'losing_trades': stats.losing_trades,
                'total_profit': stats.total_profit,
                'total_loss': stats.total_loss,
                'consecutive_losses': stats.consecutive_losses,
                'consecutive_wins': stats.consecutive_wins,
                'is_enabled': stats.is_enabled,
                'disabled_time': stats.disabled_time.isoformat() if stats.disabled_time else None,
                'disable_reason': stats.disable_reason,
                'peak_equity': stats.peak_equity,
                'current_drawdown': stats.current_drawdown,
                'max_drawdown': stats.max_drawdown,
                'week_start_time': stats.week_start_time.isoformat() if stats.week_start_time else None
            }
            
            self.stats_cache[symbol] = stats_data
            self._save_stats()
            
            self.logger.debug(f"Saved stats for {symbol}")
    
    def load_symbol_stats(self, symbol: str) -> Optional[SymbolStats]:
        """
        Load stats for a symbol.
        
        Args:
            symbol: Symbol name
            
        Returns:
            SymbolStats object or None if not found
        """
        with self.lock:
            if symbol not in self.stats_cache:
                return None
            
            data = self.stats_cache[symbol]
            
            # Parse datetime fields
            disabled_time = None
            if data.get('disabled_time'):
                try:
                    disabled_time = datetime.fromisoformat(data['disabled_time'])
                except (ValueError, TypeError):
                    pass
            
            week_start_time = None
            if data.get('week_start_time'):
                try:
                    week_start_time = datetime.fromisoformat(data['week_start_time'])
                except (ValueError, TypeError):
                    pass
            
            stats = SymbolStats(
                total_trades=data.get('total_trades', 0),
                winning_trades=data.get('winning_trades', 0),
                losing_trades=data.get('losing_trades', 0),
                total_profit=data.get('total_profit', 0.0),
                total_loss=data.get('total_loss', 0.0),
                consecutive_losses=data.get('consecutive_losses', 0),
                consecutive_wins=data.get('consecutive_wins', 0),
                is_enabled=data.get('is_enabled', True),
                disabled_time=disabled_time,
                disable_reason=data.get('disable_reason', ''),
                peak_equity=data.get('peak_equity', 0.0),
                current_drawdown=data.get('current_drawdown', 0.0),
                max_drawdown=data.get('max_drawdown', 0.0),
                week_start_time=week_start_time
            )
            
            self.logger.debug(f"Loaded stats for {symbol}")
            return stats

    def construct_stats_from_mt5_history(self, symbol: str, connector: 'MT5Connector',
                                         magic_number: int, days_back: int = 30) -> Optional[SymbolStats]:
        """
        Construct symbol stats from MT5 trade history.

        This method reads closed trades from MT5 history and reconstructs the stats
        as if they had been tracked from the beginning. Useful when:
        - Starting to track a symbol that already has trade history
        - Stats file was lost or corrupted
        - Migrating from another system

        Args:
            symbol: Symbol name
            connector: MT5 connector instance
            magic_number: Magic number to filter trades
            days_back: Number of days to look back in history (default: 30)

        Returns:
            SymbolStats object constructed from history, or None if no history found
        """
        if not connector.is_connected:
            self.logger.error("MT5 not connected, cannot construct stats from history")
            return None

        try:
            import MetaTrader5 as mt5

            # Calculate date range
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days_back)

            self.logger.info(f"Constructing stats for {symbol} from MT5 history ({days_back} days back)")

            # Get all deals in the date range
            deals = mt5.history_deals_get(from_date, to_date)

            if deals is None or len(deals) == 0:
                self.logger.info(f"No history deals found for {symbol}")
                return None

            # Filter deals for this symbol and magic number
            # We only care about OUT deals (position closures)
            closed_trades = []

            for deal in deals:
                # Filter by symbol
                if deal.symbol != symbol:
                    continue

                # Filter by magic number
                if deal.magic != magic_number:
                    continue

                # Only process OUT deals (position closures)
                if deal.entry != mt5.DEAL_ENTRY_OUT:
                    continue

                # Store the deal info
                closed_trades.append({
                    'position_id': deal.position_id,
                    'profit': deal.profit,
                    'time': datetime.fromtimestamp(deal.time)
                })

            if not closed_trades:
                self.logger.info(f"No closed trades found for {symbol} with magic number {magic_number}")
                return None

            # Sort by time to process in chronological order
            closed_trades.sort(key=lambda x: x['time'])

            self.logger.info(f"Found {len(closed_trades)} closed trades for {symbol}")

            # Initialize stats
            stats = SymbolStats()
            stats.week_start_time = self._get_current_week_start()

            # Track peak equity for drawdown calculation
            current_equity = 0.0

            # Process each trade
            for trade in closed_trades:
                profit = trade['profit']

                # Update trade counts
                stats.total_trades += 1

                if profit > 0:
                    stats.winning_trades += 1
                    stats.total_profit += profit
                    stats.consecutive_losses = 0
                    stats.consecutive_wins += 1
                else:
                    stats.losing_trades += 1
                    stats.total_loss += abs(profit)
                    stats.consecutive_losses += 1
                    stats.consecutive_wins = 0

                # Update equity and drawdown
                current_equity += profit

                if current_equity > stats.peak_equity:
                    stats.peak_equity = current_equity
                    stats.current_drawdown = 0.0
                else:
                    stats.current_drawdown = stats.peak_equity - current_equity
                    if stats.current_drawdown > stats.max_drawdown:
                        stats.max_drawdown = stats.current_drawdown

            # Log constructed stats
            self.logger.info(f"Constructed stats for {symbol}:")
            self.logger.info(f"  Total trades: {stats.total_trades}")
            self.logger.info(f"  Win rate: {stats.win_rate:.1f}%")
            self.logger.info(f"  Net P/L: ${stats.net_profit:.2f}")
            self.logger.info(f"  Consecutive losses: {stats.consecutive_losses}")
            self.logger.info(f"  Max drawdown: {stats.max_drawdown_percent:.2f}%")

            return stats

        except Exception as e:
            self.logger.error(f"Error constructing stats from MT5 history for {symbol}: {e}")
            return None

    def _get_current_week_start(self) -> datetime:
        """
        Get the start of the current week (Monday 00:00 UTC).

        Returns:
            Datetime of current week start
        """
        from datetime import timezone

        now = datetime.now(timezone.utc)
        # Get days since Monday (0 = Monday, 6 = Sunday)
        days_since_monday = now.weekday()
        # Calculate Monday 00:00 UTC
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
        return week_start
    
    def delete_symbol_stats(self, symbol: str):
        """
        Delete stats for a symbol.
        
        Args:
            symbol: Symbol name
        """
        with self.lock:
            if symbol in self.stats_cache:
                del self.stats_cache[symbol]
                self._save_stats()
                self.logger.info(f"Deleted stats for {symbol}")
    
    def get_all_symbols(self) -> list[str]:
        """
        Get list of all symbols with saved stats.
        
        Returns:
            List of symbol names
        """
        with self.lock:
            return list(self.stats_cache.keys())
    
    def clear_all_stats(self):
        """Clear all symbol stats"""
        with self.lock:
            self.stats_cache = {}
            self._save_stats()
            self.logger.info("Cleared all symbol stats")

