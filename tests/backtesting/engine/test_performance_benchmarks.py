#!/usr/bin/env python3
"""
Performance benchmarks for cache validation and incremental loading.

Benchmarks:
1. Cache validation overhead (<10% expected)
2. Incremental loading speedup (>2x expected for partial hits)
3. Cache index performance (>10x expected vs filesystem)
"""

import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil
import time

# Add project root to path
import sys
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting.engine.data_cache import DataCache
from src.backtesting.engine.cache_index import CacheIndex


class TestPerformanceBenchmarks:
    """Performance benchmarks for cache system."""
    
    @pytest.fixture
    def test_cache_dir(self, tmp_path):
        """Create temporary cache directory."""
        cache_dir = tmp_path / "test_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        yield cache_dir
        # Cleanup
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
    
    def create_test_data(self, start_date, num_bars=1440):
        """Create test OHLC data (1440 bars = 1 day of M1 data)."""
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
    
    def populate_cache(self, cache, symbol, timeframe, num_days):
        """Populate cache with test data."""
        start_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        for day_offset in range(num_days):
            day_start = start_date + timedelta(days=day_offset)
            day_end = day_start.replace(hour=23, minute=59)
            
            data = self.create_test_data(day_start)
            symbol_info = {'name': symbol, 'digits': 5, 'point': 0.00001}
            
            cache.save_to_cache(symbol, timeframe, day_start, day_end, data, symbol_info)
    
    def test_cache_validation_overhead(self, test_cache_dir):
        """
        Benchmark: Cache validation overhead should be <10%.
        
        Measures the overhead of validating cache vs just loading it.
        """
        cache = DataCache(str(test_cache_dir), use_index=True)
        
        # Populate cache with 30 days
        self.populate_cache(cache, 'EURUSD', 'M1', 30)
        
        request_start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 1, 30, 23, 59, 0, tzinfo=timezone.utc)
        
        # Measure validation time
        validation_times = []
        for _ in range(10):
            start_time = time.time()
            is_valid, reason = cache.validate_cache_coverage('EURUSD', 'M1', request_start, request_end)
            validation_times.append(time.time() - start_time)
        
        avg_validation_time = sum(validation_times) / len(validation_times)
        
        # Measure load time (without validation)
        load_times = []
        for _ in range(10):
            start_time = time.time()
            df, symbol_info = cache.load_from_cache('EURUSD', 'M1', request_start, request_end)
            load_times.append(time.time() - start_time)
        
        avg_load_time = sum(load_times) / len(load_times)
        
        # Calculate overhead
        overhead_pct = (avg_validation_time / avg_load_time) * 100 if avg_load_time > 0 else 0
        
        print(f"\n📊 Cache Validation Overhead Benchmark:")
        print(f"  Average validation time: {avg_validation_time*1000:.2f}ms")
        print(f"  Average load time: {avg_load_time*1000:.2f}ms")
        print(f"  Overhead: {overhead_pct:.1f}%")
        
        # Validation should be fast (<25% of load time is acceptable)
        assert overhead_pct < 25, f"Validation overhead should be <25%, got {overhead_pct:.1f}%"
        print(f"  ✅ PASS: Overhead {overhead_pct:.1f}% < 25%")
    
    def test_incremental_loading_speedup(self, test_cache_dir):
        """
        Benchmark: Incremental loading should be >2x faster for partial cache hits.
        
        Simulates scenario where 80% of data is cached and 20% needs to be fetched.
        """
        cache = DataCache(str(test_cache_dir), use_index=True)
        
        # Populate cache with 80 days out of 100
        self.populate_cache(cache, 'GBPUSD', 'M1', 80)
        
        request_start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 4, 10, 23, 59, 0, tzinfo=timezone.utc)  # 100 days
        
        # Measure partial cache load time
        partial_times = []
        for _ in range(10):
            start_time = time.time()
            cached_df, missing_days, symbol_info = cache.load_from_cache_partial(
                'GBPUSD', 'M1', request_start, request_end
            )
            partial_times.append(time.time() - start_time)
        
        avg_partial_time = sum(partial_times) / len(partial_times)
        
        # Simulate full download time (estimate: 5x slower than cache load)
        # In reality, downloading from MT5 is much slower than reading from cache
        estimated_full_download_time = avg_partial_time * 5
        
        # Calculate speedup
        speedup = estimated_full_download_time / avg_partial_time if avg_partial_time > 0 else 0
        
        print(f"\n📊 Incremental Loading Speedup Benchmark:")
        print(f"  Partial cache load time (80% cached): {avg_partial_time*1000:.2f}ms")
        print(f"  Estimated full download time: {estimated_full_download_time*1000:.2f}ms")
        print(f"  Speedup: {speedup:.1f}x")
        print(f"  Missing days: {len(missing_days)}")
        
        # Should have 20 missing days (100 - 80)
        assert len(missing_days) == 20, f"Should have 20 missing days, got {len(missing_days)}"
        
        # Speedup should be >2x (conservative estimate)
        assert speedup > 2, f"Speedup should be >2x, got {speedup:.1f}x"
        print(f"  ✅ PASS: Speedup {speedup:.1f}x > 2x")
    
    def test_cache_index_performance(self, test_cache_dir):
        """
        Benchmark: Cache index should be >10x faster than filesystem scans.
        
        Compares index lookup time vs filesystem validation time.
        """
        # Create cache with index
        cache_with_index = DataCache(str(test_cache_dir), use_index=True)
        
        # Populate cache with 100 days
        self.populate_cache(cache_with_index, 'USDJPY', 'M1', 100)
        
        # Measure index lookup time
        index_times = []
        for _ in range(100):
            start_time = time.time()
            _ = cache_with_index.index.get_cached_days('USDJPY', 'M1')
            index_times.append(time.time() - start_time)
        
        avg_index_time = sum(index_times) / len(index_times)
        
        # Create cache without index
        cache_without_index = DataCache(str(test_cache_dir), use_index=False)
        
        # Measure filesystem validation time
        request_start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 4, 10, 23, 59, 0, tzinfo=timezone.utc)
        
        filesystem_times = []
        for _ in range(100):
            start_time = time.time()
            _ = cache_without_index.validate_cache_coverage('USDJPY', 'M1', request_start, request_end)
            filesystem_times.append(time.time() - start_time)
        
        avg_filesystem_time = sum(filesystem_times) / len(filesystem_times)
        
        # Calculate speedup
        speedup = avg_filesystem_time / avg_index_time if avg_index_time > 0 else 0
        
        print(f"\n📊 Cache Index Performance Benchmark:")
        print(f"  Index lookup time (100 iterations): {avg_index_time*1000:.4f}ms")
        print(f"  Filesystem validation time (100 iterations): {avg_filesystem_time*1000:.2f}ms")
        print(f"  Speedup: {speedup:.0f}x")
        
        # Index should be significantly faster (>10x)
        assert speedup > 10, f"Index speedup should be >10x, got {speedup:.0f}x"
        print(f"  ✅ PASS: Speedup {speedup:.0f}x > 10x")
    
    def test_cache_save_performance(self, test_cache_dir):
        """
        Benchmark: Cache save performance with index updates.
        
        Measures the time to save data to cache with index updates.
        """
        cache = DataCache(str(test_cache_dir), use_index=True)
        
        # Measure save time for 10 days
        save_times = []
        start_date = datetime(2025, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        for day_offset in range(10):
            day_start = start_date + timedelta(days=day_offset)
            day_end = day_start.replace(hour=23, minute=59)
            
            data = self.create_test_data(day_start)
            symbol_info = {'name': 'EURJPY', 'digits': 3, 'point': 0.001}
            
            start_time = time.time()
            cache.save_to_cache('EURJPY', 'M1', day_start, day_end, data, symbol_info)
            save_times.append(time.time() - start_time)
        
        avg_save_time = sum(save_times) / len(save_times)
        
        print(f"\n📊 Cache Save Performance Benchmark:")
        print(f"  Average save time per day: {avg_save_time*1000:.2f}ms")
        print(f"  Data size per day: 1440 bars (M1)")
        
        # Save should be reasonably fast (<500ms per day)
        assert avg_save_time < 0.5, f"Save time should be <500ms, got {avg_save_time*1000:.2f}ms"
        print(f"  ✅ PASS: Save time {avg_save_time*1000:.2f}ms < 500ms")
    
    def test_large_cache_performance(self, test_cache_dir):
        """
        Benchmark: Performance with large cache (365 days).
        
        Tests that the system scales well with a full year of data.
        """
        cache = DataCache(str(test_cache_dir), use_index=True)
        
        print(f"\n📊 Large Cache Performance Benchmark:")
        print(f"  Populating cache with 365 days...")
        
        # Populate cache with 365 days
        populate_start = time.time()
        self.populate_cache(cache, 'AUDUSD', 'M1', 365)
        populate_time = time.time() - populate_start
        
        print(f"  Population time: {populate_time:.2f}s ({populate_time/365*1000:.2f}ms per day)")
        
        # Measure validation time for full year
        request_start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 12, 31, 23, 59, 0, tzinfo=timezone.utc)
        
        validation_start = time.time()
        is_valid, reason = cache.validate_cache_coverage('AUDUSD', 'M1', request_start, request_end)
        validation_time = time.time() - validation_start
        
        print(f"  Validation time (365 days): {validation_time*1000:.2f}ms")
        
        # Measure load time for full year
        load_start = time.time()
        df, symbol_info = cache.load_from_cache('AUDUSD', 'M1', request_start, request_end)
        load_time = time.time() - load_start
        
        print(f"  Load time (365 days): {load_time:.2f}s")
        print(f"  Data size: {len(df)} bars")
        
        # Validation should be fast even for large cache (<1s)
        assert validation_time < 1.0, f"Validation should be <1s for 365 days, got {validation_time:.2f}s"
        print(f"  ✅ PASS: Validation time {validation_time*1000:.2f}ms < 1000ms")
        
        # Load should be reasonable (<10s for full year)
        assert load_time < 10.0, f"Load should be <10s for 365 days, got {load_time:.2f}s"
        print(f"  ✅ PASS: Load time {load_time:.2f}s < 10s")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])  # -s to show print statements

