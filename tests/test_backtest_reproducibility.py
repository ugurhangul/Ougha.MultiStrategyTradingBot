"""
Test Backtest Reproducibility

This script runs the same backtest multiple times and verifies that results
are identical across all runs. This validates that:
1. No race conditions exist in the threading architecture
2. Random number generation is deterministic (if used)
3. Time synchronization is working correctly

Usage:
    python test_backtest_reproducibility.py

Expected Result:
    All runs should produce IDENTICAL results:
    - Same final balance (to the cent)
    - Same number of trades
    - Same trade tickets, times, and profits
    - Same equity curve
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict

# Ensure project root is in path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.backtesting.engine import (
    SimulatedBroker,
    TimeController,
    TimeMode,
    BacktestController,
    BacktestDataLoader,
)
from src.execution.order_manager import OrderManager
from src.risk.risk_manager import RiskManager
from src.execution.trade_manager import TradeManager
from src.indicators.technical_indicators import TechnicalIndicators
from src.config import config
from src.utils.logger import get_logger, init_logger


def run_single_backtest(run_number: int) -> Dict:
    """
    Run a single backtest and return results.
    
    Args:
        run_number: Run identifier (1, 2, 3, etc.)
        
    Returns:
        Dictionary with backtest results
    """
    print(f"\n{'='*80}")
    print(f"RUN #{run_number}")
    print(f"{'='*80}\n")
    
    # Configuration (short test for speed)
    symbols = ["EURUSD"]
    timeframes = ["M1", "M5", "M15", "H4"]
    start_date = datetime(2025, 11, 10, tzinfo=timezone.utc)
    end_date = datetime(2025, 11, 12, tzinfo=timezone.utc)  # 2 days
    initial_balance = 10000.0
    
    # Load data
    data_loader = BacktestDataLoader(use_cache=True, cache_dir="../data")
    symbol_data = {}
    symbol_info = {}
    
    data_load_start = start_date - timedelta(days=1)
    
    for symbol in symbols:
        for timeframe in timeframes:
            result = data_loader.load_from_mt5(symbol, timeframe, data_load_start, end_date)
            if result is None:
                print(f"ERROR: Failed to load {symbol} {timeframe}")
                return None
            
            df, info = result
            symbol_data[(symbol, timeframe)] = df
            if symbol not in symbol_info:
                symbol_info[symbol] = info
    
    # Initialize position persistence
    from src.execution.position_persistence import PositionPersistence
    backtest_data_dir = Path("../data/backtest")
    backtest_data_dir.mkdir(parents=True, exist_ok=True)
    persistence = PositionPersistence(data_dir=str(backtest_data_dir))
    persistence.clear_all()
    
    # Initialize broker
    broker = SimulatedBroker(
        initial_balance=initial_balance,
        persistence=persistence,
        enable_slippage=True,
        slippage_points=0.5
    )
    
    # Load data into broker
    for (symbol, timeframe), df in symbol_data.items():
        broker.load_symbol_data(symbol, df, symbol_info[symbol], timeframe)
    
    broker.set_start_time(start_date)
    
    # Initialize time controller
    time_controller = TimeController(symbols, mode=TimeMode.MAX_SPEED, include_position_monitor=True, broker=broker)
    
    # Initialize trading components
    risk_manager = RiskManager(connector=broker, risk_config=config.risk, persistence=persistence)
    order_manager = OrderManager(
        connector=broker,
        magic_number=config.advanced.magic_number,
        trade_comment=config.advanced.trade_comment,
        persistence=persistence,
        risk_manager=risk_manager
    )
    indicators = TechnicalIndicators()
    trade_manager = TradeManager(
        connector=broker,
        order_manager=order_manager,
        trailing_config=config.trailing_stop,
        use_breakeven=config.advanced.use_breakeven,
        breakeven_trigger_rr=config.advanced.breakeven_trigger_rr,
        indicators=indicators,
        range_configs=config.range_config.ranges
    )
    
    # Initialize backtest controller
    backtest_controller = BacktestController(
        simulated_broker=broker,
        time_controller=time_controller,
        order_manager=order_manager,
        risk_manager=risk_manager,
        trade_manager=trade_manager,
        indicators=indicators
    )
    
    if not backtest_controller.initialize(symbols):
        print("ERROR: Failed to initialize BacktestController")
        return None
    
    # Run backtest
    backtest_controller.run(backtest_start_time=start_date)
    
    # Get results
    results = backtest_controller.get_results()
    trades = broker.get_closed_trades()

    # Extract key metrics for comparison
    return {
        'run_number': run_number,
        'final_balance': results['final_balance'],
        'final_equity': results['final_equity'],
        'total_profit': results['total_profit'],
        'trade_count': len(trades),
        'trades': [
            {
                'ticket': t['ticket'],
                'symbol': t['symbol'],
                'type': t['type'],
                'volume': t['volume'],
                'open_price': t['open_price'],
                'close_price': t['close_price'],
                'profit': t['profit'],
                'open_time': t['open_time'].isoformat() if isinstance(t['open_time'], datetime) else str(t['open_time']),
                'close_time': t['close_time'].isoformat() if isinstance(t['close_time'], datetime) else str(t['close_time']),
            }
            for t in trades
        ]
    }


def compare_results(results_list: List[Dict]) -> bool:
    """
    Compare results from multiple runs.

    Args:
        results_list: List of result dictionaries from each run

    Returns:
        True if all results are identical, False otherwise
    """
    if len(results_list) < 2:
        print("ERROR: Need at least 2 runs to compare")
        return False

    print(f"\n{'='*80}")
    print("REPRODUCIBILITY TEST RESULTS")
    print(f"{'='*80}\n")

    # Compare each run with the first run
    baseline = results_list[0]
    all_identical = True

    for i, result in enumerate(results_list[1:], start=2):
        print(f"Comparing Run #{i} with Run #1:")

        # Compare final balance
        if abs(result['final_balance'] - baseline['final_balance']) > 0.01:
            print(f"  ❌ Final Balance MISMATCH: ${result['final_balance']:.2f} vs ${baseline['final_balance']:.2f}")
            all_identical = False
        else:
            print(f"  ✓ Final Balance: ${result['final_balance']:.2f}")

        # Compare trade count
        if result['trade_count'] != baseline['trade_count']:
            print(f"  ❌ Trade Count MISMATCH: {result['trade_count']} vs {baseline['trade_count']}")
            all_identical = False
        else:
            print(f"  ✓ Trade Count: {result['trade_count']}")

        # Compare total profit
        if abs(result['total_profit'] - baseline['total_profit']) > 0.01:
            print(f"  ❌ Total Profit MISMATCH: ${result['total_profit']:.2f} vs ${baseline['total_profit']:.2f}")
            all_identical = False
        else:
            print(f"  ✓ Total Profit: ${result['total_profit']:.2f}")

        # Compare individual trades
        if len(result['trades']) == len(baseline['trades']):
            trades_match = True
            for j, (trade, baseline_trade) in enumerate(zip(result['trades'], baseline['trades'])):
                if (trade['ticket'] != baseline_trade['ticket'] or
                    abs(trade['profit'] - baseline_trade['profit']) > 0.01 or
                    trade['open_time'] != baseline_trade['open_time']):
                    print(f"  ❌ Trade #{j+1} MISMATCH")
                    trades_match = False
                    all_identical = False
                    break

            if trades_match:
                print(f"  ✓ All {len(result['trades'])} trades match")

        print()

    print(f"{'='*80}")
    if all_identical:
        print("✅ SUCCESS: All runs produced IDENTICAL results!")
        print("   Backtest is REPRODUCIBLE - no race conditions detected")
    else:
        print("❌ FAILURE: Results differ between runs!")
        print("   Possible causes:")
        print("   - Race conditions in threading")
        print("   - Non-deterministic random number generation")
        print("   - Time synchronization issues")
    print(f"{'='*80}\n")

    return all_identical


def main():
    """Run reproducibility test."""
    # Initialize logger (minimal logging for speed)
    init_logger(log_to_file=False, log_to_console=False, log_level="WARNING")

    print("="*80)
    print("BACKTEST REPRODUCIBILITY TEST")
    print("="*80)
    print("\nThis test runs the same backtest 3 times and verifies identical results.")
    print("Expected duration: 1-2 minutes per run\n")

    # Run backtest 3 times
    num_runs = 3
    results_list = []

    for i in range(1, num_runs + 1):
        result = run_single_backtest(i)
        if result is None:
            print(f"ERROR: Run #{i} failed")
            return False
        results_list.append(result)

        # Save results to file for debugging
        output_file = f"reproducibility_run_{i}.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Results saved to {output_file}")

    # Compare results
    success = compare_results(results_list)

    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)


