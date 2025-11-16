"""
Run backtest with performance timing.

This script runs the backtest and measures wall-clock time and steps/second.
"""

import time
from backtest import main

if __name__ == "__main__":
    print("=" * 80)
    print("BACKTEST PERFORMANCE TEST - Phase 2 (Volume Cache)")
    print("=" * 80)
    print()
    
    start_time = time.time()
    
    # Run backtest
    main()
    
    end_time = time.time()
    elapsed = end_time - start_time
    
    print()
    print("=" * 80)
    print("PERFORMANCE RESULTS")
    print("=" * 80)
    print(f"Wall-clock time: {elapsed:.2f} seconds ({elapsed/60:.2f} minutes)")
    print()
    print("Compare with Phase 1 results to measure speedup.")
    print("=" * 80)

