"""
Test script for broker archive downloader functionality.

Tests the multi-tier fallback mechanism:
- Tier 1: Use existing cache
- Tier 2: Fetch missing data from MT5
- Tier 3: Download from broker archives (NEW)
- Tier 4: Use partial cached data with warnings
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
import MetaTrader5 as mt5

# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.backtesting.engine.data_loader import BacktestDataLoader
from src.utils.logging import init_logger, get_logger
from src.config import config


def main():
    """Test broker archive downloader."""
    # Initialize logger
    init_logger(log_to_file=False, log_to_console=True, log_level="INFO")
    logger = get_logger()
    
    logger.info("=" * 80)
    logger.info("BROKER ARCHIVE DOWNLOADER TEST")
    logger.info("=" * 80)
    logger.info("")
    
    # Display configuration
    logger.info("Configuration:")
    logger.info(f"  Archive downloads enabled: {config.tick_archive.enabled}")
    logger.info(f"  Archive URL pattern: {config.tick_archive.archive_url_pattern}")
    logger.info(f"  Trusted sources: {config.tick_archive.trusted_sources}")
    logger.info(f"  Download timeout: {config.tick_archive.download_timeout_seconds}s")
    logger.info(f"  Max retries: {config.tick_archive.max_retries}")
    logger.info(f"  Archive cache dir: {config.tick_archive.archive_cache_dir}")
    logger.info("")
    
    if not config.tick_archive.enabled:
        logger.warning("⚠️  Archive downloads are DISABLED in configuration")
        logger.warning("   To enable, set TICK_ARCHIVE_ENABLED=true in .env file")
        logger.warning("")
        logger.info("This test will still demonstrate the fallback mechanism,")
        logger.info("but Tier 3 (archive download) will be skipped.")
        logger.info("")
    
    # Test configuration
    symbol = "EURUSD"
    
    # Request data from a period where MT5 likely doesn't have data
    # (e.g., January 2025 when MT5 only has data from June 2025)
    requested_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    requested_end = datetime(2025, 6, 30, tzinfo=timezone.utc)
    
    cache_dir = "data/ticks_test_archive"
    
    logger.info(f"Test Parameters:")
    logger.info(f"  Symbol: {symbol}")
    logger.info(f"  Requested date range: {requested_start.date()} to {requested_end.date()}")
    logger.info(f"  Cache directory: {cache_dir}")
    logger.info("")
    
    # Initialize data loader
    data_loader = BacktestDataLoader(use_cache=False)
    
    # Test: Load tick data with multi-tier fallback
    logger.info("=" * 80)
    logger.info("TESTING MULTI-TIER FALLBACK MECHANISM")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Expected behavior:")
    logger.info("  Tier 1: Check cache (should be empty for first run)")
    logger.info("  Tier 2: Try to fetch from MT5 (likely fails for Jan-May 2025)")
    logger.info("  Tier 3: Try to download from broker archive (if enabled)")
    logger.info("  Tier 4: Use partial data or fail gracefully")
    logger.info("")
    
    ticks_df = data_loader.load_ticks_from_mt5(
        symbol=symbol,
        start_date=requested_start,
        end_date=requested_end,
        tick_type=mt5.COPY_TICKS_INFO,
        cache_dir=cache_dir
    )
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST RESULTS")
    logger.info("=" * 80)
    logger.info("")
    
    if ticks_df is None or len(ticks_df) == 0:
        logger.error("❌ Failed to load tick data")
        logger.error("   All tiers of the fallback mechanism failed")
        return False
    
    actual_start = ticks_df['time'].iloc[0]
    actual_end = ticks_df['time'].iloc[-1]
    
    logger.info(f"✓ Successfully loaded {len(ticks_df):,} ticks")
    logger.info(f"  Actual date range: {actual_start.date()} to {actual_end.date()}")
    logger.info("")
    
    # Check if we got data from the requested start date
    gap_days = (actual_start.to_pydatetime() - requested_start).total_seconds() / 86400
    
    if gap_days > 1:
        logger.warning(f"⚠️  Data starts {gap_days:.1f} days after requested start")
        logger.warning(f"   Requested: {requested_start.date()}")
        logger.warning(f"   Actual:    {actual_start.date()}")
        logger.warning("")
        
        if config.tick_archive.enabled:
            logger.warning("   Archive downloads are enabled but may not have data for this period")
            logger.warning("   Check the archive URL pattern and broker mapping in configuration")
        else:
            logger.warning("   Archive downloads are disabled - enable them to potentially get earlier data")
    else:
        logger.info("✓ Data covers the full requested date range!")
        logger.info("  Archive download may have successfully filled the gap")
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("Test completed successfully!")
    logger.info("=" * 80)
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

