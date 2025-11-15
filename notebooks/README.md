# Jupyter Notebook Backtesting

Interactive backtesting using **backtesting.py** library - a simple, Jupyter-friendly alternative to hftbacktest.

## 🎯 Why backtesting.py?

**Advantages over hftbacktest:**
- ✅ **Simpler** - Easy to learn and use
- ✅ **Interactive** - Works great in Jupyter notebooks
- ✅ **Visual** - Built-in interactive charts with Bokeh
- ✅ **Fast** - Vectorized operations with pandas
- ✅ **Optimization** - Built-in parameter optimization
- ✅ **No complex data format** - Works directly with pandas DataFrames

**Trade-offs:**
- ❌ Less realistic order execution simulation (no order book)
- ❌ Not optimized for tick-level HFT strategies
- ❌ Simpler fee/slippage model

## 📁 Files

- `backtest_fakeout_strategy.ipynb` - Interactive notebook for Fakeout strategy backtesting
- `README.md` - This file

## 🚀 Quick Start

### 1. Start Jupyter Notebook

```bash
jupyter notebook
```

### 2. Open the Notebook

Navigate to `notebooks/backtest_fakeout_strategy.ipynb` and run the cells.

### 3. Or Run the Test Script

```bash
python examples/test_backtesting_py.py
```

## 📊 Features

### Load Data from MT5

```python
from src.backtesting.data.backtesting_py_data_loader import BacktestingPyDataLoader

loader = BacktestingPyDataLoader()
data = loader.load_from_mt5(
    symbol='EURUSD',
    timeframe='M5',
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31)
)
```

### Run Backtest

```python
from backtesting import Backtest
from src.backtesting.adapters.backtesting_py_strategy_adapter import FakeoutStrategyAdapter

bt = Backtest(
    data,
    FakeoutStrategyAdapter,
    cash=10000,
    commission=0.0
)

stats = bt.run()
print(stats)
```

### Visualize Results

```python
bt.plot()  # Interactive Bokeh chart
```

### Optimize Parameters

```python
optimization_stats = bt.optimize(
    reference_lookback=range(3, 10, 1),
    max_breakout_volume_multiplier=[0.6, 0.7, 0.8, 0.9],
    risk_reward_ratio=[1.5, 2.0, 2.5, 3.0],
    maximize='Sharpe Ratio'
)
```

## 🔧 Creating Custom Strategies

To create your own strategy adapter:

```python
from backtesting import Strategy

class MyStrategyAdapter(Strategy):
    # Define parameters
    my_param = 10
    
    def init(self):
        # Initialize indicators
        self.sma = self.I(lambda: pd.Series(self.data.Close).rolling(self.my_param).mean())
    
    def next(self):
        # Trading logic
        if self.data.Close[-1] > self.sma[-1]:
            if not self.position:
                self.buy()
        elif self.data.Close[-1] < self.sma[-1]:
            if self.position:
                self.position.close()
```

## 📚 Documentation

- [backtesting.py Documentation](https://kernc.github.io/backtesting.py/)
- [backtesting.py GitHub](https://github.com/kernc/backtesting.py)

## 🎓 Examples

See `examples/test_backtesting_py.py` for a complete working example.

## 🎯 Why backtesting.py?

We chose **backtesting.py** for its simplicity and Jupyter integration:
- **Simple** - Easy to learn and use
- **Interactive** - Excellent Jupyter notebook support
- **Visual** - Built-in interactive charts
- **Fast** - Vectorized operations with pandas
- **Optimization** - Built-in parameter optimization

## 💡 Tips

1. **Start with small date ranges** - Test with 1-2 weeks of data first
2. **Use parameter optimization** - Find the best parameters for your strategy
3. **Check the interactive chart** - Visual analysis is powerful
4. **Export results** - Save stats to CSV for further analysis
5. **Iterate quickly** - backtesting.py is fast, so experiment freely!

## 🐛 Troubleshooting

**No trades generated?**
- Check your strategy logic
- Verify data has enough candles
- Adjust strategy parameters

**Data loading fails?**
- Ensure MT5 is running
- Check .env file has correct MT5 credentials
- Verify symbol and timeframe are valid

**Jupyter kernel crashes?**
- Reduce date range (less data)
- Close other notebooks
- Restart kernel and try again

