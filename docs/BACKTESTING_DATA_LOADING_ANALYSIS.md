# Backtesting Data Loading Phase - Comprehensive Analysis

**Date:** 2025-11-21  
**Scope:** Analysis of data loading architecture, caching, memory management, and performance characteristics

---

## Executive Summary

The backtesting data loading system implements a sophisticated multi-tier architecture with:
- ✅ **Day-by-day granular caching** (YYYY/MM/DD hierarchy)
- ✅ **Parallel data loading** (10 days concurrently for ticks)
- ✅ **Multi-source fallback** (MT5 → Broker Archives)
- ✅ **Streaming tick support** (memory-efficient for full-year backtests)
- ⚠️ **Partial lazy loading** (ticks only, candles loaded upfront)
- ⚠️ **Cache validation gaps** (no automatic refresh on incomplete data)

**Key Finding:** The system loads ALL candle data upfront into memory, but only streams tick data. For full-year backtests, this creates a memory asymmetry where candles consume ~500MB-1GB while ticks are streamed from disk.

---

## 1. Architecture & Flow

### 1.1 Data Loading Sequence

```
┌─────────────────────────────────────────────────────────────┐
│                    BACKTEST DATA LOADING                     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────────┐
        │  For Each Symbol (Async Parallel)     │
        └───────────────────────────────────────┘
                            │
        ┌───────────────────┴────────────────────┐
        ▼                                        ▼
┌──────────────────┐                  ┌──────────────────┐
│  STEP 1: TICKS   │                  │  STEP 2: CANDLES │
│  (if enabled)    │                  │  (all timeframes)│
└──────────────────┘                  └──────────────────┘
        │                                        │
        ▼                                        ▼
┌──────────────────┐                  ┌──────────────────┐
│ Day-by-Day Load  │                  │ Full Range Load  │
│ (parallel batch) │                  │ (per timeframe)  │
└──────────────────┘                  └──────────────────┘
        │                                        │
        ▼                                        ▼
┌──────────────────┐                  ┌──────────────────┐
│ Cache → MT5 →    │                  │ Cache → MT5 →    │
│ Archive Fallback │                  │ Build from Ticks │
└──────────────────┘                  └──────────────────┘
```

### 1.2 Component Responsibilities

| Component | Responsibility | Key Methods |
|-----------|---------------|-------------|
| **BacktestDataLoader** | Orchestrates data loading, manages MT5 connection | `load_from_mt5()`, `load_ticks_from_mt5()`, `_build_candles_from_ticks()` |
| **DataCache** | Day-level caching for candles/ticks | `load_from_cache()`, `save_to_cache()` |
| **BrokerArchiveDownloader** | Fetches historical data from external archives | `fetch_tick_data()`, `parse_archive()` |
| **StreamingTickLoader** | Memory-efficient tick streaming | `stream_ticks()`, `_read_symbol_chunks()` |

### 1.3 MT5 API Calls

**Candle Data:**
- `mt5.copy_rates_range(symbol, timeframe, start_date, end_date)` - Primary method
- Called once per symbol/timeframe combination
- Returns numpy structured array with OHLCV data

**Tick Data:**
- `mt5.copy_ticks_range(symbol, start_date, end_date, tick_type)` - Primary method
- Called once per day (in parallel batches of 10)
- Returns numpy structured array with tick data (time, bid, ask, last, volume, flags)

**Fallback Chain:**
```
Candles: Cache → MT5 copy_rates_range → Build from Ticks
Ticks:   Cache → MT5 copy_ticks_range → Broker Archive
```

---

## 2. Caching Strategy

### 2.1 Cache Structure

```
data/cache/
├── 2025/
│   ├── 01/
│   │   ├── 01/
│   │   │   ├── candles/
│   │   │   │   ├── EURUSD_M1.parquet
│   │   │   │   ├── EURUSD_M5.parquet
│   │   │   │   ├── EURUSD_M15.parquet
│   │   │   │   └── EURUSD_H4.parquet
│   │   │   ├── ticks/
│   │   │   │   ├── EURUSD_INFO.parquet
│   │   │   │   └── GBPUSD_INFO.parquet
│   │   │   └── symbol_info/
│   │   │       ├── EURUSD.json
│   │   │       └── GBPUSD.json
│   │   ├── 02/
│   │   │   └── ... (same structure)
```

**Benefits:**
- ✅ Easy to manage/delete old data (remove date directories)
- ✅ Clear visibility of cached date ranges
- ✅ Efficient day-by-day loading for streaming
- ✅ Parallel-safe (each day is independent file)

### 2.2 Cache Loading Logic

**Candles (DataCache.load_from_cache):**
```python
# Location: src/backtesting/engine/data_cache.py:143-221

1. Get list of days in requested range
2. For each day:
   - Check if cache file exists (YYYY/MM/DD/candles/SYMBOL_TF.parquet)
   - If ANY day missing → return None (triggers full reload)
   - Load day's data using PyArrow engine
3. Merge all daily DataFrames
4. Filter to exact requested date range
5. Return merged data + symbol_info
```

**Ticks (BacktestDataLoader.load_ticks_from_mt5):**
```python
# Location: src/backtesting/engine/data_loader.py:577-793

1. Get list of days in requested range
2. Process days in parallel batches (default: 10 concurrent)
3. For each day (in parallel):
   - Check cache (YYYY/MM/DD/ticks/SYMBOL_TICKTYPE.parquet)
   - If cached: Load from parquet (0.1-0.5s per day)
   - If not cached: Download from MT5 or Archive
4. Merge all daily DataFrames
5. Filter to exact requested range
```

### 2.3 Cache Validation

**Current Implementation:**
```python
# Location: src/backtesting/engine/data_loader.py:147-157

# Check if MT5 data covers this day (starts within 1 day of requested start)
actual_start = df['time'].iloc[0]
start_diff_days = (actual_start - day_start).total_seconds() / 86400

if start_diff_days <= 1:
    # MT5 has data for this day - cache it and return
    if cache_path:
        self._save_tick_cache(df, cache_path)
    return df
else:
    # MT5 data doesn't cover this day - try archive
```

**Issues Identified:**

1. **No Gap Detection After Caching**
   - Once data is cached, it's never re-validated
   - If MT5 initially had incomplete data (e.g., only last 2 hours of a day), that incomplete data is cached permanently
   - User preference: "if cached data has a gap >1 day from requested START_DATE, re-fetch from MT5"

2. **No Freshness Checks**
   - No timestamp tracking for when cache was created
   - No mechanism to detect if MT5 now has more complete historical data
   - User preference: "check if MT5 now has more complete data, and update cache if MT5's historical availability improves"

3. **All-or-Nothing Cache Loading**
   - If ANY day is missing, entire date range is re-downloaded
   - Could be optimized to only download missing days

### 2.4 Cache Invalidation

**Current Triggers:**
- Manual: `data_loader.clear_cache(symbol)` or `data_loader.clear_cache()`
- Force refresh: `FORCE_REFRESH = True` in backtest.py
- Corrupted files: Automatically deleted on read error

**Missing Triggers:**
- ❌ Automatic validation on load (gap detection)
- ❌ TTL-based expiration
- ❌ Version-based invalidation (if data format changes)

---

## 3. Memory Management

### 3.1 Current Memory Usage Patterns

**Candle Data (LOADED UPFRONT):**
```python
# Location: backtest.py:1073-1152

# All timeframes loaded into memory for entire date range
symbol_data[(symbol, 'M1')] = df_m1   # ~500K rows for 1 year
symbol_data[(symbol, 'M5')] = df_m5   # ~100K rows for 1 year
symbol_data[(symbol, 'M15')] = df_m15 # ~35K rows for 1 year
symbol_data[(symbol, 'H4')] = df_h4   # ~2K rows for 1 year

# Memory estimate for 4 symbols, 5 timeframes, 1 year:
# ~4 symbols × 5 TFs × 100K avg rows × 80 bytes/row = ~160 MB
```

**Tick Data (STREAMED):**
```python
# Location: src/backtesting/engine/streaming_tick_loader.py:207-295

# Ticks loaded in chunks (default: 100K ticks per chunk)
for batch in parquet_file.iter_batches(batch_size=self.chunk_size):
    chunk_df = batch.to_pandas()  # Only this chunk in memory
    # Process chunk
    del chunk_df  # Free immediately
```

### 3.2 Memory Footprint Analysis

**Full Year Backtest (2025-01-01 to 2025-11-21, 4 symbols):**

| Data Type | Loading Strategy | Memory Usage | Notes |
|-----------|-----------------|--------------|-------|
| **Candles** | All upfront | ~500 MB - 1 GB | 5 timeframes × 4 symbols × 325 days |
| **Ticks** | Streaming | ~2-3 GB peak | 100K chunk size, ~1.8B total ticks |
| **Symbol Info** | All upfront | ~1 MB | Negligible |
| **Broker State** | Runtime | ~100-500 MB | Positions, orders, equity curve |
| **Strategy State** | Runtime | ~50-200 MB | Indicators, signals, history |
| **TOTAL** | | **~3-5 GB** | With streaming enabled |

**Without Streaming (Legacy):**
- Ticks loaded upfront: ~20-30 GB
- Total memory: ~25-35 GB

### 3.3 Granularity Analysis

**Current Implementation:**
- ✅ **Ticks:** Day-by-day loading (parallel batches of 10)
- ❌ **Candles:** Full date range loaded at once

**User Preference:** "day-by-day data loading granularity instead of month-by-month"

**Current Status:**
- Ticks: ✅ Already day-by-day
- Candles: ❌ Still full-range (could be optimized to day-by-day)

**Optimization Opportunity:**
```python
# Current: Load all candles for entire year
df_m1 = data_loader.load_from_mt5('EURUSD', 'M1', 
                                   datetime(2025, 1, 1), 
                                   datetime(2025, 11, 21))

# Proposed: Load candles day-by-day (lazy)
for day in date_range:
    df_m1_day = data_loader.load_from_mt5('EURUSD', 'M1',
                                           day, day + timedelta(days=1))
    # Process day
    # Free memory
```

### 3.4 Streaming vs Upfront Loading

**Streaming (Ticks):**
- ✅ Memory-efficient (~2-3 GB vs ~20-30 GB)
- ✅ Supports full-year backtests on 16GB RAM machines
- ⚠️ Slightly slower (disk I/O overhead)
- ⚠️ Requires cached data (can't stream from MT5 API directly)

**Upfront (Candles):**
- ✅ Faster access (no disk I/O during backtest)
- ✅ Simpler code (no streaming logic)
- ⚠️ Higher memory usage (~500MB-1GB for full year)
- ⚠️ Limits backtest duration on low-RAM machines

---

## 4. Data Fallback Logic

### 4.1 Tick Data Fallback Chain

```
┌─────────────────────────────────────────────────────────┐
│              TICK DATA LOADING FALLBACK                  │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
              ┌──────────────────┐
              │  Check Cache     │
              │  (Day-level)     │
              └──────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │ Cached?                         │
        ▼                                 ▼
    ┌───────┐                      ┌──────────────┐
    │  YES  │                      │     NO       │
    └───────┘                      └──────────────┘
        │                                 │
        ▼                                 ▼
┌──────────────┐              ┌──────────────────────┐
│ Load from    │              │ Try MT5              │
│ Parquet      │              │ copy_ticks_range()   │
│ (0.1-0.5s)   │              └──────────────────────┘
└──────────────┘                         │
                        ┌────────────────┴────────────────┐
                        │ MT5 has data for this day?      │
                        ▼                                 ▼
                   ┌────────┐                      ┌──────────┐
                   │  YES   │                      │    NO    │
                   └────────┘                      └──────────┘
                        │                                 │
                        ▼                                 ▼
              ┌──────────────────┐          ┌──────────────────────┐
              │ Cache & Return   │          │ Try Broker Archive   │
              └──────────────────┘          └──────────────────────┘
                                                       │
                                      ┌────────────────┴────────────────┐
                                      │ Archive has data?               │
                                      ▼                                 ▼
                                 ┌────────┐                      ┌──────────┐
                                 │  YES   │                      │    NO    │
                                 └────────┘                      └──────────┘
                                      │                                 │
                                      ▼                                 ▼
                            ┌──────────────────┐              ┌──────────────┐
                            │ Parse, Cache &   │              │ Return None  │
                            │ Return           │              └──────────────┘
                            └──────────────────┘
```

**Implementation:** `BacktestDataLoader._download_day_ticks()` (data_loader.py:105-213)

### 4.2 Candle Data Fallback Chain

```
┌─────────────────────────────────────────────────────────┐
│             CANDLE DATA LOADING FALLBACK                 │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
              ┌──────────────────┐
              │  Check Cache     │
              │  (Day-level)     │
              └──────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │ All days cached?                │
        ▼                                 ▼
    ┌───────┐                      ┌──────────────┐
    │  YES  │                      │     NO       │
    └───────┘                      └──────────────┘
        │                                 │
        ▼                                 ▼
┌──────────────┐              ┌──────────────────────┐
│ Load & Merge │              │ Try MT5              │
│ Daily Files  │              │ copy_rates_range()   │
└──────────────┘              └──────────────────────┘
                                         │
                        ┌────────────────┴────────────────┐
                        │ MT5 has candle data?            │
                        ▼                                 ▼
                   ┌────────┐                      ┌──────────┐
                   │  YES   │                      │    NO    │
                   └────────┘                      └──────────┘
                        │                                 │
                        ▼                                 ▼
              ┌──────────────────┐          ┌──────────────────────┐
              │ Cache & Return   │          │ Build from Ticks     │
              └──────────────────┘          └──────────────────────┘
                                                       │
                                      ┌────────────────┴────────────────┐
                                      │ Ticks available?                │
                                      ▼                                 ▼
                                 ┌────────┐                      ┌──────────┐
                                 │  YES   │                      │    NO    │
                                 └────────┘                      └──────────┘
                                      │                                 │
                                      ▼                                 ▼
                            ┌──────────────────┐              ┌──────────────┐
                            │ Resample Ticks   │              │ Return None  │
                            │ to Candles,      │              │ (FAIL)       │
                            │ Cache & Return   │              └──────────────┘
                            └──────────────────┘
```

**Implementation:** `BacktestDataLoader.load_from_mt5()` (data_loader.py:224-261)

### 4.3 Candle Building from Ticks

**Method:** `BacktestDataLoader._build_candles_from_ticks()` (data_loader.py:367-462)

**Process:**
1. Use pre-loaded ticks if available (passed as parameter)
2. Otherwise, load ticks from MT5 using `copy_ticks_range()`
3. Resample ticks to desired timeframe using pandas:
   ```python
   candles = df_ticks['price'].resample(resample_freq).agg(['first', 'max', 'min', 'last'])
   ```
4. Add tick_volume (count of ticks per period)
5. Cache built candles for future use

**Supported Timeframes:**
- M1, M5, M15, M30, H1, H4, D1

**Performance:**
- Building from ticks: ~5-10 seconds for 1 year of M1 candles
- Loading from cache: ~0.5-1 second

**User Preference Compliance:**
✅ "if MT5 doesn't have candle data for a date, build the candles from the tick data instead of failing"

---

## 5. Performance Characteristics

### 5.1 Data Loading Benchmarks

**Tick Data (1 day, EURUSD, INFO type):**
| Source | Time | Notes |
|--------|------|-------|
| Cache hit | 0.1-0.5s | Parquet read |
| MT5 download | 2-5s | Network + API |
| Archive download | 10-60s | First time only |
| Archive cached | 0.6s | Parquet read (full year) |

**Candle Data (1 year, EURUSD, M1):**
| Source | Time | Notes |
|--------|------|-------|
| Cache hit | 0.5-1s | Merge 325 daily files |
| MT5 download | 3-8s | Network + API |
| Build from ticks | 5-10s | Resample operation |

**Full Year Backtest (4 symbols, 5 timeframes, tick mode):**
| Phase | Time | Notes |
|-------|------|-------|
| First run (no cache) | 30-60 min | Download + cache all data |
| Second run (cached) | 2-5 min | Load from cache |
| Tick streaming setup | 10-20s | Count ticks, build file list |

### 5.2 Bottlenecks Identified

1. **Parallel Tick Loading Overhead**
   - Location: `data_loader.py:752-768`
   - Issue: ThreadPoolExecutor overhead for small batches
   - Impact: ~10-20% overhead for <100 days
   - Mitigation: Increase `parallel_days` for longer backtests

2. **Cache Validation on Every Load**
   - Location: `data_cache.py:163-168`
   - Issue: Checks existence of every daily file
   - Impact: ~0.1-0.5s for 325 days
   - Mitigation: Could cache file list in memory

3. **DataFrame Merging**
   - Location: `data_cache.py:207-215`
   - Issue: Concatenating 325 daily DataFrames
   - Impact: ~0.5-1s per symbol/timeframe
   - Mitigation: Already optimized with PyArrow

4. **Tick Count Estimation**
   - Location: `streaming_tick_loader.py:344-404`
   - Issue: Opens every parquet file to read metadata
   - Impact: ~1-2s for 325 days × 4 symbols
   - Mitigation: Fast estimation mode (uses file size)

### 5.3 Network/API Call Efficiency

**MT5 API Calls (per symbol, full year backtest):**
- Candles: 5 calls (one per timeframe)
- Ticks: 325 calls (one per day, but parallelized in batches of 10)

**Optimization:**
- ✅ Parallel execution (10 concurrent tick downloads)
- ✅ Caching (subsequent runs: 0 API calls)
- ⚠️ No request batching (MT5 API doesn't support)

**Archive Downloads:**
- First run: 1 download per symbol/year (~100-500 MB each)
- Cached: 0 downloads
- Parsed archives split into daily files automatically

---

## 6. Issues & Improvements

### 6.1 Critical Issues

**ISSUE #1: No Automatic Cache Validation**
- **Problem:** Cached data never re-validated, even if incomplete
- **Impact:** Permanently stores incomplete datasets
- **User Preference:** "if cached data has a gap >1 day from requested START_DATE, re-fetch from MT5"
- **Solution:** Add gap detection in `DataCache.load_from_cache()`:
  ```python
  # Check if first cached day is >1 day after requested start
  if first_day_in_cache - start_date > timedelta(days=1):
      # Re-fetch from MT5 to check for newer data
      return None
  ```

**ISSUE #2: Candles Not Lazy-Loaded**
- **Problem:** All candles loaded upfront (500MB-1GB for full year)
- **Impact:** Unnecessary memory usage, limits backtest duration
- **User Preference:** "lazy/streaming data loading (load data while advancing through backtest)"
- **Solution:** Implement day-by-day candle loading similar to ticks

**ISSUE #3: All-or-Nothing Cache Loading**
- **Problem:** If ANY day missing, re-downloads entire range
- **Impact:** Wastes time re-downloading already-cached days
- **Solution:** Download only missing days, merge with cached data

### 6.2 Performance Improvements

**IMPROVEMENT #1: Candle Streaming**
- **Current:** All candles loaded upfront
- **Proposed:** Stream candles day-by-day like ticks
- **Benefit:** Reduce memory by ~500MB-1GB
- **Complexity:** Medium (requires refactoring BacktestController)

**IMPROVEMENT #2: Incremental Cache Loading**
- **Current:** All-or-nothing (missing 1 day = reload all)
- **Proposed:** Load cached days, download only missing
- **Benefit:** Faster partial cache hits
- **Complexity:** Low (modify `DataCache.load_from_cache()`)

**IMPROVEMENT #3: Cache Metadata Index**
- **Current:** Scans filesystem for every cache check
- **Proposed:** Maintain index file (cache_index.json) with available date ranges
- **Benefit:** Faster cache validation (~0.5s → ~0.01s)
- **Complexity:** Medium (requires index management)

### 6.3 Recommended Action Plan

**Priority 1 (Critical):**
1. ✅ Implement automatic cache validation with gap detection
2. ✅ Add cache refresh trigger when MT5 has newer data

**Priority 2 (High):**
3. ⚠️ Implement incremental cache loading (download only missing days)
4. ⚠️ Add cache metadata index for faster validation

**Priority 3 (Medium):**
5. ⏸️ Implement lazy candle loading (day-by-day streaming)
6. ⏸️ Add TTL-based cache expiration

**Priority 4 (Low):**
7. ⏸️ Optimize tick count estimation (already has fast mode)
8. ⏸️ Add cache compression options (already uses Snappy)

---

## 7. Compliance with User Preferences

| Preference | Status | Notes |
|------------|--------|-------|
| Lazy/streaming data loading | ⚠️ Partial | Ticks: ✅ Streamed<br>Candles: ❌ Upfront |
| Day-by-day granularity | ⚠️ Partial | Ticks: ✅ Day-by-day<br>Candles: ❌ Full range |
| Cache validation & refresh | ❌ Missing | No gap detection, no freshness checks |
| Prioritize tick data first | ✅ Implemented | Ticks loaded before candles |
| Build candles from ticks | ✅ Implemented | Automatic fallback when MT5 lacks candles |

---

## 8. Conclusion

The backtesting data loading system is well-architected with strong caching and fallback mechanisms. However, there are opportunities for improvement:

**Strengths:**
- ✅ Day-by-day tick caching with parallel loading
- ✅ Multi-tier fallback (MT5 → Archives)
- ✅ Memory-efficient tick streaming
- ✅ Automatic candle building from ticks

**Weaknesses:**
- ❌ No cache validation (gap detection, freshness)
- ❌ Candles loaded upfront (not lazy)
- ❌ All-or-nothing cache loading

**Next Steps:**
1. Implement cache validation with gap detection
2. Add incremental cache loading
3. Consider lazy candle loading for very long backtests (>1 year)

---

## Appendix A: Code Reference Index

### A.1 Key Files and Line Numbers

**backtest.py** (2037 lines)
- Configuration: Lines 1-100
- Data loading orchestration: Lines 1000-1200
- Async symbol loading: Lines 1014-1164
- Tick progress callback: Lines 1033-1045

**src/backtesting/engine/data_loader.py** (809 lines)
- `BacktestDataLoader` class: Lines 1-809
- `load_from_mt5()` (candles): Lines 224-261
- `_download_from_mt5()` (candles with fallback): Lines 263-365
- `_build_candles_from_ticks()`: Lines 367-462
- `load_ticks_from_mt5()`: Lines 577-793
- `_download_day_ticks()`: Lines 105-213
- `_get_tick_cache_path()`: Lines 56-80
- Cache validation logic: Lines 147-157

**src/backtesting/engine/data_cache.py** (444 lines)
- `DataCache` class: Lines 1-444
- `load_from_cache()`: Lines 143-221
- `save_to_cache()`: Lines 223-282
- `_get_day_cache_path()`: Lines 54-75
- Cache miss detection: Lines 163-168
- Daily file merging: Lines 207-215

**src/backtesting/engine/streaming_tick_loader.py** (418 lines)
- `StreamingTickLoader` class: Lines 1-418
- `GlobalTick` dataclass: Lines 21-38
- `stream_ticks()`: Lines 135-184
- `_read_symbol_chunks()`: Lines 207-295
- `_build_cache_file_list()`: Lines 87-133
- Tick count estimation: Lines 344-404

**src/backtesting/engine/broker_archive_downloader.py** (922 lines)
- `BrokerArchiveDownloader` class: Lines 38-922
- `fetch_tick_data()`: Lines 735-900
- `parse_archive()`: Lines 400-600 (approx)
- `_split_and_cache_by_day()`: Lines 650-733
- In-memory cache management: Lines 69-87, 801-884

### A.2 Critical Code Sections

**Cache Validation (NEEDS IMPROVEMENT):**
```python
# Location: data_loader.py:147-157
# Current: Only validates on initial download, not on cache load
actual_start = df['time'].iloc[0]
start_diff_days = (actual_start - day_start).total_seconds() / 86400

if start_diff_days <= 1:
    # MT5 has data for this day - cache it
    if cache_path:
        self._save_tick_cache(df, cache_path)
    return df
else:
    # MT5 data doesn't cover this day - try archive
    # ISSUE: This check only runs on download, not when loading from cache
```

**All-or-Nothing Cache Loading (NEEDS IMPROVEMENT):**
```python
# Location: data_cache.py:163-168
# Current: Returns None if ANY day is missing
for day in days:
    day_cache_path = self._get_day_cache_path(symbol, day, timeframe, data_type)
    if not day_cache_path.exists():
        # Missing day - return None to trigger full reload
        # ISSUE: Could download only missing days instead
        return None
```

**Parallel Tick Loading (OPTIMIZED):**
```python
# Location: data_loader.py:752-768
# Current: Efficiently loads days in parallel batches
with ThreadPoolExecutor(max_workers=parallel_days) as executor:
    futures = []
    for day in days:
        future = executor.submit(self._download_day_ticks, symbol, day, ...)
        futures.append((day, future))

    for day, future in futures:
        df = future.result()
        if df is not None:
            all_ticks.append(df)
```

**Streaming Tick Reader (OPTIMIZED):**
```python
# Location: streaming_tick_loader.py:207-295
# Current: Efficiently streams ticks in chunks
for batch in parquet_file.iter_batches(batch_size=self.chunk_size):
    chunk_df = batch.to_pandas()

    # Vectorized operations for speed
    times_np = chunk_df['time'].to_numpy()
    bids_np = chunk_df['bid'].to_numpy()
    asks_np = chunk_df['ask'].to_numpy()

    # Yield ticks one by one
    for i in range(len(chunk_df)):
        yield GlobalTick(...)
```

### A.3 Configuration Parameters

**backtest.py:**
- `PARALLEL_TICK_DAYS = 10` - Number of days to load concurrently
- `STREAM_TICKS_FROM_DISK = True` - Enable tick streaming
- `USE_TICK_DATA = True` - Enable tick-level backtesting
- `FORCE_REFRESH = False` - Force cache refresh

**streaming_tick_loader.py:**
- `chunk_size = 100000` - Ticks per chunk when streaming
- `fast_estimation = True` - Use file size for tick count estimation

**broker_archive_downloader.py:**
- `_use_memory_cache = False` - Disable in-memory archive cache (saves RAM)
- `max_retries = 3` - Archive download retry attempts
- `download_timeout_seconds = 300` - Archive download timeout

### A.4 Performance Metrics

**Measured Timings (from code comments and logs):**
- Cache hit (1 day ticks): 0.1-0.5s
- MT5 download (1 day ticks): 2-5s
- Archive download (1 year): 10-60s (first time)
- Archive cached read (1 year): 0.6s
- Candle cache hit (1 year): 0.5-1s
- Candle MT5 download (1 year): 3-8s
- Build candles from ticks (1 year M1): 5-10s
- Full backtest data load (cached): 2-5 min
- Full backtest data load (uncached): 30-60 min

---

## Appendix B: Detailed Improvement Specifications

### B.1 Cache Validation Implementation

**File:** `src/backtesting/engine/data_cache.py`

**Changes Required:**

1. Add metadata tracking to cache files:
```python
# Add to each cached parquet file's metadata
metadata = {
    'cached_at': datetime.now().isoformat(),
    'source': 'mt5',  # or 'archive'
    'first_tick_time': df['time'].iloc[0].isoformat(),
    'last_tick_time': df['time'].iloc[-1].isoformat(),
    'tick_count': len(df)
}
```

2. Modify `load_from_cache()` to validate:
```python
def load_from_cache(self, symbol, start_date, end_date, timeframe, data_type):
    # ... existing code ...

    # NEW: Validate first day for gaps
    first_day_path = self._get_day_cache_path(symbol, days[0], timeframe, data_type)
    if first_day_path.exists():
        # Read metadata
        pf = pq.ParquetFile(first_day_path)
        metadata = pf.schema_arrow.metadata

        if metadata and b'first_tick_time' in metadata:
            first_tick_time = datetime.fromisoformat(metadata[b'first_tick_time'].decode())
            gap_days = (first_tick_time - start_date).total_seconds() / 86400

            if gap_days > 1:
                # Gap detected - invalidate cache
                self.logger.warning(f"Cache gap detected: {gap_days:.1f} days")
                return None

    # ... rest of existing code ...
```

### B.2 Incremental Cache Loading

**File:** `src/backtesting/engine/data_cache.py`

**Changes Required:**

```python
def load_from_cache(self, symbol, start_date, end_date, timeframe, data_type):
    days = self._get_days_in_range(start_date, end_date)

    cached_days = []
    missing_days = []

    # Separate cached vs missing days
    for day in days:
        day_cache_path = self._get_day_cache_path(symbol, day, timeframe, data_type)
        if day_cache_path.exists():
            cached_days.append(day)
        else:
            missing_days.append(day)

    # NEW: Return partial result with missing days list
    if len(cached_days) == 0:
        return None, missing_days  # No cache at all

    # Load cached days
    daily_dfs = []
    for day in cached_days:
        day_cache_path = self._get_day_cache_path(symbol, day, timeframe, data_type)
        df = pd.read_parquet(day_cache_path, engine='pyarrow')
        daily_dfs.append(df)

    merged_df = pd.concat(daily_dfs, ignore_index=True)

    # Return partial data + missing days list
    return merged_df, missing_days
```

### B.3 Lazy Candle Loading

**File:** `src/backtesting/engine/backtest_controller.py` (hypothetical)

**Changes Required:**

```python
class LazyDataProvider:
    """Provides data on-demand during backtest execution."""

    def __init__(self, data_loader, symbols, timeframes, start_date, end_date):
        self.data_loader = data_loader
        self.symbols = symbols
        self.timeframes = timeframes
        self.start_date = start_date
        self.end_date = end_date

        # Cache for current day's data
        self.current_day = None
        self.current_data = {}

    def get_candles(self, symbol, timeframe, current_time):
        """Get candles for current day, loading on-demand."""
        day = current_time.date()

        # Check if we need to load new day
        if day != self.current_day:
            self._load_day(day)
            self.current_day = day

        # Return cached data for current day
        return self.current_data.get((symbol, timeframe))

    def _load_day(self, day):
        """Load all symbols/timeframes for a single day."""
        day_start = datetime.combine(day, datetime.min.time())
        day_end = day_start + timedelta(days=1)

        # Clear previous day's data
        self.current_data.clear()

        # Load all symbols/timeframes for this day
        for symbol in self.symbols:
            for timeframe in self.timeframes:
                df = self.data_loader.load_from_mt5(
                    symbol, timeframe, day_start, day_end
                )
                self.current_data[(symbol, timeframe)] = df
```

---

## Appendix C: Testing Recommendations

### C.1 Cache Validation Tests

**Test Cases:**
1. **Gap Detection Test**
   - Create cache with 2-day gap at start
   - Verify cache is invalidated
   - Verify re-download from MT5

2. **Freshness Test**
   - Create cache with old timestamp (>7 days)
   - Verify re-validation triggered
   - Verify cache updated if MT5 has newer data

3. **Partial Data Test**
   - Create cache with incomplete day (only 2 hours)
   - Verify gap detection catches it
   - Verify re-download fills missing hours

### C.2 Incremental Loading Tests

**Test Cases:**
1. **Partial Cache Hit**
   - Cache days 1-5, request days 1-10
   - Verify days 1-5 loaded from cache
   - Verify days 6-10 downloaded from MT5
   - Verify merged result is correct

2. **Interleaved Missing Days**
   - Cache days 1,3,5,7,9
   - Request days 1-10
   - Verify cached days loaded
   - Verify missing days downloaded
   - Verify chronological merge

### C.3 Performance Tests

**Test Cases:**
1. **Full Year Load Time**
   - Measure time to load 365 days (cached)
   - Target: <5 minutes
   - Verify parallel loading efficiency

2. **Memory Usage**
   - Monitor memory during full year backtest
   - Target: <5GB with streaming
   - Verify no memory leaks

3. **Cache Hit Rate**
   - Run backtest twice
   - Verify 100% cache hit on second run
   - Verify <5 min load time on second run

