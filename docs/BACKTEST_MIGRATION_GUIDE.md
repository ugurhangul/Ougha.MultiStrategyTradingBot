# Backtest System Migration Guide

## What Changed?

The old backtesting system (based on the third-party `backtesting.py` library) has been **removed** and replaced with our **custom backtest engine**.

### Old System (Removed)
- ❌ `backtest.py` - Main runner using backtesting.py library
- ❌ `src/backtesting/adapters/` - GenericStrategyAdapter and wrappers
- ❌ `src/backtesting/data/` - BacktestingPyDataLoader
- ❌ `src/backtesting/portfolio_analyzer.py`
- ❌ `src/backtesting/position_limit_validator.py`
- ❌ `examples/run_full_backtest.py`
- ❌ `examples/test_backtesting_py.py`
- ❌ `examples/test_generic_adapter.py`
- ❌ All Jupyter notebooks (backtest_all_strategies.ipynb, etc.)

### New System (Active)
- ✅ `src/backtesting/engine/` - Custom backtest engine
- ✅ `examples/test_custom_backtest_engine.py` - Main example
- ✅ `docs/CUSTOM_BACKTEST_ENGINE.md` - Documentation

## Why the Change?

The custom backtest engine provides:

1. **Architectural Fidelity**: Runs the exact same code as live trading
2. **Concurrent Execution**: Simulates how strategies compete for positions
3. **Position Limits**: Accurately models global and per-symbol limits
4. **Risk Management**: Tests the actual risk management logic
5. **No Code Duplication**: Strategies work unchanged in both live and backtest
6. **Realistic Results**: Closely matches live trading behavior

The old system required:
- Strategy adapters (code duplication)
- Separate backtest logic
- Independent backtests (no concurrent simulation)
- Manual portfolio aggregation

## How to Migrate

### Before (Old System)
```python
from backtesting import Backtest
from src.backtesting.data import BacktestingPyDataLoader
from src.backtesting.adapters import GenericStrategyAdapter
from src.strategy import TrueBreakoutStrategy

# Load data
loader = BacktestingPyDataLoader()
data = loader.load_from_mt5(symbol='EURUSD', timeframe='M1', ...)

# Wrap strategy
WrappedStrategy = GenericStrategyAdapter.wrap(
    strategy_class=TrueBreakoutStrategy,
    symbol='EURUSD',
    timeframe='M1',
    strategy_config=config
)

# Run backtest
bt = Backtest(data, WrappedStrategy, cash=10000)
stats = bt.run()
```

### After (New System)
```python
from src.backtesting import (
    SimulatedBroker,
    TimeController,
    TimeMode,
    BacktestController,
    BacktestDataLoader
)
from src.execution.order_manager import OrderManager
from src.risk.risk_manager import RiskManager
# ... other imports

# Load data
loader = BacktestDataLoader()
broker = SimulatedBroker(initial_balance=10000.0)
for symbol in symbols:
    data, symbol_info = loader.load_symbol_data(symbol, timeframe, start_date, end_date)
    broker.load_symbol_data(symbol, data, symbol_info)

# Initialize components (same as live trading)
time_controller = TimeController(symbols, mode=TimeMode.MAX_SPEED)
order_manager = OrderManager(broker, ...)
risk_manager = RiskManager(broker, ...)
trade_manager = TradeManager(broker, ...)

# Run backtest
backtest = BacktestController(broker, time_controller, order_manager, risk_manager, trade_manager, indicators)
backtest.initialize(symbols)
backtest.run()

# Get results
results = backtest.get_results()
```

## Quick Start

1. **Use the example script:**
   ```bash
   python examples/test_custom_backtest_engine.py
   ```

2. **Read the documentation:**
   - [CUSTOM_BACKTEST_ENGINE.md](CUSTOM_BACKTEST_ENGINE.md)
   - [BACKTESTING_RESEARCH_AND_IMPLEMENTATION.md](BACKTESTING_RESEARCH_AND_IMPLEMENTATION.md)

3. **Customize for your needs:**
   - Edit `examples/test_custom_backtest_engine.py`
   - Change symbols, date range, initial balance
   - Adjust time mode (REALTIME, FAST, MAX_SPEED)

## Key Differences

| Feature | Old System | New System |
|---------|-----------|------------|
| Strategy Code | Requires adapters | Uses live code directly |
| Execution Model | Sequential, independent | Concurrent, synchronized |
| Position Limits | Manual validation | Automatic simulation |
| Risk Management | Simplified | Full live logic |
| Results | Per-strategy metrics | Portfolio-level simulation |
| Logging | Separate format | Same as live trading |
| Time Simulation | Not synchronized | Synchronized across symbols |

## Benefits

- ✅ **No more adapter code** - strategies work unchanged
- ✅ **Realistic simulation** - same code as live trading
- ✅ **Better testing** - concurrent execution, position limits
- ✅ **Easier maintenance** - single codebase for live and backtest
- ✅ **Accurate results** - closely matches live trading behavior

## Need Help?

See the complete example in `examples/test_custom_backtest_engine.py` or read the [Custom Backtest Engine Guide](CUSTOM_BACKTEST_ENGINE.md).

