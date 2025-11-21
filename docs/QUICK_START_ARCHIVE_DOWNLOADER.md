# Quick Start: Tick Archive Downloader

## What Is This?

The Tick Archive Downloader automatically downloads historical tick data from external broker archives when MT5 doesn't have the data you need for backtesting.

**Problem**: MT5 only has tick data from June 2025, but you want to backtest from January 2025.

**Solution**: The system automatically downloads the missing 5 months from external archives.

## How to Enable

### Step 1: Edit `.env` File

Add this line to your `.env` file:

```bash
TICK_ARCHIVE_ENABLED=true
```

That's it! The system will now automatically download missing tick data.

### Step 2: Run Your Backtest

```bash
python backtest.py
```

The system will:
1. ✅ Check cache for existing data
2. ✅ Try to fetch from MT5
3. ✅ **Download from archives if MT5 doesn't have it** (NEW!)
4. ✅ Merge and cache the complete dataset

## What You'll See

### Before (Without Archive Downloader)

```
⚠️  WARNING: Tick data not available from configured START_DATE!
   Configured: 2025-01-01 | Actual first tick: 2025-06-11
   Backtest will start from 2025-06-11 (missing 161 days)
```

### After (With Archive Downloader)

```
Cache validation: Cached data starts 161.0 days after requested start
  Requested start: 2025-01-01
  Cached start:    2025-06-11
Checking MT5 for additional historical data...
  MT5 still does not have data for the missing period
Attempting to fetch tick data from external archive
  Symbol: EURUSD -> EURUSD
  Broker: Exness
  Downloading tick archive: EURUSD 2025
    URL: https://ticks.ex2archive.com/ticks/EURUSD/2025/Exness_EURUSD_2025.zip
    Archive size: 125.3 MB
  ✓ Download successful (125.3 MB)
  ✓ Parsed 8,234,567 ticks from archive
✓ Extended cache with 3,456,789 ticks from archive
Total ticks: 10,000,000
```

## Advanced Configuration (Optional)

### Custom Archive URL

If you have a different archive source:

```bash
TICK_ARCHIVE_URL_PATTERN=https://your-archive.com/{SYMBOL}/{YEAR}.zip
```

### Download Settings

```bash
TICK_ARCHIVE_TIMEOUT=300          # 5 minutes timeout
TICK_ARCHIVE_MAX_RETRIES=3        # Retry up to 3 times
TICK_ARCHIVE_SAVE=true            # Save downloaded archives
TICK_ARCHIVE_CACHE_DIR=data/tick_archives
```

## Supported Archive Sources

The system currently supports:
- ✅ ex2archive.com (example)
- ✅ tickdata.fxcorporate.com (example)
- ✅ historical.dukascopy.com (example)

**Note**: These are example sources. You need to verify they exist and have data for your symbols.

## Adding Your Broker

If your broker isn't recognized, add it to `src/config/configs/tick_archive_config.py`:

```python
broker_name_mapping: dict = {
    "YourBroker-MT5Trial": "YourBroker",
    "YourBroker-MT5Live": "YourBroker",
}
```

## Testing

Test the feature:

```bash
python test_archive_downloader.py
```

This will show:
- Current configuration
- Which tier provides data (cache, MT5, or archive)
- Any gaps in the data

## Troubleshooting

### "Archive downloads are disabled"

**Solution**: Add `TICK_ARCHIVE_ENABLED=true` to `.env`

### "Could not get MT5 server name for broker detection"

**Solution**: Make sure MT5 is connected before running the backtest

### "No data available from external archives"

**Possible causes**:
1. Archive doesn't have data for your symbol/year
2. Broker name mapping is incorrect
3. Archive URL is wrong
4. Network connection issue

**Solution**: Check logs for detailed error messages

### "Validation failed: Only 500 ticks (minimum: 1000)"

**Solution**: The archive has too few ticks. This is a data quality issue.

## Security

The system only downloads from **trusted sources** defined in the configuration:

```python
trusted_sources: List[str] = [
    "ticks.ex2archive.com",
    "tickdata.fxcorporate.com",
    "historical.dukascopy.com"
]
```

To add a new source, edit `src/config/configs/tick_archive_config.py`.

## Performance

### First Run
- Downloads archive (~50-200 MB per symbol/year)
- Takes 30-120 seconds depending on connection
- Parses and validates data (~5-15 seconds)

### Subsequent Runs
- Uses cached archive (no re-download)
- Very fast (~5-15 seconds to parse)

## Disable the Feature

To disable:

```bash
TICK_ARCHIVE_ENABLED=false
```

Or remove the line from `.env` (disabled by default).

## More Information

- **Full Documentation**: See `docs/TICK_ARCHIVE_DOWNLOADER.md`
- **Implementation Details**: See `IMPLEMENTATION_SUMMARY.md`
- **Test Script**: Run `test_archive_downloader.py`

## Summary

1. ✅ Add `TICK_ARCHIVE_ENABLED=true` to `.env`
2. ✅ Run `python backtest.py`
3. ✅ System automatically downloads missing data
4. ✅ Complete dataset ready for backtesting!

**That's it!** The system handles everything else automatically.

