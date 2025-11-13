"""
Market status checking functionality.
"""

from src.core.mt5_connector import MT5Connector
from src.utils.autotrading_cooldown import AutoTradingCooldown
from src.utils.logging import TradingLogger


class MarketChecker:
    """Handles market status checking and reopening detection"""

    def __init__(self, connector: MT5Connector, cooldown: AutoTradingCooldown, logger: TradingLogger):
        """
        Initialize market checker.

        Args:
            connector: MT5 connector instance
            cooldown: AutoTrading cooldown manager
            logger: Logger instance
        """
        self.connector = connector
        self.cooldown = cooldown
        self.logger = logger

    def check_market_reopened(self, symbol: str):
        """
        Check if the market has reopened after being closed.

        Args:
            symbol: Symbol to check
        """
        # Update the last check time
        self.cooldown.update_market_check_time()

        # Check if market is now open
        if self.connector.is_market_open(symbol):
            self.logger.info(
                f"Market status check: Market appears to be open for {symbol}",
                symbol
            )
            # Clear the market closed state
            self.cooldown.clear_market_closed()
        else:
            self.logger.debug(
                f"Market status check: Market still closed for {symbol}",
                symbol
            )

