# Custom Backtesting Engine

A high-fidelity backtesting engine that simulates the exact live trading architecture.

## Overview

This custom backtesting engine is designed to:
- **Run the exact same code** as live trading (no strategy rewrites needed)
- **Simulate concurrent execution** of multiple symbols and strategies
- **Accurately model** position limits, risk management, and order execution
- **Provide realistic results** that closely match live trading behavior

## Key Components

### 1. SimulatedBroker
Replaces `MT5Connector` with historical data replay:
- Loads historical OHLC data for each symbol and timeframe from MT5
- **Multi-timeframe support** (M1, M5, M15, H4) - fetches actual data, no resampling
- Simulates order execution with realistic slippage and spread
- Tracks positions, balance, and equity
- Provides the same interface as `MT5Connector`

### 2. BacktestController
Orchestrates the backtest execution:
- Initializes `TradingController` with `SimulatedBroker`
- Advances time synchronously across all symbols
- Calls `strategy.on_tick()` for each symbol at each time step
- Records equity curve and trade log

### 3. TimeController
Manages time synchronization:
- Ensures all symbols advance time together
- Supports different time modes (REALTIME, FAST, MAX_SPEED)
- Prevents race conditions in concurrent execution

### 4. BacktestDataLoader
Loads historical data from MT5:
- Fetches OHLC data using `copy_rates_range()`
- Extracts symbol information (point, digits, tick_value, etc.)
- Validates data quality
- Supports loading extra historical context for lookback periods

### 5. ResultsAnalyzer
Analyzes backtest results:
- Calculates performance metrics (return, Sharpe ratio, max drawdown, etc.)
- Generates equity curves
- Provides trade-by-trade analysis
- Exports results to CSV/JSON

## Quick Start

### Option 1: Use the Production Entry Point (Recommended)

```bash
python backtest.py
```

This is the easiest way to run backtests. Simply edit the CONFIGURATION section at the top of `backtest.py`:

```python
# Date Range
START_DATE = datetime(2024, 11, 1, tzinfo=timezone.utc)
END_DATE = datetime(2024, 11, 15, tzinfo=timezone.utc)

# Initial Balance
INITIAL_BALANCE = 10000.0

# Symbols (None = load from active.set)
SYMBOLS = None  # or ["EURUSD", "GBPUSD"]

# Time Mode
TIME_MODE = TimeMode.MAX_SPEED
```

Then run:
```bash
python backtest.py
```

### Option 2: Use the API Directly

```python
from datetime import datetime, timedelta, timezone
from src.backtesting import (
    SimulatedBroker,
    TimeController,
    TimeMode,
    BacktestController,
    BacktestDataLoader,
    ResultsAnalyzer
)
from src.execution.order_manager import OrderManager
from src.risk.risk_manager import RiskManager
from src.execution.trade_manager import TradeManager
from src.indicators.technical_indicators import TechnicalIndicators
from src.config import config

# 1. Load historical data
loader = BacktestDataLoader()
symbols = ["EURUSD", "GBPUSD"]
timeframe = "M1"
end_date = datetime.now(timezone.utc)
start_date = end_date - timedelta(days=7)

broker = SimulatedBroker(initial_balance=10000.0)
for symbol in symbols:
    data, symbol_info = loader.load_from_mt5(symbol, timeframe, start_date, end_date)
    if data is not None:
        broker.load_symbol_data(symbol, data[0], data[1])

# 2. Initialize components
time_controller = TimeController(symbols, mode=TimeMode.MAX_SPEED)
order_manager = OrderManager(broker, config.advanced.magic_number, config.advanced.trade_comment)
risk_manager = RiskManager(broker, config.risk)
indicators = TechnicalIndicators()
trade_manager = TradeManager(broker, order_manager, config.trailing_stop,
                             config.advanced.use_breakeven,
                             config.advanced.breakeven_trigger_rr, indicators)

# 3. Run backtest
backtest = BacktestController(broker, time_controller, order_manager, risk_manager, trade_manager, indicators)
backtest.initialize(symbols)
backtest.run()

# 4. Analyze results
results = backtest.get_results()
analyzer = ResultsAnalyzer()
metrics = analyzer.analyze(results)
```

## Examples

- **`backtest.py`** - Production-ready main entry point (recommended)
- **`examples/test_custom_backtest_engine.py`** - Complete API example for learning

## Documentation

- **[CUSTOM_BACKTEST_ENGINE.md](../../docs/CUSTOM_BACKTEST_ENGINE.md)** - Detailed architecture and usage guide
- **[BACKTESTING_RESEARCH_AND_IMPLEMENTATION.md](../../docs/BACKTESTING_RESEARCH_AND_IMPLEMENTATION.md)** - Research and design decisions

## Advantages Over Third-Party Libraries

1. **Architectural Fidelity**: Runs the exact same code as live trading
2. **Multi-Timeframe Support**: Fetches actual M1, M5, M15, H4 data from MT5 (no resampling)
3. **Concurrent Execution**: Simulates how strategies compete for positions
4. **Position Limits**: Accurately models global and per-symbol position limits
5. **Risk Management**: Tests the actual risk management logic
6. **No Code Duplication**: Strategies work unchanged in both live and backtest
7. **Realistic Results**: Closely matches live trading behavior

## Time Modes

- **REALTIME**: 1x speed (1 second per bar) - for visual debugging
- **FAST**: 10x speed (100ms per bar) - for faster testing
- **MAX_SPEED**: As fast as possible - for production backtests

## Logging

Backtest logs are saved to `logs/backtest/<timestamp>/` with:
- Simulated timestamps in log messages
- Separate log files per symbol
- Same log format as live trading

## Version

Current version: 1.0.0

