# Data Loading Improvements - Quick Start Guide

**For developers ready to start implementing the improvements**

---

## 🚀 Getting Started

### Prerequisites

1. **Read the analysis documents:**
   - [BACKTESTING_DATA_LOADING_ANALYSIS.md](./BACKTESTING_DATA_LOADING_ANALYSIS.md) - Full analysis
   - [DATA_LOADING_IMPLEMENTATION_PLAN.md](./DATA_LOADING_IMPLEMENTATION_PLAN.md) - Detailed plan

2. **Set up development environment:**
   ```bash
   # Create feature branch
   git checkout -b feature/cache-validation-improvements
   
   # Ensure dependencies installed
   pip install -r requirements.txt
   
   # Run existing tests to ensure baseline
   pytest tests/backtesting/engine/
   ```

3. **Review current code:**
   - `src/backtesting/engine/data_cache.py` (444 lines)
   - `src/backtesting/engine/data_loader.py` (809 lines)
   - `src/backtesting/engine/streaming_tick_loader.py` (418 lines)

---

## 📋 Implementation Order

### Week 1: Phase 1 - Cache Validation (P0)

**Goal:** Fix critical data integrity issues

#### Day 1-2: Task 1.1 - Cache Metadata Tracking (1.5h)

**File:** `src/backtesting/engine/data_cache.py`

**Step 1:** Add helper method to read metadata
```python
def _read_cache_metadata(self, cache_path: Path) -> Optional[Dict[str, str]]:
    """Read metadata from cached parquet file."""
    if not cache_path.exists():
        return None
    
    try:
        pf = pq.ParquetFile(cache_path)
        metadata = pf.schema_arrow.metadata
        
        if not metadata:
            return None
        
        return {k.decode(): v.decode() for k, v in metadata.items()}
    except Exception as e:
        self.logger.warning(f"Error reading cache metadata: {e}")
        return None
```

**Step 2:** Modify `save_to_cache()` to add metadata

Find this section (around line 260):
```python
# Current code:
pq.write_table(table, cache_path, compression='snappy')
```

Replace with:
```python
# Add metadata before writing
from datetime import timezone

metadata = {
    'cached_at': datetime.now(timezone.utc).isoformat(),
    'source': 'mt5',  # or 'archive' if from archive
    'first_data_time': df['time'].iloc[0].isoformat() if len(df) > 0 else '',
    'last_data_time': df['time'].iloc[-1].isoformat() if len(df) > 0 else '',
    'row_count': str(len(df)),
    'cache_version': '1.0'
}

# Convert to bytes for parquet metadata
metadata_bytes = {k.encode(): v.encode() for k, v in metadata.items()}

# Add to table schema
table = table.replace_schema_metadata(metadata_bytes)

# Write with metadata
pq.write_table(table, cache_path, compression='snappy')
```

**Step 3:** Test manually
```python
# In Python console or test script
from src.backtesting.engine.data_cache import DataCache
from datetime import datetime
import pandas as pd

cache = DataCache('data/cache')

# Create test data
df = pd.DataFrame({
    'time': pd.date_range('2025-01-01', periods=100, freq='1min'),
    'open': [1.0] * 100,
    'high': [1.1] * 100,
    'low': [0.9] * 100,
    'close': [1.0] * 100,
    'tick_volume': [100] * 100
})

# Save with metadata
cache.save_to_cache(df, 'EURUSD', datetime(2025, 1, 1), datetime(2025, 1, 2), 'M1', 'candles', {})

# Read metadata
path = cache._get_day_cache_path('EURUSD', datetime(2025, 1, 1), 'M1', 'candles')
metadata = cache._read_cache_metadata(path)
print(metadata)
# Should print: {'cached_at': '2025-11-22T...', 'source': 'mt5', ...}
```

**Acceptance Criteria:**
- ✅ Metadata written to all new cache files
- ✅ Metadata readable with `_read_cache_metadata()`
- ✅ Cache files without metadata are invalidated (triggers rebuild)

---

#### Day 2-3: Task 1.2 - Gap Detection (2h)

**File:** `src/backtesting/engine/data_cache.py`

**Step 1:** Add validation method (insert after `_read_cache_metadata()`)
```python
def validate_cache_coverage(self, symbol: str, start_date: datetime, 
                           end_date: datetime, timeframe: str, 
                           data_type: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that cached data covers requested range without gaps.
    
    Returns:
        (is_valid, reason) - True if valid, False with reason if invalid
    """
    days = self._get_days_in_range(start_date, end_date)
    
    if len(days) == 0:
        return False, "No days in range"
    
    # Check first day for gap at start
    first_day_path = self._get_day_cache_path(symbol, days[0], timeframe, data_type)
    if not first_day_path.exists():
        return False, f"First day {days[0].date()} not cached"
    
    metadata = self._read_cache_metadata(first_day_path)
    if metadata and 'first_data_time' in metadata:
        try:
            first_data_time = datetime.fromisoformat(metadata['first_data_time'])
            gap_seconds = (first_data_time - start_date).total_seconds()
            gap_days = gap_seconds / 86400
            
            if gap_days > 1:
                self.logger.warning(
                    f"Cache gap detected for {symbol} {timeframe}: "
                    f"{gap_days:.1f} days between requested start and first data"
                )
                return False, f"Gap of {gap_days:.1f} days at start"
        except Exception as e:
            self.logger.warning(f"Error parsing metadata timestamp: {e}")
    
    # Check for missing days in middle
    for day in days:
        day_path = self._get_day_cache_path(symbol, day, timeframe, data_type)
        if not day_path.exists():
            return False, f"Missing day {day.date()}"
    
    return True, None
```

**Step 2:** Modify `load_from_cache()` to use validation

Find the beginning of `load_from_cache()` method (around line 143):
```python
def load_from_cache(self, symbol, start_date, end_date, timeframe, data_type):
    """Load data from cache if available."""
    
    # ADD THIS VALIDATION BLOCK AT THE START:
    is_valid, reason = self.validate_cache_coverage(
        symbol, start_date, end_date, timeframe, data_type
    )
    
    if not is_valid:
        self.logger.info(f"Cache validation failed for {symbol} {timeframe}: {reason}")
        return None
    
    # ... rest of existing code ...
```

**Step 3:** Test gap detection
```python
# Test script
from src.backtesting.engine.data_cache import DataCache
from datetime import datetime, timedelta
import pandas as pd

cache = DataCache('data/cache')

# Create cache with gap
# Cache day 1
df1 = pd.DataFrame({
    'time': pd.date_range('2025-01-01 20:00', periods=100, freq='1min'),  # Starts at 20:00 (gap!)
    'open': [1.0] * 100,
    'high': [1.1] * 100,
    'low': [0.9] * 100,
    'close': [1.0] * 100,
    'tick_volume': [100] * 100
})
cache.save_to_cache(df1, 'TESTGAP', datetime(2025, 1, 1), datetime(2025, 1, 2), 'M1', 'candles', {})

# Try to load from 00:00 (should detect gap)
result = cache.load_from_cache('TESTGAP', datetime(2025, 1, 1), datetime(2025, 1, 2), 'M1', 'candles')
assert result is None, "Should detect gap and return None"
print("✓ Gap detection working!")
```

**Acceptance Criteria:**
- ✅ Detects gaps >1 day at start
- ✅ Detects missing days in middle
- ✅ Returns None to trigger re-download
- ✅ Logs clear reason for invalidation

---

#### Day 3-4: Task 1.3 - Freshness Checks (1.5h)

**File:** `src/backtesting/engine/data_cache.py`

**Step 1:** Add TTL configuration to `__init__()` (around line 30)
```python
def __init__(self, base_cache_dir: str, cache_ttl_days: int = 7):
    """
    Initialize data cache.
    
    Args:
        base_cache_dir: Base directory for cache files
        cache_ttl_days: Cache time-to-live in days (default: 7)
    """
    self.base_cache_dir = Path(base_cache_dir)
    self.cache_ttl_days = cache_ttl_days
    self.logger = get_logger()
```

**Step 2:** Add freshness check method
```python
def is_cache_fresh(self, cache_path: Path) -> bool:
    """Check if cache file is fresh (within TTL)."""
    metadata = self._read_cache_metadata(cache_path)
    
    if not metadata or 'cached_at' not in metadata:
        # No metadata - assume stale (legacy cache)
        return False
    
    try:
        from datetime import timezone
        cached_at = datetime.fromisoformat(metadata['cached_at'])
        age_seconds = (datetime.now(timezone.utc) - cached_at).total_seconds()
        age_days = age_seconds / 86400
        
        return age_days <= self.cache_ttl_days
    except Exception as e:
        self.logger.warning(f"Error checking cache freshness: {e}")
        return False  # Treat as stale on error
```

**Step 3:** Integrate with validation
```python
# In validate_cache_coverage(), after checking for gap:
if metadata and 'first_data_time' in metadata:
    # ... existing gap check ...
    
    # ADD FRESHNESS CHECK:
    if not self.is_cache_fresh(first_day_path):
        self.logger.info(
            f"Cache is stale (>{self.cache_ttl_days} days old), "
            f"will re-validate with MT5"
        )
        return False, "Cache is stale"
```

**Acceptance Criteria:**
- ✅ Detects cache older than TTL
- ✅ Triggers re-validation for stale cache
- ✅ TTL configurable via parameter

---

#### Day 4-5: Task 1.4 - Unit Tests (1h)

**File:** `tests/backtesting/engine/test_data_cache_validation.py` (NEW)

Create comprehensive test file:
```python
"""Unit tests for cache validation functionality."""
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
import shutil

from src.backtesting.engine.data_cache import DataCache


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create temporary cache directory."""
    cache_dir = tmp_path / "test_cache"
    cache_dir.mkdir()
    yield str(cache_dir)
    # Cleanup
    shutil.rmtree(cache_dir, ignore_errors=True)


@pytest.fixture
def sample_df():
    """Create sample DataFrame for testing."""
    return pd.DataFrame({
        'time': pd.date_range('2025-01-01', periods=1440, freq='1min'),
        'open': [1.0] * 1440,
        'high': [1.1] * 1440,
        'low': [0.9] * 1440,
        'close': [1.0] * 1440,
        'tick_volume': [100] * 1440
    })


def test_gap_detection_at_start(temp_cache_dir, sample_df):
    """Test that gaps >1 day at start are detected."""
    cache = DataCache(temp_cache_dir)
    
    # Create cache with 2-day gap (data starts at day 3)
    df_with_gap = sample_df.copy()
    df_with_gap['time'] = pd.date_range('2025-01-03', periods=1440, freq='1min')
    
    cache.save_to_cache(
        df_with_gap, 'EURUSD', 
        datetime(2025, 1, 3), datetime(2025, 1, 4),
        'M1', 'candles', {}
    )
    
    # Try to load from day 1 (should detect gap)
    is_valid, reason = cache.validate_cache_coverage(
        'EURUSD', datetime(2025, 1, 1), datetime(2025, 1, 4),
        'M1', 'candles'
    )
    
    assert not is_valid
    assert 'gap' in reason.lower() or 'missing' in reason.lower()


def test_missing_day_in_middle(temp_cache_dir, sample_df):
    """Test that missing days in middle are detected."""
    cache = DataCache(temp_cache_dir)
    
    # Cache days 1, 2, 4, 5 (missing day 3)
    for day in [1, 2, 4, 5]:
        df = sample_df.copy()
        start = datetime(2025, 1, day)
        end = start + timedelta(days=1)
        cache.save_to_cache(df, 'EURUSD', start, end, 'M1', 'candles', {})
    
    # Try to load days 1-5 (should detect missing day 3)
    is_valid, reason = cache.validate_cache_coverage(
        'EURUSD', datetime(2025, 1, 1), datetime(2025, 1, 6),
        'M1', 'candles'
    )
    
    assert not is_valid
    assert '2025-01-03' in reason


def test_stale_cache_detection(temp_cache_dir, sample_df):
    """Test that old cache is detected as stale."""
    cache = DataCache(temp_cache_dir, cache_ttl_days=7)
    
    # Save cache
    cache.save_to_cache(
        sample_df, 'EURUSD',
        datetime(2025, 1, 1), datetime(2025, 1, 2),
        'M1', 'candles', {}
    )
    
    # Manually modify metadata to make it old
    path = cache._get_day_cache_path('EURUSD', datetime(2025, 1, 1), 'M1', 'candles')
    import pyarrow.parquet as pq
    import pyarrow as pa
    
    table = pq.read_table(path)
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    metadata = {
        b'cached_at': old_time.encode(),
        b'source': b'mt5',
        b'cache_version': b'1.0'
    }
    table = table.replace_schema_metadata(metadata)
    pq.write_table(table, path, compression='snappy')
    
    # Check freshness
    assert not cache.is_cache_fresh(path)
    
    # Validation should fail
    is_valid, reason = cache.validate_cache_coverage(
        'EURUSD', datetime(2025, 1, 1), datetime(2025, 1, 2),
        'M1', 'candles'
    )
    
    assert not is_valid
    assert 'stale' in reason.lower()


def test_valid_cache_passes(temp_cache_dir, sample_df):
    """Test that valid cache passes validation."""
    cache = DataCache(temp_cache_dir)
    
    # Create complete, fresh cache
    for day in range(1, 6):
        df = sample_df.copy()
        start = datetime(2025, 1, day)
        end = start + timedelta(days=1)
        cache.save_to_cache(df, 'EURUSD', start, end, 'M1', 'candles', {})
    
    # Validation should pass
    is_valid, reason = cache.validate_cache_coverage(
        'EURUSD', datetime(2025, 1, 1), datetime(2025, 1, 6),
        'M1', 'candles'
    )
    
    assert is_valid
    assert reason is None


def test_cache_without_metadata(temp_cache_dir, sample_df):
    """Test that cache without metadata is invalidated."""
    cache = DataCache(temp_cache_dir)

    # Save cache
    path = cache._get_day_cache_path('EURUSD', datetime(2025, 1, 1), 'M1', 'candles')
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write parquet without metadata (simulate old/broken cache)
    import pyarrow as pa
    table = pa.Table.from_pandas(sample_df)
    import pyarrow.parquet as pq
    pq.write_table(table, path, compression='snappy')

    # Should be treated as invalid (no metadata)
    assert not cache.is_cache_fresh(path)

    # Validation should fail - cache will be rebuilt
    is_valid, reason = cache.validate_cache_coverage(
        'EURUSD', datetime(2025, 1, 1), datetime(2025, 1, 2),
        'M1', 'candles'
    )

    # Should fail - no metadata means rebuild needed
    assert not is_valid
    assert 'metadata' in reason.lower() or 'rebuild' in reason.lower()
```

**Run tests:**
```bash
pytest tests/backtesting/engine/test_data_cache_validation.py -v
```

**Acceptance Criteria:**
- ✅ All tests pass
- ✅ >95% code coverage for validation logic
- ✅ Tests run in <5 seconds

---

### Week 2: Phase 2 - Incremental Loading (P1)

Follow similar pattern for Phase 2 tasks. See [DATA_LOADING_IMPLEMENTATION_PLAN.md](./DATA_LOADING_IMPLEMENTATION_PLAN.md) for detailed specifications.

---

## 🧪 Testing Workflow

### After Each Task

1. **Run unit tests:**
   ```bash
   pytest tests/backtesting/engine/test_data_cache_validation.py -v
   ```

2. **Check code coverage:**
   ```bash
   pytest --cov=src/backtesting/engine/data_cache tests/backtesting/engine/ --cov-report=html
   open htmlcov/index.html
   ```

3. **Manual smoke test:**
   ```bash
   python backtest.py  # Run a short backtest
   ```

### Before Committing

1. **Run all tests:**
   ```bash
   pytest tests/backtesting/engine/ -v
   ```

2. **Check for breaking changes:**
   ```bash
   # Test with existing cache
   python backtest.py  # Should work with old cache files
   ```

3. **Format code:**
   ```bash
   black src/backtesting/engine/data_cache.py
   ```

---

## 📝 Commit Message Format

```
feat(cache): Add cache metadata tracking

- Add metadata to parquet files (cached_at, source, timestamps)
- Create _read_cache_metadata() helper method
- Maintain backward compatibility with legacy cache files

Related to: Phase 1, Task 1.1
Effort: 1.5h
```

---

## 🆘 Troubleshooting

### Issue: Tests failing with import errors

**Solution:**
```bash
# Ensure PYTHONPATH includes project root
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Issue: Cache files not found during tests

**Solution:**
```python
# Use tmp_path fixture in pytest
@pytest.fixture
def temp_cache_dir(tmp_path):
    cache_dir = tmp_path / "test_cache"
    cache_dir.mkdir()
    return str(cache_dir)
```

### Issue: Metadata not being written

**Solution:**
```python
# Verify pyarrow version
import pyarrow as pa
print(pa.__version__)  # Should be >=8.0.0

# Check if metadata is in schema
import pyarrow.parquet as pq
pf = pq.ParquetFile('path/to/file.parquet')
print(pf.schema_arrow.metadata)
```

---

## ✅ Checklist Before Moving to Next Phase

- [ ] All Phase 1 tasks completed
- [ ] All unit tests passing
- [ ] Code coverage >90%
- [ ] Manual testing completed
- [ ] Code reviewed
- [ ] Documentation updated
- [ ] No breaking changes introduced
- [ ] Performance benchmarks run (validation overhead <10%)

---

## 📚 Additional Resources

- **Full Analysis:** [BACKTESTING_DATA_LOADING_ANALYSIS.md](./BACKTESTING_DATA_LOADING_ANALYSIS.md)
- **Implementation Plan:** [DATA_LOADING_IMPLEMENTATION_PLAN.md](./DATA_LOADING_IMPLEMENTATION_PLAN.md)
- **Quick Reference:** [DATA_LOADING_QUICK_REFERENCE.md](./DATA_LOADING_QUICK_REFERENCE.md)
- **Task List:** Use `view_tasklist` command to see all tasks

---

## 🎯 Success Criteria

**Phase 1 Complete When:**
- ✅ Cache validation prevents incomplete data from being cached permanently
- ✅ Stale cache is automatically re-validated
- ✅ All tests pass with >90% coverage
- ✅ Backward compatible with existing cache files
- ✅ Performance overhead <10%

**Ready to proceed to Phase 2!**

