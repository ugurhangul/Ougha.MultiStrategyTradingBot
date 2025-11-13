"""
Symbol performance tracking and auto-disable/enable logic.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING
from src.models.data_models import SymbolStats
from src.config.configs import SymbolAdaptationConfig
from src.strategy.symbol_performance_persistence import SymbolPerformancePersistence
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.core.mt5_connector import MT5Connector


class SymbolTracker:
    """Tracks symbol performance and manages auto-disable/enable"""

    def __init__(self, symbol: str, config: SymbolAdaptationConfig,
                 persistence: Optional[SymbolPerformancePersistence] = None,
                 connector: Optional['MT5Connector'] = None,
                 magic_number: Optional[int] = None):
        """
        Initialize symbol tracker.

        Args:
            symbol: Symbol name
            config: Symbol adaptation configuration
            persistence: Symbol performance persistence instance (optional)
            connector: MT5 connector instance (optional, for history reconstruction)
            magic_number: Magic number for filtering trades (optional, for history reconstruction)
        """
        self.symbol = symbol
        self.config = config
        self.logger = get_logger()

        # Persistence
        self.persistence = persistence if persistence is not None else SymbolPerformancePersistence()

        # Load existing stats or create new
        loaded_stats = self.persistence.load_symbol_stats(symbol)
        if loaded_stats:
            self.stats = loaded_stats
            self.logger.info(f"Loaded existing stats for {symbol}: {self.stats.total_trades} trades, "
                           f"Win rate: {self.stats.win_rate:.1f}%, Net P/L: ${self.stats.net_profit:.2f}", symbol)
        else:
            # Try to construct stats from MT5 history if connector is provided
            if connector is not None and magic_number is not None:
                self.logger.info(f"No existing stats for {symbol}, attempting to construct from MT5 history", symbol)
                constructed_stats = self.persistence.construct_stats_from_mt5_history(
                    symbol=symbol,
                    connector=connector,
                    magic_number=magic_number,
                    days_back=30  # Look back 30 days
                )

                if constructed_stats:
                    self.stats = constructed_stats
                    # Save the constructed stats
                    self._save_stats()
                    self.logger.info(f"Successfully constructed stats from history for {symbol}", symbol)
                else:
                    # No history found, start fresh
                    self.stats = SymbolStats()
                    self.stats.week_start_time = self._get_current_week_start()
                    self._save_stats()
                    self.logger.info(f"No history found, starting fresh stats for {symbol}", symbol)
            else:
                # No connector provided, start fresh
                self.stats = SymbolStats()
                self.stats.week_start_time = self._get_current_week_start()
                self._save_stats()

        # Disable tracking (derived from stats)
        self.is_disabled = not self.stats.is_enabled
        self.disabled_at = self.stats.disabled_time

        # Check if weekly reset is needed
        if self.config.reset_weekly:
            self._check_weekly_reset()
    
    def on_trade_closed(self, profit: float):
        """
        Update stats when a trade is closed.

        Args:
            profit: Trade profit (positive or negative)
        """
        self.stats.total_trades += 1

        if profit > 0:
            self.stats.winning_trades += 1
            self.stats.total_profit += profit
            self.stats.consecutive_losses = 0
            self.stats.consecutive_wins += 1
        else:
            self.stats.losing_trades += 1
            self.stats.total_loss += abs(profit)
            self.stats.consecutive_losses += 1
            self.stats.consecutive_wins = 0

        # Update drawdown tracking
        self._update_drawdown()

        # Log updated stats
        self.logger.info("=== Symbol Performance Updated ===", self.symbol)
        self.logger.info(f"Total Trades: {self.stats.total_trades}", self.symbol)
        self.logger.info(f"Win Rate: {self.stats.win_rate:.1f}%", self.symbol)
        self.logger.info(f"Net Profit: ${self.stats.net_profit:.2f}", self.symbol)
        self.logger.info(f"Consecutive Losses: {self.stats.consecutive_losses}", self.symbol)
        self.logger.info(f"Current Drawdown: {self.stats.current_drawdown_percent:.2f}%", self.symbol)
        self.logger.info(f"Max Drawdown: {self.stats.max_drawdown_percent:.2f}%", self.symbol)
        self.logger.separator()

        # Save stats to persistence
        self._save_stats()

        # Check if symbol should be disabled
        if self.config.use_symbol_adaptation and not self.is_disabled:
            self._check_disable_criteria()
    
    def _check_disable_criteria(self):
        """Check if symbol should be disabled based on performance"""
        should_disable = False
        reason = ""

        # Check minimum trades requirement
        if self.stats.total_trades < self.config.min_trades_for_evaluation:
            return

        # Check consecutive losses (highest priority)
        if self.stats.consecutive_losses >= self.config.max_consecutive_losses:
            should_disable = True
            reason = f"Consecutive losses {self.stats.consecutive_losses} reached maximum {self.config.max_consecutive_losses}"

        # Check drawdown percentage
        elif self.stats.current_drawdown_percent >= self.config.max_drawdown_percent:
            should_disable = True
            reason = f"Drawdown {self.stats.current_drawdown_percent:.2f}% exceeds maximum {self.config.max_drawdown_percent}%"

        # Check win rate
        elif self.stats.win_rate < self.config.min_win_rate:
            should_disable = True
            reason = f"Win rate {self.stats.win_rate:.1f}% below minimum {self.config.min_win_rate}%"

        # Check total loss
        elif self.stats.total_loss > self.config.max_total_loss:
            should_disable = True
            reason = f"Total loss ${self.stats.total_loss:.2f} exceeds maximum ${self.config.max_total_loss:.2f}"

        if should_disable:
            self._disable_symbol(reason)
    
    def _disable_symbol(self, reason: str):
        """
        Disable symbol trading.

        Args:
            reason: Reason for disabling
        """
        self.is_disabled = True
        self.disabled_at = datetime.now(timezone.utc)

        # Update stats
        self.stats.is_enabled = False
        self.stats.disabled_time = self.disabled_at
        self.stats.disable_reason = reason

        # Calculate re-enable date (end of current trading week)
        if self.config.reset_weekly:
            # Disable until next weekly reset
            reenable_date = self._get_next_week_start()
        else:
            # Disable for cooling period
            reenable_date = self.disabled_at + timedelta(hours=self.config.cooling_period_hours)

        # Prepare stats for logging
        stats = {
            'total_trades': self.stats.total_trades,
            'wins': self.stats.winning_trades,
            'losses': self.stats.losing_trades,
            'win_rate': self.stats.win_rate,
            'net_pnl': self.stats.net_profit,
            'consecutive_losses': self.stats.consecutive_losses,
            'current_drawdown': self.stats.current_drawdown_percent,
            'max_drawdown': self.stats.max_drawdown_percent,
            'reenable_date': reenable_date.strftime('%Y-%m-%d %H:%M:%S UTC')
        }

        # Save stats to persistence
        self._save_stats()

        # Log symbol disabled with stats
        self.logger.symbol_disabled(self.symbol, reason, stats)
        self.logger.info(
            f"Symbol will be re-enabled at {reenable_date.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            self.symbol
        )
    
    def check_reenable(self) -> bool:
        """
        Check if symbol should be re-enabled after cooling period.

        Returns:
            True if symbol was re-enabled
        """
        if not self.is_disabled or self.disabled_at is None:
            return False

        # Check if we should re-enable based on weekly reset or cooling period
        should_reenable = False

        if self.config.reset_weekly:
            # Check if we've reached the next week
            current_week_start = self._get_current_week_start()
            if self.stats.week_start_time and current_week_start > self.stats.week_start_time:
                should_reenable = True
        else:
            # Check if cooling period has passed
            cooling_period = timedelta(hours=self.config.cooling_period_hours)
            if datetime.now(timezone.utc) - self.disabled_at >= cooling_period:
                should_reenable = True

        if should_reenable:
            self._reenable_symbol()
            return True

        return False

    def _reenable_symbol(self):
        """Re-enable symbol after cooling period or weekly reset"""
        # Prepare old stats for logging
        old_stats = {
            'total_trades': self.stats.total_trades,
            'net_pnl': self.stats.net_profit,
            'disable_reason': self.stats.disable_reason
        }

        self.is_disabled = False
        self.disabled_at = None

        # Update stats
        self.stats.is_enabled = True
        self.stats.disabled_time = None
        self.stats.disable_reason = ""

        # Reset consecutive losses
        self.stats.consecutive_losses = 0

        # Save stats
        self._save_stats()

        self.logger.symbol_reenabled(self.symbol, old_stats)
    
    def can_trade(self) -> bool:
        """
        Check if symbol can trade.
        
        Returns:
            True if trading is allowed
        """
        # Check if re-enable is due
        if self.is_disabled:
            self.check_reenable()
        
        return not self.is_disabled
    
    def get_stats(self) -> SymbolStats:
        """Get current stats"""
        return self.stats
    
    def reset_stats(self):
        """Reset performance stats"""
        old_stats = {
            'total_trades': self.stats.total_trades,
            'win_rate': self.stats.win_rate,
            'net_pnl': self.stats.net_profit,
            'max_drawdown': self.stats.max_drawdown_percent
        }

        self.stats = SymbolStats()
        self.stats.week_start_time = self._get_current_week_start()

        # Re-enable symbol on weekly reset
        self.is_disabled = False
        self.disabled_at = None

        # Save reset stats
        self._save_stats()

        self.logger.info("=== Symbol Stats Reset ===", self.symbol)
        self.logger.info(f"Previous: {old_stats['total_trades']} trades, "
                        f"Win rate: {old_stats['win_rate']:.1f}%, "
                        f"Net P/L: ${old_stats['net_pnl']:.2f}", self.symbol)
        self.logger.separator()

    def _update_drawdown(self):
        """Update drawdown tracking based on current equity"""
        current_equity = self.stats.net_profit

        # Update peak equity if we've reached a new high
        if current_equity > self.stats.peak_equity:
            self.stats.peak_equity = current_equity
            self.stats.current_drawdown = 0.0
        else:
            # Calculate current drawdown from peak
            self.stats.current_drawdown = self.stats.peak_equity - current_equity

            # Update max drawdown if current is worse
            if self.stats.current_drawdown > self.stats.max_drawdown:
                self.stats.max_drawdown = self.stats.current_drawdown

    def _get_current_week_start(self) -> datetime:
        """
        Get the start of the current trading week.

        Returns:
            Datetime of current week start
        """
        now = datetime.now(timezone.utc)

        # Calculate days since the reset day
        days_since_reset = (now.weekday() - self.config.weekly_reset_day) % 7

        # Get the most recent reset day
        week_start = now - timedelta(days=days_since_reset)

        # Set to the reset hour
        week_start = week_start.replace(hour=self.config.weekly_reset_hour, minute=0, second=0, microsecond=0)

        # If we haven't reached the reset time this week yet, go back one week
        if week_start > now:
            week_start -= timedelta(days=7)

        return week_start

    def _get_next_week_start(self) -> datetime:
        """
        Get the start of the next trading week.

        Returns:
            Datetime of next week start
        """
        current_week_start = self._get_current_week_start()
        return current_week_start + timedelta(days=7)

    def _check_weekly_reset(self):
        """Check if weekly reset is needed and perform it"""
        current_week_start = self._get_current_week_start()

        # If week_start_time is not set or is from a previous week, reset
        if not self.stats.week_start_time or self.stats.week_start_time < current_week_start:
            if self.stats.total_trades > 0:
                self.logger.info(f"Weekly reset triggered for {self.symbol}", self.symbol)
                self.reset_stats()
            else:
                # Just update the week start time
                self.stats.week_start_time = current_week_start
                self._save_stats()

    def _save_stats(self):
        """Save current stats to persistence"""
        self.persistence.save_symbol_stats(self.symbol, self.stats)

