"""
Export sample tick data from MT5 for backtesting.

This script exports a small sample of tick data from MT5 to test
the backtesting framework with all three strategy adapters.

Usage:
    python examples/export_sample_data.py
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.mt5_connector import MT5Connector
from src.backtesting.data.mt5_data_exporter import MT5DataExporter
from src.utils.logger import get_logger
from src.config import config


def main():
    """Export sample tick data for testing."""
    logger = get_logger()
    
    logger.info("=" * 80)
    logger.info("MT5 Sample Data Export for Backtesting")
    logger.info("=" * 80)
    
    # Initialize MT5 connector using global config
    logger.info("Initializing MT5 connector...")
    connector = MT5Connector(config.mt5)
    
    if not connector.connect():
        logger.error("Failed to connect to MT5. Please ensure MT5 is running.")
        return
    
    try:
        # Create data exporter
        output_dir = project_root / "data" / "backtest"
        exporter = MT5DataExporter(connector, output_dir=str(output_dir))
        
        # Export parameters
        symbol = "EURUSD"
        
        # Export 1 day of recent tick data for testing
        # This should give us enough data to test all three strategies
        end_date = datetime.now()
        start_date = end_date - timedelta(days=1)
        
        logger.info(f"\nExporting tick data for {symbol}")
        logger.info(f"Period: {start_date.strftime('%Y-%m-%d %H:%M')} to {end_date.strftime('%Y-%m-%d %H:%M')}")
        logger.info(f"Output directory: {output_dir}")
        
        # Export tick data
        tick_file = exporter.export_tick_data(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        if tick_file:
            logger.info(f"\n✓ Tick data exported successfully: {tick_file}")
            
            # Validate the exported data
            logger.info("\nValidating exported data...")
            is_valid = exporter.validate_data(tick_file)
            
            if is_valid:
                logger.info("✓ Data validation passed!")
            else:
                logger.warning("⚠ Data validation found issues")
        else:
            logger.error("✗ Failed to export tick data")
        
        # Also export some OHLCV data for reference (optional)
        logger.info(f"\nExporting M1 OHLCV data for {symbol}...")
        ohlcv_file = exporter.export_ohlcv_data(
            symbol=symbol,
            timeframe="M1",
            start_date=start_date,
            end_date=end_date
        )
        
        if ohlcv_file:
            logger.info(f"✓ OHLCV data exported successfully: {ohlcv_file}")
        
        logger.info("\n" + "=" * 80)
        logger.info("Export Complete!")
        logger.info("=" * 80)
        logger.info(f"\nExported files are in: {output_dir}")
        logger.info("\nYou can now run backtests using:")
        logger.info("  python examples/run_backtest_example.py")
        
    except Exception as e:
        logger.error(f"Error during export: {e}", exc_info=True)
    
    finally:
        # Disconnect from MT5
        connector.disconnect()
        logger.info("\nMT5 disconnected")


if __name__ == "__main__":
    main()

