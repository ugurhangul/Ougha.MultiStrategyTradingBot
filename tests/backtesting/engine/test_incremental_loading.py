#!/usr/bin/env python3
"""
Integration tests for incremental cache loading.

Tests the complete flow of:
1. Partial cache hits (some days cached, some missing)
2. Interleaved missing days (non-contiguous cache)
3. Cache index performance
4. End-to-end incremental loading with DataLoader
"""

import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil
from unittest.mock import Mock, patch
import time

# Add project root to path
import sys
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting.engine.data_loader import BacktestDataLoader
from src.backtesting.engine.data_cache import DataCache
from src.backtesting.engine.cache_index import CacheIndex
from src.core.mt5_connector import MT5Connector


class TestIncrementalLoading:
    """Integration tests for incremental cache loading."""
    
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
    def mock_connector(self):
        """Create mock MT5 connector."""
        connector = Mock(spec=MT5Connector)
        connector.is_connected = True
        return connector
    
    @pytest.fixture
    def data_loader(self, mock_connector, test_cache_dir):
        """Create data loader with mock connector."""
        return BacktestDataLoader(
            connector=mock_connector,
            use_cache=True,
            cache_dir=str(test_cache_dir),
            cache_ttl_days=7
        )
    
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
    
    def test_partial_cache_hit(self, data_loader, test_cache_dir):
        """
        Test loading with partial cache (some days missing).
        
        Scenario:
        - Cache days 1-5
        - Request days 1-10
        - Verify days 1-5 loaded from cache
        - Verify days 6-10 downloaded
        - Verify merged result correct
        """
        # Pre-populate cache with days 1-5
        for day_offset in range(5):
            day_start = datetime(2025, 1, 1 + day_offset, 0, 0, 0, tzinfo=timezone.utc)
            day_end = datetime(2025, 1, 1 + day_offset, 23, 59, 0, tzinfo=timezone.utc)
            
            test_data = self.create_test_data(day_start)
            symbol_info = {'name': 'EURUSD', 'digits': 5, 'point': 0.00001}
            
            data_loader.cache.save_to_cache('EURUSD', 'M1', day_start, day_end, test_data, symbol_info)
        
        # Mock download for missing days
        download_count = 0
        def mock_download(symbol, timeframe, start_date, end_date, preloaded_ticks=None):
            nonlocal download_count
            download_count += 1
            data = self.create_test_data(start_date)
            return data, {'name': symbol, 'digits': 5, 'point': 0.00001}
        
        # Request 10 days (5 cached, 5 missing)
        with patch.object(data_loader, '_download_from_mt5', side_effect=mock_download):
            request_start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            request_end = datetime(2025, 1, 10, 23, 59, 0, tzinfo=timezone.utc)
            
            result = data_loader.load_from_mt5(
                'EURUSD', 'M1', request_start, request_end,
                use_incremental_loading=True
            )
        
        assert result is not None, "Load should succeed"
        df, symbol_info = result
        
        # Verify we got data
        assert len(df) > 0, "Should have data"
        
        # Verify only missing days were downloaded
        assert download_count == 5, f"Should download 5 missing days, got {download_count}"
        
        # Verify date range
        assert df['time'].min() >= request_start, "Data should start at or after request start"
        assert df['time'].max() <= request_end, "Data should end at or before request end"
    
    def test_interleaved_missing_days(self, data_loader, test_cache_dir):
        """
        Test with non-contiguous cached days.
        
        Scenario:
        - Cache days 1, 3, 5, 7, 9
        - Request days 1-10
        - Verify correct merge of cached and downloaded data
        """
        # Pre-populate cache with odd days only
        for day_offset in [0, 2, 4, 6, 8]:  # Days 1, 3, 5, 7, 9
            day_start = datetime(2025, 2, 1 + day_offset, 0, 0, 0, tzinfo=timezone.utc)
            day_end = datetime(2025, 2, 1 + day_offset, 23, 59, 0, tzinfo=timezone.utc)
            
            test_data = self.create_test_data(day_start)
            symbol_info = {'name': 'GBPUSD', 'digits': 5, 'point': 0.00001}
            
            data_loader.cache.save_to_cache('GBPUSD', 'M1', day_start, day_end, test_data, symbol_info)
        
        # Mock download for missing even days
        downloaded_days = []
        def mock_download(symbol, timeframe, start_date, end_date, preloaded_ticks=None):
            downloaded_days.append(start_date.day)
            data = self.create_test_data(start_date)
            return data, {'name': symbol, 'digits': 5, 'point': 0.00001}
        
        # Request 10 days
        with patch.object(data_loader, '_download_from_mt5', side_effect=mock_download):
            request_start = datetime(2025, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
            request_end = datetime(2025, 2, 10, 23, 59, 0, tzinfo=timezone.utc)
            
            result = data_loader.load_from_mt5(
                'GBPUSD', 'M1', request_start, request_end,
                use_incremental_loading=True
            )
        
        assert result is not None, "Load should succeed"
        df, symbol_info = result
        
        # Verify we got data
        assert len(df) > 0, "Should have data"
        
        # Verify only even days were downloaded (2, 4, 6, 8, 10)
        assert len(downloaded_days) == 5, f"Should download 5 even days, got {len(downloaded_days)}"
        assert set(downloaded_days) == {2, 4, 6, 8, 10}, f"Should download days 2,4,6,8,10, got {downloaded_days}"
    
    def test_cache_index_performance(self, test_cache_dir):
        """
        Test that cache index improves performance.
        
        Scenario:
        - Create cache with many days
        - Measure time with index
        - Measure time without index
        - Verify >10x speedup
        """
        # Create cache with index
        cache_with_index = DataCache(str(test_cache_dir), use_index=True)
        
        # Populate cache with 100 days
        for day_offset in range(100):
            day_start = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_offset)
            day_end = day_start.replace(hour=23, minute=59)
            
            test_data = self.create_test_data(day_start, num_bars=10)
            symbol_info = {'name': 'EURUSD', 'digits': 5, 'point': 0.00001}
            
            cache_with_index.save_to_cache('EURUSD', 'M1', day_start, day_end, test_data, symbol_info)
        
        # Measure index lookup time
        start_time = time.time()
        for _ in range(100):
            _ = cache_with_index.index.get_cached_days('EURUSD', 'M1')
        index_time = time.time() - start_time
        
        # Create cache without index
        cache_without_index = DataCache(str(test_cache_dir), use_index=False)
        
        # Measure filesystem scan time (validate_cache_coverage does filesystem checks)
        start_time = time.time()
        for _ in range(100):
            request_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            request_end = datetime(2025, 4, 10, tzinfo=timezone.utc)
            _ = cache_without_index.validate_cache_coverage('EURUSD', 'M1', request_start, request_end)
        filesystem_time = time.time() - start_time
        
        # Index should be significantly faster
        speedup = filesystem_time / index_time if index_time > 0 else float('inf')
        
        assert index_time < 0.1, f"Index lookup should be fast (<0.1s for 100 lookups), got {index_time:.3f}s"
        assert speedup > 10, f"Index should be >10x faster, got {speedup:.1f}x"
    
    def test_complete_cache_hit_no_download(self, data_loader, test_cache_dir):
        """
        Test that complete cache hit doesn't trigger download.
        
        Scenario:
        - Cache all requested days
        - Request those days
        - Verify no download triggered
        """
        # Pre-populate cache with all days
        for day_offset in range(5):
            day_start = datetime(2025, 3, 1 + day_offset, 0, 0, 0, tzinfo=timezone.utc)
            day_end = datetime(2025, 3, 1 + day_offset, 23, 59, 0, tzinfo=timezone.utc)
            
            test_data = self.create_test_data(day_start)
            symbol_info = {'name': 'USDJPY', 'digits': 3, 'point': 0.001}
            
            data_loader.cache.save_to_cache('USDJPY', 'M1', day_start, day_end, test_data, symbol_info)
        
        # Track if download was called
        download_called = False
        def track_download(*args, **kwargs):
            nonlocal download_called
            download_called = True
            return None
        
        # Request all cached days
        with patch.object(data_loader, '_download_from_mt5', side_effect=track_download):
            request_start = datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
            request_end = datetime(2025, 3, 5, 23, 59, 0, tzinfo=timezone.utc)
            
            result = data_loader.load_from_mt5(
                'USDJPY', 'M1', request_start, request_end,
                use_incremental_loading=True
            )
        
        assert result is not None, "Load should succeed"
        assert not download_called, "Download should not be called for complete cache hit"
    
    def test_cache_index_rebuild(self, test_cache_dir):
        """
        Test that cache index can rebuild from filesystem.
        
        Scenario:
        - Create cache with data
        - Clear index
        - Rebuild index
        - Verify index matches filesystem
        """
        cache = DataCache(str(test_cache_dir), use_index=True)
        
        # Populate cache
        for day_offset in range(5):
            day_start = datetime(2025, 5, 1 + day_offset, 0, 0, 0, tzinfo=timezone.utc)
            day_end = datetime(2025, 5, 1 + day_offset, 23, 59, 0, tzinfo=timezone.utc)
            
            test_data = self.create_test_data(day_start)
            symbol_info = {'name': 'EURJPY', 'digits': 3, 'point': 0.001}
            
            cache.save_to_cache('EURJPY', 'M1', day_start, day_end, test_data, symbol_info)
        
        # Get cached days before clear
        days_before = cache.index.get_cached_days('EURJPY', 'M1')
        
        # Clear index
        cache.index.clear_all()
        
        # Verify index is empty
        days_after_clear = cache.index.get_cached_days('EURJPY', 'M1')
        assert len(days_after_clear) == 0, "Index should be empty after clear"
        
        # Rebuild index
        cache.index.rebuild_index()
        
        # Verify index matches original
        days_after_rebuild = cache.index.get_cached_days('EURJPY', 'M1')
        assert days_after_rebuild == days_before, "Rebuilt index should match original"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

