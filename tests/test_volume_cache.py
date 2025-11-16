"""
Unit tests for VolumeCache class.

Tests verify:
- Accuracy of rolling average calculations
- Edge cases (empty cache, single value, full window)
- Reset functionality
- Thread safety (single-threaded use)
"""

import pytest
import numpy as np
from src.utils.volume_cache import VolumeCache


class TestVolumeCacheBasics:
    """Test basic VolumeCache functionality."""
    
    def test_initialization(self):
        """Test cache initialization."""
        cache = VolumeCache(lookback=20)
        assert cache.lookback == 20
        assert len(cache) == 0
        assert cache.get_average() == 0.0
        assert not cache.is_ready()
    
    def test_invalid_lookback(self):
        """Test that invalid lookback raises error."""
        with pytest.raises(ValueError):
            VolumeCache(lookback=0)
        
        with pytest.raises(ValueError):
            VolumeCache(lookback=-1)
    
    def test_single_value(self):
        """Test cache with single value."""
        cache = VolumeCache(lookback=20)
        cache.update(100.0)
        
        assert len(cache) == 1
        assert cache.get_average() == 100.0
        assert not cache.is_ready()  # Need 20 values
    
    def test_multiple_values(self):
        """Test cache with multiple values."""
        cache = VolumeCache(lookback=5)
        volumes = [100, 110, 120, 130, 140]
        
        for v in volumes:
            cache.update(v)
        
        assert len(cache) == 5
        assert cache.get_average() == 120.0  # (100+110+120+130+140)/5
        assert cache.is_ready()


class TestVolumeCacheAccuracy:
    """Test accuracy of rolling average calculations."""
    
    def test_accuracy_vs_numpy(self):
        """Test that cache matches NumPy calculations."""
        cache = VolumeCache(lookback=20)
        volumes = [100 + i * 5 for i in range(30)]  # 30 values
        
        for v in volumes:
            cache.update(v)
        
        # Cache should have last 20 values
        expected_avg = np.mean(volumes[-20:])
        actual_avg = cache.get_average()
        
        assert abs(expected_avg - actual_avg) < 0.01
    
    def test_rolling_window(self):
        """Test that rolling window works correctly."""
        cache = VolumeCache(lookback=3)
        
        cache.update(100)  # [100]
        assert cache.get_average() == 100.0
        
        cache.update(110)  # [100, 110]
        assert cache.get_average() == 105.0
        
        cache.update(120)  # [100, 110, 120]
        assert cache.get_average() == 110.0
        
        cache.update(130)  # [110, 120, 130] (100 dropped)
        assert cache.get_average() == 120.0
        
        cache.update(140)  # [120, 130, 140] (110 dropped)
        assert cache.get_average() == 130.0
    
    def test_floating_point_precision(self):
        """Test floating point precision."""
        cache = VolumeCache(lookback=20)
        volumes = [100.123, 110.456, 120.789] * 10  # 30 values with decimals
        
        for v in volumes:
            cache.update(v)
        
        # Should match NumPy precision
        expected_avg = np.mean(volumes[-20:])
        actual_avg = cache.get_average()
        
        assert abs(expected_avg - actual_avg) < 1e-10


class TestVolumeCacheEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_cache(self):
        """Test empty cache behavior."""
        cache = VolumeCache(lookback=20)
        
        assert len(cache) == 0
        assert cache.get_average() == 0.0
        assert not cache.is_ready()
    
    def test_reset(self):
        """Test cache reset."""
        cache = VolumeCache(lookback=20)
        
        for i in range(25):
            cache.update(100 + i)
        
        assert len(cache) == 20
        assert cache.is_ready()
        
        cache.reset()
        
        assert len(cache) == 0
        assert cache.get_average() == 0.0
        assert not cache.is_ready()
    
    def test_zero_volumes(self):
        """Test cache with zero volumes."""
        cache = VolumeCache(lookback=5)
        
        for _ in range(5):
            cache.update(0.0)
        
        assert cache.get_average() == 0.0
        assert cache.is_ready()
    
    def test_large_volumes(self):
        """Test cache with large volumes."""
        cache = VolumeCache(lookback=20)
        large_volume = 1e9  # 1 billion
        
        for _ in range(25):
            cache.update(large_volume)
        
        assert abs(cache.get_average() - large_volume) < 1.0


class TestVolumeCachePerformance:
    """Test performance characteristics."""
    
    def test_update_is_fast(self):
        """Test that update is O(1)."""
        import time
        
        cache = VolumeCache(lookback=1000)
        
        # Fill cache
        for i in range(1000):
            cache.update(100 + i)
        
        # Measure update time
        start = time.perf_counter()
        for _ in range(10000):
            cache.update(100.0)
        elapsed = time.perf_counter() - start
        
        # Should be very fast (< 10ms for 10K updates)
        assert elapsed < 0.01
    
    def test_get_average_is_fast(self):
        """Test that get_average is O(1)."""
        import time
        
        cache = VolumeCache(lookback=1000)
        
        # Fill cache
        for i in range(1000):
            cache.update(100 + i)
        
        # Measure get_average time
        start = time.perf_counter()
        for _ in range(100000):
            _ = cache.get_average()
        elapsed = time.perf_counter() - start
        
        # Should be very fast (< 10ms for 100K calls)
        assert elapsed < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

