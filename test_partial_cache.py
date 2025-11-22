#!/usr/bin/env python3
"""
Test script for partial cache loading functionality.
"""

import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from src.backtesting.engine.data_cache import DataCache


def test_partial_cache_loading():
    """Test partial cache loading with missing days."""
    
    print("="*60)
    print("TESTING PARTIAL CACHE LOADING")
    print("="*60)
    
    # Create temporary cache directory
    test_cache_dir = Path("data/test_partial_cache")
    if test_cache_dir.exists():
        shutil.rmtree(test_cache_dir)
    
    try:
        cache = DataCache(str(test_cache_dir), cache_ttl_days=7)
        
        # Test 1: Complete cache (all days available)
        print("\n" + "="*60)
        print("TEST 1: Complete cache (all days available)")
        print("="*60)
        
        # Cache 3 days of data
        for day_offset in range(3):
            day_start = datetime(2025, 1, 1 + day_offset, 0, 0, 0, tzinfo=timezone.utc)
            day_end = datetime(2025, 1, 1 + day_offset, 23, 59, 0, tzinfo=timezone.utc)
            
            test_data = pd.DataFrame({
                'time': pd.date_range(day_start, periods=1440, freq='1min'),
                'open': [1.1000 + day_offset*0.01 + i*0.0001 for i in range(1440)],
                'high': [1.1010 + day_offset*0.01 + i*0.0001 for i in range(1440)],
                'low': [1.0990 + day_offset*0.01 + i*0.0001 for i in range(1440)],
                'close': [1.1005 + day_offset*0.01 + i*0.0001 for i in range(1440)],
                'tick_volume': [100 + i for i in range(1440)]
            })
            
            symbol_info = {'name': 'EURUSD', 'digits': 5, 'point': 0.00001}
            cache.save_to_cache('EURUSD', 'M1', day_start, day_end, test_data, symbol_info)
        
        # Load with all days cached
        request_start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        request_end = datetime(2025, 1, 3, 23, 59, 0, tzinfo=timezone.utc)
        
        cached_df, missing_days, symbol_info = cache.load_from_cache_partial('EURUSD', 'M1', request_start, request_end)
        
        if cached_df is not None and len(missing_days) == 0:
            print(f"✅ PASS: Complete cache loaded")
            print(f"  Cached bars: {len(cached_df)}")
            print(f"  Missing days: {len(missing_days)}")
        else:
            print(f"❌ FAIL: Expected complete cache, got {len(missing_days)} missing days")
            return False
        
        # Test 2: Partial cache (some days missing)
        print("\n" + "="*60)
        print("TEST 2: Partial cache (some days missing)")
        print("="*60)
        
        # Request 5 days but only 3 are cached
        request_end_5days = datetime(2025, 1, 5, 23, 59, 0, tzinfo=timezone.utc)
        
        cached_df, missing_days, symbol_info = cache.load_from_cache_partial('EURUSD', 'M1', request_start, request_end_5days)
        
        if cached_df is not None and len(missing_days) == 2:
            print(f"✅ PASS: Partial cache detected")
            print(f"  Cached bars: {len(cached_df)}")
            print(f"  Missing days: {len(missing_days)}")
            print(f"  Missing dates: {[d.date() for d in missing_days]}")
            
            # Verify missing days are correct
            expected_missing = [
                datetime(2025, 1, 4, 0, 0, 0, tzinfo=timezone.utc),
                datetime(2025, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
            ]
            if missing_days == expected_missing:
                print(f"  ✓ Missing days are correct")
            else:
                print(f"  ✗ Missing days incorrect: expected {[d.date() for d in expected_missing]}")
                return False
        else:
            print(f"❌ FAIL: Expected 2 missing days, got {len(missing_days)}")
            return False
        
        # Test 3: No cache (all days missing)
        print("\n" + "="*60)
        print("TEST 3: No cache (all days missing)")
        print("="*60)
        
        # Request days that don't exist in cache
        no_cache_start = datetime(2025, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        no_cache_end = datetime(2025, 2, 3, 23, 59, 0, tzinfo=timezone.utc)
        
        cached_df, missing_days, symbol_info = cache.load_from_cache_partial('GBPUSD', 'M1', no_cache_start, no_cache_end)
        
        if cached_df is None and len(missing_days) == 3:
            print(f"✅ PASS: No cache detected")
            print(f"  Cached bars: None")
            print(f"  Missing days: {len(missing_days)}")
            print(f"  Missing dates: {[d.date() for d in missing_days]}")
        else:
            print(f"❌ FAIL: Expected no cache and 3 missing days, got cached_df={cached_df is not None}, missing={len(missing_days)}")
            return False
        
        # Test 4: Interleaved missing days
        print("\n" + "="*60)
        print("TEST 4: Interleaved missing days (day 1, 3, 5 cached)")
        print("="*60)
        
        # Cache days 1, 3, 5 (skip 2, 4)
        for day_offset in [0, 2, 4]:  # Jan 1, 3, 5
            day_start = datetime(2025, 3, 1 + day_offset, 0, 0, 0, tzinfo=timezone.utc)
            day_end = datetime(2025, 3, 1 + day_offset, 23, 59, 0, tzinfo=timezone.utc)
            
            test_data = pd.DataFrame({
                'time': pd.date_range(day_start, periods=100, freq='1min'),
                'open': [1.3000] * 100,
                'high': [1.3010] * 100,
                'low': [1.2990] * 100,
                'close': [1.3005] * 100,
                'tick_volume': [100] * 100
            })
            
            cache.save_to_cache('AUDUSD', 'M1', day_start, day_end, test_data, symbol_info)
        
        # Request all 5 days
        interleaved_start = datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        interleaved_end = datetime(2025, 3, 5, 23, 59, 0, tzinfo=timezone.utc)
        
        cached_df, missing_days, symbol_info = cache.load_from_cache_partial('AUDUSD', 'M1', interleaved_start, interleaved_end)
        
        if cached_df is not None and len(missing_days) == 2:
            print(f"✅ PASS: Interleaved cache detected")
            print(f"  Cached bars: {len(cached_df)}")
            print(f"  Missing days: {len(missing_days)}")
            print(f"  Missing dates: {[d.date() for d in missing_days]}")
            
            # Verify missing days are correct (Mar 2 and Mar 4)
            expected_missing = [
                datetime(2025, 3, 2, 0, 0, 0, tzinfo=timezone.utc),
                datetime(2025, 3, 4, 0, 0, 0, tzinfo=timezone.utc)
            ]
            if missing_days == expected_missing:
                print(f"  ✓ Missing days are correct")
            else:
                print(f"  ✗ Missing days incorrect: expected {[d.date() for d in expected_missing]}")
                return False
        else:
            print(f"❌ FAIL: Expected 2 missing days, got {len(missing_days)}")
            return False
        
        # Test 5: Expired cache treated as missing
        print("\n" + "="*60)
        print("TEST 5: Expired cache treated as missing")
        print("="*60)
        
        # Create cache with old timestamp
        import pyarrow as pa
        import pyarrow.parquet as pq
        
        old_cached_at = datetime.now(timezone.utc) - timedelta(days=10)
        old_start = datetime(2025, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
        old_end = datetime(2025, 4, 1, 23, 59, 0, tzinfo=timezone.utc)
        
        old_data = pd.DataFrame({
            'time': pd.date_range(old_start, periods=100, freq='1min'),
            'open': [1.4000] * 100,
            'high': [1.4010] * 100,
            'low': [1.3990] * 100,
            'close': [1.4005] * 100,
            'tick_volume': [100] * 100
        })
        
        cache_path = cache._get_day_cache_path(old_start, 'USDJPY', 'M1')
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        metadata = {
            'cached_at': old_cached_at.isoformat(),
            'source': 'mt5',
            'first_data_time': old_data['time'].iloc[0].isoformat(),
            'last_data_time': old_data['time'].iloc[-1].isoformat(),
            'row_count': str(len(old_data)),
            'cache_version': '1.0'
        }
        
        metadata_bytes = {k.encode(): v.encode() for k, v in metadata.items()}
        table = pa.Table.from_pandas(old_data, preserve_index=False)
        table = table.replace_schema_metadata(metadata_bytes)
        pq.write_table(table, cache_path, compression='snappy')
        
        cached_df, missing_days, symbol_info = cache.load_from_cache_partial('USDJPY', 'M1', old_start, old_end)
        
        if cached_df is None and len(missing_days) == 1:
            print(f"✅ PASS: Expired cache treated as missing")
            print(f"  Missing days: {len(missing_days)}")
        else:
            print(f"❌ FAIL: Expected expired cache to be missing, got cached_df={cached_df is not None}, missing={len(missing_days)}")
            return False
        
        print("\n" + "="*60)
        print("✅ ALL PARTIAL CACHE TESTS PASSED!")
        print("="*60)
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup
        if test_cache_dir.exists():
            shutil.rmtree(test_cache_dir)
            print(f"\n🧹 Cleaned up test cache directory")


if __name__ == '__main__':
    success = test_partial_cache_loading()
    sys.exit(0 if success else 1)

