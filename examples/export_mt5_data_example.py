"""
Example script demonstrating MT5 data export for backtesting.

This script shows how to:
1. Connect to MT5
2. Export tick data for backtesting
3. Export OHLCV data for backtesting
4. Validate exported data
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import MetaTrader5 as mt5
from src.core.mt5_connector import MT5Connector
from src.backtesting.data import MT5DataExporter
from src.utils.logger import get_logger


def main():
    """Main function to demonstrate data export."""
    logger = get_logger()
    
    # Initialize MT5 connector
    logger.info("Initializing MT5 connector...")
    connector = MT5Connector()
    
    if not connector.connect():
        logger.error("Failed to connect to MT5")
        return
    
    try:
        # Create data exporter
        exporter = MT5DataExporter(connector, output_dir="data/backtest")
        
        # Define date range (last 7 days)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        # Example 1: Export tick data for EURUSD
        logger.info("=" * 60)
        logger.info("Example 1: Exporting tick data for EURUSD")
        logger.info("=" * 60)
        
        tick_file = exporter.export_tick_data(
            symbol="EURUSD",
            start_date=start_date,
            end_date=end_date
        )
        
        if tick_file:
            logger.info(f"Tick data exported successfully: {tick_file}")
            # Validate the exported data
            if exporter.validate_data(tick_file):
                logger.info("Tick data validation passed!")
        
        # Example 2: Export OHLCV data for EURUSD (M1 timeframe)
        logger.info("\n" + "=" * 60)
        logger.info("Example 2: Exporting OHLCV data for EURUSD (M1)")
        logger.info("=" * 60)
        
        ohlcv_file = exporter.export_ohlcv_data(
            symbol="EURUSD",
            timeframe=mt5.TIMEFRAME_M1,
            start_date=start_date,
            end_date=end_date
        )
        
        if ohlcv_file:
            logger.info(f"OHLCV data exported successfully: {ohlcv_file}")
            # Validate the exported data
            if exporter.validate_data(ohlcv_file):
                logger.info("OHLCV data validation passed!")
        
        # Example 3: Export data range (multiple days)
        logger.info("\n" + "=" * 60)
        logger.info("Example 3: Exporting date range (3 days of tick data)")
        logger.info("=" * 60)
        
        range_start = end_date - timedelta(days=3)
        exported_files = exporter.export_date_range(
            symbol="EURUSD",
            start_date=range_start,
            end_date=end_date,
            data_type="tick"
        )
        
        logger.info(f"Exported {len(exported_files)} files:")
        for file_path in exported_files:
            logger.info(f"  - {file_path}")
        
        logger.info("\n" + "=" * 60)
        logger.info("Data export completed successfully!")
        logger.info("=" * 60)
        
    finally:
        # Disconnect from MT5
        connector.disconnect()
        logger.info("Disconnected from MT5")


if __name__ == "__main__":
    main()

