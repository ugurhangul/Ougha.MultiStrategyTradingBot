# How to Profile Your Working Backtest

Since the standalone profiler can't access MT5 data for historical dates, you need to profile your actual working backtest.

## Method 1: Add Profiling to backtest.py (Recommended)

### Step 1: Add profiling code to backtest.py

Find this section in `backtest.py` (around line 1762):

```python
try:
    # Run the backtest
    # Pass START_DATE for log directory naming (data was loaded from earlier for lookback)
    if USE_SEQUENTIAL_MODE:
        # PERFORMANCE: Sequential mode (10-50x faster, no threading)
        backtest_controller.run_sequential(backtest_start_time=START_DATE)
    else:
        # Threaded mode (tests exact live trading behavior)
        backtest_controller.run(backtest_start_time=START_DATE)
```

Replace with:

```python
try:
    # Run the backtest with profiling
    import cProfile
    import pstats
    from pathlib import Path
    
    # Create profiler
    profiler = cProfile.Profile()
    profiler.enable()
    
    # Run the backtest
    # Pass START_DATE for log directory naming (data was loaded from earlier for lookback)
    if USE_SEQUENTIAL_MODE:
        # PERFORMANCE: Sequential mode (10-50x faster, no threading)
        backtest_controller.run_sequential(backtest_start_time=START_DATE)
    else:
        # Threaded mode (tests exact live trading behavior)
        backtest_controller.run(backtest_start_time=START_DATE)
    
    # Stop profiling
    profiler.disable()
    
    # Save results
    profile_dir = Path("profile_results")
    profile_dir.mkdir(exist_ok=True)
    
    profile_file = profile_dir / f"backtest_profile_{START_DATE.strftime('%Y%m%d')}.prof"
    profiler.dump_stats(str(profile_file))
    
    # Print top 30 functions
    print("\n" + "=" * 80)
    print("PROFILING RESULTS - TOP 30 FUNCTIONS BY CUMULATIVE TIME")
    print("=" * 80)
    
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumtime')
    stats.print_stats(30)
    
    # Save to text file
    text_file = profile_dir / f"backtest_profile_{START_DATE.strftime('%Y%m%d')}.txt"
    with open(text_file, 'w') as f:
        stats = pstats.Stats(profiler, stream=f)
        stats.sort_stats('cumtime')
        stats.print_stats(50)
    
    print(f"\nProfile saved to:")
    print(f"  Binary: {profile_file}")
    print(f"  Text:   {text_file}")
    print("=" * 80)
```

### Step 2: Run your backtest normally

```bash
python backtest.py
```

### Step 3: Analyze results

The profiling results will be printed at the end and saved to:
- `profile_results/backtest_profile_YYYYMMDD.prof` (binary format)
- `profile_results/backtest_profile_YYYYMMDD.txt` (text format)

Look for:
1. **Top functions by cumulative time** - these are the bottlenecks
2. **Functions in your code** (not Python stdlib or libraries)
3. **Functions called many times** with high tottime

---

## Method 2: Profile Specific Section (For Targeted Analysis)

If you want to profile only the tick processing loop (not data loading), add profiling around the specific section:

### In backtest_controller.py (around line 500-600)

Find the main tick processing loop in `run_sequential()`:

```python
def run_sequential(self, backtest_start_time: Optional[datetime] = None):
    # ... setup code ...
    
    # Main tick processing loop
    for tick in ticks:
        # Process tick
        # ...
```

Wrap just the loop:

```python
def run_sequential(self, backtest_start_time: Optional[datetime] = None):
    # ... setup code ...
    
    import cProfile
    import pstats
    
    profiler = cProfile.Profile()
    profiler.enable()
    
    # Main tick processing loop
    for tick in ticks:
        # Process tick
        # ...
    
    profiler.disable()
    
    # Print results
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumtime')
    stats.print_stats(30)
```

This will profile ONLY the tick processing, excluding data loading and setup.

---

## Method 3: Use line_profiler for Line-by-Line Analysis

For detailed line-by-line profiling of specific functions:

### Step 1: Install line_profiler

```bash
pip install line_profiler
```

### Step 2: Add @profile decorator to functions you want to profile

```python
# In fakeout_strategy.py
@profile
def on_tick(self, tick_data: Dict[str, Any]) -> None:
    # ... strategy code ...
```

### Step 3: Run with kernprof

```bash
kernprof -l -v backtest.py
```

This will show you exactly which lines are slow within each function.

---

## What to Look For in Profiling Results

### 1. **High Cumulative Time (cumtime)**

Functions with high cumtime are the bottlenecks. Focus on:
- Functions in your code (not stdlib)
- Functions called many times
- Functions with high cumtime/call ratio

Example:
```
ncalls  tottime  percall  cumtime  percall filename:lineno(function)
100000    0.500    0.000    5.000    0.000 fakeout_strategy.py:123(on_tick)
```

This means `on_tick()` was called 100,000 times and took 5 seconds total (5% of total time if backtest took 100 seconds).

### 2. **High Total Time (tottime)**

Functions with high tottime are doing actual work (not calling other functions). These are good optimization targets.

### 3. **High Call Count (ncalls)**

Functions called many times are good candidates for caching or optimization.

---

## Example Analysis

Let's say profiling shows:

```
ncalls  tottime  percall  cumtime  percall filename:lineno(function)
500000    2.500    0.000   15.000    0.000 base_strategy.py:565(get_candles_cached)
500000    5.000    0.000   10.000    0.000 talib._ta_lib.RSI
300000    3.000    0.000    8.000    0.000 fakeout_strategy.py:234(_check_divergence)
```

**Analysis**:
1. `get_candles_cached()` called 500k times, taking 15s total (15% of time)
   - **Action**: Already optimized with DataFrame caching
   - **Next**: Check if we can reduce call count

2. `talib.RSI()` called 500k times, taking 10s total (10% of time)
   - **Action**: Implement indicator caching
   - **Expected gain**: 10% speedup

3. `_check_divergence()` called 300k times, taking 8s total (8% of time)
   - **Action**: Optimize divergence detection logic
   - **Expected gain**: 5-8% speedup

**Total potential gain**: 15-18% speedup

---

## Recommended Workflow

1. **Add profiling to backtest.py** (Method 1)
2. **Run a short backtest** (1-2 days) to get profiling data
3. **Analyze top 10-20 functions** by cumtime
4. **Identify optimization opportunities**:
   - Caching (indicators, calculations)
   - Reducing call count (early exits, lazy evaluation)
   - Algorithmic improvements (better data structures)
5. **Implement highest-impact optimization**
6. **Re-profile and measure improvement**
7. **Repeat until satisfied**

---

## Notes

- **Don't optimize without profiling!** You'll waste time on the wrong things.
- **Focus on cumtime, not tottime** for finding bottlenecks.
- **Optimize the top 3-5 functions** - they usually account for 80% of time.
- **Measure improvement** after each optimization.
- **Stop when gains < 5%** - diminishing returns.

---

## Summary

**Best Approach**: Add profiling to backtest.py (Method 1)

**Steps**:
1. Add profiling code to backtest.py
2. Run your normal backtest
3. Analyze results
4. Implement targeted optimizations
5. Re-profile and measure

**Expected Outcome**: Identify the actual bottlenecks and achieve 5-15% additional speedup with targeted optimizations.

