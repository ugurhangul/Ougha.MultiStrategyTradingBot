# Backtesting Package

Simple, Jupyter-friendly backtesting infrastructure for the Multi-Strategy Trading Bot using `backtesting.py` library.

## Overview

This package provides comprehensive backtesting capabilities that allow you to:
- Test strategies before live deployment
- Optimize parameters per symbol
- Assess risk and drawdown patterns
- Compare strategy combinations
- Analyze market regime performance
- Interactive visualization in Jupyter notebooks

## Features

### ✅ Completed
- [x] **backtesting.py integration** - Simple, powerful backtesting library
- [x] **Package structure** - Organized module hierarchy
- [x] **MT5 data loader** - Load historical data from MetaTrader 5
  - OHLCV candle data loading
  - CSV data loading
  - Automatic data formatting
  - Data validation
- [x] **Strategy adapters** - Convert live strategies to backtesting format
  - Base adapter class
  - Fakeout strategy adapter
- [x] **Jupyter notebook** - Interactive backtesting environment
- [x] **Test script** - Quick testing without Jupyter
- [x] **Documentation** - Complete usage guide

### 📋 Future Enhancements
- [ ] Additional strategy adapters (TrueBreakout, HFT Momentum)
- [ ] Advanced parameter optimization
- [ ] Walk-forward analysis
- [ ] Multi-symbol backtesting
- [ ] Custom performance metrics

## Package Structure

```
src/backtesting/
├── __init__.py                              # Package initialization
├── README.md                                # This file
├── data/                                    # Data loading
│   ├── __init__.py
│   └── backtesting_py_data_loader.py       # MT5 and CSV data loader
├── adapters/                                # Strategy adapters
│   ├── __init__.py
│   └── backtesting_py_strategy_adapter.py  # backtesting.py adapters
├── metrics/                                 # Performance metrics
│   └── __init__.py
└── visualization/                           # Results visualization
    └── __init__.py
```

## Quick Start

### 1. Using Jupyter Notebook (Recommended)

```bash
jupyter notebook
# Open notebooks/backtest_fakeout_strategy.ipynb
```

### 2. Using Python Script

```bash
python examples/test_backtesting_py.py
```

### 3. Load Data from MT5

```python
from src.backtesting.data import BacktestingPyDataLoader
from datetime import datetime

# Create loader
loader = BacktestingPyDataLoader()

# Load data
data = loader.load_from_mt5(
    symbol='EURUSD',
    timeframe='M5',
    start_date=datetime(2024, 11, 1),
    end_date=datetime(2024, 11, 15)
)

print(f"Loaded {len(data)} candles")
print(data.head())
```

### 4. Run Backtest

```python
from backtesting import Backtest
from src.backtesting.adapters import FakeoutStrategyAdapter

# Create backtest
bt = Backtest(
    data,
    FakeoutStrategyAdapter,
    cash=10000,
    commission=0.0
)

# Run backtest
stats = bt.run()
print(stats)

# Plot results
bt.plot()
```

### 5. Optimize Parameters

```python
# Optimize strategy parameters
optimization_stats = bt.optimize(
    reference_lookback=range(3, 10, 1),
    max_breakout_volume_multiplier=[0.6, 0.7, 0.8, 0.9],
    risk_reward_ratio=[1.5, 2.0, 2.5, 3.0],
    maximize='Sharpe Ratio'
)

print(optimization_stats)
```

## Data Format

The loader converts MT5 data to pandas DataFrame format required by backtesting.py:

### Required Columns
- **Open** - Opening price
- **High** - Highest price
- **Low** - Lowest price
- **Close** - Closing price
- **Volume** - Trading volume

### Index
- **DatetimeIndex** - Timestamp for each candle

## Examples

See the following for complete working examples:
- `examples/test_backtesting_py.py` - Python script example
- `notebooks/backtest_fakeout_strategy.ipynb` - Jupyter notebook example
- `notebooks/README.md` - Complete documentation

## Dependencies

- `backtesting>=0.3.3` - Simple backtesting library
- `MetaTrader5>=5.0.45` - MT5 API
- `numpy>=1.24.0` - Numerical computing
- `pandas>=2.0.0` - Data manipulation
- `jupyter>=1.0.0` - Jupyter notebook support
- `notebook>=7.0.0` - Notebook interface

## Next Steps

1. **Create additional strategy adapters** - TrueBreakout, HFT Momentum
2. **Advanced parameter optimization** - Walk-forward analysis
3. **Multi-symbol backtesting** - Portfolio-level testing
4. **Custom performance metrics** - Strategy-specific metrics

## Resources

- [backtesting.py Documentation](https://kernc.github.io/backtesting.py/)
- [backtesting.py GitHub](https://github.com/kernc/backtesting.py)
- [Jupyter Notebook Documentation](https://jupyter.org/documentation)

## License

Part of the Ougha Multi-Strategy Trading Bot project.

