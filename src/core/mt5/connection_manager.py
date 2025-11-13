"""
MT5 connection management.
"""

import MetaTrader5 as mt5
from src.config.configs import MT5Config
from src.utils.logging import TradingLogger


class ConnectionManager:
    """Manages connection to MetaTrader 5"""

    def __init__(self, config: MT5Config, logger: TradingLogger):
        """
        Initialize connection manager.

        Args:
            config: MT5 configuration
            logger: Logger instance
        """
        self.config = config
        self.logger = logger
        self.is_connected = False

    def connect(self) -> bool:
        """
        Connect to MetaTrader 5.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Initialize MT5
            if not mt5.initialize():
                self.logger.error(f"MT5 initialize() failed, error code: {mt5.last_error()}")
                return False

            # Login to account
            authorized = mt5.login(
                login=self.config.login,
                password=self.config.password,
                server=self.config.server,
                timeout=self.config.timeout
            )

            if not authorized:
                error = mt5.last_error()
                self.logger.error(f"MT5 login failed, error code: {error}")
                mt5.shutdown()
                return False

            self.is_connected = True

            # Log account info
            account_info = mt5.account_info()
            if account_info:
                self.logger.info("=== MT5 Connection Successful ===")
                self.logger.info(f"Account: {account_info.login}")
                self.logger.info(f"Server: {account_info.server}")
                self.logger.info(f"Balance: ${account_info.balance:.2f}")
                self.logger.info(f"Equity: ${account_info.equity:.2f}")
                self.logger.info(f"Currency: {account_info.currency}")
                self.logger.separator()

            return True

        except Exception as e:
            self.logger.error(f"Error connecting to MT5: {e}")
            return False

    def disconnect(self):
        """Disconnect from MetaTrader 5"""
        if self.is_connected:
            mt5.shutdown()
            self.is_connected = False
            self.logger.info("Disconnected from MT5")

