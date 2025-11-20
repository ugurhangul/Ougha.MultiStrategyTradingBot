"""
Backtest Controller.

Wraps TradingController to work with SimulatedBroker and TimeController.
Maintains the same concurrent architecture as live trading.
"""
from typing import List, Dict, Optional
from datetime import datetime, timezone
import threading
import sys

from src.core.trading_controller import TradingController
from src.backtesting.engine.simulated_broker import SimulatedBroker
from src.backtesting.engine.time_controller import TimeController, TimeMode
from src.backtesting.engine.mt5_monkey_patch import apply_mt5_patch, restore_mt5_functions
from src.execution.order_manager import OrderManager
from src.risk.risk_manager import RiskManager
from src.execution.trade_manager import TradeManager
from src.indicators.technical_indicators import TechnicalIndicators
from src.utils.logger import get_logger
from src.utils.logging import set_backtest_mode, set_live_mode

# Rich progress display (optional, with fallback to plain text)
try:
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, TimeElapsedColumn
    from rich.console import Console, Group
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class BacktestController:
    """
    Backtest controller that simulates the TradingController's concurrent architecture.
    
    Key features:
    - Uses SimulatedBroker instead of MT5Connector
    - Synchronizes time across all symbol threads using TimeController
    - Maintains same threading model as live trading
    - Reuses existing strategies without modification
    """
    
    def __init__(self,
                 simulated_broker: SimulatedBroker,
                 time_controller: TimeController,
                 order_manager: OrderManager,
                 risk_manager: RiskManager,
                 trade_manager: TradeManager,
                 indicators: TechnicalIndicators,
                 stop_loss_threshold: float = 0.0):
        """
        Initialize backtest controller.

        Args:
            simulated_broker: Simulated broker instance
            time_controller: Time controller instance
            order_manager: Order manager instance
            risk_manager: Risk manager instance
            trade_manager: Trade manager instance
            indicators: Technical indicators instance
            stop_loss_threshold: Stop backtest if balance falls below this % of initial (0 = disabled)
        """
        self.logger = get_logger()
        self.broker = simulated_broker
        self.time_controller = time_controller

        # Create TradingController with simulated broker and time controller
        self.trading_controller = TradingController(
            connector=simulated_broker,  # Pass SimulatedBroker as connector
            order_manager=order_manager,
            risk_manager=risk_manager,
            trade_manager=trade_manager,
            indicators=indicators,
            time_controller=time_controller  # Pass TimeController for backtest synchronization
        )

        # Backtest state
        self.running = False
        self.symbols: List[str] = []

        # Backtest time range (set during run())
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

        # Results tracking
        self.equity_curve: List[Dict] = []

        # Early termination settings
        self.stop_loss_threshold = stop_loss_threshold
        self.stop_loss_triggered = False
        self.stop_loss_balance_threshold = 0.0  # Will be set when backtest starts
        self.trade_log: List[Dict] = []

        # Track length of last printed progress line to overwrite cleanly
        self._last_progress_len: int = 0

        # ETA CALCULATION: Moving average window for candle mode
        from collections import deque
        import time
        self.eta_window_size = 100  # Track last 100 progress updates for moving average
        self.eta_progress_history = deque(maxlen=self.eta_window_size)  # (progress_pct, wall_clock_time) pairs
        self.eta_warmup_updates = 10  # Wait for 10 updates before showing ETA
        self.backtest_wall_start_time = None  # Will be set when backtest starts

        self.logger.info("BacktestController initialized")
    
    def initialize(self, symbols: List[str]) -> bool:
        """
        Initialize backtest with symbols.
        
        Args:
            symbols: List of symbols to backtest
            
        Returns:
            True if initialization successful
        """
        self.symbols = symbols
        
        # Initialize TradingController (this creates strategies)
        success = self.trading_controller.initialize(symbols)
        
        if success:
            self.logger.info(f"BacktestController initialized with {len(symbols)} symbols")
        
        return success
    
    def run(self, backtest_start_time: Optional[datetime] = None):
        """
        Run the backtest using the REAL TradingController threading architecture.

        This method starts TradingController.start() which creates:
        - One worker thread per symbol (calling strategy.on_tick() in a loop)
        - One position monitor thread (managing positions)
        - All threads synchronized via TimeController barrier

        Args:
            backtest_start_time: Optional explicit backtest start time for log directory naming.
                                If None, uses the earliest time from loaded data.
                                This is useful when data is loaded with extra historical context
                                (e.g., 1 day before actual backtest start for reference candle lookback).
        """
        self.logger.info("=" * 60)
        self.logger.info("Starting THREADED Backtest")
        self.logger.info(f"Symbols: {', '.join(self.symbols)}")
        self.logger.info(f"Architecture: Real TradingController with {len(self.symbols)} worker threads + position monitor")
        self.logger.info("=" * 60)

        # Apply MT5 monkey patch to redirect mt5.order_send() to SimulatedBroker
        apply_mt5_patch(self.broker)

        # Get backtest start time for log directory naming
        # Use explicit start time if provided, otherwise use earliest time from loaded data
        if backtest_start_time is None:
            backtest_start_time = self.broker.get_start_time()

        # Store start and end times for progress calculation
        self.start_time = backtest_start_time
        self.end_time = self.broker.get_end_time()

        # Update logging time provider to use a NON-BLOCKING simulated time getter from broker
        # (backtest mode was already set in backtest.py, this updates the time getter)
        # Using the non-blocking getter prevents logging from contending on broker.time_lock
        set_backtest_mode(self.broker.get_current_time_nonblocking, backtest_start_time)

        self.logger.info("Logging time provider updated to use non-blocking simulated time from broker")
        self.logger.info(f"Backtest time range: {self.start_time} to {self.end_time}")

        # Set stop loss threshold
        if self.stop_loss_threshold > 0:
            self.stop_loss_balance_threshold = self.broker.initial_balance * (self.stop_loss_threshold / 100.0)
            self.logger.info(f"Stop loss threshold: ${self.stop_loss_balance_threshold:,.2f} ({self.stop_loss_threshold}% of initial balance)")
        else:
            self.logger.info("Stop loss threshold: DISABLED (will run full backtest period)")

        try:
            self.running = True

            # Start TimeController
            self.time_controller.start()

            # Start TradingController (this creates all worker threads)
            self.logger.info("Starting TradingController with real threading architecture...")
            self.trading_controller.start()

            # Wait for all threads to complete
            self._wait_for_completion()

        finally:
            # Stop TimeController
            self.time_controller.stop()

            # Stop TradingController
            self.trading_controller.stop()

            # Always restore MT5 functions after backtest
            restore_mt5_functions()

            # Note: We don't restore live mode here because backtest.py needs to
            # log results to the backtest directory. backtest.py will restore live mode
            # at the very end after displaying all results.

        self.logger.info("=" * 60)
        self.logger.info("Backtest Completed")
        self.logger.info("=" * 60)
    
    def _wait_for_completion(self):
        """
        Wait for all worker threads to complete.

        Monitors thread status and logs progress periodically.
        Uses Rich progress bar if available, otherwise falls back to plain text.
        """
        self.logger.info("Waiting for worker threads to complete...")

        import time
        step = 0

        # Use Rich progress bar if available
        if RICH_AVAILABLE:
            self._wait_for_completion_with_rich()
        else:
            self._wait_for_completion_plain()

    def _wait_for_completion_with_rich(self):
        """Wait for completion with Rich progress bar display and live positions table."""
        import time
        step = 0

        # Create Rich progress bar
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(complete_style="green", finished_style="bold green"),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
        )

        # Determine total for progress bar
        if hasattr(self.broker, 'use_tick_data') and self.broker.use_tick_data:
            # Tick mode: use total ticks
            if hasattr(self.broker, 'global_tick_timeline'):
                total = len(self.broker.global_tick_timeline)
            else:
                total = 100  # Fallback to percentage
        else:
            # Candle mode: use time-based progress (0-100)
            total = 100

        task = progress.add_task("Backtesting", total=total)
        console = Console()

        # Use Live display to show both progress and positions table
        with Live(console=console, refresh_per_second=1, transient=False) as live:
            while self.running:
                # Check if all symbol threads are still alive
                with self.trading_controller.lock:
                    active_threads = [
                        symbol for symbol, thread in self.trading_controller.threads.items()
                        if thread.is_alive()
                    ]

                if not active_threads:
                    progress.update(task, completed=total)
                    self.logger.info("All worker threads completed")
                    break

                # Check for early termination due to stop loss threshold
                if self.stop_loss_threshold > 0 and not self.stop_loss_triggered:
                    current_equity = self.broker.get_account_equity()
                    if current_equity <= self.stop_loss_balance_threshold:
                        self.stop_loss_triggered = True
                        progress.stop()
                        print()  # Move to next line
                        self.logger.warning("")
                        current_balance = self.broker.get_account_balance()
                        self.logger.warning("=" * 80)
                        self.logger.warning("⚠️  STOP LOSS THRESHOLD REACHED - TERMINATING BACKTEST")
                        self.logger.warning("=" * 80)
                        self.logger.warning(f"  Initial Balance:    ${self.broker.initial_balance:,.2f}")
                        self.logger.warning(f"  Current Balance:    ${current_balance:,.2f}")
                        self.logger.warning(f"  Current Equity:     ${current_equity:,.2f}")
                        self.logger.warning(f"  Threshold:          ${self.stop_loss_balance_threshold:,.2f} ({self.stop_loss_threshold}%)")
                        self.logger.warning(f"  Loss:               ${current_equity - self.broker.initial_balance:,.2f} ({((current_equity - self.broker.initial_balance) / self.broker.initial_balance * 100):.2f}%)")
                        self.logger.warning("=" * 80)
                        self.logger.warning("")

                        # Stop the backtest
                        self.running = False
                        self.time_controller.stop()
                        self.trading_controller.stop()
                        break

                # Update progress bar
                current_progress = self._get_current_progress()
                if current_progress is not None:
                    if hasattr(self.broker, 'use_tick_data') and self.broker.use_tick_data:
                        # Tick mode: update with tick count
                        progress.update(task, completed=current_progress)
                    else:
                        # Candle mode: update with percentage
                        progress.update(task, completed=current_progress)

                # Update task description with live stats
                stats_text = self._get_progress_stats_text()
                progress.update(task, description=f"Backtesting {stats_text}")

                # Create combined display with progress and positions table
                positions_table = self._create_positions_table()
                display_group = Group(
                    progress,
                    positions_table
                )
                live.update(display_group)

                # Record equity curve periodically
                if step % 10 == 0:  # Record every 10 checks (10 seconds)
                    self._record_equity_snapshot()

                # Log detailed progress to file less frequently
                if step % 100 == 0:  # Log to file every 100 checks (100 seconds)
                    self._log_progress()
                    self.logger.info(f"Active threads: {len(active_threads)}/{len(self.symbols)}")

                step += 1
                time.sleep(1)  # Check every second

    def _wait_for_completion_plain(self):
        """Wait for completion with plain text progress display (fallback)."""
        import time
        step = 0

        while self.running:
            # Check if all symbol threads are still alive
            with self.trading_controller.lock:
                active_threads = [
                    symbol for symbol, thread in self.trading_controller.threads.items()
                    if thread.is_alive()
                ]

            if not active_threads:
                # Print final newline to move past the progress line
                self._last_progress_len = 0
                print()  # Move to next line after progress updates
                self.logger.info("All worker threads completed")
                break

            # Check for early termination due to stop loss threshold
            if self.stop_loss_threshold > 0 and not self.stop_loss_triggered:
                current_equity = self.broker.get_account_equity()
                if current_equity <= self.stop_loss_balance_threshold:
                    self.stop_loss_triggered = True
                    self._last_progress_len = 0
                    print()  # Move to next line after progress updates
                    self.logger.warning("")
                    current_balance = self.broker.get_account_balance()
                    self.logger.warning("=" * 80)
                    self.logger.warning("⚠️  STOP LOSS THRESHOLD REACHED - TERMINATING BACKTEST")
                    self.logger.warning("=" * 80)
                    self.logger.warning(f"  Initial Balance:    ${self.broker.initial_balance:,.2f}")
                    self.logger.warning(f"  Current Balance:    ${current_balance:,.2f}")
                    self.logger.warning(f"  Current Equity:     ${current_equity:,.2f}")
                    self.logger.warning(f"  Threshold:          ${self.stop_loss_balance_threshold:,.2f} ({self.stop_loss_threshold}%)")
                    self.logger.warning(f"  Loss:               ${current_equity - self.broker.initial_balance:,.2f} ({((current_equity - self.broker.initial_balance) / self.broker.initial_balance * 100):.2f}%)")
                    self.logger.warning("=" * 80)
                    self.logger.warning("")

                    # Stop the backtest
                    self.running = False
                    self.time_controller.stop()
                    self.trading_controller.stop()
                    break

            # Record equity curve periodically
            if step % 10 == 0:  # Record every 10 checks (10 seconds)
                self._record_equity_snapshot()

            # Console progress (lightweight, once per second)
            self._print_progress_to_console()

            # Log detailed progress to file less frequently
            if step % 100 == 0:  # Log to file every 100 checks (100 seconds)
                self._log_progress()
                self.logger.info(f"Active threads: {len(active_threads)}/{len(self.symbols)}")

            step += 1
            time.sleep(1)  # Check every second

    def _get_current_progress(self):
        """Get current progress value for progress bar."""
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

    def _get_progress_stats_text(self):
        """Get concise stats text for progress bar description."""
        stats = self.broker.get_statistics()
        current_time = self.broker.get_current_time()

        if not current_time:
            return ""

        # Get basic metrics
        closed_trades = self.broker.closed_trades
        total_trades = len(closed_trades)

        # Calculate live metrics
        metrics = self._calculate_live_metrics(stats, closed_trades)

        # Format profit with color indicator
        profit = stats['profit']
        profit_sign = "+" if profit >= 0 else ""

        # Format profit factor display
        pf_display = f"{metrics['profit_factor']:.2f}" if metrics['profit_factor'] != float('inf') else "∞"

        # Build concise stats text with additional metrics
        stats_text = (
            f"[{current_time.strftime('%H:%M')}] "
            f"Equity: ${stats['equity']:,.0f} | "
            f"P&L: {profit_sign}${profit:,.0f} ({stats['profit_percent']:+.1f}%) | "
            f"Trades: {total_trades} ({metrics['total_wins']}W/{metrics['total_losses']}L) | "
            f"WR: {metrics['win_rate']:.1f}% | "
            f"PF: {pf_display} | "
            f"Open: {stats['open_positions']}"
        )

        return stats_text

    def _create_positions_table(self):
        """Create a rich table showing currently open positions."""
        if not RICH_AVAILABLE:
            return ""

        from datetime import datetime

        # Get open positions from broker
        positions = self.broker.get_positions()

        # Create table
        table = Table(
            title=f"📊 Open Positions ({len(positions)})",
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
            title_style="bold white",
            show_lines=False,
            padding=(0, 1)
        )

        # Add columns
        table.add_column("Ticket", style="cyan", width=8, justify="right")
        table.add_column("Symbol", style="white", width=10)
        table.add_column("Type", style="white", width=5)
        table.add_column("Entry", style="white", width=10, justify="right")
        table.add_column("Current", style="white", width=10, justify="right")
        table.add_column("P&L", style="white", width=12, justify="right")
        table.add_column("SL", style="yellow", width=10, justify="right")
        table.add_column("TP", style="green", width=10, justify="right")
        table.add_column("Time", style="white", width=10)

        # If no positions, show empty message
        if not positions:
            table.add_row("—", "—", "—", "—", "—", "—", "—", "—", "—")
            return table

        # Sort positions by open time (newest first)
        sorted_positions = sorted(positions, key=lambda p: p.open_time, reverse=True)

        # Limit to most recent 10 positions to avoid cluttering the display
        display_positions = sorted_positions

        # Get current time for duration calculation
        current_time = self.broker.get_current_time()

        # Add rows for each position
        for pos in display_positions:
            # Calculate time held
            if current_time and pos.open_time:
                time_held = current_time - pos.open_time
                hours = int(time_held.total_seconds() // 3600)
                minutes = int((time_held.total_seconds() % 3600) // 60)
                time_str = f"{hours}h{minutes}m" if hours > 0 else f"{minutes}m"
            else:
                time_str = "—"

            # Color code P&L
            profit = pos.profit
            if profit > 0:
                pnl_str = f"[green]+${profit:,.2f}[/green]"
            elif profit < 0:
                pnl_str = f"[red]${profit:,.2f}[/red]"
            else:
                pnl_str = f"${profit:,.2f}"

            # Format position type
            pos_type = "BUY" if pos.position_type.name == "BUY" else "SELL"
            type_color = "green" if pos_type == "BUY" else "red"

            # Format SL/TP
            sl_str = f"{pos.sl:.5f}" if pos.sl > 0 else "—"
            tp_str = f"{pos.tp:.5f}" if pos.tp > 0 else "—"

            table.add_row(
                f"{pos.ticket}",
                pos.symbol,
                f"[{type_color}]{pos_type}[/{type_color}]",
                f"{pos.open_price:.5f}",
                f"{pos.current_price:.5f}",
                pnl_str,
                sl_str,
                tp_str,
                time_str
            )

        return table

    def _record_equity_snapshot(self):
        """Record current equity for equity curve."""
        stats = self.broker.get_statistics()
        current_time = self.broker.get_current_time()

        snapshot = {
            'time': current_time,
            'balance': stats['balance'],
            'equity': stats['equity'],
            'profit': stats['profit'],
            'open_positions': stats['open_positions'],
        }

        self.equity_curve.append(snapshot)

    def _calculate_live_metrics(self, stats: Dict, closed_trades: List[Dict]) -> Dict:
        """
        Calculate live trading metrics during backtest.

        Args:
            stats: Current broker statistics
            closed_trades: List of closed trades

        Returns:
            Dictionary with calculated metrics
        """
        metrics = {
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'total_wins': 0,
            'total_losses': 0,
            'sharpe_ratio': 0.0,
            'max_drawdown': 0.0,
        }

        if not closed_trades:
            return metrics

        # Calculate win/loss statistics
        profits = [trade.get('profit', 0) for trade in closed_trades]
        winning_trades = [p for p in profits if p > 0]
        losing_trades = [p for p in profits if p < 0]

        metrics['total_wins'] = len(winning_trades)
        metrics['total_losses'] = len(losing_trades)
        total_trades = len(profits)

        if total_trades > 0:
            metrics['win_rate'] = (metrics['total_wins'] / total_trades) * 100

        if winning_trades:
            metrics['avg_win'] = sum(winning_trades) / len(winning_trades)

        if losing_trades:
            metrics['avg_loss'] = abs(sum(losing_trades) / len(losing_trades))

        # Calculate profit factor
        if losing_trades:
            metrics['profit_factor'] = sum(winning_trades) / abs(sum(losing_trades))
        elif winning_trades:
            metrics['profit_factor'] = float('inf')

        # Calculate Sharpe ratio from equity curve
        if len(self.equity_curve) > 1:
            import numpy as np
            equity_values = [snapshot['equity'] for snapshot in self.equity_curve]
            returns = np.diff(equity_values) / equity_values[:-1]

            if len(returns) > 0 and np.std(returns) > 0:
                metrics['sharpe_ratio'] = np.mean(returns) / np.std(returns) * np.sqrt(252)

        # Calculate maximum drawdown
        if len(self.equity_curve) > 1:
            import numpy as np
            equity_values = [snapshot['equity'] for snapshot in self.equity_curve]
            running_max = np.maximum.accumulate(equity_values)
            drawdown = (equity_values - running_max) / running_max * 100.0
            metrics['max_drawdown'] = abs(min(drawdown))

        return metrics

    def _print_progress_to_console(self):
        """
        Print concise progress update to console.

        Shows: Current date, equity, balance, total trades, win rate, profit factor
        This provides real-time feedback without the overhead of full logging.
        """
        stats = self.broker.get_statistics()
        current_time = self.broker.get_current_time()

        if current_time:
            # Get total trades count
            closed_trades = self.broker.closed_trades
            total_trades = len(closed_trades)

            # Get progress percentage
            # For tick mode: use tick index, for candle mode: use time
            progress_pct = 0
            tick_info = ""

            if hasattr(self.broker, 'use_tick_data') and self.broker.use_tick_data:
                # Tick mode: show tick progress
                if hasattr(self.broker, 'global_tick_index') and hasattr(self.broker, 'global_tick_timeline'):
                    total_ticks = len(self.broker.global_tick_timeline)
                    current_tick = self.broker.global_tick_index
                    if total_ticks > 0:
                        progress_pct = (current_tick / total_ticks * 100)
                        tick_info = f" | Tick: {current_tick:,}/{total_ticks:,}"
            else:
                # Candle mode: use time-based progress
                if self.start_time and self.end_time and current_time:
                    # Calculate progress as percentage of time elapsed
                    total_duration = (self.end_time - self.start_time).total_seconds()
                    elapsed_duration = (current_time - self.start_time).total_seconds()

                    if total_duration > 0:
                        progress_pct = (elapsed_duration / total_duration * 100)
                        # Clamp to 0-100 range
                        progress_pct = max(0, min(100, progress_pct))

            # Calculate ETA (Estimated Time to Finish) using moving average
            eta_display = ""
            if progress_pct > 0:
                import time
                current_wall_time = time.time()

                # Initialize wall start time on first call
                if self.backtest_wall_start_time is None:
                    self.backtest_wall_start_time = current_wall_time

                    # Add current progress to the moving window
                    self.eta_progress_history.append((progress_pct, current_wall_time))

                    # Calculate ETA from the moving window (skip initial warm-up period)
                    if len(self.eta_progress_history) >= self.eta_warmup_updates:
                        oldest_pct, oldest_time = self.eta_progress_history[0]
                        newest_pct, newest_time = self.eta_progress_history[-1]

                        # Calculate progress rate (percentage points per second)
                        progress_delta = newest_pct - oldest_pct
                        time_delta = newest_time - oldest_time

                        if time_delta > 0 and progress_delta > 0:
                            pct_per_second = progress_delta / time_delta
                            remaining_pct = 100.0 - progress_pct
                            eta_seconds = remaining_pct / pct_per_second if pct_per_second > 0 else 0

                            # Format ETA
                            if eta_seconds < 60:
                                eta_display = f" | ETA: {int(eta_seconds):>3}s"
                            elif eta_seconds < 3600:
                                eta_display = f" | ETA: {int(eta_seconds / 60):>2}m {int(eta_seconds % 60):>2}s"
                            else:
                                hours = int(eta_seconds / 3600)
                                minutes = int((eta_seconds % 3600) / 60)
                                eta_display = f" | ETA: {hours}h {minutes}m"
                    else:
                        eta_display = " | ETA: calculating..."

            # Calculate live metrics
            metrics = self._calculate_live_metrics(stats, closed_trades)

            # Check for positions without SL (diagnostic)
            # Note: TP can be 0.0 legitimately (e.g., after trailing stop removes it)
            positions_without_sl = 0
            with self.broker.position_lock:
                for pos in self.broker.positions.values():
                    if pos.sl == 0.0:  # Only check SL, not TP
                        positions_without_sl += 1

            # Get barrier synchronization status (how many participants have arrived at the barrier)
            # Note: TimeController no longer tracks a symbols_ready set; it uses an arrivals counter.
            # We read the current arrivals under the barrier_condition lock for a consistent snapshot.
            symbols_waiting = 0
            if hasattr(self.trading_controller, 'time_controller'):
                with self.trading_controller.time_controller.barrier_condition:
                    symbols_waiting = self.trading_controller.time_controller.arrivals
                    total_participants = self.trading_controller.time_controller.total_participants

            # Print concise progress (overwrites previous line with \r)
            warning_flag = " ⚠️ NO SL!" if positions_without_sl > 0 else ""

            # Format profit factor display
            pf_display = f"{metrics['profit_factor']:.2f}" if metrics['profit_factor'] != float('inf') else "∞"

            # Show barrier status (how many symbols are waiting vs total)
            barrier_status = f"Waiting: {symbols_waiting}/{total_participants}" if symbols_waiting > 0 else ""

            # Build single-line status message
            message = (
                f"[{progress_pct:5.1f}%] {current_time.strftime('%Y-%m-%d %H:%M')}{tick_info}{eta_display} | "
                f"Equity: ${stats['equity']:>10,.2f} | "
                f"P&L: ${stats['profit']:>8,.2f} ({stats['profit_percent']:>+6.2f}%) | "
                f"Floating: ${stats['floating_pnl']:>8,.2f} | "
                f"Trades: {total_trades:>4} ({metrics['total_wins']}W/{metrics['total_losses']}L) | "
                f"WR: {metrics['win_rate']:>5.1f}% | "
                f"PF: {pf_display:>6} | "
                f"Open: {stats['open_positions']:>2}{warning_flag} | "
                f"{barrier_status}"
            )

            # Overwrite the previous line robustly without relying on ANSI support
            # 1) Carriage return to line start
            # 2) Write message
            # 3) Pad with spaces if new message is shorter than the previous one
            pad = max(0, self._last_progress_len - len(message))
            sys.stdout.write("\r" + message + (" " * pad))
            sys.stdout.flush()
            self._last_progress_len = len(message)

    def _log_progress(self):
        """Log detailed backtest progress to file with comprehensive metrics."""
        stats = self.broker.get_statistics()
        current_time = self.broker.get_current_time()
        closed_trades = self.broker.closed_trades

        # Get progress for first symbol (representative)
        if self.symbols:
            current_idx, total_bars = self.broker.get_progress(self.symbols[0])
            progress_pct = (current_idx / total_bars * 100) if total_bars > 0 else 0

            # Calculate live metrics
            metrics = self._calculate_live_metrics(stats, closed_trades)

            # Format profit factor
            pf_display = f"{metrics['profit_factor']:.2f}" if metrics['profit_factor'] != float('inf') else "∞"

            self.logger.info("=" * 100)
            self.logger.info(f"[BACKTEST STATUS] Progress: {progress_pct:.1f}% | Time: {current_time}")
            self.logger.info("-" * 100)
            self.logger.info(
                f"  Account Metrics:"
            )
            self.logger.info(
                f"    Balance:        ${stats['balance']:>12,.2f}  |  "
                f"Equity:         ${stats['equity']:>12,.2f}"
            )
            self.logger.info(
                f"    Realized P&L:   ${stats['profit']:>12,.2f}  ({stats['profit_percent']:>+6.2f}%)  |  "
                f"Floating P&L:   ${stats['floating_pnl']:>12,.2f}"
            )
            self.logger.info(
                f"    Open Positions: {stats['open_positions']:>3}  |  "
                f"Total Trades:   {len(closed_trades):>4}"
            )
            self.logger.info("-" * 100)
            self.logger.info(
                f"  Performance Metrics:"
            )
            self.logger.info(
                f"    Win Rate:       {metrics['win_rate']:>6.2f}%  |  "
                f"Trades:         {metrics['total_wins']}W / {metrics['total_losses']}L"
            )
            self.logger.info(
                f"    Profit Factor:  {pf_display:>6}  |  "
                f"Avg Win/Loss:   ${metrics['avg_win']:>8,.2f} / ${metrics['avg_loss']:>8,.2f}"
            )
            self.logger.info(
                f"    Sharpe Ratio:   {metrics['sharpe_ratio']:>6.2f}  |  "
                f"Max Drawdown:   {metrics['max_drawdown']:>6.2f}%"
            )
            self.logger.info("=" * 100)

    def get_results(self) -> Dict:
        """
        Get backtest results.

        Returns:
            Dictionary with backtest results
        """
        stats = self.broker.get_statistics()

        # Get closed trades from broker
        closed_trades = self.broker.get_closed_trades()

        return {
            'final_balance': stats['balance'],
            'final_equity': stats['equity'],
            'total_profit': stats['profit'],
            'profit_percent': stats['profit_percent'],
            'open_positions': stats['open_positions'],
            'equity_curve': self.equity_curve,
            'trade_log': closed_trades,  # Use actual closed trades from broker
        }

    def stop(self):
        """Stop the backtest."""
        self.running = False
        self.time_controller.stop()
        self.trading_controller.stop()

