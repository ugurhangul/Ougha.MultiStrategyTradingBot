# Examples

This directory contains example scripts demonstrating how to use the trading bot.

## Backtesting

### Production Backtest (Recommended)

**File:** `../backtest.py` (in repository root)

The main production-ready backtesting entry point:
- Easy configuration at the top of the file
- Automatic symbol loading from active.set
- Comprehensive error handling and logging
- Detailed progress updates
- Performance metrics display

**Usage:**
```bash
python backtest.py
```

**Configuration:**
Edit the CONFIGURATION section in `backtest.py`:
```python
START_DATE = datetime(2024, 11, 1, tzinfo=timezone.utc)
END_DATE = datetime(2024, 11, 15, tzinfo=timezone.utc)
INITIAL_BALANCE = 10000.0
SYMBOLS = None  # Load from active.set
TIME_MODE = TimeMode.MAX_SPEED
```

### Custom Backtest Engine Example

**File:** `test_custom_backtest_engine.py`

A simpler example script for learning and testing:
- Demonstrates the custom backtest engine API
- Shows how to initialize components manually
- Good for understanding the architecture
- Useful for custom backtest scenarios

**Usage:**
```bash
python examples/test_custom_backtest_engine.py
```

**Configuration:**
Edit the script to customize:
- Symbols to test
- Date range
- Initial balance
- Time mode (REALTIME, FAST, MAX_SPEED)

**Documentation:**
- [CUSTOM_BACKTEST_ENGINE.md](../docs/CUSTOM_BACKTEST_ENGINE.md) - Detailed guide
- [BACKTESTING_RESEARCH_AND_IMPLEMENTATION.md](../docs/BACKTESTING_RESEARCH_AND_IMPLEMENTATION.md) - Design decisions

## Strategy Examples

### HFT Momentum with Decorator

**File:** `hft_momentum_with_decorator.py`

Demonstrates how to use the validation decorator pattern with HFT Momentum strategy.

**Usage:**
```bash
python examples/hft_momentum_with_decorator.py
```

### Validation Decorator Example

**File:** `validation_decorator_example.py`

Shows how to use the validation decorator pattern for signal validation.

**Usage:**
```bash
python examples/validation_decorator_example.py
```

## Quick Start

1. **Run a backtest (Production):**
   ```bash
   python backtest.py
   ```

2. **Or run the example (Learning):**
   ```bash
   python examples/test_custom_backtest_engine.py
   ```

3. **Check the results:**
   - Logs are saved to `logs/backtest/<timestamp>/`
   - Equity curve and trade log are displayed in console
   - Performance metrics are calculated automatically

4. **Customize the backtest:**
   - Edit `backtest.py` (for production use)
   - Or edit `test_custom_backtest_engine.py` (for testing)
   - Change symbols, date range, or initial balance
   - Adjust time mode for faster/slower execution

## Tips

- **Start with a short date range** (e.g., 1 week) to test quickly
- **Use MAX_SPEED mode** for production backtests
- **Use REALTIME or FAST mode** for visual debugging
- **Check the logs** for detailed strategy execution information
- **Compare with live trading** to validate the simulation accuracy

## Need Help?

- Read the [Custom Backtest Engine Guide](../docs/CUSTOM_BACKTEST_ENGINE.md)
- Check the [Research Document](../docs/BACKTESTING_RESEARCH_AND_IMPLEMENTATION.md)
- Review the example script comments for inline documentation

