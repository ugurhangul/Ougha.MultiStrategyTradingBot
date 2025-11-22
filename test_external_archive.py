"""
Test script for external tick data archive integration.

This script tests the fallback mechanism:
1. MT5 data (if available)
2. Day-based archive
3. Month-based archive
4. Year-based archive

Usage:
    python test_external_archive.py
"""

from datetime import datetime, timezone
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.backtesting.engine import BacktestDataLoader
from src.config import config
from src.utils.logger import get_logger, init_logger
import MetaTrader5 as mt5

def test_archive_integration():
    """Test the external archive integration."""
    
    # Initialize logging
    init_logger(log_to_console=True, log_level="INFO")
    logger = get_logger()
    
    logger.info("=" * 80)
    logger.info("EXTERNAL TICK DATA ARCHIVE INTEGRATION TEST")
    logger.info("=" * 80)
    logger.info("")
    
    # Check configuration
    logger.info("Configuration:")
    logger.info(f"  Archive enabled: {config.tick_archive.enabled}")
    logger.info(f"  Use granular downloads: {config.tick_archive.use_granular_downloads}")
    logger.info(f"  Archive cache dir: {config.tick_archive.archive_cache_dir}")
    logger.info("")
    
    if not config.tick_archive.enabled:
        logger.error("External archive is DISABLED!")
        logger.error("Set TICK_ARCHIVE_ENABLED=true in .env to enable")
        return False
    
    # Initialize data loader
    logger.info("Initializing data loader...")
    loader = BacktestDataLoader(
        use_cache=True,
        cache_dir="data/cache",
        cache_ttl_days=7
    )
    logger.info("✓ Data loader initialized")
    logger.info("")
    
    # Test with a date that MT5 likely doesn't have (6 months ago)
    from datetime import timedelta
    test_date = datetime.now(timezone.utc) - timedelta(days=180)
    test_date = test_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Test symbol
    test_symbol = "XAUUSD"
    
    logger.info("Test Parameters:")
    logger.info(f"  Symbol: {test_symbol}")
    logger.info(f"  Date: {test_date.date()}")
    logger.info(f"  Tick type: COPY_TICKS_INFO")
    logger.info("")
    
    # Try to load tick data
    logger.info("=" * 80)
    logger.info("LOADING TICK DATA (will test fallback mechanism)")
    logger.info("=" * 80)
    logger.info("")
    
    try:
        start_time = datetime.now()
        
        ticks_df = loader.load_ticks_from_mt5(
            symbol=test_symbol,
            start_date=test_date,
            end_date=test_date + timedelta(days=1),
            tick_type=mt5.COPY_TICKS_INFO,
            cache_dir="data/cache",
            progress_callback=None,
            parallel_days=1
        )
        
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("RESULTS")
        logger.info("=" * 80)
        
        if ticks_df is not None and len(ticks_df) > 0:
            logger.info(f"✓ Successfully loaded {len(ticks_df):,} ticks")
            logger.info(f"  Time range: {ticks_df['time'].min()} to {ticks_df['time'].max()}")
            logger.info(f"  Load time: {elapsed:.2f} seconds")
            logger.info("")
            
            # Show sample data
            logger.info("Sample data (first 5 ticks):")
            logger.info(ticks_df.head().to_string())
            logger.info("")
            
            # Check cache
            cache_path = Path("data/cache") / str(test_date.year) / f"{test_date.month:02d}" / f"{test_date.day:02d}" / "ticks" / f"{test_symbol}_INFO.parquet"
            if cache_path.exists():
                logger.info(f"✓ Data cached at: {cache_path}")
                logger.info(f"  Cache size: {cache_path.stat().st_size / 1024 / 1024:.2f} MB")
            
            logger.info("")
            logger.info("=" * 80)
            logger.info("TEST PASSED ✓")
            logger.info("=" * 80)
            return True
        else:
            logger.warning("⚠ No tick data loaded")
            logger.warning("Possible reasons:")
            logger.warning("  1. MT5 doesn't have data for this date")
            logger.warning("  2. Archive doesn't have data for this symbol/broker/date")
            logger.warning("  3. Broker name mapping is missing")
            logger.warning("  4. Network/download issues")
            logger.info("")
            logger.info("=" * 80)
            logger.info("TEST FAILED ✗")
            logger.info("=" * 80)
            return False
            
    except Exception as e:
        logger.error(f"Error during test: {e}")
        import traceback
        logger.error(traceback.format_exc())
        logger.info("")
        logger.info("=" * 80)
        logger.info("TEST FAILED ✗")
        logger.info("=" * 80)
        return False

def test_url_construction():
    """Test URL construction for different granularities."""
    
    init_logger(log_to_console=True, log_level="INFO")
    logger = get_logger()
    
    logger.info("=" * 80)
    logger.info("URL CONSTRUCTION TEST")
    logger.info("=" * 80)
    logger.info("")
    
    from src.backtesting.engine.broker_archive_downloader import BrokerArchiveDownloader
    
    downloader = BrokerArchiveDownloader(config.tick_archive)
    
    symbol = "XAUUSD"
    broker = "Exness"
    year = 2025
    month = 11
    day = 21
    
    # Test year-based URL
    url_year = downloader.construct_archive_url(symbol, year, broker)
    logger.info(f"Year-based URL:")
    logger.info(f"  {url_year}")
    logger.info("")
    
    # Test month-based URL
    url_month = downloader.construct_archive_url(symbol, year, broker, month)
    logger.info(f"Month-based URL:")
    logger.info(f"  {url_month}")
    logger.info("")
    
    # Test day-based URL
    url_day = downloader.construct_archive_url(symbol, year, broker, month, day)
    logger.info(f"Day-based URL:")
    logger.info(f"  {url_day}")
    logger.info("")
    
    # Verify format
    expected_year = "https://ticks.ex2archive.com/ticks/XAUUSD/2025/Exness_XAUUSD_2025.zip"
    expected_month = "https://ticks.ex2archive.com/ticks/XAUUSD/2025/11/Exness_XAUUSD_2025_11.zip"
    expected_day = "https://ticks.ex2archive.com/ticks/XAUUSD/2025/11/21/Exness_XAUUSD_2025_11_21.zip"
    
    logger.info("Verification:")
    logger.info(f"  Year URL matches: {url_year == expected_year}")
    logger.info(f"  Month URL matches: {url_month == expected_month}")
    logger.info(f"  Day URL matches: {url_day == expected_day}")
    logger.info("")
    
    if url_year == expected_year and url_month == expected_month and url_day == expected_day:
        logger.info("=" * 80)
        logger.info("URL CONSTRUCTION TEST PASSED ✓")
        logger.info("=" * 80)
        return True
    else:
        logger.error("=" * 80)
        logger.error("URL CONSTRUCTION TEST FAILED ✗")
        logger.error("=" * 80)
        return False

if __name__ == "__main__":
    print("\n")
    print("=" * 80)
    print("EXTERNAL TICK DATA ARCHIVE - INTEGRATION TEST SUITE")
    print("=" * 80)
    print("\n")
    
    # Test 1: URL Construction
    print("TEST 1: URL Construction")
    print("-" * 80)
    test1_passed = test_url_construction()
    print("\n")
    
    # Test 2: Archive Integration
    print("TEST 2: Archive Integration (Live Test)")
    print("-" * 80)
    print("NOTE: This test will attempt to download data from ex2archive.com")
    print("      It may take 30-60 seconds depending on network speed.")
    print("")
    
    response = input("Do you want to run the live integration test? (y/n): ")
    if response.lower() == 'y':
        test2_passed = test_archive_integration()
    else:
        print("Skipping live integration test.")
        test2_passed = None
    
    print("\n")
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"  URL Construction: {'✓ PASSED' if test1_passed else '✗ FAILED'}")
    if test2_passed is not None:
        print(f"  Archive Integration: {'✓ PASSED' if test2_passed else '✗ FAILED'}")
    else:
        print(f"  Archive Integration: SKIPPED")
    print("=" * 80)
    print("\n")

