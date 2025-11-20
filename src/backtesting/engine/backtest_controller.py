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
        """
        self.logger.info("Waiting for worker threads to complete...")

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
                # Reset progress overwrite tracking before moving to a new line
                self._last_progress_len = 0
                print()  # Move to next line after progress updates
                self.logger.info("All worker threads completed")
                break

            # Check for early termination due to stop loss threshold
            # Use EQUITY (balance + floating P/L) instead of just balance
            if self.stop_loss_threshold > 0 and not self.stop_loss_triggered:
                current_equity = self.broker.get_account_equity()
                if current_equity <= self.stop_loss_balance_threshold:
                    self.stop_loss_triggered = True
                    # Reset progress overwrite tracking before moving to a new line
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

            # Console progress is now handled by broker on every tick
            # (disabled to avoid conflicting with tick-by-tick console output)
            # self._print_progress_to_console()

            # Log detailed progress to file less frequently
            if step % 100 == 0:  # Log to file every 100 checks (100 seconds)
                self._log_progress()
                self.logger.info(f"Active threads: {len(active_threads)}/{len(self.symbols)}")

            step += 1
            time.sleep(1)  # Check every second

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
                f"[{progress_pct:5.1f}%] {current_time.strftime('%Y-%m-%d %H:%M')}{tick_info} | "
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
            'equity_curve': self.equity_curve,
            'trade_log': closed_trades,  # Use actual closed trades from broker
        }

    def stop(self):
        """Stop the backtest."""
        self.running = False
        self.time_controller.stop()
        self.trading_controller.stop()

