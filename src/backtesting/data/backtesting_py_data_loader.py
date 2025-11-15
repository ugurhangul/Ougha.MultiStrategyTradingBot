"""
Data loader for backtesting.py library.

Converts MT5 data to pandas DataFrame format required by backtesting.py.
"""
from typing import Optional
from pathlib import Path
from datetime import datetime
import pandas as pd
import MetaTrader5 as mt5

from src.core.mt5_connector import MT5Connector
from src.config import config
from src.utils.logger import get_logger


class BacktestingPyDataLoader:
    """
    Load and prepare data for backtesting.py library.
    
    backtesting.py requires a DataFrame with columns:
    - Open, High, Low, Close (OHLC prices)
    - Volume (trading volume)
    - Index must be DatetimeIndex
    """
    
    def __init__(self, connector: Optional[MT5Connector] = None):
        """
        Initialize data loader.

        Args:
            connector: MT5 connector instance (optional, creates new if None)
        """
        self.logger = get_logger()
        self.connector = connector
        self._owns_connector = False

        if self.connector is None:
            # Create connector with global config
            self.connector = MT5Connector(config.mt5)
            self._owns_connector = True
    
    def load_from_mt5(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Load historical data from MT5.
        
        Args:
            symbol: Trading symbol (e.g., 'EURUSD')
            timeframe: Timeframe string (e.g., 'M5', 'H1', 'H4')
            start_date: Start date for historical data
            end_date: End date for historical data
            
        Returns:
            DataFrame with OHLCV data formatted for backtesting.py, or None if error
        """
        try:
            # Connect if not already connected
            if self._owns_connector and not self.connector.is_connected:
                if not self.connector.connect():
                    self.logger.error("Failed to connect to MT5")
                    return None
            
            # Convert timeframe string to MT5 constant
            mt5_timeframe = self._convert_timeframe(timeframe)
            if mt5_timeframe is None:
                return None
            
            # Get data from MT5
            self.logger.info(f"Loading {symbol} {timeframe} data from {start_date} to {end_date}")
            
            rates = mt5.copy_rates_range(symbol, mt5_timeframe, start_date, end_date)
            
            if rates is None or len(rates) == 0:
                self.logger.error(f"No data retrieved for {symbol} {timeframe}")
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(rates)
            
            # Format for backtesting.py
            df = self._format_for_backtesting_py(df)
            
            self.logger.info(f"Loaded {len(df)} candles for {symbol} {timeframe}")
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error loading data from MT5: {e}")
            return None
    
    def load_from_csv(self, csv_path: str) -> Optional[pd.DataFrame]:
        """
        Load historical data from CSV file.
        
        CSV must have columns: time, open, high, low, close, tick_volume
        
        Args:
            csv_path: Path to CSV file
            
        Returns:
            DataFrame with OHLCV data formatted for backtesting.py, or None if error
        """
        try:
            self.logger.info(f"Loading data from CSV: {csv_path}")
            
            df = pd.read_csv(csv_path)
            
            # Format for backtesting.py
            df = self._format_for_backtesting_py(df)
            
            self.logger.info(f"Loaded {len(df)} candles from CSV")
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error loading data from CSV: {e}")
            return None
    
    def _format_for_backtesting_py(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Format DataFrame for backtesting.py requirements.
        
        Args:
            df: Raw DataFrame with MT5 data
            
        Returns:
            Formatted DataFrame
        """
        # Rename columns to match backtesting.py requirements (capitalized)
        df = df.rename(columns={
            'time': 'Time',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'tick_volume': 'Volume'
        })
        
        # Convert time to datetime and set as index
        df['Time'] = pd.to_datetime(df['Time'], unit='s')
        df = df.set_index('Time')
        
        # Select only required columns
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
        
        return df
    
    def _convert_timeframe(self, timeframe: str) -> Optional[int]:
        """Convert timeframe string to MT5 constant."""
        timeframe_map = {
            'M1': mt5.TIMEFRAME_M1,
            'M5': mt5.TIMEFRAME_M5,
            'M15': mt5.TIMEFRAME_M15,
            'M30': mt5.TIMEFRAME_M30,
            'H1': mt5.TIMEFRAME_H1,
            'H4': mt5.TIMEFRAME_H4,
            'D1': mt5.TIMEFRAME_D1,
        }
        
        mt5_tf = timeframe_map.get(timeframe)
        if mt5_tf is None:
            self.logger.error(f"Unsupported timeframe: {timeframe}")
        
        return mt5_tf
    
    def __del__(self):
        """Cleanup: disconnect if we own the connector."""
        if self._owns_connector and self.connector:
            self.connector.disconnect()

