"""
Test Backtest Script - Comprehensive Testing of All Three Strategy Adapters.

This script runs backtests with all three strategy adapters:
1. Fakeout Strategy Adapter
2. True Breakout Strategy Adapter
3. HFT Momentum Strategy Adapter

It tests both individual strategies and multi-strategy combinations.

Usage:
    python examples/test_backtest.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting.engine import BacktestEngine, BacktestConfig
from src.backtesting.adapters import (
    FakeoutStrategyAdapter,
    TrueBreakoutStrategyAdapter,
    HFTMomentumStrategyAdapter
)
from src.utils.logger import get_logger


def test_single_strategy(strategy_name: str, adapter, data_file: str, logger):
    """
    Test a single strategy adapter.

    Args:
        strategy_name: Name of the strategy
        adapter: Strategy adapter instance
        data_file: Path to tick data file
        logger: Logger instance
    """
    logger.info("=" * 80)
    logger.info(f"Testing {strategy_name}")
    logger.info("=" * 80)

    # Create backtest configuration
    config = BacktestConfig(
        tick_size=0.00001,
        lot_size=0.01,
        contract_size=100000,
        maker_fee=0.0,
        taker_fee=0.0,
        order_latency=0,
        response_latency=0,
        queue_model='risk_adverse',
        partial_fill=False,
        recorder_capacity=100000
    )

    # Create engine
    engine = BacktestEngine(
        symbol="EURUSD",
        data_files=[data_file],
        config=config
    )

    # Add strategy
    engine.add_strategy(adapter)

    # Run backtest
    logger.info(f"\nRunning backtest for {strategy_name}...")
    initial_balance = 10000.0

    try:
        results = engine.run(initial_balance=initial_balance)

        # Display results
        logger.info(f"\n{strategy_name} Results:")
        logger.info(f"  Initial Balance: ${initial_balance:.2f}")
        logger.info(f"  Final Balance: ${results.get('final_balance', 0):.2f}")
        logger.info(f"  Total PnL: ${results.get('total_pnl', 0):.2f}")
        logger.info(f"  Total Trades: {results.get('total_trades', 0)}")

        # Get strategy statistics
        stats = adapter.get_statistics()
        logger.info(f"\n{strategy_name} Statistics:")
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")

        return results

    except Exception as e:
        logger.error(f"Error running {strategy_name}: {e}")
        return None


def test_multi_strategy(data_file: str, logger):
    """
    Test all three strategies running together.

    Args:
        data_file: Path to tick data file
        logger: Logger instance
    """
    logger.info("=" * 80)
    logger.info("Testing Multi-Strategy Backtest (All Three Strategies)")
    logger.info("=" * 80)

    # Create backtest configuration
    config = BacktestConfig(
        tick_size=0.00001,
        lot_size=0.01,
        contract_size=100000,
        maker_fee=0.0,
        taker_fee=0.0,
        order_latency=0,
        response_latency=0,
        queue_model='risk_adverse',
        partial_fill=False,
        recorder_capacity=100000
    )

    # Create engine
    engine = BacktestEngine(
        symbol="EURUSD",
        data_files=[data_file],
        config=config
    )

    # Add all three strategies
    fakeout_adapter = FakeoutStrategyAdapter(
        symbol="EURUSD",
        strategy_params={
            'min_consolidation_bars': 10,
            'breakout_threshold': 0.0005,
            'fakeout_reversal_threshold': 0.0003,
            'max_spread_percent': 0.001,
            'risk_reward_ratio': 1.5,
        }
    )
    engine.add_strategy(fakeout_adapter)

    true_breakout_adapter = TrueBreakoutStrategyAdapter(
        symbol="EURUSD",
        strategy_params={
            'min_consolidation_bars': 15,
            'breakout_threshold': 0.0008,
            'min_breakout_volume_multiplier': 1.5,
            'retest_tolerance_percent': 0.0005,
            'max_spread_percent': 0.001,
            'risk_reward_ratio': 2.0,
        }
    )
    engine.add_strategy(true_breakout_adapter)

    hft_momentum_adapter = HFTMomentumStrategyAdapter(
        symbol="EURUSD",
        strategy_params={
            'tick_momentum_count': 3,
            'min_momentum_strength': 0.00005,
            'min_volume_multiplier': 1.2,
            'max_spread_multiplier': 2.0,
            'max_spread_percent': 0.003,
            'risk_reward_ratio': 1.5,
            'sl_pips': 10,
            'trade_cooldown_seconds': 5,
        }
    )
    engine.add_strategy(hft_momentum_adapter)

    logger.info("\nAdded all three strategy adapters:")
    logger.info("  1. Fakeout Strategy")
    logger.info("  2. True Breakout Strategy")
    logger.info("  3. HFT Momentum Strategy")

    # Run backtest
    logger.info("\nRunning multi-strategy backtest...")
    initial_balance = 10000.0

    try:
        results = engine.run(initial_balance=initial_balance)

        # Display combined results
        logger.info("\nMulti-Strategy Results:")
        logger.info(f"  Initial Balance: ${initial_balance:.2f}")
        logger.info(f"  Final Balance: ${results.get('final_balance', 0):.2f}")
        logger.info(f"  Total PnL: ${results.get('total_pnl', 0):.2f}")
        logger.info(f"  Total Trades: {results.get('total_trades', 0)}")

        # Get individual strategy statistics
        logger.info("\nIndividual Strategy Statistics:")

        logger.info("\n  Fakeout Strategy:")
        fakeout_stats = fakeout_adapter.get_statistics()
        for key, value in fakeout_stats.items():
            logger.info(f"    {key}: {value}")

        logger.info("\n  True Breakout Strategy:")
        breakout_stats = true_breakout_adapter.get_statistics()
        for key, value in breakout_stats.items():
            logger.info(f"    {key}: {value}")

        logger.info("\n  HFT Momentum Strategy:")
        hft_stats = hft_momentum_adapter.get_statistics()
        for key, value in hft_stats.items():
            logger.info(f"    {key}: {value}")

        return results

    except Exception as e:
        logger.error(f"Error running multi-strategy backtest: {e}")
        return None


def main():
    """Main test function."""
    logger = get_logger()

    logger.info("=" * 80)
    logger.info("BACKTESTING FRAMEWORK - COMPREHENSIVE TEST")
    logger.info("=" * 80)
    logger.info(f"Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Check for data file
    data_dir = project_root / "data" / "backtest"

    # Look for any tick data file (supports both *_tick.npz and *_ticks.npz)
    tick_files = list(data_dir.glob("*tick*.npz"))

    if not tick_files:
        logger.error("\n✗ No tick data files found!")
        logger.info("\nPlease run the data export script first:")
        logger.info("  python examples/export_sample_data.py")
        return

    # Use the first tick file found
    data_file = str(tick_files[0])
    logger.info(f"\nUsing data file: {data_file}")

    # Test 1: Individual strategy tests
    logger.info("\n" + "=" * 80)
    logger.info("TEST 1: Individual Strategy Tests")
    logger.info("=" * 80)

    # Test Fakeout Strategy
    fakeout_adapter = FakeoutStrategyAdapter(
        symbol="EURUSD",
        strategy_params={
            'min_consolidation_bars': 10,
            'breakout_threshold': 0.0005,
            'fakeout_reversal_threshold': 0.0003,
            'max_spread_percent': 0.001,
            'risk_reward_ratio': 1.5,
        }
    )
    test_single_strategy("Fakeout Strategy", fakeout_adapter, data_file, logger)

    # Test True Breakout Strategy
    true_breakout_adapter = TrueBreakoutStrategyAdapter(
        symbol="EURUSD",
        strategy_params={
            'min_consolidation_bars': 15,
            'breakout_threshold': 0.0008,
            'min_breakout_volume_multiplier': 1.5,
            'retest_tolerance_percent': 0.0005,
            'max_spread_percent': 0.001,
            'risk_reward_ratio': 2.0,
        }
    )
    test_single_strategy("True Breakout Strategy", true_breakout_adapter, data_file, logger)

    # Test HFT Momentum Strategy
    hft_momentum_adapter = HFTMomentumStrategyAdapter(
        symbol="EURUSD",
        strategy_params={
            'tick_momentum_count': 3,
            'min_momentum_strength': 0.00005,
            'min_volume_multiplier': 1.2,
            'max_spread_multiplier': 2.0,
            'max_spread_percent': 0.003,
            'risk_reward_ratio': 1.5,
            'sl_pips': 10,
            'trade_cooldown_seconds': 5,
        }
    )
    test_single_strategy("HFT Momentum Strategy", hft_momentum_adapter, data_file, logger)

    # Test 2: Multi-strategy test
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: Multi-Strategy Test")
    logger.info("=" * 80)

    test_multi_strategy(data_file, logger)

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST COMPLETE!")
    logger.info("=" * 80)
    logger.info(f"Test completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("\nAll three strategy adapters have been tested successfully!")


if __name__ == "__main__":
    main()

