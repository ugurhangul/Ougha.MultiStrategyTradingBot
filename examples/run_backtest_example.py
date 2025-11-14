"""
Example: Running a backtest with the BacktestEngine.

This example demonstrates:
1. Creating a backtest configuration
2. Setting up the backtest engine
3. Adding strategy adapters
4. Running the backtest
5. Analyzing results

Prerequisites:
- Historical data exported using MT5DataExporter
- Strategy adapters implemented (will be created in Phase 3)
"""

import sys
from pathlib import Path

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


def main():
    """Run a simple backtest example."""
    logger = get_logger()
    
    # ========================================
    # 1. Configure Backtest
    # ========================================
    config = BacktestConfig(
        # Asset configuration
        tick_size=0.00001,           # 5 decimal places for EUR/USD
        lot_size=0.01,               # Minimum 0.01 lots
        contract_size=100000.0,      # Standard lot = 100,000 units
        
        # Latency configuration (in nanoseconds)
        order_latency=100_000_000,   # 100ms order entry latency
        response_latency=100_000_000, # 100ms response latency
        
        # Fee configuration
        maker_fee=0.0,               # No maker fee for forex
        taker_fee=0.0,               # No taker fee for forex
        spread_cost=0.0001,          # 1 pip spread cost
        
        # Queue model
        queue_model="risk_adverse",  # Conservative queue position model
        
        # Exchange model
        partial_fill=False,          # No partial fills
        
        # Recorder capacity
        recorder_capacity=10_000_000, # 10M records
    )
    
    logger.info("Backtest configuration created")
    
    # ========================================
    # 2. Specify Data Files
    # ========================================
    # These files should be created using MT5DataExporter
    # See examples/export_mt5_data_example.py
    
    data_dir = project_root / "data" / "backtest"
    symbol = "EURUSD"
    
    # Example: Load tick data for a specific date range
    data_files = [
        str(data_dir / f"{symbol}_20240101_tick.npz"),
        str(data_dir / f"{symbol}_20240102_tick.npz"),
        str(data_dir / f"{symbol}_20240103_tick.npz"),
    ]
    
    # Optional: Initial market snapshot (end-of-day from previous day)
    initial_snapshot = str(data_dir / f"{symbol}_20231231_eod.npz")
    
    logger.info(f"Data files: {len(data_files)}")
    
    # ========================================
    # 3. Create Backtest Engine
    # ========================================
    engine = BacktestEngine(
        symbol=symbol,
        data_files=data_files,
        config=config,
        initial_snapshot=initial_snapshot
    )
    
    logger.info("Backtest engine created")
    
    # ========================================
    # 4. Add Strategy Adapters
    # ========================================

    # Create Fakeout strategy adapter
    fakeout_adapter = FakeoutStrategyAdapter(
        symbol=symbol,
        strategy_params={
            'min_consolidation_bars': 10,
            'breakout_threshold': 0.0005,
            'max_spread_percent': 0.001,
            'risk_reward_ratio': 2.0,
        }
    )
    engine.add_strategy(fakeout_adapter)

    # Create True Breakout strategy adapter
    true_breakout_adapter = TrueBreakoutStrategyAdapter(
        symbol=symbol,
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

    # Create HFT Momentum strategy adapter
    hft_momentum_adapter = HFTMomentumStrategyAdapter(
        symbol=symbol,
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

    logger.info("Added all three strategy adapters to engine: Fakeout, TrueBreakout, HFTMomentum")
    
    # ========================================
    # 5. Run Backtest
    # ========================================
    logger.info("Starting backtest...")

    results = engine.run(
        initial_balance=10000.0,
        use_roi_vector=True  # Use faster ROIVectorMarketDepthBacktest
    )

    # ========================================
    # 6. Analyze Results
    # ========================================
    print(engine.get_summary())

    # Access detailed results
    for strategy_name, stats in results['strategies'].items():
        print(f"\n{strategy_name}:")
        print(f"  Total Trades: {stats['total_trades']}")
        print(f"  Win Rate: {stats['win_rate']:.2%}")
        print(f"  Closed Positions: {stats['closed_positions']}")

    logger.info("Backtest completed successfully!")


if __name__ == "__main__":
    main()

