"""
Test double-buffering correctness by running backtest multiple times.

This script runs the backtest 3 times and verifies that results are identical,
which confirms there are no race conditions in the double-buffering implementation.
"""

import subprocess
import sys
import time
from pathlib import Path


def run_backtest(run_number: int) -> dict:
    """Run backtest and return results."""
    print(f"\n{'='*80}")
    print(f"RUN #{run_number}")
    print(f"{'='*80}\n")
    
    start_time = time.time()
    
    # Run backtest
    result = subprocess.run(
        [sys.executable, "backtest.py"],
        capture_output=True,
        text=True
    )
    
    elapsed = time.time() - start_time
    
    if result.returncode != 0:
        print(f"❌ Run #{run_number} FAILED")
        print(f"Error: {result.stderr}")
        return None
    
    # Extract final balance from output
    output = result.stdout
    final_balance = None
    trade_count = None
    
    for line in output.split('\n'):
        if 'Final Balance' in line:
            # Extract balance value
            parts = line.split('$')
            if len(parts) > 1:
                try:
                    final_balance = float(parts[1].split()[0].replace(',', ''))
                except:
                    pass
        if 'Total Trades' in line or 'Trades:' in line:
            # Extract trade count
            try:
                trade_count = int(line.split(':')[-1].strip().split()[0])
            except:
                pass
    
    print(f"✓ Run #{run_number} completed in {elapsed:.2f} seconds")
    print(f"  Final Balance: ${final_balance:.2f}" if final_balance else "  Final Balance: Unknown")
    print(f"  Trade Count: {trade_count}" if trade_count else "  Trade Count: Unknown")
    
    return {
        'run': run_number,
        'elapsed': elapsed,
        'final_balance': final_balance,
        'trade_count': trade_count,
        'output': output
    }


def main():
    """Run multiple backtests and compare results."""
    print("="*80)
    print("DOUBLE-BUFFERING CORRECTNESS TEST")
    print("="*80)
    print()
    print("This test runs the backtest 3 times to verify:")
    print("1. No race conditions in double-buffering")
    print("2. Results are deterministic and identical")
    print("3. Thread safety is maintained")
    print()
    
    num_runs = 3
    results = []
    
    for i in range(1, num_runs + 1):
        result = run_backtest(i)
        if result is None:
            print(f"\n❌ TEST FAILED: Run #{i} did not complete successfully")
            return 1
        results.append(result)
        
        # Small delay between runs
        if i < num_runs:
            time.sleep(2)
    
    # Compare results
    print(f"\n{'='*80}")
    print("RESULTS COMPARISON")
    print(f"{'='*80}\n")
    
    # Check if all final balances match
    balances = [r['final_balance'] for r in results if r['final_balance'] is not None]
    trade_counts = [r['trade_count'] for r in results if r['trade_count'] is not None]
    
    if len(balances) == num_runs:
        balance_match = all(abs(b - balances[0]) < 0.01 for b in balances)
        print(f"Final Balances: {balances}")
        print(f"  Match: {'✓ YES' if balance_match else '✗ NO'}")
    else:
        print(f"⚠ Could not extract final balance from all runs")
        balance_match = False
    
    if len(trade_counts) == num_runs:
        trades_match = all(t == trade_counts[0] for t in trade_counts)
        print(f"Trade Counts: {trade_counts}")
        print(f"  Match: {'✓ YES' if trades_match else '✗ NO'}")
    else:
        print(f"⚠ Could not extract trade count from all runs")
        trades_match = False
    
    # Performance stats
    elapsed_times = [r['elapsed'] for r in results]
    avg_time = sum(elapsed_times) / len(elapsed_times)
    print(f"\nPerformance:")
    print(f"  Average time: {avg_time:.2f} seconds")
    print(f"  Min time: {min(elapsed_times):.2f} seconds")
    print(f"  Max time: {max(elapsed_times):.2f} seconds")
    
    # Final verdict
    print(f"\n{'='*80}")
    if balance_match and trades_match:
        print("✓ TEST PASSED: All runs produced identical results")
        print("✓ Double-buffering is working correctly (no race conditions)")
        print(f"{'='*80}\n")
        return 0
    else:
        print("✗ TEST FAILED: Results differ between runs")
        print("✗ Possible race condition in double-buffering")
        print(f"{'='*80}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())

