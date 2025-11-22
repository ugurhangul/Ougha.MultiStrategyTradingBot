#!/usr/bin/env python3
"""
Unit tests for cache validation functionality.

Tests the cache validation system including:
1. Gap detection (>1 day gaps)
2. Missing days detection
3. Stale cache detection (TTL expiration)
4. Valid cache scenarios
5. Legacy cache handling (no metadata)
"""

import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil
import pyarrow as pa
import pyarrow.parquet as pq

# Add project root to path
import sys
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting.engine.data_cache import DataCache


class TestCacheValidation:
    """Unit tests for cache validation."""
    
    @pytest.fixture
    def test_cache_dir(self, tmp_path):
        """Create temporary cache directory."""
        cache_dir = tmp_path / "test_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        yield cache_dir
        # Cleanup
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
    
    @pytest.fixture
    def cache(self, test_cache_dir):
        """Create DataCache instance."""
        return DataCache(str(test_cache_dir), cache_ttl_days=7, use_index=True)
    
    def create_test_data(self, start_date, num_bars=100):
        """Create test OHLC data."""
        return pd.DataFrame({
            'time': pd.date_range(start_date, periods=num_bars, freq='1min'),
            'open': [1.1000] * num_bars,
            'high': [1.1010] * num_bars,
            'low': [1.0990] * num_bars,
            'close': [1.1005] * num_bars,
            'tick_volume': [100] * num_bars,
            'spread': [2] * num_bars,
            'real_volume': [0] * num_bars
        })
    
    def save_cache_file_with_metadata(self, cache, symbol, timeframe, day_date, data, cached_at=None):
        """Helper to save cache file with custom metadata."""
        if cached_at is None:
            cached_at = datetime.now(timezone.utc)
        
        cache_path = cache._get_day_cache_path(day_date, symbol, timeframe)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        metadata = {
            'cached_at': cached_at.isoformat(),
            'source': 'mt5',
            'first_data_time': data['time'].iloc[0].isoformat() if len(data) > 0 else '',
            'last_data_time': data['time'].iloc[-1].isoformat() if len(data) > 0 else '',
            'row_count': str(len(data)),
            'cache_version': '1.0'
        }
        
        metadata_bytes = {k.encode(): v.encode() for k, v in metadata.items()}
        table = pa.Table.from_pandas(data, preserve_index=False)
        table = table.replace_schema_metadata(metadata_bytes)
        pq.write_table(table, cache_path, compression='snappy')
    
    def save_cache_file_without_metadata(self, cache, symbol, timeframe, day_date, data):
        """Helper to save cache file without metadata (legacy format)."""
        cache_path = cache._get_day_cache_path(day_date, symbol, timeframe)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save without custom metadata (only pandas metadata)
        data.to_parquet(cache_path, compression='snappy', index=False)
    
    def test_gap_detection_at_start(self, cache):
        """
        Test gap detection when there's a >1 day gap at the start.
        
        Scenario:
        - Request: Jan 1-10
        - Cache: Jan 5-10 (missing Jan 1-4, gap >1 day)
        - Expected: Invalid (gap at start)
        """
        # Cache days 5-10
        for day_offset in range(5, 11):
            day_date = datetime(2025, 1, day_offset, 0, 0, 0, tzinfo=timezone.utc)
            data = self.create_test_data(day_date)
            self.save_cache_file_with_metadata(cache, 'EURUSD', 'M1', day_date, data)
        
        # Validate cache for Jan 1-10
        request_start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 1, 10, 23, 59, 0, tzinfo=timezone.utc)
        
        is_valid, reason = cache.validate_cache_coverage('EURUSD', 'M1', request_start, request_end)

        assert not is_valid, "Cache should be invalid due to gap at start"
        assert "missing" in reason.lower() or "gap" in reason.lower(), f"Reason should mention missing/gap, got: {reason}"
    
    def test_missing_days_in_middle(self, cache):
        """
        Test detection of missing days in the middle of the range.
        
        Scenario:
        - Request: Jan 1-10
        - Cache: Jan 1-3, 8-10 (missing Jan 4-7)
        - Expected: Invalid (missing days in middle)
        """
        # Cache days 1-3
        for day_offset in range(1, 4):
            day_date = datetime(2025, 2, day_offset, 0, 0, 0, tzinfo=timezone.utc)
            data = self.create_test_data(day_date)
            self.save_cache_file_with_metadata(cache, 'GBPUSD', 'M5', day_date, data)
        
        # Cache days 8-10
        for day_offset in range(8, 11):
            day_date = datetime(2025, 2, day_offset, 0, 0, 0, tzinfo=timezone.utc)
            data = self.create_test_data(day_date)
            self.save_cache_file_with_metadata(cache, 'GBPUSD', 'M5', day_date, data)
        
        # Validate cache for Feb 1-10
        request_start = datetime(2025, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 2, 10, 23, 59, 0, tzinfo=timezone.utc)
        
        is_valid, reason = cache.validate_cache_coverage('GBPUSD', 'M5', request_start, request_end)
        
        assert not is_valid, "Cache should be invalid due to missing days"
        assert "missing" in reason.lower(), f"Reason should mention missing days, got: {reason}"
    
    def test_stale_cache_detection(self, cache):
        """
        Test detection of stale cache (older than TTL).
        
        Scenario:
        - Cache TTL: 7 days
        - Cache age: 10 days
        - Expected: Invalid (stale)
        """
        # Create cache file with old timestamp (10 days ago)
        old_timestamp = datetime.now(timezone.utc) - timedelta(days=10)
        
        day_date = datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        data = self.create_test_data(day_date)
        self.save_cache_file_with_metadata(cache, 'USDJPY', 'M1', day_date, data, cached_at=old_timestamp)
        
        # Validate cache
        request_start = datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 3, 1, 23, 59, 0, tzinfo=timezone.utc)
        
        is_valid, reason = cache.validate_cache_coverage('USDJPY', 'M1', request_start, request_end)
        
        assert not is_valid, "Cache should be invalid due to staleness"
        assert "stale" in reason.lower() or "expired" in reason.lower(), f"Reason should mention staleness, got: {reason}"
    
    def test_valid_cache(self, cache):
        """
        Test valid cache scenario.
        
        Scenario:
        - Request: Jan 1-5
        - Cache: Jan 1-5 (all days present, fresh)
        - Expected: Valid
        """
        # Cache all days 1-5
        for day_offset in range(1, 6):
            day_date = datetime(2025, 4, day_offset, 0, 0, 0, tzinfo=timezone.utc)
            data = self.create_test_data(day_date)
            self.save_cache_file_with_metadata(cache, 'EURJPY', 'H1', day_date, data)
        
        # Validate cache
        request_start = datetime(2025, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 4, 5, 23, 59, 0, tzinfo=timezone.utc)
        
        is_valid, reason = cache.validate_cache_coverage('EURJPY', 'H1', request_start, request_end)

        assert is_valid, f"Cache should be valid, got reason: {reason}"
        assert reason is None, f"Reason should be None for valid cache, got: {reason}"
    
    def test_legacy_cache_without_metadata(self, cache):
        """
        Test handling of legacy cache files without metadata.
        
        Scenario:
        - Cache file exists but has no metadata
        - Expected: Invalid (no metadata)
        """
        # Create cache file without metadata
        day_date = datetime(2025, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        data = self.create_test_data(day_date)
        self.save_cache_file_without_metadata(cache, 'AUDUSD', 'M1', day_date, data)
        
        # Validate cache
        request_start = datetime(2025, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 5, 1, 23, 59, 0, tzinfo=timezone.utc)
        
        is_valid, reason = cache.validate_cache_coverage('AUDUSD', 'M1', request_start, request_end)
        
        assert not is_valid, "Cache should be invalid due to missing metadata"
        assert "metadata" in reason.lower(), f"Reason should mention metadata, got: {reason}"
    
    def test_partial_cache_returns_missing_days(self, cache):
        """
        Test that load_from_cache_partial returns correct missing days.
        
        Scenario:
        - Request: Jan 1-10
        - Cache: Jan 1-3, 7-10
        - Expected: Returns cached data + missing days [4, 5, 6]
        """
        # Cache days 1-3
        for day_offset in range(1, 4):
            day_date = datetime(2025, 6, day_offset, 0, 0, 0, tzinfo=timezone.utc)
            data = self.create_test_data(day_date)
            day_end = day_date.replace(hour=23, minute=59)
            cache.save_to_cache('NZDUSD', 'M1', day_date, day_end, data, {'name': 'NZDUSD'})
        
        # Cache days 7-10
        for day_offset in range(7, 11):
            day_date = datetime(2025, 6, day_offset, 0, 0, 0, tzinfo=timezone.utc)
            data = self.create_test_data(day_date)
            day_end = day_date.replace(hour=23, minute=59)
            cache.save_to_cache('NZDUSD', 'M1', day_date, day_end, data, {'name': 'NZDUSD'})
        
        # Load partial cache
        request_start = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 6, 10, 23, 59, 0, tzinfo=timezone.utc)
        
        cached_df, missing_days, symbol_info = cache.load_from_cache_partial(
            'NZDUSD', 'M1', request_start, request_end
        )
        
        # Verify cached data
        assert cached_df is not None, "Should have cached data"
        assert len(cached_df) > 0, "Cached data should not be empty"
        
        # Verify missing days (returned as datetime objects, not date objects)
        expected_missing = [
            datetime(2025, 6, 4, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 6, 5, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 6, 6, 0, 0, 0, tzinfo=timezone.utc)
        ]

        assert len(missing_days) == 3, f"Should have 3 missing days, got {len(missing_days)}"
        assert set(missing_days) == set(expected_missing), f"Missing days should be {expected_missing}, got {missing_days}"
    
    def test_fresh_cache_within_ttl(self, cache):
        """
        Test that cache within TTL is considered fresh.
        
        Scenario:
        - Cache TTL: 7 days
        - Cache age: 3 days
        - Expected: Valid (fresh)
        """
        # Create cache file with recent timestamp (3 days ago)
        recent_timestamp = datetime.now(timezone.utc) - timedelta(days=3)
        
        day_date = datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        data = self.create_test_data(day_date)
        self.save_cache_file_with_metadata(cache, 'CADJPY', 'M5', day_date, data, cached_at=recent_timestamp)
        
        # Validate cache
        request_start = datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 7, 1, 23, 59, 0, tzinfo=timezone.utc)
        
        is_valid, reason = cache.validate_cache_coverage('CADJPY', 'M5', request_start, request_end)
        
        assert is_valid, f"Cache should be valid (within TTL), got reason: {reason}"
    
    def test_metadata_read_helper(self, cache):
        """
        Test _read_cache_metadata helper method.
        
        Scenario:
        - File with metadata: Returns metadata dict
        - File without metadata: Returns None
        - Non-existent file: Returns None
        """
        # Test with metadata
        day_date = datetime(2025, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        data = self.create_test_data(day_date)
        self.save_cache_file_with_metadata(cache, 'CHFJPY', 'M1', day_date, data)
        
        cache_path = cache._get_day_cache_path(day_date, 'CHFJPY', 'M1')
        metadata = cache._read_cache_metadata(cache_path)
        
        assert metadata is not None, "Should read metadata"
        assert 'cache_version' in metadata, "Should have cache_version"
        assert 'cached_at' in metadata, "Should have cached_at"
        assert metadata['cache_version'] == '1.0', "Version should be 1.0"
        
        # Test without metadata
        day_date2 = datetime(2025, 8, 2, 0, 0, 0, tzinfo=timezone.utc)
        data2 = self.create_test_data(day_date2)
        self.save_cache_file_without_metadata(cache, 'CHFJPY', 'M1', day_date2, data2)
        
        cache_path2 = cache._get_day_cache_path(day_date2, 'CHFJPY', 'M1')
        metadata2 = cache._read_cache_metadata(cache_path2)
        
        assert metadata2 is None, "Should return None for file without metadata"
        
        # Test non-existent file
        day_date3 = datetime(2025, 8, 3, 0, 0, 0, tzinfo=timezone.utc)
        cache_path3 = cache._get_day_cache_path(day_date3, 'CHFJPY', 'M1')
        metadata3 = cache._read_cache_metadata(cache_path3)
        
        assert metadata3 is None, "Should return None for non-existent file"
    
    def test_empty_cache_returns_all_missing_days(self, cache):
        """
        Test that empty cache returns all days as missing.
        
        Scenario:
        - Request: Jan 1-5
        - Cache: Empty
        - Expected: All 5 days missing
        """
        request_start = datetime(2025, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 9, 5, 23, 59, 0, tzinfo=timezone.utc)
        
        cached_df, missing_days, symbol_info = cache.load_from_cache_partial(
            'EURGBP', 'M1', request_start, request_end
        )
        
        assert cached_df is None or len(cached_df) == 0, "Should have no cached data"
        assert len(missing_days) == 5, f"Should have 5 missing days, got {len(missing_days)}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

