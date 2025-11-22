# Data Loading Quick Reference Card

**Quick lookup guide for developers working with the backtesting data loading system**

---

## 🗂️ File Structure

```
src/backtesting/engine/
├── data_loader.py              # Main orchestrator (809 lines)
├── data_cache.py               # Day-level caching (444 lines)
├── streaming_tick_loader.py   # Memory-efficient streaming (418 lines)
└── broker_archive_downloader.py # External archive fallback (922 lines)

data/cache/
└── YYYY/
    └── MM/
        └── DD/
            ├── ticks/
            │   ├── EURUSD_INFO.parquet
            │   └── GBPUSD_INFO.parquet
            ├── candles/
            │   ├── EURUSD_M1.parquet
            │   ├── EURUSD_M5.parquet
            │   └── ...
            └── symbol_info/
                ├── EURUSD.json
                └── GBPUSD.json
```

---

## 🔑 Key Classes & Methods

### BacktestDataLoader (data_loader.py)

```python
# Load candles (full range, upfront)
df, info = data_loader.load_from_mt5(
    symbol='EURUSD',
    timeframe='M1',
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 11, 21),
    force_refresh=False
)

# Load ticks (day-by-day, parallel)
df = data_loader.load_ticks_from_mt5(
    symbol='EURUSD',
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 11, 21),
    tick_type=mt5.COPY_TICKS_INFO,
    cache_dir='data/cache',
    progress_callback=None,
    parallel_days=10  # Load 10 days concurrently
)

# Build candles from ticks (fallback)
df = data_loader._build_candles_from_ticks(
    symbol='EURUSD',
    timeframe='M1',
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 11, 21),
    ticks_df=None  # Will load ticks if None
)

# Clear cache
data_loader.clear_cache(symbol='EURUSD')  # Specific symbol
data_loader.clear_cache()                 # All symbols
```

### DataCache (data_cache.py)

```python
cache = DataCache(base_cache_dir='data/cache')

# Load from cache (returns None if any day missing)
df, info = cache.load_from_cache(
    symbol='EURUSD',
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 11, 21),
    timeframe='M1',
    data_type='candles'  # or 'ticks'
)

# Save to cache (splits into daily files)
cache.save_to_cache(
    df=df,
    symbol='EURUSD',
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 11, 21),
    timeframe='M1',
    data_type='candles',
    symbol_info=info
)

# Get cache path for specific day
path = cache._get_day_cache_path(
    symbol='EURUSD',
    day=datetime(2025, 1, 1),
    timeframe='M1',
    data_type='candles'
)
# Returns: data/cache/2025/01/01/candles/EURUSD_M1.parquet
```

### StreamingTickLoader (streaming_tick_loader.py)

```python
loader = StreamingTickLoader(
    cache_dir='data/cache',
    chunk_size=100000,  # Ticks per chunk
    fast_estimation=True
)

# Stream ticks (memory-efficient)
for tick in loader.stream_ticks(
    symbols=['EURUSD', 'GBPUSD'],
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 11, 21),
    tick_type=mt5.COPY_TICKS_INFO
):
    # tick is a GlobalTick object
    print(f"{tick.time} {tick.symbol} {tick.bid}/{tick.ask}")

# Count ticks (fast estimation)
count = loader.count_ticks(
    symbols=['EURUSD'],
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 11, 21),
    tick_type=mt5.COPY_TICKS_INFO
)
```

### BrokerArchiveDownloader (broker_archive_downloader.py)

```python
from src.config.configs.tick_archive_config import TickArchiveConfig

config = TickArchiveConfig()
downloader = BrokerArchiveDownloader(config)

# Fetch from external archive
df = downloader.fetch_tick_data(
    symbol='EURUSD',
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 11, 21),
    server_name='Exness-MT5Trial15',
    tick_type=mt5.COPY_TICKS_INFO,
    cache_dir='data/cache',
    progress_callback=None
)
```

---

## 🔄 Data Flow Patterns

### Pattern 1: Load Candles (Standard)

```
1. Check cache (all days must exist)
   ├─ Cache hit → Load & merge daily files → Return
   └─ Cache miss → Continue to step 2

2. Try MT5 copy_rates_range()
   ├─ Has data → Cache by day → Return
   └─ No data → Continue to step 3

3. Build from ticks
   ├─ Ticks available → Resample → Cache → Return
   └─ No ticks → FAIL
```

### Pattern 2: Load Ticks (Parallel)

```
1. Split date range into days
2. Process in parallel batches (default: 10 days)
   For each day:
     ├─ Check cache
     │  ├─ Cache hit → Load parquet → Continue
     │  └─ Cache miss → Continue to MT5
     ├─ Try MT5 copy_ticks_range()
     │  ├─ Has data → Cache → Continue
     │  └─ No data → Continue to Archive
     └─ Try Broker Archive
        ├─ Has data → Parse → Cache by day → Continue
        └─ No data → Skip day
3. Merge all days
4. Return merged DataFrame
```

### Pattern 3: Stream Ticks (Memory-Efficient)

```
1. Build list of cache files (YYYY/MM/DD/ticks/*.parquet)
2. Open all files with PyArrow
3. Use heap-based merge to stream chronologically
4. Read in chunks (100K ticks per chunk)
5. Yield GlobalTick objects one by one
6. Free chunk memory immediately after processing
```

---

## ⚙️ Configuration Parameters

### backtest.py

```python
# Date range
START_DATE = datetime(2025, 1, 1)
END_DATE = datetime(2025, 11, 21)

# Symbols and timeframes
SYMBOLS = ['EURUSD', 'GBPUSD', 'XAUUSD', 'BTCUSD']
TIMEFRAMES = ['M1', 'M5', 'M15', 'H4']

# Tick data settings
USE_TICK_DATA = True
STREAM_TICKS_FROM_DISK = True
PARALLEL_TICK_DAYS = 10  # Load 10 days concurrently

# Cache settings
FORCE_REFRESH = False  # Force re-download from MT5
```

### streaming_tick_loader.py

```python
# Chunk size for streaming
chunk_size = 100000  # Ticks per chunk

# Fast estimation (uses file size instead of reading metadata)
fast_estimation = True
```

### broker_archive_downloader.py

```python
# In-memory cache (disabled by default to save RAM)
_use_memory_cache = False

# Download settings
max_retries = 3
download_timeout_seconds = 300
```

---

## 📊 Performance Benchmarks

### Typical Timings (4 symbols, 325 days)

| Operation | Time | Notes |
|-----------|------|-------|
| **Cache hit (1 day ticks)** | 0.1-0.5s | Parquet read |
| **MT5 download (1 day ticks)** | 2-5s | Network + API |
| **Archive download (1 year)** | 10-60s | First time only |
| **Archive cached read (1 year)** | 0.6s | Parquet read |
| **Candle cache hit (1 year)** | 0.5-1s | Merge 325 files |
| **Candle MT5 download (1 year)** | 3-8s | Network + API |
| **Build candles from ticks (1 year M1)** | 5-10s | Resample |
| **Full backtest load (cached)** | 2-5 min | All symbols/TFs |
| **Full backtest load (uncached)** | 30-60 min | First run |

### Memory Usage (4 symbols, 325 days)

| Component | Memory | Notes |
|-----------|--------|-------|
| **Candles (upfront)** | 500MB-1GB | All timeframes |
| **Ticks (streaming)** | 2-3GB peak | 100K chunks |
| **Ticks (upfront)** | 20-30GB | Legacy mode |
| **Total (streaming)** | 3-5GB | Recommended |

---

## 🐛 Common Issues & Solutions

### Issue 1: "No tick data available"

**Cause:** MT5 doesn't have historical ticks, archive disabled/unavailable

**Solution:**
```python
# Enable archive downloads in .env
TICK_ARCHIVE_ENABLED=true
TICK_ARCHIVE_URL_PATTERN=https://example.com/{BROKER}/{SYMBOL}/{YEAR}.zip

# Or use candle-only mode
USE_TICK_DATA = False
```

### Issue 2: "Insufficient data (< 10 bars)"

**Cause:** MT5 doesn't have candle data for requested timeframe

**Solution:**
```python
# Enable tick data to build candles
USE_TICK_DATA = True

# Or adjust date range to where MT5 has data
START_DATE = datetime(2024, 1, 1)  # Try earlier date
```

### Issue 3: "Memory error during backtest"

**Cause:** Loading too much data upfront

**Solution:**
```python
# Enable tick streaming
STREAM_TICKS_FROM_DISK = True

# Reduce date range
END_DATE = datetime(2025, 6, 30)  # 6 months instead of 11

# Reduce symbols
SYMBOLS = ['EURUSD', 'GBPUSD']  # 2 instead of 4
```

### Issue 4: "Cache loading very slow"

**Cause:** Too many daily files to merge

**Solution:**
```python
# Already optimized with PyArrow
# If still slow, check disk I/O:
# - Use SSD instead of HDD
# - Defragment cache directory
# - Reduce number of symbols/timeframes
```

---

## 🔍 Debugging Tips

### Enable Detailed Logging

```python
import logging
logging.getLogger('src.backtesting.engine.data_loader').setLevel(logging.DEBUG)
logging.getLogger('src.backtesting.engine.data_cache').setLevel(logging.DEBUG)
```

### Check Cache Contents

```bash
# List cached days for EURUSD ticks
ls data/cache/2025/01/*/ticks/EURUSD_INFO.parquet

# Check cache size
du -sh data/cache/

# Count cached days
find data/cache -name "EURUSD_M1.parquet" | wc -l
```

### Validate Cache Files

```python
import pandas as pd

# Read cache file
df = pd.read_parquet('data/cache/2025/01/01/ticks/EURUSD_INFO.parquet')

# Check data
print(f"Rows: {len(df)}")
print(f"Columns: {df.columns.tolist()}")
print(f"Date range: {df['time'].min()} to {df['time'].max()}")
print(f"Memory: {df.memory_usage(deep=True).sum() / 1024 / 1024:.1f} MB")
```

### Monitor Memory Usage

```python
import psutil
import os

process = psutil.Process(os.getpid())
print(f"Memory: {process.memory_info().rss / 1024 / 1024 / 1024:.2f} GB")
```

---

## 📚 Related Documentation

- **Full Analysis:** [BACKTESTING_DATA_LOADING_ANALYSIS.md](./BACKTESTING_DATA_LOADING_ANALYSIS.md)
- **Summary:** [DATA_LOADING_ANALYSIS_SUMMARY.md](./DATA_LOADING_ANALYSIS_SUMMARY.md)
- **Architecture Diagrams:** See Mermaid diagrams in analysis report

