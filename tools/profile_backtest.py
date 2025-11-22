"""
Profiling tool for backtesting performance analysis.

This script profiles the backtesting engine to identify hot spots and bottlenecks.
It uses cProfile to measure CPU time spent in each function.

Usage:
    python tools/profile_backtest.py [--ticks N] [--output FILE]

Options:
    --ticks N           : Number of ticks to process (default: 1000000)
    --output FILE       : Save profiling results to file (default: profile_results.txt)
    --top N             : Show top N functions by time (default: 50)
    --sort METRIC       : Sort by metric (time, cumtime, calls) (default: cumtime)
"""

import cProfile
import pstats
import io
import sys
import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set environment variable to run in sequential mode
os.environ['BACKTEST_SEQUENTIAL_MODE'] = '1'


def profile_backtest(num_ticks: int = 1000000, output_file: str = "profile_results.txt",
                     top_n: int = 50, sort_by: str = "cumtime"):
    """
    Profile the backtesting engine by running backtest.py with profiling.

    Args:
        num_ticks: Number of ticks to process (default: 1,000,000)
        output_file: Where to save profiling results
        top_n: Number of top functions to display
        sort_by: Metric to sort by (time, cumtime, calls)
    """
    print("=" * 80)
    print("BACKTESTING PERFORMANCE PROFILER")
    print("=" * 80)
    print(f"Ticks to Process: {num_ticks:,}")
    print(f"Output: {output_file}")
    print(f"Top Functions: {top_n}")
    print(f"Sort By: {sort_by}")
    print("=" * 80)

    # Import backtest main function
    import backtest

    # Override configuration for profiling
    backtest.USE_TICK_DATA = True
    backtest.SEQUENTIAL_MODE = True
    backtest.SYMBOLS = ["EURUSD"]  # Single symbol for simplicity
    backtest.START_DATE = datetime(2024, 10, 1, tzinfo=backtest.timezone.utc)  # Use historical date with data
    backtest.END_DATE = datetime(2024, 10, 2, tzinfo=backtest.timezone.utc)  # 1 day
    backtest.INITIAL_BALANCE = 10000.0

    print(f"\nConfiguration:")
    print(f"  Symbols: {backtest.SYMBOLS}")
    print(f"  Period: {backtest.START_DATE.date()} to {backtest.END_DATE.date()}")
    print(f"  Mode: Sequential (tick-level)")
    print(f"  Initial Balance: ${backtest.INITIAL_BALANCE:,.2f}")

    print(f"\nStarting profiler...")
    print("=" * 80)

    # Create profiler
    profiler = cProfile.Profile()

    # Start profiling
    profiler.enable()

    try:
        # Run backtest
        backtest.main()

    except KeyboardInterrupt:
        print("\n\nProfiling interrupted by user")
    except Exception as e:
        print(f"\n\nERROR during backtest: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Stop profiling
        profiler.disable()
    
    print("=" * 80)
    print("Profiling complete. Analyzing results...")
    print("=" * 80)
    
    # Create stats object
    stats = pstats.Stats(profiler)
    
    # Sort by cumulative time
    stats.sort_stats(sort_by)
    
    # Print to console
    print(f"\n{'=' * 80}")
    print(f"TOP {top_n} FUNCTIONS BY {sort_by.upper()}")
    print(f"{'=' * 80}\n")
    
    # Capture output
    string_io = io.StringIO()
    ps = pstats.Stats(profiler, stream=string_io)
    ps.sort_stats(sort_by)
    ps.print_stats(top_n)
    
    # Print to console
    output = string_io.getvalue()
    print(output)
    
    # Save to file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get total time from stats
    total_time = sum(stat[2] for stat in stats.stats.values())

    with open(output_path, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("BACKTESTING PERFORMANCE PROFILE\n")
        f.write("=" * 80 + "\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total CPU Time: {total_time:.2f} seconds\n")
        f.write(f"Symbols: {backtest.SYMBOLS}\n")
        f.write(f"Period: {backtest.START_DATE.date()} to {backtest.END_DATE.date()}\n")
        f.write(f"Sort By: {sort_by}\n")
        f.write("=" * 80 + "\n\n")
        f.write(output)

        # Add callers for top 10 functions
        f.write("\n" + "=" * 80 + "\n")
        f.write("CALLERS FOR TOP 10 FUNCTIONS\n")
        f.write("=" * 80 + "\n\n")

        string_io2 = io.StringIO()
        ps2 = pstats.Stats(profiler, stream=string_io2)
        ps2.sort_stats(sort_by)
        ps2.print_callers(10)
        f.write(string_io2.getvalue())
    
    print(f"\n{'=' * 80}")
    print(f"Results saved to: {output_path.absolute()}")
    print(f"{'=' * 80}")
    
    # Print summary statistics
    print(f"\n{'=' * 80}")
    print("SUMMARY STATISTICS")
    print(f"{'=' * 80}")
    
    # Get total time
    total_time = sum(stat[2] for stat in stats.stats.values())
    print(f"Total CPU Time: {total_time:.2f} seconds")
    
    # Get top 5 functions
    print(f"\nTop 5 Functions by Cumulative Time:")
    stats.sort_stats('cumtime')
    
    # Extract top 5
    items = list(stats.stats.items())[:5]
    for i, (func, (cc, nc, tt, ct, callers)) in enumerate(items, 1):
        func_name = f"{func[0]}:{func[1]}({func[2]})"
        pct = (ct / total_time * 100) if total_time > 0 else 0
        print(f"  {i}. {func_name}")
        print(f"     Cumulative Time: {ct:.3f}s ({pct:.1f}%)")
        print(f"     Calls: {nc:,}")
    
    print(f"\n{'=' * 80}")
    print("PROFILING COMPLETE")
    print(f"{'=' * 80}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Profile backtesting performance",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--ticks',
        type=int,
        default=1000000,
        help='Number of ticks to process (default: 1,000,000)'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='profile_results.txt',
        help='Save profiling results to file (default: profile_results.txt)'
    )
    
    parser.add_argument(
        '--top',
        type=int,
        default=50,
        help='Show top N functions by time (default: 50)'
    )
    
    parser.add_argument(
        '--sort',
        type=str,
        default='cumtime',
        choices=['time', 'cumtime', 'calls'],
        help='Sort by metric (default: cumtime)'
    )
    
    args = parser.parse_args()

    profile_backtest(
        num_ticks=args.ticks,
        output_file=args.output,
        top_n=args.top,
        sort_by=args.sort
    )


if __name__ == '__main__':
    main()

