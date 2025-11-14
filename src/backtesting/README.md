# Backtesting Package

High-performance backtesting infrastructure for the Multi-Strategy Trading Bot using `hftbacktest` library.

## Overview

This package provides comprehensive backtesting capabilities that allow you to:
- Test strategies before live deployment
- Optimize parameters per symbol
- Assess risk and drawdown patterns
- Compare strategy combinations
- Analyze market regime performance

## Features

### ✅ Phase 1: Foundation (COMPLETED)
- [x] **hftbacktest installation** - High-performance backtesting library
- [x] **Package structure** - Organized module hierarchy
- [x] **MT5 data exporter** - Export historical data from MetaTrader 5
  - Tick data export
  - OHLCV candle data export
  - Batch export for date ranges
  - Data validation

### 🚧 Phase 2: Core Engine (IN PROGRESS)
- [ ] Multi-strategy backtest engine
- [ ] Unified data stream manager
- [ ] Execution simulator with slippage
- [ ] Results compilation and metrics

### 📋 Phase 3: Strategy Integration (PLANNED)
- [ ] Adapt existing strategies for backtesting
- [ ] HFT-specific tick data handling
- [ ] Multi-timeframe coordination
- [ ] Performance optimization

### 📋 Phase 4: Validation (PLANNED)
- [ ] Compare backtest vs live results
- [ ] Parameter optimization
- [ ] Walk-forward analysis
- [ ] Documentation and examples

## Package Structure

```
src/backtesting/
├── __init__.py                 # Package initialization
├── README.md                   # This file
├── data/                       # Data export and conversion
│   ├── __init__.py
│   └── mt5_data_exporter.py   # MT5 to hftbacktest converter
├── adapters/                   # Strategy adapters
│   └── __init__.py
├── engine/                     # Backtesting engine
│   └── __init__.py
├── metrics/                    # Performance metrics
│   └── __init__.py
└── visualization/              # Results visualization
    └── __init__.py
```

## Quick Start

### 1. Export Data from MT5

```python
from src.core.mt5_connector import MT5Connector
from src.backtesting.data import MT5DataExporter
from datetime import datetime, timedelta
import MetaTrader5 as mt5

# Connect to MT5
connector = MT5Connector()
connector.connect()

# Create exporter
exporter = MT5DataExporter(connector, output_dir="data/backtest")

# Export tick data
end_date = datetime.now()
start_date = end_date - timedelta(days=7)

tick_file = exporter.export_tick_data(
    symbol="EURUSD",
    start_date=start_date,
    end_date=end_date
)

# Export OHLCV data
ohlcv_file = exporter.export_ohlcv_data(
    symbol="EURUSD",
    timeframe=mt5.TIMEFRAME_M1,
    start_date=start_date,
    end_date=end_date
)

# Validate exported data
exporter.validate_data(tick_file)
```

### 2. Batch Export

```python
# Export multiple days
exported_files = exporter.export_date_range(
    symbol="EURUSD",
    start_date=start_date,
    end_date=end_date,
    data_type="tick"
)
```

## Data Format

The exporter converts MT5 data to hftbacktest-compatible `.npz` format:

### Tick Data Structure
```python
dtype=[
    ('timestamp', 'i8'),  # microseconds
    ('bid', 'f8'),        # bid price
    ('ask', 'f8'),        # ask price
    ('bid_qty', 'f8'),    # bid quantity
    ('ask_qty', 'f8'),    # ask quantity
]
```

### OHLCV Data Structure
```python
dtype=[
    ('timestamp', 'i8'),  # microseconds
    ('open', 'f8'),
    ('high', 'f8'),
    ('low', 'f8'),
    ('close', 'f8'),
    ('volume', 'f8'),
]
```

## Examples

See `examples/export_mt5_data_example.py` for a complete working example.

## Dependencies

- `hftbacktest>=2.4.3` - High-frequency backtesting library
- `MetaTrader5>=5.0.45` - MT5 API
- `numpy>=1.24.0` - Numerical computing
- `pandas>=2.0.0` - Data manipulation

## Next Steps

1. **Implement strategy adapters** - Bridge between live strategies and backtesting
2. **Build backtest engine** - Multi-strategy execution simulator
3. **Add performance metrics** - Sharpe, Sortino, Max DD, etc.
4. **Create visualization tools** - Equity curves, trade analysis

## License

Part of the Ougha Multi-Strategy Trading Bot project.

