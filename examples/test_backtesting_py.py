"""
Test script for backtesting.py integration.

This script demonstrates how to use the new backtesting.py setup.
"""
import sys
from pathlib import Path
from datetime import datetime
from backtesting import Backtest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting.data.backtesting_py_data_loader import BacktestingPyDataLoader
from src.backtesting.adapters.backtesting_py_strategy_adapter import FakeoutStrategyAdapter
from src.utils.logger import init_logger


def main():
    """Run a simple backtest."""
    logger = init_logger()
    
    print("="*60)
    print("BACKTESTING.PY TEST")
    print("="*60)
    
    # Configuration
    SYMBOL = 'EURUSD'
    TIMEFRAME = 'M5'
    START_DATE = datetime(2024, 11, 1)
    END_DATE = datetime(2024, 11, 15)
    INITIAL_CASH = 10000
    
    print(f"\nConfiguration:")
    print(f"  Symbol: {SYMBOL}")
    print(f"  Timeframe: {TIMEFRAME}")
    print(f"  Period: {START_DATE.date()} to {END_DATE.date()}")
    print(f"  Initial Cash: ${INITIAL_CASH:,.2f}")
    
    # Step 1: Load data
    print(f"\n[1/3] Loading data from MT5...")
    loader = BacktestingPyDataLoader()
    data = loader.load_from_mt5(
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        start_date=START_DATE,
        end_date=END_DATE
    )
    
    if data is None:
        print("✗ Failed to load data")
        return False
    
    print(f"✓ Loaded {len(data)} candles")
    print(f"\nData preview:")
    print(data.head())
    
    # Step 2: Create backtest
    print(f"\n[2/3] Creating backtest instance...")
    bt = Backtest(
        data,
        FakeoutStrategyAdapter,
        cash=INITIAL_CASH,
        commission=0.0,  # No commission for forex
        exclusive_orders=True
    )
    print("✓ Backtest instance created")
    
    # Step 3: Run backtest
    print(f"\n[3/3] Running backtest...")
    stats = bt.run()
    
    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    print(stats)
    
    # Key metrics
    print("\n" + "="*60)
    print("KEY METRICS")
    print("="*60)
    print(f"Return: {stats['Return [%]']:.2f}%")
    print(f"Sharpe Ratio: {stats['Sharpe Ratio']:.2f}")
    print(f"Max Drawdown: {stats['Max. Drawdown [%]']:.2f}%")
    print(f"Win Rate: {stats['Win Rate [%]']:.2f}%")
    print(f"Total Trades: {stats['# Trades']}")
    
    # Save results
    print(f"\n[Optional] To view interactive chart, run:")
    print(f"  bt.plot()")
    
    return True


if __name__ == "__main__":
    success = main()
    if success:
        print("\n✓ Test completed successfully!")
    else:
        print("\n✗ Test failed!")

