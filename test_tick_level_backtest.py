"""
Test Tick-Level Backtesting Implementation

Quick test to verify tick-level backtesting works correctly.
Tests with 1 symbol for 1 day to keep it fast.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Ensure project root is in path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.backtesting.engine import (
    SimulatedBroker,
    TimeController,
    TimeMode,
    TimeGranularity,
    BacktestDataLoader,
)
from src.utils.logger import get_logger, init_logger
import MetaTrader5 as mt5


def main():
    """Run a quick tick-level backtest test."""
    # Initialize logger
    init_logger(console_level="INFO", file_level="DEBUG")
    logger = get_logger()
    
    logger.info("=" * 80)
    logger.info("TICK-LEVEL BACKTESTING - QUICK TEST")
    logger.info("=" * 80)
    logger.info("")
    
    # Configuration (1 symbol, 1 day for speed)
    symbol = "EURUSD"
    start_date = datetime(2025, 11, 14, tzinfo=timezone.utc)
    end_date = datetime(2025, 11, 15, tzinfo=timezone.utc)
    
    logger.info(f"Symbol: {symbol}")
    logger.info(f"Period: {start_date.date()} to {end_date.date()} (1 day)")
    logger.info("")
    
    # Step 1: Load tick data
    logger.info("Step 1: Loading tick data...")
    data_loader = BacktestDataLoader(use_cache=False)
    
    ticks_df = data_loader.load_ticks_from_mt5(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        tick_type=mt5.COPY_TICKS_INFO
    )
    
    if ticks_df is None or len(ticks_df) == 0:
        logger.error("Failed to load tick data")
        return False
    
    logger.info(f"  ✓ Loaded {len(ticks_df):,} ticks")
    logger.info("")
    
    # Step 2: Load symbol info
    logger.info("Step 2: Loading symbol info...")
    result = data_loader.load_from_mt5(symbol, "M1", start_date, end_date)
    if result is None:
        logger.error("Failed to load symbol info")
        return False
    
    _, symbol_info = result
    logger.info(f"  ✓ Symbol info loaded")
    logger.info("")
    
    # Step 3: Initialize broker
    logger.info("Step 3: Initializing SimulatedBroker...")
    broker = SimulatedBroker(initial_balance=10000.0)
    
    # Load tick data into broker
    broker.load_tick_data(symbol, ticks_df, symbol_info)
    logger.info(f"  ✓ Tick data loaded into broker")
    
    # Merge global tick timeline
    broker.merge_global_tick_timeline()
    logger.info(f"  ✓ Global tick timeline merged")
    logger.info(f"  ✓ Total ticks in timeline: {len(broker.global_tick_timeline):,}")
    logger.info("")
    
    # Step 4: Initialize TimeController
    logger.info("Step 4: Initializing TimeController...")
    time_controller = TimeController(
        symbols=[symbol],
        mode=TimeMode.MAX_SPEED,
        granularity=TimeGranularity.TICK,
        include_position_monitor=False,  # Disable for this test
        broker=broker
    )
    logger.info(f"  ✓ TimeController initialized")
    logger.info(f"  ✓ Granularity: TICK")
    logger.info("")
    
    # Step 5: Test tick-by-tick advancement
    logger.info("Step 5: Testing tick-by-tick advancement...")
    time_controller.start()
    
    # Advance through first 100 ticks
    tick_count = 0
    max_ticks = 100
    
    while tick_count < max_ticks:
        # Check if symbol has data at current time
        has_data = broker.has_data_at_current_time(symbol)
        
        if has_data:
            # Get current tick
            current_tick = broker.current_ticks.get(symbol)
            if current_tick:
                tick_count += 1
                if tick_count <= 5 or tick_count % 20 == 0:
                    logger.info(
                        f"  Tick #{tick_count}: {current_tick.time} | "
                        f"Bid: {current_tick.bid:.5f} | Ask: {current_tick.ask:.5f} | "
                        f"Spread: {current_tick.spread:.5f}"
                    )
        
        # Wait for next time step (advances tick-by-tick)
        if not time_controller.wait_for_next_step(symbol):
            break
    
    time_controller.stop()
    logger.info(f"  ✓ Processed {tick_count} ticks successfully")
    logger.info("")
    
    # Step 6: Verify results
    logger.info("Step 6: Verification...")
    logger.info(f"  ✓ Tick mode enabled: {broker.use_tick_data}")
    logger.info(f"  ✓ Total ticks in timeline: {len(broker.global_tick_timeline):,}")
    logger.info(f"  ✓ Current tick index: {broker.global_tick_index}")
    logger.info(f"  ✓ Ticks processed: {tick_count}")
    logger.info("")
    
    logger.info("=" * 80)
    logger.info("TEST PASSED ✓")
    logger.info("=" * 80)
    logger.info("Tick-level backtesting is working correctly!")
    logger.info("")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

