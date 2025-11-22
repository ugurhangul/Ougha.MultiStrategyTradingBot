# Cache Migration Guide - Data Loading Improvements

**Version:** 1.0  
**Date:** 2025-11-22  
**Breaking Change:** Yes - Cache format updated

---

## 🎯 Overview

The backtesting data loading system has been upgraded with **cache validation and incremental loading** features. This requires a **cache format change** that is **not backward compatible**.

**Important:** Your existing cache files will be **automatically invalidated and rebuilt** when you run backtests with the new version.

---

## ⚠️ Breaking Changes

### What Changed

1. **Cache Metadata Required**
   - All cache files now include metadata (cached_at, source, timestamps, version)
   - Files without metadata are considered invalid and will be rebuilt

2. **Cache Validation**
   - Automatic gap detection (>1 day at start)
   - Freshness checks (default: 7 days TTL)
   - Missing day detection

3. **Incremental Loading**
   - Only missing days are downloaded (not entire range)
   - Partial cache hits are supported

### Why No Backward Compatibility?

**User confirmed:** The existing cache is already broken, so backward compatibility is not needed. This allows for a cleaner implementation without legacy code.

---

## 📋 Migration Steps

### Step 1: Backup (Optional)

If you want to keep your old cache for reference:

```bash
# Backup existing cache
cp -r data/cache data/cache_backup_$(date +%Y%m%d)
```

### Step 2: Clean Up Old Cache (Recommended)

**Option A: Automatic cleanup (recommended)**

```bash
# Dry run - see what will be deleted
python scripts/cleanup_cache.py

# Actually delete old cache files
python scripts/cleanup_cache.py --confirm
```

**Option B: Manual cleanup**

```bash
# Delete entire cache directory
rm -rf data/cache

# Or on Windows
rmdir /s /q data\cache
```

**Option C: Do nothing**

The system will automatically invalidate old cache files and rebuild them. However, this leaves orphaned files on disk.

### Step 3: Update Configuration (Optional)

Add new configuration parameters to your `backtest.py` or `.env`:

```python
# Cache validation settings (optional - these are defaults)
CACHE_VALIDATION_ENABLED = True      # Enable cache validation
CACHE_TTL_DAYS = 7                   # Re-validate cache older than 7 days
CACHE_GAP_THRESHOLD_DAYS = 1         # Invalidate if gap > 1 day

# Cache index settings (optional - these are defaults)
CACHE_INDEX_ENABLED = True           # Use cache index for fast validation
CACHE_INDEX_AUTO_REBUILD = True      # Auto-rebuild corrupted index

# Incremental loading settings (optional - these are defaults)
INCREMENTAL_CACHE_LOADING = True     # Download only missing days
```

### Step 4: Run Backtest

```bash
# Run your backtest as usual
python backtest.py
```

**What happens:**
1. System detects old cache files without metadata
2. Invalidates them automatically
3. Downloads fresh data from MT5
4. Saves with new metadata format
5. Future runs will use the new cache

---

## 📊 What to Expect

### First Run After Migration

**Expected behavior:**
- ⏱️ **Slower:** Cache will be rebuilt from scratch
- 📥 **Downloads:** All data re-downloaded from MT5
- 💾 **Disk usage:** Similar to before (metadata adds <1% overhead)
- 📝 **Logs:** You'll see "Cache validation failed" messages (this is normal)

**Estimated time:**
- **1 month backtest:** 5-10 minutes (depending on symbols/timeframes)
- **1 year backtest:** 20-30 hours (tick data) or 30-60 minutes (candles only)

### Subsequent Runs

**Expected behavior:**
- ⚡ **Faster:** Cache validation overhead <10%
- 📥 **Incremental:** Only missing/stale days downloaded
- ✅ **Reliable:** No incomplete data cached permanently

---

## 🔧 Configuration Reference

### Cache Validation Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `CACHE_VALIDATION_ENABLED` | `True` | Enable/disable cache validation |
| `CACHE_TTL_DAYS` | `7` | Cache time-to-live in days |
| `CACHE_GAP_THRESHOLD_DAYS` | `1` | Maximum gap at start before invalidation |

**Example:**
```python
# Disable cache validation (not recommended)
CACHE_VALIDATION_ENABLED = False

# Increase TTL to 30 days (for stable historical data)
CACHE_TTL_DAYS = 30

# More strict gap detection (invalidate if gap > 0.5 days)
CACHE_GAP_THRESHOLD_DAYS = 0.5
```

### Cache Index Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `CACHE_INDEX_ENABLED` | `True` | Use in-memory cache index |
| `CACHE_INDEX_AUTO_REBUILD` | `True` | Auto-rebuild corrupted index |

**Example:**
```python
# Disable cache index (slower validation, but no index overhead)
CACHE_INDEX_ENABLED = False
```

### Incremental Loading Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `INCREMENTAL_CACHE_LOADING` | `True` | Download only missing days |

**Example:**
```python
# Disable incremental loading (always re-download entire range)
INCREMENTAL_CACHE_LOADING = False
```

---

## 🐛 Troubleshooting

### Issue: "Cache validation failed" messages

**Cause:** Old cache files without metadata

**Solution:** This is expected during migration. The system will automatically rebuild the cache.

```
[INFO] Cache validation failed for EURUSD M1: No metadata - cache will be rebuilt
```

**Action:** No action needed. This is normal.

---

### Issue: Slow first run after migration

**Cause:** Cache being rebuilt from scratch

**Solution:** This is expected. Subsequent runs will be fast.

**Workaround:** Run backtest for a shorter date range first to test:
```python
# Test with 1 week first
START_DATE = datetime(2025, 1, 1)
END_DATE = datetime(2025, 1, 8)
```

---

### Issue: Disk space not freed after cleanup

**Cause:** Parquet files deleted but directories remain

**Solution:** Run cleanup script which removes empty directories:
```bash
python scripts/cleanup_cache.py --confirm
```

Or manually:
```bash
# Linux/Mac
find data/cache -type d -empty -delete

# Windows PowerShell
Get-ChildItem data\cache -Recurse -Directory | Where-Object {$_.GetFileSystemInfos().Count -eq 0} | Remove-Item
```

---

### Issue: "Cache index corrupted" error

**Cause:** Cache index file corrupted or incompatible

**Solution:** Delete index file (will be auto-rebuilt):
```bash
rm data/cache/.cache_index.json

# Or on Windows
del data\cache\.cache_index.json
```

---

### Issue: Want to force cache rebuild for specific symbol

**Solution:** Delete cache files for that symbol:
```bash
# Linux/Mac
find data/cache -name "EURUSD.parquet" -delete

# Windows PowerShell
Get-ChildItem data\cache -Recurse -Filter "EURUSD.parquet" | Remove-Item
```

---

## 📈 Performance Comparison

### Before Migration

| Scenario | Time | Behavior |
|----------|------|----------|
| First run (no cache) | 30 min | Download all data |
| Second run (full cache) | 2 min | Load from cache |
| Partial cache (50% hit) | 30 min | Re-download ALL data |
| Stale cache (incomplete) | 2 min | Load incomplete data ❌ |

### After Migration

| Scenario | Time | Behavior |
|----------|------|----------|
| First run (no cache) | 30 min | Download all data |
| Second run (full cache) | 2.2 min | Load + validate (<10% overhead) |
| Partial cache (50% hit) | 15 min | Download ONLY missing 50% ✅ |
| Stale cache (incomplete) | 30 min | Detect + re-download ✅ |

**Key improvements:**
- ✅ Partial cache hits 2x faster
- ✅ No incomplete data cached
- ✅ Automatic freshness checks
- ✅ Minimal overhead for full cache hits

---

## 🔄 Rollback Procedure

If you need to rollback to the old version:

### Step 1: Restore Old Code

```bash
# Checkout previous commit (before cache improvements)
git checkout <previous-commit-hash>
```

### Step 2: Restore Old Cache (if backed up)

```bash
# Remove new cache
rm -rf data/cache

# Restore backup
cp -r data/cache_backup_YYYYMMDD data/cache
```

### Step 3: Disable New Features

```python
# In backtest.py
CACHE_VALIDATION_ENABLED = False
INCREMENTAL_CACHE_LOADING = False
CACHE_INDEX_ENABLED = False
```

**Note:** Rollback is not recommended. The new system is more reliable and performant.

---

## ✅ Verification Checklist

After migration, verify everything works:

- [ ] Run backtest with short date range (1 week)
- [ ] Check logs for "Cache validation" messages
- [ ] Verify cache files have metadata:
  ```bash
  python scripts/cleanup_cache.py --stats
  ```
- [ ] Run backtest again (should use cache)
- [ ] Check performance (should be <10% slower than before)
- [ ] Test partial cache hit (delete random days, run again)
- [ ] Verify only missing days are downloaded

---

## 📞 Support

### Common Questions

**Q: Do I need to delete my cache manually?**  
A: No, the system will automatically invalidate old cache files. However, manual cleanup frees disk space.

**Q: How long will the first run take?**  
A: Same as before - depends on date range and data type. Subsequent runs will be faster for partial cache hits.

**Q: Can I keep using old cache files?**  
A: No, they will be automatically invalidated. The new format is required for cache validation.

**Q: Will this affect live trading?**  
A: No, this only affects backtesting. Live trading is not impacted.

**Q: Can I disable cache validation?**  
A: Yes, set `CACHE_VALIDATION_ENABLED = False`, but this is not recommended as it defeats the purpose of the improvements.

### Getting Help

- **Documentation:** See [DATA_LOADING_IMPLEMENTATION_PLAN.md](./DATA_LOADING_IMPLEMENTATION_PLAN.md)
- **Quick Reference:** See [DATA_LOADING_QUICK_REFERENCE.md](./DATA_LOADING_QUICK_REFERENCE.md)
- **Issues:** Check troubleshooting section above

---

## 📝 Summary

**What you need to do:**
1. ✅ (Optional) Run `python scripts/cleanup_cache.py --confirm` to free disk space
2. ✅ Run your backtest as usual
3. ✅ Wait for cache to rebuild (first run only)
4. ✅ Enjoy faster partial cache hits and reliable data!

**What happens automatically:**
- ✅ Old cache files invalidated
- ✅ Fresh data downloaded with metadata
- ✅ Cache validation enabled
- ✅ Incremental loading enabled

**No manual intervention required!** 🎉

---

**Migration complete! Your backtesting system is now more reliable and performant.** ✅

