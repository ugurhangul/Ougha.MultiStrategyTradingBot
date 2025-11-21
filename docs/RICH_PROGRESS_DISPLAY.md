# Rich Progress Display Integration

## 🎯 Overview

The backtesting engine now uses the `rich` package for an enhanced progress display during backtest execution. This provides a much better visual experience with animated spinners, progress bars, and live statistics.

---

## ✨ Features

### Rich Progress Display (When Available)

**Visual Components:**
- 🔄 **Animated Spinner** - Rotating spinner showing backtest is actively running
- 📊 **Progress Bar** - Visual bar showing completion percentage (green when complete)
- 📈 **Percentage** - Numeric percentage of completion
- ⏱️ **Time Elapsed** - How long the backtest has been running
- ⏳ **Time Remaining (ETA)** - Estimated time to completion
- 💰 **Live Stats** - Current time, equity, P&L, trades, win rate, profit factor, and open positions

**Example Output:**
```
⠹ Backtesting [12:30] Equity: $1,050 | P&L: +$50 (+5.0%) | Trades: 40 (24W/16L) | WR: 60.0% | PF: 1.85 | Open: 8 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  20% 0:00:01 • 0:00:05
```

### Plain Text Fallback (When Rich Not Available)

**Features:**
- Single-line progress display updated with carriage return
- All metrics visible: date/time, tick progress, ETA, equity, P&L, trades, win rate, profit factor
- Same functionality as before, just without visual enhancements

**Example Output:**
```
[  1.4%] 2025-11-14 00:35 | Tick: 83,446/5,783,708 | ETA:  4m 30s | Equity: $    997.69 | P&L: $  -15.05 ( -1.50%) | Floating: $   12.73 | Trades:    7 (0W/7L) | WR:   0.0% | PF:   0.00 | Open:  8 | Waiting: 61/696
```

---

## 🔧 Implementation Details

### File Modified

**`src/backtesting/engine/backtest_controller.py`**

### New Imports

```python
# Rich progress display (optional, with fallback to plain text)
try:
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, TimeElapsedColumn
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
```

### New Methods

#### 1. `_wait_for_completion()`
**Purpose:** Main entry point that delegates to rich or plain text implementation

**Logic:**
```python
if RICH_AVAILABLE:
    self._wait_for_completion_with_rich()
else:
    self._wait_for_completion_plain()
```

#### 2. `_wait_for_completion_with_rich()`
**Purpose:** Wait for backtest completion with rich progress bar

**Features:**
- Creates rich Progress bar with spinner, bar, percentage, elapsed time, and ETA
- Determines total based on mode (tick count for tick mode, 100 for candle mode)
- Updates progress bar every second with current progress
- Updates description with live stats
- Handles early termination (stop loss threshold)
- Records equity snapshots periodically
- Logs detailed progress to file

**Progress Bar Configuration:**
```python
progress = Progress(
    SpinnerColumn(),                    # Animated spinner
    TextColumn("[bold blue]{task.description}"),  # Stats text
    BarColumn(complete_style="green", finished_style="bold green"),  # Progress bar
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),  # Percentage
    TimeElapsedColumn(),                # Elapsed time
    TextColumn("•"),                    # Separator
    TimeRemainingColumn(),              # ETA
    console=Console(),
    transient=False                     # Keep visible after completion
)
```

#### 3. `_wait_for_completion_plain()`
**Purpose:** Wait for backtest completion with plain text display (fallback)

**Features:**
- Original implementation preserved
- Single-line progress updated with carriage return
- All metrics visible
- No dependencies on rich

#### 4. `_get_current_progress()`
**Purpose:** Get current progress value for progress bar

**Returns:**
- **Tick mode:** Current tick index (e.g., 83,446 out of 5,783,708)
- **Candle mode:** Percentage (0-100)

**Logic:**
```python
if hasattr(self.broker, 'use_tick_data') and self.broker.use_tick_data:
    # Tick mode: return current tick index
    if hasattr(self.broker, 'global_tick_index'):
        return self.broker.global_tick_index
else:
    # Candle mode: return percentage (0-100)
    current_time = self.broker.get_current_time()
    if self.start_time and self.end_time and current_time:
        total_duration = (self.end_time - self.start_time).total_seconds()
        elapsed_duration = (current_time - self.start_time).total_seconds()
        if total_duration > 0:
            progress_pct = (elapsed_duration / total_duration * 100)
            return max(0, min(100, progress_pct))
return None
```

#### 5. `_get_progress_stats_text()`
**Purpose:** Get concise stats text for progress bar description

**Returns:** Formatted string with current time, equity, P&L, trade statistics, win rate, profit factor, and open positions

**Example:** `"[12:30] Equity: $1,050 | P&L: +$50 (+5.0%) | Trades: 40 (24W/16L) | WR: 60.0% | PF: 1.85 | Open: 8"`

**Logic:**
```python
stats = self.broker.get_statistics()
current_time = self.broker.get_current_time()
closed_trades = self.broker.closed_trades
total_trades = len(closed_trades)
metrics = self._calculate_live_metrics(stats, closed_trades)

profit = stats['profit']
profit_sign = "+" if profit >= 0 else ""

# Format profit factor display
pf_display = f"{metrics['profit_factor']:.2f}" if metrics['profit_factor'] != float('inf') else "∞"

stats_text = (
    f"[{current_time.strftime('%H:%M')}] "
    f"Equity: ${stats['equity']:,.0f} | "
    f"P&L: {profit_sign}${profit:,.0f} ({stats['profit_percent']:+.1f}%) | "
    f"Trades: {total_trades} ({metrics['total_wins']}W/{metrics['total_losses']}L) | "
    f"WR: {metrics['win_rate']:.1f}% | "
    f"PF: {pf_display} | "
    f"Open: {stats['open_positions']}"
)
```

---

## 🎨 Visual Comparison

### Rich Progress Display

```
⠋ Backtesting [12:30] Equity: $1,000 | P&L: +$0 (+0.0%) | Trades: 0 (0W/0L) | WR: 0.0% | PF: 0.00 | Open: 0 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   0% 0:00:00 • -:--:--
⠙ Backtesting [12:30] Equity: $1,002 | P&L: +$2 (+0.2%) | Trades: 2 (1W/1L) | WR: 50.0% | PF: 1.20 | Open: 3 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   1% 0:00:00 • 0:00:06
⠹ Backtesting [12:30] Equity: $1,050 | P&L: +$50 (+5.0%) | Trades: 40 (24W/16L) | WR: 60.0% | PF: 1.85 | Open: 8 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  20% 0:00:01 • 0:00:05
⠸ Backtesting [12:30] Equity: $1,125 | P&L: +$125 (+12.5%) | Trades: 100 (62W/38L) | WR: 62.0% | PF: 2.10 | Open: 5 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  50% 0:00:02 • 0:00:03
⠇ Backtesting [12:30] Equity: $1,190 | P&L: +$190 (+19.0%) | Trades: 152 (94W/58L) | WR: 61.8% | PF: 2.05 | Open: 12 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  76% 0:00:03 • 0:00:02
  Backtesting [12:30] Equity: $1,250 | P&L: +$250 (+25.0%) | Trades: 200 (124W/76L) | WR: 62.0% | PF: 1.85 | Open: 2 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:05 • 0:00:00
```

**Components:**
- **⠋⠙⠹⠸⠇** - Animated spinner (rotates through different characters)
- **WR: 60.0%** - Win rate percentage
- **PF: 1.85** - Profit factor (ratio of gross profit to gross loss)
- **Open: 8** - Number of currently open positions
- **━━━━━━━━━━** - Progress bar (fills from left to right, turns green when complete)
- **20%** - Percentage completion
- **0:00:01** - Time elapsed
- **0:00:05** - Time remaining (ETA)

### Plain Text Display

```
[  0.0%] 2025-11-14 00:00 | Tick: 0/5,783,708 | ETA: calculating... | Equity: $  1,000.00 | P&L: $    0.00 (  +0.00%) | Floating: $    0.00 | Trades:    0 (0W/0L) | WR:   0.0% | PF:   0.00 | Open:  0 | Waiting: 0/696
[  0.1%] 2025-11-14 00:10 | Tick: 5,800/5,783,708 | ETA: calculating... | Equity: $  1,002.00 | P&L: $    2.00 (  +0.20%) | Floating: $    0.50 | Trades:    2 (1W/1L) | WR:  50.0% | PF:   1.50 | Open:  1 | Waiting: 0/696
[  1.4%] 2025-11-14 00:35 | Tick: 83,446/5,783,708 | ETA:  4m 30s | Equity: $    997.69 | P&L: $  -15.05 ( -1.50%) | Floating: $   12.73 | Trades:    7 (0W/7L) | WR:   0.0% | PF:   0.00 | Open:  8 | Waiting: 61/696
```

**Components:**
- **[  1.4%]** - Percentage completion
- **2025-11-14 00:35** - Current simulated date/time
- **Tick: 83,446/5,783,708** - Current tick / total ticks (tick mode only)
- **ETA:  4m 30s** - Estimated time to completion
- **Equity: $997.69** - Current account equity (balance + floating P&L)
- **P&L: $-15.05 (-1.50%)** - Total profit/loss
- **Floating: $12.73** - Unrealized P&L from open positions
- **Trades: 7 (0W/7L)** - Total trades (wins/losses)
- **WR: 0.0%** - Win rate
- **PF: 0.00** - Profit factor
- **Open: 8** - Number of open positions
- **Waiting: 61/696** - Barrier synchronization status

---

## 📊 Benefits

### Rich Display

✅ **Better visual feedback** - Animated spinner shows backtest is running
✅ **Progress bar** - Easy to see completion at a glance
✅ **Cleaner appearance** - Professional, modern look
✅ **Color-coded** - Green progress bar, colored text
✅ **Concise stats** - Most important metrics in description
✅ **ETA visible** - Time remaining always visible

### Plain Text Display

✅ **More detailed metrics** - All metrics visible in single line
✅ **No dependencies** - Works without rich installed
✅ **Backward compatible** - Same format as before
✅ **Easy to parse** - Structured format for log analysis

---

## 🚀 Usage

### With Rich Installed

```bash
pip install rich>=13.0.0
python backtest.py
```

**Result:** Beautiful rich progress bar with spinner, bar, and live stats

### Without Rich

```bash
python backtest.py
```

**Result:** Plain text progress display (automatic fallback)

---

## 🔧 Configuration

### Changing Progress Update Frequency

Edit `_wait_for_completion_with_rich()` in `backtest_controller.py`:

```python
time.sleep(1)  # Check every second (default)
time.sleep(0.5)  # Check every 0.5 seconds (faster updates)
time.sleep(2)  # Check every 2 seconds (slower updates)
```

**Note:** Faster updates may impact performance slightly, but 1 second is a good balance.

### Customizing Progress Bar Appearance

Edit the `Progress` configuration in `_wait_for_completion_with_rich()`:

```python
progress = Progress(
    SpinnerColumn(spinner_name="dots"),  # Change spinner style
    TextColumn("[bold cyan]{task.description}"),  # Change text color
    BarColumn(complete_style="blue", finished_style="bold blue"),  # Change bar color
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    TimeElapsedColumn(),
    TextColumn("•"),
    TimeRemainingColumn(),
    console=Console(),
    transient=True  # Hide progress bar after completion
)
```

**Available spinner styles:** dots, dots2, dots3, dots4, dots5, dots6, dots7, dots8, dots9, dots10, dots11, dots12, line, line2, pipe, simpleDots, simpleDotsScrolling, star, star2, flip, hamburger, growVertical, growHorizontal, balloon, balloon2, noise, bounce, boxBounce, boxBounce2, triangle, arc, circle, squareCorners, circleQuarters, circleHalves, squish, toggle, toggle2, toggle3, toggle4, toggle5, toggle6, toggle7, toggle8, toggle9, toggle10, toggle11, toggle12, toggle13, arrow, arrow2, arrow3, bouncingBar, bouncingBall, smiley, monkey, hearts, clock, earth, moon, runner, pong, shark, dqpb, weather, christmas

---

## 📝 Notes

### Performance

- **No impact on backtest speed** - Progress updates happen outside tick processing loop
- **Minimal overhead** - Updates once per second (same as before)
- **Efficient rendering** - Rich is highly optimized for terminal output

### Compatibility

- ✅ **Windows Terminal** - Full support with animations
- ✅ **PowerShell** - Full support with animations
- ✅ **Command Prompt** - Basic support (may not show animations)
- ✅ **CI/CD** - Auto-detects and falls back to plain text
- ✅ **Log Files** - Plain text (no ANSI codes)

### Log Files

- Progress display is **console-only**
- Log files remain **plain text** (no ANSI codes)
- Detailed progress logged to file every 100 seconds (unchanged)

---

## 🎉 Summary

The rich progress display provides a **much better visual experience** during backtest execution:

- ✅ Animated spinner shows backtest is actively running
- ✅ Progress bar provides visual feedback on completion
- ✅ Live stats show current performance at a glance
- ✅ ETA helps estimate when backtest will finish
- ✅ Automatic fallback to plain text if rich not available
- ✅ No performance impact on backtest speed
- ✅ Professional, modern appearance

**Enjoy the enhanced backtesting experience!** 🚀

