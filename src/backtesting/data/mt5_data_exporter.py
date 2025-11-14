"""
MT5 Data Exporter for hftbacktest.

This module exports historical data from MetaTrader 5 and converts it
to hftbacktest-compatible format (.npz files).

Supports:
- Tick data export
- OHLCV candle data export
- Order book reconstruction (simulated from bid/ask)
- Data validation and quality checks
"""

import os
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from pathlib import Path

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
import hftbacktest.types as hbt_types

from src.core.mt5_connector import MT5Connector
from src.utils.logger import get_logger


class MT5DataExporter:
    """Exports historical data from MT5 to hftbacktest format.

    hftbacktest expects data in .npz format with specific structure based on
    :mod:`hftbacktest.types`:

    - Tick data / market depth events: ``event_dtype`` structured array with
      fields ``(ev, exch_ts, local_ts, px, qty, order_id, ival, fval)``.
    - Order book and trade information are encoded via event types and flags
      (``DEPTH_*_EVENT``, ``TRADE_EVENT``, ``BUY_EVENT``, ``SELL_EVENT``, etc.).
    """

    def __init__(self, connector: MT5Connector, output_dir: str = "data/backtest"):
        """
        Initialize MT5 data exporter.
        
        Args:
            connector: MT5 connector instance
            output_dir: Directory to save exported data
        """
        self.connector = connector
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger()
        
    def export_tick_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        output_filename: Optional[str] = None
    ) -> Optional[str]:
        """
        Export tick data from MT5 to hftbacktest format.
        
        Args:
            symbol: Trading symbol
            start_date: Start date for data export
            end_date: End date for data export
            output_filename: Optional custom filename
            
        Returns:
            Path to exported file or None if failed
        """
        self.logger.info(
            f"Exporting tick data for {symbol} from {start_date} to {end_date}"
        )
        
        try:
            # Get ticks from MT5
            ticks = mt5.copy_ticks_range(symbol, start_date, end_date, mt5.COPY_TICKS_ALL)

            if ticks is None or len(ticks) == 0:
                self.logger.error(f"No tick data available for {symbol}")
                return None

            self.logger.info(f"Retrieved {len(ticks)} ticks from MT5")

            # Convert to DataFrame for easier manipulation
            df = pd.DataFrame(ticks)

            # Determine exchange and local timestamps in nanoseconds
            if 'time_msc' in df.columns:
                # MT5 provides time in milliseconds; convert to nanoseconds
                df['exch_ts'] = (df['time_msc'] * 1_000_000).astype(np.int64)
            else:
                # Fallback: use 'time' in seconds
                df['exch_ts'] = (df['time'] * 1_000_000_000).astype(np.int64)

            df['local_ts'] = df['exch_ts']

            # Build event array in the format expected by hftbacktest.types.event_dtype
            # We represent each tick as two BBO depth events:
            #   - one for the bid side
            #   - one for the ask side
            num_ticks = len(df)
            num_events = num_ticks * 2

            data = np.zeros(num_events, dtype=hbt_types.event_dtype)

            # Event codes (combine depth event + exchange event + side)
            bid_ev = (
                hbt_types.DEPTH_EVENT
                | hbt_types.EXCH_EVENT
                | hbt_types.BUY_EVENT
            )
            ask_ev = (
                hbt_types.DEPTH_EVENT
                | hbt_types.EXCH_EVENT
                | hbt_types.SELL_EVENT
            )

            # Prepare quantity per tick: start from MT5 volume, fall back to
            # tick_volume if needed, and ensure strictly positive quantities so
            # that hftbacktest's market depth book is populated correctly.
            if 'volume' in df.columns:
                volume = df['volume'].astype(float)
            else:
                volume = np.zeros(len(df), dtype=float)

            if (not np.any(volume > 0)) and 'tick_volume' in df.columns:
                self.logger.debug(
                    "MT5 volume column non-positive; falling back to tick_volume for qty."
                )
                volume = df['tick_volume'].astype(float)

            volume = np.asarray(volume, dtype=np.float64)
            invalid = ~np.isfinite(volume) | (volume <= 0)
            if np.any(invalid):
                self.logger.debug(
                    "Replacing %d non-positive/invalid volume entries with 1.0 for depth qty.",
                    int(invalid.sum()),
                )
                volume[invalid] = 1.0

            # Fill bid events (even indices)
            data['ev'][0::2] = bid_ev
            data['exch_ts'][0::2] = df['exch_ts'].values
            data['local_ts'][0::2] = df['local_ts'].values
            data['px'][0::2] = df['bid'].values
            data['qty'][0::2] = volume

            # Fill ask events (odd indices)
            data['ev'][1::2] = ask_ev
            data['exch_ts'][1::2] = df['exch_ts'].values
            data['local_ts'][1::2] = df['local_ts'].values
            data['px'][1::2] = df['ask'].values
            data['qty'][1::2] = volume

            # Leave order_id, ival, fval as zeros (not used for simple BBO reconstruction)

            # Generate filename if not provided
            if output_filename is None:
                date_str = start_date.strftime('%Y%m%d')
                output_filename = f"{symbol.lower()}_{date_str}_ticks.npz"
                
            output_path = self.output_dir / output_filename
            
            # Save to .npz format
            np.savez_compressed(output_path, data=data)
            
            self.logger.info(f"Tick data exported to {output_path}")
            return str(output_path)
            
        except Exception as e:
            self.logger.error(f"Error exporting tick data: {e}")
            return None
    
    def export_ohlcv_data(
        self,
        symbol: str,
        timeframe: int,
        start_date: datetime,
        end_date: datetime,
        output_filename: Optional[str] = None
    ) -> Optional[str]:
        """
        Export OHLCV candle data from MT5 to hftbacktest format.

        Args:
            symbol: Trading symbol
            timeframe: MT5 timeframe constant (e.g., mt5.TIMEFRAME_M1)
            start_date: Start date for data export
            end_date: End date for data export
            output_filename: Optional custom filename

        Returns:
            Path to exported file or None if failed
        """
        self.logger.info(
            f"Exporting OHLCV data for {symbol} timeframe {timeframe} "
            f"from {start_date} to {end_date}"
        )

        try:
            # Get candles from MT5
            rates = mt5.copy_rates_range(symbol, timeframe, start_date, end_date)

            if rates is None or len(rates) == 0:
                self.logger.error(f"No OHLCV data available for {symbol}")
                return None

            self.logger.info(f"Retrieved {len(rates)} candles from MT5")

            # Convert to DataFrame
            df = pd.DataFrame(rates)

            # Convert time to microseconds
            df['time_us'] = (df['time'] * 1_000_000).astype(np.int64)

            # Create hftbacktest-compatible structure
            data = np.zeros(
                len(df),
                dtype=[
                    ('timestamp', 'i8'),  # microseconds
                    ('open', 'f8'),
                    ('high', 'f8'),
                    ('low', 'f8'),
                    ('close', 'f8'),
                    ('volume', 'f8'),
                ]
            )

            data['timestamp'] = df['time_us'].values
            data['open'] = df['open'].values
            data['high'] = df['high'].values
            data['low'] = df['low'].values
            data['close'] = df['close'].values
            data['volume'] = df['tick_volume'].values

            # Generate filename if not provided
            if output_filename is None:
                date_str = start_date.strftime('%Y%m%d')
                output_filename = f"{symbol.lower()}_{date_str}_ohlcv.npz"

            output_path = self.output_dir / output_filename

            # Save to .npz format
            np.savez_compressed(output_path, data=data)

            self.logger.info(f"OHLCV data exported to {output_path}")
            return str(output_path)

        except Exception as e:
            self.logger.error(f"Error exporting OHLCV data: {e}")
            return None

    def export_date_range(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        data_type: str = "tick",
        timeframe: Optional[int] = None
    ) -> List[str]:
        """
        Export data for a date range, splitting into daily files.

        Args:
            symbol: Trading symbol
            start_date: Start date
            end_date: End date
            data_type: "tick" or "ohlcv"
            timeframe: MT5 timeframe (required for OHLCV)

        Returns:
            List of exported file paths
        """
        exported_files = []
        current_date = start_date

        while current_date <= end_date:
            next_date = current_date + timedelta(days=1)

            if data_type == "tick":
                file_path = self.export_tick_data(
                    symbol, current_date, next_date
                )
            elif data_type == "ohlcv":
                if timeframe is None:
                    self.logger.error("Timeframe required for OHLCV export")
                    break
                file_path = self.export_ohlcv_data(
                    symbol, timeframe, current_date, next_date
                )
            else:
                self.logger.error(f"Unknown data type: {data_type}")
                break

            if file_path:
                exported_files.append(file_path)

            current_date = next_date

        self.logger.info(f"Exported {len(exported_files)} files")
        return exported_files

    def validate_data(self, file_path: str) -> bool:
        """
        Validate exported data file.

        Args:
            file_path: Path to .npz file

        Returns:
            True if valid, False otherwise
        """
        try:
            data = np.load(file_path)

            if 'data' not in data:
                self.logger.error(f"Missing 'data' key in {file_path}")
                return False

            arr = data['data']

            # Check for NaN values in floating-point fields only
            for field_name in arr.dtype.names:
                if arr.dtype[field_name].kind == 'f':  # float fields
                    if np.any(np.isnan(arr[field_name])):
                        self.logger.warning(
                            f"NaN values found in field '{field_name}' of {file_path}"
                        )
                        break

            # Check timestamp ordering using exchange timestamp field
            if 'exch_ts' in arr.dtype.names:
                if not np.all(arr['exch_ts'][:-1] <= arr['exch_ts'][1:]):
                    self.logger.error(f"Timestamps not in order in {file_path}")
                    return False

            self.logger.info(f"Data validation passed for {file_path}")
            return True

        except Exception as e:
            self.logger.error(f"Error validating data: {e}")
            return False

