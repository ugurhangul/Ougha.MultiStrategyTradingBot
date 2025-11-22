# External Tick Data Integration (ex2archive.com)

## Overview

The backtesting engine now supports automatic fallback to external tick data sources when MT5 doesn't have sufficient historical data. This integration uses **ex2archive.com** as the primary external data source with intelligent multi-tier download strategies.

## Architecture

### Data Source Hierarchy

When loading tick data for backtesting, the system follows this priority:

1. **Local Parquet Cache** (fastest - instant)
   - Day-level cache files: `data/cache/YYYY/MM/DD/ticks/SYMBOL_TICKTYPE.parquet`
   - Pre-converted archive cache: `data/archives/parquet/Broker_SYMBOL_YEAR[_MONTH].parquet`

2. **MT5 Historical Data** (fast - seconds)
   - Direct download from MetaTrader 5 terminal
   - Limited historical depth (typically 1-3 months)

3. **External Archive - Day-based** (medium - 10-30 seconds per day)
   - URL: `https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{MONTH}/{DAY}/{BROKER}_{SYMBOL}_{YEAR}_{MONTH}_{DAY}.zip`
   - Downloads only the requested day (most efficient)

4. **External Archive - Month-based** (slower - 1-3 minutes per month)
   - URL: `https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{MONTH}/{BROKER}_{SYMBOL}_{YEAR}_{MONTH}.zip`
   - Downloads 28-31 days, extracts the requested day
   - Cached for future use

5. **External Archive - Year-based** (slowest - 5-15 minutes per year)
   - URL: `https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{BROKER}_{SYMBOL}_{YEAR}.zip`
   - Downloads 365 days, extracts the requested day
   - Automatically split into daily cache files

### Intelligent Caching Strategy

The system implements multiple caching layers to minimize downloads:

#### 1. Day-level Parquet Cache
- **Location**: `data/cache/YYYY/MM/DD/ticks/SYMBOL_TICKTYPE.parquet`
- **Purpose**: Fast access to individual days
- **Created by**: MT5 downloads, archive downloads, or archive splitting
- **Speed**: 0.1-0.5 seconds per day

#### 2. Archive Parquet Cache
- **Location**: `data/archives/parquet/Broker_SYMBOL_YEAR[_MONTH].parquet`
- **Purpose**: Avoid re-parsing large CSV archives (10-50x faster)
- **Created by**: First-time archive parsing
- **Speed**: 0.5-2 seconds vs 30-60 seconds for CSV parsing

#### 3. Archive ZIP Cache
- **Location**: `data/archives/Broker_SYMBOL_YEAR[_MONTH[_DAY]].zip`
- **Purpose**: Avoid re-downloading archives
- **Created by**: First-time archive download
- **Speed**: Instant vs 10-300 seconds for download

## Configuration

### Environment Variables (.env)

```bash
# Enable external archive downloads
TICK_ARCHIVE_ENABLED=true

# URL patterns for different granularities
TICK_ARCHIVE_URL_PATTERN_YEAR=https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{BROKER}_{SYMBOL}_{YEAR}.zip
TICK_ARCHIVE_URL_PATTERN_MONTH=https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{MONTH}/{BROKER}_{SYMBOL}_{YEAR}_{MONTH}.zip
TICK_ARCHIVE_URL_PATTERN_DAY=https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{MONTH}/{DAY}/{BROKER}_{SYMBOL}_{YEAR}_{MONTH}_{DAY}.zip

# Use granular downloads (day/month) instead of only year-based
TICK_ARCHIVE_USE_GRANULAR=true

# Download settings
TICK_ARCHIVE_TIMEOUT=300
TICK_ARCHIVE_MAX_RETRIES=3

# Cache settings
TICK_ARCHIVE_SAVE=true
TICK_ARCHIVE_CACHE_DIR=data/archives
```

### Broker Mapping

The system automatically detects the broker name from your MT5 server. Common mappings are pre-configured in `src/config/configs/tick_archive_config.py`:

```python
broker_name_mapping: dict = {
    "Exness-MT5Trial15": "Exness",
    "Exness-MT5Real": "Exness",
    "ICMarkets-Demo": "ICMarkets",
    "ICMarkets-Live": "ICMarkets",
    "FTMO-Demo": "FTMO",
    # Add more as needed
}
```

**To add a new broker:**
1. Find your MT5 server name (shown in MT5 terminal)
2. Determine the broker name used in ex2archive.com URLs
3. Add mapping to `broker_name_mapping` in `tick_archive_config.py`

### Symbol Mapping

If your MT5 symbol names differ from archive symbol names (e.g., `XAUUSD.a` vs `XAUUSD`), configure the mapping:

```python
symbol_name_mapping: dict = {
    "XAUUSD.a": "XAUUSD",
    "EURUSD.a": "EURUSD",
    # Add more as needed
}
```

## Usage

### Automatic Integration

The external data source is **automatically used** when:
1. `TICK_ARCHIVE_ENABLED=true` in `.env`
2. MT5 doesn't have data for the requested date
3. The broker is recognized (has a mapping)

No code changes needed - just run your backtest as usual:

```bash
python backtest.py
```

### Manual Testing

To test the integration with a specific date range:

```python
from datetime import datetime, timezone
from src.backtesting.engine import BacktestDataLoader
from src.config import config

# Initialize data loader
loader = BacktestDataLoader(
    use_cache=True,
    cache_dir="data/cache",
    cache_ttl_days=7
)

# Load tick data (will use archive if MT5 doesn't have it)
ticks_df = loader.load_ticks_from_mt5(
    symbol="XAUUSD",
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
    tick_type=mt5.COPY_TICKS_INFO,
    cache_dir="data/cache"
)

print(f"Loaded {len(ticks_df):,} ticks")
```

## Cache Reuse Optimization

### Problem Solved

When processing multiple consecutive days from the same month (e.g., backtesting January 1-31), the naive approach would download the month archive 31 times - once for each day. This would be extremely inefficient:

- **Without optimization**: 31 downloads × 60s = 1,860 seconds (31 minutes)
- **With optimization**: 1 download × 60s = 60 seconds

### How It Works

The optimization checks for cached Parquet files **before** attempting to download:

1. **Check day-level cache first** (fastest)
   - If found, return immediately (0.1-0.5s)

2. **Check month Parquet cache** (before downloading)
   - If found, extract the requested day (0.5-2s)
   - Skip URL validation and download entirely

3. **Only download if cache doesn't exist**
   - Download month archive once
   - Save to Parquet cache for future reuse
   - Extract requested day

### Cache Priority Order

```
Day 1 request:
  ├─ Day cache? → No
  ├─ Month Parquet cache? → No
  └─ Download month archive → Save to cache → Extract day 1

Day 2 request:
  ├─ Day cache? → No
  ├─ Month Parquet cache? → YES! ✓
  └─ Extract day 2 (no download needed)

Day 3-31 requests:
  ├─ Day cache? → No
  ├─ Month Parquet cache? → YES! ✓
  └─ Extract day (no download needed)
```

### Performance Impact

For a typical backtest of 30 days in the same month:

| Metric | Without Optimization | With Optimization | Improvement |
|--------|---------------------|-------------------|-------------|
| Downloads | 30 | 1 | 30x fewer |
| Download time | 1,800s (30 min) | 60s (1 min) | 30x faster |
| Parse time | 300s (5 min) | 10s | 30x faster |
| Total time | 2,100s (35 min) | 70s (1.2 min) | 30x faster |
| Network usage | 4.5 GB | 150 MB | 30x less |

### Thread Safety

The optimization is **thread-safe** for parallel day loading:

- Multiple threads can read the same month Parquet cache simultaneously
- Parquet files are read-only after creation
- No race conditions when multiple days from the same month are loaded in parallel

## Performance Characteristics

### First-Time Download (No Cache)

| Granularity | Download Time | Parse Time | Total Time | Data Size |
|-------------|---------------|------------|------------|-----------|
| Day         | 10-30s        | 1-5s       | 15-35s     | 5-20 MB   |
| Month       | 30-90s        | 10-30s     | 40-120s    | 50-200 MB |
| Year        | 60-300s       | 30-120s    | 90-420s    | 500-2000 MB |

### Subsequent Access (With Cache)

| Cache Type           | Access Time | Notes                                    |
|---------------------|-------------|------------------------------------------|
| Day Parquet         | 0.1-0.5s    | Fastest - individual day access          |
| Archive Parquet     | 0.5-2s      | Fast - extract day from month/year       |
| Archive ZIP (cached)| 1-5s        | Medium - parse CSV from cached ZIP       |

### Memory Usage

- **Day-based**: ~10-50 MB per day in memory
- **Month-based**: ~100-500 MB per month in memory (then split to daily cache)
- **Year-based**: ~1-5 GB per year in memory (then split to daily cache)

**Recommendation**: Use `TICK_ARCHIVE_USE_GRANULAR=true` to minimize memory usage.

## Fallback Strategy Example

### Single Day Load (2024-01-15)

```
1. Check day cache: data/cache/2024/01/15/ticks/XAUUSD_INFO.parquet
   ❌ Not found

2. Try MT5: copy_ticks_range(2024-01-15)
   ❌ MT5 only has data from 2024-10-01

3. Try day archive: .../2024/01/15/Exness_XAUUSD_2024_01_15.zip
   ❌ HTTP 404 (day archives not available)

4. Check month Parquet cache: data/archives/parquet/Exness_XAUUSD_2024_01.parquet
   ❌ Not found

5. Try month archive: .../2024/01/Exness_XAUUSD_2024_01.zip
   ✅ Downloaded (150 MB, 45 seconds)
   ✅ Parsed to Parquet (10 seconds)
   ✅ Cached: data/archives/parquet/Exness_XAUUSD_2024_01.parquet
   ✅ Extracted day 15: 45,234 ticks
   ✅ Cached: data/cache/2024/01/15/ticks/XAUUSD_INFO.parquet

6. Next time: Load from day cache (0.3 seconds) ⚡
```

### Multiple Consecutive Days (2024-01-15 to 2024-01-25)

**OPTIMIZED BEHAVIOR** (with month cache reuse):

```
Day 1 (2024-01-15):
  1. Check day cache → Not found
  2. Try MT5 → No data
  3. Try day archive → 404
  4. Check month Parquet cache → Not found
  5. Download month archive → ✅ (150 MB, 45s)
  6. Cache month Parquet → ✅
  7. Extract day 15 → ✅ (45,234 ticks)
  8. Cache day 15 → ✅
  Total time: ~55 seconds

Day 2 (2024-01-16):
  1. Check day cache → Not found
  2. Try MT5 → No data
  3. Try day archive → 404
  4. Check month Parquet cache → ✅ FOUND! (reuse from day 1)
  5. Extract day 16 → ✅ (43,891 ticks)
  6. Cache day 16 → ✅
  Total time: ~0.5 seconds ⚡

Day 3-10 (2024-01-17 to 2024-01-25):
  Same as Day 2 - reuse month Parquet cache
  Total time per day: ~0.5 seconds ⚡

TOTAL TIME FOR 10 DAYS: 55s + (9 × 0.5s) = ~60 seconds
```

**OLD BEHAVIOR** (without optimization - would download month archive 10 times):

```
Each day: Download month archive (45s) + Parse (10s) = 55s
TOTAL TIME FOR 10 DAYS: 10 × 55s = 550 seconds (9+ minutes)

TIME SAVED: 490 seconds (8+ minutes) for just 10 days!
```

## Troubleshooting

### "Could not determine broker name from server"

**Problem**: Your MT5 server is not in the broker mapping.

**Solution**: Add your server to `broker_name_mapping` in `tick_archive_config.py`:
```python
"YourServer-MT5": "BrokerName"
```

### "Archive not found (HTTP 404)"

**Problem**: The archive doesn't exist for that date/symbol/broker combination.

**Possible causes**:
1. Broker name is incorrect (check ex2archive.com for available brokers)
2. Symbol name needs normalization (add to `symbol_name_mapping`)
3. Data genuinely not available for that date

**Solution**: Check the URL in the logs and verify it exists on ex2archive.com.

### "Download timeout"

**Problem**: Archive download is taking too long.

**Solution**: Increase timeout in `.env`:
```bash
TICK_ARCHIVE_TIMEOUT=600  # 10 minutes
```

### High Memory Usage

**Problem**: Year-based archives consume too much RAM.

**Solution**: Ensure granular downloads are enabled:
```bash
TICK_ARCHIVE_USE_GRANULAR=true
```

## Data Quality

### Validation

Downloaded data is automatically validated:
- Minimum tick count threshold (default: 1000 ticks)
- Valid price ranges (bid/ask > 0, ask >= bid)
- Time continuity checks
- Format validation

### Metadata

Each cached file includes metadata:
```python
{
    'cached_at': '2024-11-22T10:30:00Z',
    'source': 'archive',  # or 'mt5'
    'first_data_time': '2024-01-15T00:00:01Z',
    'last_data_time': '2024-01-15T23:59:58Z',
    'row_count': '45234',
    'cache_version': '1.0'
}
```

## Future Enhancements

Potential improvements for future versions:

1. **Multiple Archive Sources**: Support for Dukascopy, FXCM, etc.
2. **Parallel Downloads**: Download multiple days/months concurrently
3. **Smart Prefetching**: Pre-download likely needed data
4. **Compression Optimization**: Better compression for cache files
5. **Cloud Storage**: S3/Azure integration for shared cache
6. **Data Quality Metrics**: Track and report data quality scores

## Related Documentation

- [Data Loading Quick Reference](DATA_LOADING_QUICK_REFERENCE.md)
- [Custom Backtest Engine](CUSTOM_BACKTEST_ENGINE.md)
- [Tick Archive Configuration](../src/config/configs/tick_archive_config.py)

