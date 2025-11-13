"""
AutoTrading Cooldown Manager.
Manages cooldown period when server disables AutoTrading (error 10026).
Also manages market closed state (error 10018).
"""
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional
from src.utils.logger import get_logger


class AutoTradingCooldown:
    """
    Manages cooldown period when AutoTrading is disabled by server or market is closed.

    When error 10026 is detected, all trading operations (opening new positions
    and modifying existing positions) are paused for a cooldown period.

    When error 10018 (market closed) is detected, all trading operations are paused
    indefinitely until the market reopens (detected by successful operation or check).
    """

    def __init__(self, cooldown_minutes: int = 5, market_check_interval_seconds: int = 300):
        """
        Initialize cooldown manager.

        Args:
            cooldown_minutes: Duration of cooldown period in minutes (default: 5)
            market_check_interval_seconds: Interval for checking if market reopened (default: 300 = 5 minutes)
        """
        self.cooldown_minutes = cooldown_minutes
        self.cooldown_until: Optional[datetime] = None
        self.market_closed: bool = False  # Flag for market closed state
        self.market_closed_since: Optional[datetime] = None
        self.last_market_check: Optional[datetime] = None
        self.market_check_interval_seconds = market_check_interval_seconds
        self.lock = threading.Lock()
        self.logger = get_logger()
        self.last_log_time: Optional[datetime] = None
        self.log_interval_seconds = 60  # Log status every 60 seconds
    
    def activate_cooldown(self, reason: str = "AutoTrading disabled by server"):
        """
        Activate cooldown period.

        Args:
            reason: Reason for activating cooldown
        """
        with self.lock:
            now = datetime.now(timezone.utc)
            self.cooldown_until = now + timedelta(minutes=self.cooldown_minutes)
            self.last_log_time = now

            self.logger.warning(
                f"🚫 TRADING COOLDOWN ACTIVATED: {reason}"
            )
            self.logger.warning(
                f"⏸️  All trading operations paused for {self.cooldown_minutes} minutes"
            )
            self.logger.warning(
                f"⏰ Cooldown will end at: {self.cooldown_until.strftime('%H:%M:%S')} UTC"
            )

    def activate_market_closed(self, symbol: str = ""):
        """
        Activate market closed state.

        This is different from cooldown - it pauses trading indefinitely until
        the market reopens (detected by successful operation or periodic check).

        Args:
            symbol: Symbol that triggered the market closed error (for logging)
        """
        with self.lock:
            # Only activate if not already in market closed state
            if not self.market_closed:
                now = datetime.now(timezone.utc)
                self.market_closed = True
                self.market_closed_since = now
                self.last_log_time = now
                self.last_market_check = now

                symbol_info = f" (triggered by {symbol})" if symbol else ""
                self.logger.warning(
                    f"🔒 MARKET CLOSED DETECTED{symbol_info}"
                )
                self.logger.warning(
                    f"⏸️  All trading operations paused until market reopens"
                )
                self.logger.warning(
                    f"🔍 Will check market status every {self.market_check_interval_seconds // 60} minutes"
                )

    def clear_market_closed(self):
        """
        Clear market closed state (called when market reopens).
        """
        with self.lock:
            if self.market_closed:
                self.logger.info(
                    f"✅ MARKET REOPENED - Resuming normal trading operations"
                )
                self.market_closed = False
                self.market_closed_since = None
                self.last_market_check = None
    
    def is_in_cooldown(self) -> bool:
        """
        Check if currently in cooldown period or market closed state.

        Returns:
            True if in cooldown or market closed, False otherwise
        """
        with self.lock:
            # Check market closed state first
            if self.market_closed:
                self._log_market_closed_status()
                return True

            # Check timed cooldown
            if self.cooldown_until is None:
                return False

            now = datetime.now(timezone.utc)

            # Check if cooldown has expired
            if now >= self.cooldown_until:
                # Cooldown expired - log and clear
                self.logger.info(
                    f"✅ TRADING COOLDOWN ENDED - Resuming normal operations"
                )
                self.cooldown_until = None
                self.last_log_time = None
                return False

            # Still in cooldown - log periodic updates
            self._log_cooldown_status(now)
            return True

    def is_market_closed(self) -> bool:
        """
        Check if currently in market closed state.

        Returns:
            True if market is closed, False otherwise
        """
        with self.lock:
            return self.market_closed

    def should_check_market_status(self) -> bool:
        """
        Check if it's time to verify if market has reopened.

        Returns:
            True if market status should be checked
        """
        with self.lock:
            if not self.market_closed:
                return False

            if self.last_market_check is None:
                return True

            now = datetime.now(timezone.utc)
            elapsed = (now - self.last_market_check).total_seconds()

            return elapsed >= self.market_check_interval_seconds

    def update_market_check_time(self):
        """
        Update the last market check timestamp.
        """
        with self.lock:
            self.last_market_check = datetime.now(timezone.utc)
    
    def _log_cooldown_status(self, now: datetime):
        """
        Log cooldown status if enough time has passed since last log.

        Args:
            now: Current time
        """
        # Only log if we haven't logged recently
        if self.last_log_time is None or \
           (now - self.last_log_time).total_seconds() >= self.log_interval_seconds:

            remaining = self.cooldown_until - now
            remaining_minutes = int(remaining.total_seconds() / 60)
            remaining_seconds = int(remaining.total_seconds() % 60)

            self.logger.info(
                f"⏸️  Trading cooldown active - {remaining_minutes}m {remaining_seconds}s remaining"
            )
            self.last_log_time = now

    def _log_market_closed_status(self):
        """
        Log market closed status if enough time has passed since last log.
        """
        now = datetime.now(timezone.utc)

        # Only log if we haven't logged recently
        if self.last_log_time is None or \
           (now - self.last_log_time).total_seconds() >= self.log_interval_seconds:

            if self.market_closed_since:
                elapsed = now - self.market_closed_since
                elapsed_minutes = int(elapsed.total_seconds() / 60)

                self.logger.info(
                    f"🔒 Market closed - Trading paused for {elapsed_minutes} minutes"
                )
                self.logger.info(
                    f"🔍 Next market status check in ~{self.market_check_interval_seconds // 60} minutes"
                )
            else:
                self.logger.info(
                    f"🔒 Market closed - Trading operations paused"
                )

            self.last_log_time = now
    
    def get_remaining_time(self) -> Optional[timedelta]:
        """
        Get remaining cooldown time.
        
        Returns:
            Remaining time as timedelta, or None if not in cooldown
        """
        with self.lock:
            if self.cooldown_until is None:
                return None
            
            now = datetime.now(timezone.utc)
            if now >= self.cooldown_until:
                return None
            
            return self.cooldown_until - now
    
    def reset_cooldown(self):
        """
        Manually reset/clear cooldown period.
        Useful for testing or manual intervention.
        """
        with self.lock:
            if self.cooldown_until is not None:
                self.logger.info("Cooldown manually reset")
                self.cooldown_until = None
                self.last_log_time = None

