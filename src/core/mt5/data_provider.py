"""
MT5 data retrieval (candles).
"""

import MetaTrader5 as mt5
import pandas as pd
from typing import Optional

from src.models.data_models import CandleData
from src.utils.logging import TradingLogger
from src.utils.timeframe_converter import TimeframeConverter
from src.constants import ERROR_MT5_NOT_CONNECTED, ERROR_INVALID_TIMEFRAME


class DataProvider:
    """Provides candle data from MT5"""

    def __init__(self, connection_manager, logger: TradingLogger):
        """
        Initialize data provider.

        Args:
            connection_manager: ConnectionManager instance
            logger: Logger instance
        """
        self.connection_manager = connection_manager
        self.logger = logger

    def get_candles(self, symbol: str, timeframe: str, count: int = 100) -> Optional[pd.DataFrame]:
        """
        Get historical candles for a symbol.

        Args:
            symbol: Symbol name
            timeframe: Timeframe ('M5', 'H4', etc.)
            count: Number of candles to retrieve

        Returns:
            DataFrame with OHLCV data or None if error
        """
        if not self.connection_manager.is_connected:
            self.logger.error(ERROR_MT5_NOT_CONNECTED)
            return None

        # Convert timeframe string to MT5 constant
        tf = TimeframeConverter.to_mt5_constant(timeframe)
        if tf is None:
            self.logger.error(f"{ERROR_INVALID_TIMEFRAME}: {timeframe}")
            return None

        try:
            # Get candles
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)

            if rates is None or len(rates) == 0:
                self.logger.trade_error(
                    symbol=symbol,
                    error_type="Data Retrieval",
                    error_message=f"Failed to get {timeframe} candles from MT5",
                    context={
                        "timeframe": timeframe,
                        "count": count,
                        "mt5_error": str(mt5.last_error())
                    }
                )
                return None

            # Convert to DataFrame
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)

            return df

        except Exception as e:
            self.logger.trade_error(
                symbol=symbol,
                error_type="Data Retrieval",
                error_message=f"Exception while getting {timeframe} candles: {str(e)}",
                context={
                    "timeframe": timeframe,
                    "count": count,
                    "exception_type": type(e).__name__
                }
            )
            return None

    def get_latest_candle(self, symbol: str, timeframe: str) -> Optional[CandleData]:
        """
        Get the latest closed candle.

        Args:
            symbol: Symbol name
            timeframe: Timeframe

        Returns:
            CandleData object or None
        """
        df = self.get_candles(symbol, timeframe, count=2)
        if df is None or len(df) < 2:
            return None

        # Get the second-to-last candle (last closed candle)
        candle = df.iloc[-2]

        return CandleData(
            time=pd.Timestamp(candle['time']).to_pydatetime(),
            open=float(candle['open']),
            high=float(candle['high']),
            low=float(candle['low']),
            close=float(candle['close']),
            volume=int(candle['tick_volume'])
        )

