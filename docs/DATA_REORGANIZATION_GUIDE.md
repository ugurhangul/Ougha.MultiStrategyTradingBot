# Data Directory Reorganization Guide

## Overview

This guide explains the data directory reorganization to improve organization and maintainability.

---

## 📁 New Directory Structure

### Before (Cluttered)
```
data/
├── EURUSD/              # 70+ symbol directories scattered at root
├── GBPUSD/
├── AAPL/
├── ... (70+ more)
├── ticks/               # Tick cache files
├── tick_archives/       # Downloaded archives
├── backtest/            # Backtest results
├── active.set
└── positions.json
```

### After (Organized)
```
data/
├── cache/
│   ├── candles/         # All candle cache files (OHLCV data)
│   │   ├── EURUSD/
│   │   │   ├── M1_2025-01-01_2025-11-20.parquet
│   │   │   ├── M5_2025-01-01_2025-11-20.parquet
│   │   │   ├── H1_2025-01-01_2025-11-20.parquet
│   │   │   └── symbol_info.json
│   │   ├── GBPUSD/
│   │   └── ... (all symbols)
│   └── ticks/           # All tick cache files
│       ├── EURUSD_20250101_20251120_INFO.parquet
│       ├── GBPUSD_20250101_20251120_INFO.parquet
│       └── ...
├── archives/            # External tick archives (zip files)
│   ├── Exness_EURUSD_2025.zip
│   ├── Exness_GBPUSD_2025.zip
│   └── ...
├── backtest/            # Backtest results
│   └── positions.json
├── active.set           # Active symbols list
└── positions.json       # Live trading positions
```

---

## ✅ Benefits

1. **Clear Separation**: Candles vs Ticks vs Archives vs Results
2. **Easier Navigation**: All ticks in one place, all candles in another
3. **Easier Cleanup**: Delete old candles without affecting ticks
4. **Better .gitignore**: Ignore `data/cache/` but keep `data/active.set`
5. **Scalability**: Easy to add new data types (e.g., `data/cache/indicators/`)

---

## 🚀 How to Reorganize

### Step 1: Dry Run (Recommended)

First, see what will be moved **without actually moving anything**:

```bash
python tools/reorganize_data_directory.py --dry-run
```

This will show you:
- How many symbol directories will be moved
- How many tick files will be moved
- How many archive files will be moved
- Total data size to be moved
- Any potential errors

### Step 2: Create Backup (Optional but Recommended)

Create a backup before reorganizing:

```bash
python tools/reorganize_data_directory.py --backup
```

This creates a timestamped backup: `data_backup_YYYYMMDD_HHMMSS/`

### Step 3: Run Reorganization

Once you're satisfied with the dry-run output:

```bash
python tools/reorganize_data_directory.py
```

Or with backup:

```bash
python tools/reorganize_data_directory.py --backup
```

---

## 📝 What the Script Does

1. **Creates new directory structure**:
   - `data/cache/candles/`
   - `data/cache/ticks/`
   - `data/archives/`

2. **Moves symbol directories**:
   - `data/EURUSD/` → `data/cache/candles/EURUSD/`
   - `data/GBPUSD/` → `data/cache/candles/GBPUSD/`
   - ... (all 70+ symbols)

3. **Moves tick cache files**:
   - `data/ticks/*.parquet` → `data/cache/ticks/*.parquet`

4. **Moves tick archives**:
   - `data/tick_archives/*.zip` → `data/archives/*.zip`

5. **Cleans up empty directories**:
   - Removes `data/ticks/` if empty
   - Removes `data/tick_archives/` if empty

6. **Preserves important files**:
   - `data/active.set` stays at root
   - `data/positions.json` stays at root
   - `data/backtest/` stays at root

---

## 🔧 Code Changes Made

The following files were updated to use the new paths:

### 1. `src/backtesting/engine/data_cache.py`
- **Old**: `cache_dir: str = "data"`
- **New**: `cache_dir: str = "data/cache/candles"`

### 2. `backtest.py`
- **Old**: `CACHE_DIR = "data"`
- **New**: `CACHE_DIR = "data/cache/candles"`
- **Old**: `tick_cache_dir = Path("data/ticks")`
- **New**: `tick_cache_dir = Path("data/cache/ticks")`

### 3. `src/config/configs/tick_archive_config.py`
- **Old**: `archive_cache_dir: str = "data/tick_archives"`
- **New**: `archive_cache_dir: str = "data/archives"`

### 4. `src/config/trading_config.py`
- **Old**: `archive_cache_dir=os.getenv('TICK_ARCHIVE_CACHE_DIR', 'data/tick_archives')`
- **New**: `archive_cache_dir=os.getenv('TICK_ARCHIVE_CACHE_DIR', 'data/archives')`

---

## ⚠️ Important Notes

### Backward Compatibility

If you have existing cache files and want to keep using them:

1. **Option A**: Run the reorganization script (recommended)
   - Moves all files to new locations
   - Code automatically uses new paths

2. **Option B**: Override paths in your code
   ```python
   # In backtest.py
   CACHE_DIR = "data"  # Keep old path
   tick_cache_dir = Path("data/ticks")  # Keep old path
   ```

### Environment Variables

If you have `TICK_ARCHIVE_CACHE_DIR` in your `.env` file, update it:

```bash
# Old
TICK_ARCHIVE_CACHE_DIR=data/tick_archives

# New
TICK_ARCHIVE_CACHE_DIR=data/archives
```

Or remove it to use the new default.

---

## 🧪 Testing After Reorganization

After reorganizing, test that everything works:

### 1. Test Backtest with Cached Data
```bash
python backtest.py
```

Should load data from:
- `data/cache/candles/EURUSD/M1_*.parquet`
- `data/cache/ticks/EURUSD_*_INFO.parquet`

### 2. Test Archive Downloads (if enabled)
```bash
python test_archive_downloader.py
```

Should save archives to:
- `data/archives/Exness_EURUSD_2025.zip`

### 3. Verify Directory Structure
```bash
# Windows
tree data /F

# Linux/Mac
tree data
```

Should show the new organized structure.

---

## 🔄 Rollback (If Needed)

If something goes wrong and you created a backup:

```bash
# Windows
Remove-Item -Path data -Recurse -Force
Rename-Item -Path data_backup_YYYYMMDD_HHMMSS -NewName data

# Linux/Mac
rm -rf data
mv data_backup_YYYYMMDD_HHMMSS data
```

---

## 📊 Expected Output

When you run the reorganization script, you should see:

```
================================================================================
DATA DIRECTORY REORGANIZATION
================================================================================

Data directory: C:\repos\ugurhangul\Ougha.MultiStrategyTradingBot\data
Mode: LIVE (files will be moved)

Step 1: Creating new directory structure...
  ✓ Created: data\cache\candles
  ✓ Created: data\cache\ticks
  ✓ Created: data\archives

Step 2: Moving symbol directories to cache/candles/...
  EURUSD         (   12.5 MB) -> cache/candles/EURUSD
  GBPUSD         (   10.3 MB) -> cache/candles/GBPUSD
  ... (70+ more)

Step 3: Moving tick cache files to cache/ticks/...
  EURUSD_20250101_20251120_INFO.parquet          (  250.0 MB)
  GBPUSD_20250101_20251120_INFO.parquet          (  180.0 MB)
  ...

Step 4: Moving tick archives to archives/...
  Exness_EURUSD_2025.zip                         (  125.3 MB)
  Exness_GBPUSD_2025.zip                         (   98.7 MB)
  ...

================================================================================
SUMMARY
================================================================================
Symbol directories moved:  72
Tick files moved:          15
Archive files moved:       8
Total data moved:          2,345.6 MB

✓ Reorganization complete!
================================================================================
```

---

## 🎯 Next Steps

After reorganization:

1. ✅ **Verify structure**: Check that files are in the right places
2. ✅ **Test backtest**: Run `python backtest.py` to ensure it works
3. ✅ **Update .gitignore**: Add `data/cache/` to ignore cached data
4. ✅ **Delete backup**: Once confirmed working, delete the backup to save space

---

## 📚 Additional Resources

- **Reorganization Script**: `tools/reorganize_data_directory.py`
- **Backtest Configuration**: `backtest.py` (lines 167-171, 642-650)
- **Data Cache Implementation**: `src/backtesting/engine/data_cache.py`
- **Archive Downloader**: `src/backtesting/engine/broker_archive_downloader.py`

---

## ❓ FAQ

### Q: Will this affect my live trading?
**A**: No. Live trading uses `data/positions.json` and `data/active.set` which stay at the root level.

### Q: Will I lose my cached data?
**A**: No. The script **moves** files, it doesn't delete them. Use `--backup` for extra safety.

### Q: Can I undo the reorganization?
**A**: Yes. If you created a backup, you can restore it. See "Rollback" section above.

### Q: Do I need to re-download data?
**A**: No. All existing cache files are moved to the new locations and will be used automatically.

### Q: What if I have custom paths in my code?
**A**: The reorganization script only moves files. If you have hardcoded paths, you'll need to update them manually.

---

**Ready to reorganize?** Start with a dry-run:

```bash
python tools/reorganize_data_directory.py --dry-run
```

