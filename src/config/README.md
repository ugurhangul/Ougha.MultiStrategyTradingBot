# Configuration System Documentation

This directory contains the hierarchical configuration system for the FiveMinScalper trading bot.

## 📁 Directory Structure

```
src/config/
├── __init__.py                    # Re-exports TradingConfig and config singleton
├── trading_config.py              # Main configuration aggregator (TradingConfig class)
├── configs/                       # General configuration dataclasses
│   ├── __init__.py
│   ├── mt5_config.py             # MT5 connection settings
│   ├── strategy_config.py        # Strategy enable/disable flags
│   ├── risk_config.py            # Risk management & trailing stops
│   ├── trading_hours_config.py   # Trading hours restrictions
│   ├── advanced_config.py        # Advanced settings
│   ├── range_config.py           # Range detection settings
│   ├── logging_config.py         # Logging configuration
│   ├── adaptive_config.py        # Adaptive filters
│   ├── volume_divergence_config.py  # Volume & divergence settings
│   └── hft_momentum_config.py    # HFT Momentum strategy config
├── strategies/                    # Strategy-specific configurations
│   ├── __init__.py
│   ├── martingale_types.py       # Martingale position sizing types (enum)
│   ├── breakout_config.py        # Base breakout strategy config
│   ├── true_breakout_config.py   # True breakout strategy config
│   └── fakeout_config.py         # Fakeout/reversal strategy config
└── symbols/                       # Symbol-specific optimization
    ├── __init__.py
    ├── category_detector.py      # Symbol category detection (Forex, Crypto, etc.)
    ├── parameters_repository.py  # Category-based parameter storage
    └── optimizer.py              # Facade for symbol parameter retrieval
```

## 🎯 Configuration Hierarchy

The configuration system follows a **three-tier hierarchy**:

### 1. **Global Configuration** (`trading_config.py`)
- **Purpose**: Aggregates all configuration settings into a single `TradingConfig` class
- **Scope**: Application-wide settings
- **Usage**: `from src.config import config`
- **Contains**:
  - MT5 connection settings
  - Risk management parameters
  - Trading hours
  - Strategy enable/disable flags
  - All general settings from `configs/` subdirectory

### 2. **Strategy-Specific Configuration** (`strategies/`)
- **Purpose**: Configuration specific to individual trading strategies
- **Scope**: Per-strategy settings
- **Usage**: `from src.config.strategies import TrueBreakoutConfig, FakeoutConfig`
- **Contains**:
  - Strategy-specific parameters (e.g., retest confirmation, divergence validation)
  - Multi-range support (4H_5M, 15M_1M timeframe combinations)
  - Martingale position sizing types

### 3. **Symbol-Specific Optimization** (`symbols/`)
- **Purpose**: Optimize parameters based on symbol category
- **Scope**: Per-symbol or per-category settings
- **Usage**: `from src.config.symbols import SymbolOptimizer`
- **Contains**:
  - Symbol category detection (Major Forex, Crypto, Metals, etc.)
  - Category-based parameter overrides (spread limits, lot sizes, etc.)
  - Hybrid detection using MT5 native categories + pattern matching

## 🔧 How to Use

### Basic Usage

```python
# Import the global config singleton
from src.config import config

# Access MT5 settings
print(config.mt5.login)

# Access risk settings
print(config.risk.risk_percent_per_trade)

# Access strategy configs
print(config.true_breakout.retest_confirmation_enabled)
```

### Strategy-Specific Configuration

```python
# Import strategy configs
from src.config.strategies import TrueBreakoutConfig, FakeoutConfig

# Load from environment variables
tb_config = TrueBreakoutConfig.from_env(range_id="4H5M")
fb_config = FakeoutConfig.from_env(range_id="15M1M")
```

### Symbol-Specific Optimization

```python
# Import symbol optimizer
from src.config.symbols import SymbolOptimizer

# Get optimized parameters for a symbol
params = SymbolOptimizer.get_symbol_parameters(
    symbol="EURUSD",
    mt5_category="Majors"  # Optional: from mt5.symbol_info().category
)

print(params.max_spread_points)  # Category-optimized spread limit
```

## ➕ Adding New Configuration Settings

### 1. Adding a General Setting

1. **Choose the appropriate config file** in `configs/` (or create a new one)
2. **Add the field** to the dataclass:
   ```python
   @dataclass
   class RiskConfig:
       new_setting: float = 1.0
   ```
3. **Update `from_env()` method** to load from environment:
   ```python
   new_setting=float(os.getenv('NEW_SETTING', '1.0'))
   ```
4. **Update `trading_config.py`** to pass the value when creating the config object

### 2. Adding a Strategy-Specific Setting

1. **Edit the strategy config file** in `strategies/`
2. **Add the field** to the dataclass
3. **Update `from_env()` method** with the environment variable name
4. **Re-export** in `strategies/__init__.py` if it's a new class

### 3. Adding a Symbol Category

1. **Edit `symbols/category_detector.py`**
2. **Add the category** to `SymbolCategory` enum (in `src/models/models/enums.py`)
3. **Update `CATEGORY_PATTERNS`** or `MT5_CATEGORY_MAPPING`
4. **Edit `symbols/parameters_repository.py`** to add category-specific parameters

## 🔄 Configuration Precedence

Settings are applied in the following order (later overrides earlier):

1. **Default values** in dataclass definitions
2. **Environment variables** (`.env` file)
3. **Symbol-specific overrides** (if `USE_SYMBOL_SPECIFIC_SETTINGS=true`)

## 📝 Environment Variables

All configuration is loaded from environment variables via the `.env` file. See `.env.example` for a complete list of available settings.

### Key Environment Variables:

- **MT5 Connection**: `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`
- **Risk Management**: `RISK_PERCENT_PER_TRADE`, `MAX_RISK_PERCENT_PER_TRADE`
- **Strategy Flags**: `TB_ENABLED`, `FB_ENABLED`, `HFT_ENABLED`
- **Symbol Settings**: `USE_SYMBOL_SPECIFIC_SETTINGS`

## 🏗️ Design Principles

This configuration system follows **SOLID principles**:

- **Single Responsibility**: Each config file has one clear purpose
- **Open/Closed**: Easy to extend with new strategies without modifying existing code
- **Liskov Substitution**: All config classes follow the same `from_env()` pattern
- **Interface Segregation**: Configs are split into focused modules
- **Dependency Inversion**: Strategies depend on config abstractions, not concrete implementations

## 🔍 Troubleshooting

### Import Errors

If you encounter import errors after the reorganization:

```python
# ❌ Old imports (deprecated)
from src.config.config import config
from src.config.strategy_parameters import TrueBreakoutConfig
from src.config.symbol_optimizer import SymbolOptimizer

# ✅ New imports
from src.config import config
from src.config.strategies import TrueBreakoutConfig
from src.config.symbols import SymbolOptimizer
```

### Configuration Not Loading

1. **Check `.env` file exists** in the project root
2. **Verify environment variable names** match the config file
3. **Check data types** (e.g., `'true'` for booleans, not `'True'`)

---

**Last Updated**: 2025-11-12  
**Maintainer**: FiveMinScalper Development Team

