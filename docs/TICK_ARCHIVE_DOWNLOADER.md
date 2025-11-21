# Tick Archive Downloader

## Overview

The Tick Archive Downloader is an enhancement to the backtesting engine that enables downloading historical tick data from external broker archives when MT5 doesn't have the requested data available.

This creates a **multi-tier fallback system** for maximum data completeness:

1. **Tier 1**: Use existing cache
2. **Tier 2**: Fetch missing data from MT5
3. **Tier 3**: Download from broker archives (**NEW**)
4. **Tier 4**: Use partial cached data with warnings

## Why This Feature?

MT5 has limited historical tick data availability. For example:
- MT5 might only have tick data from June 2025 onwards
- You want to backtest from January 2025
- Without this feature, you'd miss 5 months of data

The Tick Archive Downloader automatically:
- Detects when MT5 doesn't have the requested data
- Downloads missing data from external broker archives
- Merges it with existing data
- Updates the cache for future use

## Configuration

### Enable/Disable

Add to your `.env` file:

```bash
# Enable external tick archive downloads
TICK_ARCHIVE_ENABLED=true

# Archive URL pattern (supports {SYMBOL}, {YEAR}, {BROKER} placeholders)
TICK_ARCHIVE_URL_PATTERN=https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{BROKER}_{SYMBOL}_{YEAR}.zip

# Download settings
TICK_ARCHIVE_TIMEOUT=300          # 5 minutes timeout
TICK_ARCHIVE_MAX_RETRIES=3        # Retry up to 3 times
TICK_ARCHIVE_SAVE=true            # Save downloaded archives for reuse
TICK_ARCHIVE_CACHE_DIR=data/tick_archives
```

### Configuration Options

All configuration is in `src/config/configs/tick_archive_config.py`:

```python
@dataclass
class TickArchiveConfig:
    # Enable/disable external archive downloads
    enabled: bool = False
    
    # URL pattern for tick data archives
    archive_url_pattern: str = "https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{BROKER}_{SYMBOL}_{YEAR}.zip"
    
    # Trusted archive sources (for security)
    trusted_sources: List[str] = [
        "ticks.ex2archive.com",
        "tickdata.fxcorporate.com",
        "historical.dukascopy.com"
    ]
    
    # Download settings
    download_timeout_seconds: int = 300
    max_retries: int = 3
    retry_delay_seconds: int = 5
    
    # Data validation
    validate_tick_format: bool = True
    min_ticks_threshold: int = 1000
    
    # Cache settings
    save_downloaded_archives: bool = True
    archive_cache_dir: str = "data/tick_archives"
    
    # Broker name mapping (MT5 server -> archive broker name)
    broker_name_mapping: dict = {
        "Exness-MT5Trial15": "Exness",
        "Exness-MT5Real": "Exness",
        "ICMarkets-Demo": "ICMarkets",
        "ICMarkets-Live": "ICMarkets",
        # Add more as needed
    }
    
    # Symbol name mapping (MT5 symbol -> archive symbol)
    symbol_name_mapping: dict = {
        "XAUUSD.a": "XAUUSD",
        "EURUSD.a": "EURUSD",
        # Add more as needed
    }
```

## How It Works

### 1. Cache Validation

When loading tick data, the system checks if cached data covers the full requested date range:

```python
# Example: Request data from Jan 1, 2025
requested_start = datetime(2025, 1, 1, tzinfo=timezone.utc)

# Cache only has data from June 11, 2025
cached_start = datetime(2025, 6, 11, tzinfo=timezone.utc)

# Gap detected: 161 days missing
gap_days = (cached_start - requested_start).days  # 161
```

### 2. MT5 Fetch Attempt (Tier 2)

The system first tries to fetch the missing period from MT5:

```python
missing_ticks = mt5.copy_ticks_range(symbol, requested_start, cached_start, tick_type)
```

If MT5 returns no data, proceed to Tier 3.

### 3. Archive Download (Tier 3)

If MT5 doesn't have the data, the system:

1. **Detects broker** from MT5 server name:
   ```python
   server_name = "Exness-MT5Trial15"
   broker = "Exness"  # From broker_name_mapping
   ```

2. **Normalizes symbol** name:
   ```python
   symbol = "XAUUSD.a"
   normalized = "XAUUSD"  # From symbol_name_mapping
   ```

3. **Constructs download URL**:
   ```python
   url = "https://ticks.ex2archive.com/ticks/XAUUSD/2025/Exness_XAUUSD_2025.zip"
   ```

4. **Downloads and validates** the archive:
   - Checks if source is trusted
   - Downloads with retry logic
   - Validates ZIP format
   - Parses tick data (CSV format)

5. **Merges with cached data**:
   - Filters to requested date range
   - Removes overlapping ticks
   - Concatenates and sorts by time
   - Updates cache file

### 4. Data Format

Downloaded archives should contain CSV files with tick data:

**Supported CSV formats:**

```csv
# Format 1: Broker Archive Format (e.g., ex2archive.com)
Exness,Symbol,Timestamp,Bid,Ask
1,BTCJPY,2025-01-01 00:00:00,150000.50,150001.50
2,BTCJPY,2025-01-01 00:00:01,150001.00,150002.00

# Format 2: Standard
time,bid,ask,volume
2025-01-01 00:00:00,1.10500,1.10520,100
2025-01-01 00:00:01,1.10501,1.10521,150

# Format 3: With timestamp
timestamp,bid_price,ask_price,vol
1704067200,1.10500,1.10520,100
1704067201,1.10501,1.10521,150

# Format 4: Minimal
datetime,b,a
2025-01-01 00:00:00,1.10500,1.10520
```

The system **auto-detects** column names and formats:
- **Time columns**: `time`, `timestamp`, `datetime`, `date`, `Timestamp`
- **Bid columns**: `bid`, `bid_price`, `bidprice`, `b`, `Bid`
- **Ask columns**: `ask`, `ask_price`, `askprice`, `a`, `Ask`
- **Volume columns**: `volume`, `vol`, `v`, `size` (optional)

## Usage

### In Backtesting

The feature is **automatically used** when running backtests:

```python
from src.backtesting.engine.data_loader import BacktestDataLoader

data_loader = BacktestDataLoader(use_cache=True)

# This will automatically use the multi-tier fallback
ticks_df = data_loader.load_ticks_from_mt5(
    symbol="EURUSD",
    start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
    end_date=datetime(2025, 11, 21, tzinfo=timezone.utc),
    tick_type=mt5.COPY_TICKS_INFO,
    cache_dir="data/ticks"
)
```

### Testing

Run the test script to verify functionality:

```bash
python test_archive_downloader.py
```

This will:
- Display current configuration
- Test the multi-tier fallback mechanism
- Show which tier successfully provided data
- Report any gaps in the data

## Archive Sources

### Supported Sources

The system supports any HTTP/HTTPS archive source that provides:
- ZIP files containing tick data
- CSV format with time, bid, ask columns
- Organized by symbol and year

### Example Sources

1. **ex2archive.com** (Example)
   - URL: `https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{BROKER}_{SYMBOL}_{YEAR}.zip`
   - Format: CSV with time, bid, ask, volume

2. **Dukascopy** (Example)
   - URL: `https://historical.dukascopy.com/ticks/{SYMBOL}/{YEAR}.zip`
   - Format: Binary (requires custom parser)

3. **Custom Broker Archives**
   - Many brokers provide historical tick data
   - Configure URL pattern to match their structure

### Adding New Sources

1. Add to `trusted_sources` in configuration:
   ```python
   trusted_sources: List[str] = [
       "ticks.ex2archive.com",
       "your-archive-source.com"  # Add here
   ]
   ```

2. Update URL pattern if needed:
   ```python
   archive_url_pattern: str = "https://your-archive-source.com/{SYMBOL}/{YEAR}.zip"
   ```

3. Add broker/symbol mappings if needed

## Security

### Trusted Sources

Only archives from **trusted sources** are downloaded:

```python
trusted_sources: List[str] = [
    "ticks.ex2archive.com",
    "tickdata.fxcorporate.com",
    "historical.dukascopy.com"
]
```

If a URL doesn't match a trusted source, the download is **rejected**.

### Data Validation

Downloaded data is validated before use:

1. **Format validation**: Checks for required columns (time, bid, ask)
2. **Price validation**: Ensures bid/ask > 0 and ask >= bid
3. **Minimum ticks**: Requires at least 1000 ticks (configurable)
4. **Date range**: Verifies data is within requested range

## Error Handling

The system handles errors gracefully:

### Download Failures

```
⚠️  Download failed: HTTP 404
⚠️  Retrying in 5 seconds... (attempt 2/3)
```

After max retries, falls back to Tier 4 (partial data).

### Parse Failures

```
⚠️  Invalid ZIP archive
⚠️  Could not detect required columns in CSV
```

Falls back to Tier 4 (partial data).

### Validation Failures

```
⚠️  Validation failed: Only 500 ticks (minimum: 1000)
⚠️  Validation failed: Ask < Bid in some rows
```

Falls back to Tier 4 (partial data).

## Performance

### Caching

Downloaded archives are **cached locally**:

```
data/tick_archives/
  ├── Exness_EURUSD_2025.zip
  ├── Exness_XAUUSD_2025.zip
  └── ICMarkets_GBPUSD_2025.zip
```

Subsequent requests use the cached archive (no re-download).

### Download Times

Typical download times:
- 1 year of tick data: ~50-200 MB
- Download time: 30-120 seconds (depends on connection)
- Parse time: 5-15 seconds

## Troubleshooting

### Archive downloads not working

1. **Check if enabled**:
   ```bash
   TICK_ARCHIVE_ENABLED=true
   ```

2. **Check broker mapping**:
   ```python
   # In tick_archive_config.py
   broker_name_mapping: dict = {
       "YourBroker-MT5Server": "YourBroker"
   }
   ```

3. **Check URL pattern**:
   - Verify the URL is correct
   - Test manually in browser
   - Check if archive exists for your symbol/year

4. **Check trusted sources**:
   - Ensure archive domain is in `trusted_sources`

### Data validation failures

1. **Check CSV format**:
   - Must have time, bid, ask columns
   - Time must be parseable as datetime
   - Prices must be numeric

2. **Check minimum ticks**:
   - Default: 1000 ticks minimum
   - Adjust `min_ticks_threshold` if needed

### Broker not detected

Add your broker to the mapping:

```python
broker_name_mapping: dict = {
    "YourBroker-MT5Trial": "YourBroker",
    "YourBroker-MT5Live": "YourBroker",
}
```

## Logs

The system provides detailed logs:

```
Cache validation: Cached data starts 161.0 days after requested start
  Requested start: 2025-01-01
  Cached start:    2025-06-11
Checking MT5 for additional historical data...
  MT5 still does not have data for the missing period
Attempting to fetch tick data from external archive
  Symbol: EURUSD -> EURUSD
  Broker: Exness
  Date range: 2025-01-01 to 2025-06-11
Fetching data for year 2025...
  Downloading tick archive: EURUSD 2025
    URL: https://ticks.ex2archive.com/ticks/EURUSD/2025/Exness_EURUSD_2025.zip
    Archive size: 125.3 MB
  ✓ Download successful (125.3 MB)
  Parsing tick archive for EURUSD 2025
    Archive contains 1 file(s)
    Parsing file: EURUSD_2025.csv
  ✓ Parsed 8,234,567 ticks from archive
  ✓ Got 3,456,789 ticks for 2025
✓ Successfully fetched 3,456,789 ticks from external archive
✓ Extended cache with 3,456,789 ticks from archive
Total ticks: 10,000,000
```

## Future Enhancements

Potential improvements:

1. **Binary format support**: Parse binary tick data formats
2. **Parallel downloads**: Download multiple years simultaneously
3. **Compression**: Better compression for cached archives
4. **Incremental updates**: Update existing archives with new data
5. **Multiple sources**: Try multiple archive sources if one fails
6. **Authentication**: Support password-protected archives

