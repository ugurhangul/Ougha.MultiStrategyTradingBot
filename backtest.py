"""
Multi-Strategy Trading Bot - Backtesting Engine

Production-ready backtesting using the custom backtest engine.
This engine simulates the exact live trading architecture for realistic results.

Usage:
    python backtest.py

Configuration:
    Edit the CONFIGURATION section below to customize:
    - Date range (START_DATE, END_DATE)
    - Initial balance (INITIAL_BALANCE)
    - Symbols (SYMBOLS or load from active.set)
    - Timeframe (TIMEFRAME)
    - Time mode (TIME_MODE)

Features:
    ✓ Runs the same strategies as live trading (no code duplication)
    ✓ Simulates concurrent multi-symbol, multi-strategy execution
    ✓ Accurately models position limits and risk management
    ✓ Provides realistic results that closely match live trading
    ✓ Saves logs to logs/backtest/<timestamp>/ directory
    ✓ Displays comprehensive performance metrics

Performance Optimization:
    ✓ Console logging is DISABLED by default for maximum speed
    ✓ All logs are still saved to files for later analysis
    ✓ Key progress messages are shown on console
    ✓ To enable full console logging (slower), set ENABLE_CONSOLE_LOGS = True in main()

    Performance impact:
    - Console logging OFF: ~10-50x faster (recommended for production backtests)
    - Console logging ON: Useful for debugging, but significantly slower

    Tick Mode Optimizations (v2.0):
    ✓ Progress updates: Every 1000 ticks (0.1%) instead of every tick
    ✓ Statistics caching: Only recalculated when trades change
    ✓ P&L updates: Only for current symbol's positions
    ✓ SL/TP logging: Complete logging preserved for trade history analysis
    ✓ Expected speedup: 50-100x faster than v1.0

    Logs location: logs/backtest/YYYY-MM-DD/

Documentation:
    See docs/CUSTOM_BACKTEST_ENGINE.md for detailed information
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional
import sys
from pathlib import Path
import psutil
import os

project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.backtesting.engine import (
    SimulatedBroker,
    TimeController,
    TimeMode,
    TimeGranularity,
    BacktestController,
    BacktestDataLoader,
    ResultsAnalyzer
)
from src.execution.order_manager import OrderManager
from src.risk.risk_manager import RiskManager
from src.execution.trade_manager import TradeManager
from src.indicators.technical_indicators import TechnicalIndicators
from src.config import config
from src.utils.logger import get_logger, init_logger
from src.core.mt5_connector import MT5Connector

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None

START_DATE = datetime(2025, 1, 1, tzinfo=timezone.utc)
END_DATE = datetime(2025, 11, 21, tzinfo=timezone.utc)

STREAM_TICKS_FROM_DISK = True

PARALLEL_TICK_DAYS = 1

INITIAL_BALANCE = 1000.0

STOP_LOSS_THRESHOLD = 1.0

SYMBOLS: Optional[List[str]] = ['EURUSD', 'GBPUSD', 'USDJPY', 'GBPJPY']

TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4"]

TIME_MODE = TimeMode.MAX_SPEED

USE_TICK_DATA = True
TICK_TYPE = "INFO"

USE_SEQUENTIAL_MODE = True

HISTORICAL_BUFFER_DAYS = 10

USE_CACHE = True
CACHE_DIR = "data/cache"
CACHE_TTL_DAYS = 7
FORCE_REFRESH = False

USE_INCREMENTAL_LOADING = True

DEBUG_DATA_LOADING = True

ENABLE_SLIPPAGE = False
SLIPPAGE_POINTS = 0.5

LEVERAGE = 2000


def get_memory_usage() -> float:
    """Get current memory usage in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024
def log_memory(logger, label: str):
    """Log current memory usage."""
    mem_mb = get_memory_usage()
    logger.info(f"  💾 Memory usage ({label}): {mem_mb:.1f} MB")
def load_symbols(logger) -> List[str]:
    """
    Load symbols from configuration or active.set file.
    
    Returns:
        List of symbol names to backtest
    """
    if SYMBOLS is not None and len(SYMBOLS) > 0:
        logger.info(f"Using {len(SYMBOLS)} symbols from configuration")
        return SYMBOLS

    logger.info("Loading symbols from active.set file...")

    connector = MT5Connector(config.mt5)
    if not connector.connect():
        logger.error("Failed to connect to MT5 for symbol loading")
        logger.info("Falling back to default symbols: EURUSD, GBPUSD")
        return ["EURUSD", "GBPUSD"]

    try:
        if config.load_symbols_from_active_set(connector=connector, logger=logger):
            symbols = config.symbols
            logger.info(f"Loaded {len(symbols)} symbols from active.set (after prioritization)")
            return symbols
        else:
            logger.warning("Failed to load from active.set, loading from Market Watch")
            if config.load_symbols_from_market_watch(connector):
                symbols = config.symbols
                logger.info(f"Loaded {len(symbols)} symbols from Market Watch")
                return symbols
            else:
                logger.error("Failed to load symbols from Market Watch")
                logger.info("Falling back to default symbols: EURUSD, GBPUSD")
                return ["EURUSD", "GBPUSD"]
    finally:
        connector.disconnect()
def print_configuration_panel(config_data: dict, logger=None):
    """
    Print backtest configuration in a formatted panel (rich if available, plain text otherwise).

    Args:
        config_data: Dictionary with configuration values
        logger: Optional logger instance to also log to file
    """
    if RICH_AVAILABLE:
        config_lines = []
        config_lines.append(f"[cyan]Date Range:[/cyan]       {config_data['date_range']}")
        config_lines.append(f"[cyan]Duration:[/cyan]         {config_data['duration']}")
        config_lines.append(f"[cyan]Initial Balance:[/cyan]  ${config_data['initial_balance']:,.2f}")
        config_lines.append(f"[cyan]Stop Threshold:[/cyan]   {config_data['stop_threshold']}")
        config_lines.append(f"[cyan]Timeframes:[/cyan]       {config_data['timeframes']}")
        config_lines.append(f"[cyan]Time Mode:[/cyan]        {config_data['time_mode']}")
        config_lines.append(f"[cyan]Tick Data:[/cyan]        {config_data['tick_data']}")

        if config_data.get('tick_warning'):
            config_lines.append(f"[yellow]⚠ WARNING:[/yellow]        {config_data['tick_warning']}")
            config_lines.append(f"                    {config_data['tick_warning_detail']}")

        config_lines.append(f"[cyan]Spreads:[/cyan]          {config_data['spreads']}")
        config_lines.append(f"[cyan]Slippage:[/cyan]         {config_data['slippage']}")
        config_lines.append(f"[cyan]Leverage:[/cyan]         {config_data['leverage']}")

        config_text = "\n".join(config_lines)
        panel = Panel(config_text, title="⚙️  Backtest Configuration", border_style="blue", padding=(1, 2))
        console.print(panel)
        console.print()
    else:
        print("BACKTEST CONFIGURATION:")
        print(f"  Date Range:       {config_data['date_range']}")
        print(f"  Duration:         {config_data['duration']}")
        print(f"  Initial Balance:  ${config_data['initial_balance']:,.2f}")
        print(f"  Stop Threshold:   {config_data['stop_threshold']}")
        print(f"  Timeframes:       {config_data['timeframes']}")
        print(f"  Time Mode:        {config_data['time_mode']}")
        print(f"  Tick Data:        {config_data['tick_data']}")

        if config_data.get('tick_warning'):
            print(f"  ⚠ WARNING:        {config_data['tick_warning']}")
            print(f"                    {config_data['tick_warning_detail']}")

        print(f"  Spreads:          {config_data['spreads']}")
        print(f"  Slippage:         {config_data['slippage']}")
        print(f"  Leverage:         {config_data['leverage']}")
        print()

    if logger:
        logger.info("BACKTEST CONFIGURATION:")
        logger.info(f"  Date Range:       {config_data['date_range']}")
        logger.info(f"  Duration:         {config_data['duration']}")
        logger.info(f"  Initial Balance:  ${config_data['initial_balance']:,.2f}")
        logger.info(f"  Stop Threshold:   {config_data['stop_threshold']}")
        logger.info(f"  Timeframes:       {config_data['timeframes']}")
        logger.info(f"  Time Mode:        {config_data['time_mode']}")
        logger.info(f"  Tick Data:        {config_data['tick_data']}")
        if config_data.get('tick_warning'):
            logger.info(f"  ⚠ WARNING:        {config_data['tick_warning']}")
            logger.info(f"                    {config_data['tick_warning_detail']}")
        logger.info(f"  Spreads:          {config_data['spreads']}")
        logger.info(f"  Slippage:         {config_data['slippage']}")
        logger.info(f"  Leverage:         {config_data['leverage']}")
        logger.info("")
def print_results_table(metrics: dict, initial_balance: float, logger=None):
    """
    Print backtest results in a formatted table (rich if available, plain text otherwise).

    Args:
        metrics: Dictionary with backtest metrics
        initial_balance: Initial account balance
        logger: Optional logger instance to also log to file
    """
    if RICH_AVAILABLE:
        table = Table(title="📊 Backtest Results", show_header=True, header_style="bold cyan", border_style="green" if metrics.get('total_profit', 0) > 0 else "red")
        table.add_column("Metric", style="cyan", width=25)
        table.add_column("Value", style="white", width=20, justify="right")

        total_profit = metrics.get('total_profit', 0)
        profit_color = "green" if total_profit > 0 else "red"

        table.add_row("", "")
        table.add_row("[bold]ACCOUNT PERFORMANCE[/bold]", "")
        table.add_row("Initial Balance", f"${initial_balance:,.2f}")
        table.add_row("Final Balance", f"${metrics.get('final_balance', 0):,.2f}")
        table.add_row("Final Equity", f"${metrics.get('final_equity', 0):,.2f}")
        table.add_row("Total Profit", f"[{profit_color}]${total_profit:,.2f}[/{profit_color}]")
        table.add_row("Total Return", f"[{profit_color}]{metrics.get('total_return', 0):.2f}%[/{profit_color}]")

        table.add_row("", "")
        table.add_row("[bold]RISK METRICS[/bold]", "")
        max_dd = metrics.get('max_drawdown', 0)
        dd_color = "red" if max_dd < -10 else "yellow" if max_dd < -5 else "green"
        table.add_row("Max Drawdown", f"[{dd_color}]{max_dd:.2f}%[/{dd_color}]")

        sharpe = metrics.get('sharpe_ratio', 0)
        sharpe_color = "green" if sharpe > 1.5 else "yellow" if sharpe > 1.0 else "red"
        table.add_row("Sharpe Ratio", f"[{sharpe_color}]{sharpe:.2f}[/{sharpe_color}]")

        pf = metrics.get('profit_factor', 0)
        pf_display = f"{pf:.2f}" if pf != float('inf') else "∞"
        pf_color = "green" if pf > 1.5 else "yellow" if pf > 1.0 else "red"
        table.add_row("Profit Factor", f"[{pf_color}]{pf_display}[/{pf_color}]")

        table.add_row("", "")
        table.add_row("[bold]TRADE STATISTICS[/bold]", "")
        table.add_row("Total Trades", f"{metrics.get('total_trades', 0)}")

        win_rate = metrics.get('win_rate', 0)
        wr_color = "green" if win_rate > 60 else "yellow" if win_rate > 50 else "red"
        table.add_row("Winning Trades", f"[{wr_color}]{metrics.get('winning_trades', 0)} ({win_rate:.1f}%)[/{wr_color}]")
        table.add_row("Losing Trades", f"{metrics.get('losing_trades', 0)} ({100 - win_rate:.1f}%)")

        open_positions = metrics.get('open_positions', 0)
        open_color = "yellow" if open_positions > 0 else "green"
        table.add_row("Open Positions", f"[{open_color}]{open_positions}[/{open_color}]")

        if metrics.get('total_trades', 0) > 0:
            table.add_row("", "")
            table.add_row("[bold]TRADE DETAILS[/bold]", "")
            avg_win = metrics.get('avg_win', 0)
            table.add_row("Avg Win", f"[green]${avg_win:,.2f}[/green]")
            avg_loss = metrics.get('avg_loss', 0)
            table.add_row("Avg Loss", f"[red]${avg_loss:,.2f}[/red]")
            table.add_row("Largest Win", f"[green]${metrics.get('largest_win', 0):,.2f}[/green]")
            table.add_row("Largest Loss", f"[red]${metrics.get('largest_loss', 0):,.2f}[/red]")
            table.add_row("Max Consecutive Wins", f"{metrics.get('max_consecutive_wins', 0)}")
            table.add_row("Max Consecutive Losses", f"{metrics.get('max_consecutive_losses', 0)}")

        console.print()
        console.print(table)
        console.print()
    else:
        print()
        print("=" * 80)
        print("BACKTEST RESULTS")
        print("=" * 80)
        print()

        print("ACCOUNT PERFORMANCE:")
        print(f"  Initial Balance:  ${initial_balance:>12,.2f}")
        print(f"  Final Balance:    ${metrics.get('final_balance', 0):>12,.2f}")
        print(f"  Final Equity:     ${metrics.get('final_equity', 0):>12,.2f}")
        print(f"  Total Profit:     ${metrics.get('total_profit', 0):>12,.2f}")
        print(f"  Total Return:     {metrics.get('total_return', 0):>12.2f}%")
        print()

        print("RISK METRICS:")
        print(f"  Max Drawdown:     {metrics.get('max_drawdown', 0):>12.2f}%")
        print(f"  Sharpe Ratio:     {metrics.get('sharpe_ratio', 0):>12.2f}")
        pf = metrics.get('profit_factor', 0)
        pf_display = f"{pf:.2f}" if pf != float('inf') else "∞"
        print(f"  Profit Factor:    {pf_display:>12}")
        print()

        print("TRADE STATISTICS:")
        print(f"  Total Trades:     {metrics.get('total_trades', 0):>12}")
        print(f"  Winning Trades:   {metrics.get('winning_trades', 0):>12} ({metrics.get('win_rate', 0):.1f}%)")
        print(f"  Losing Trades:    {metrics.get('losing_trades', 0):>12} ({100 - metrics.get('win_rate', 0):.1f}%)")
        print(f"  Win/Loss Ratio:   {metrics.get('winning_trades', 0):>5} / {metrics.get('losing_trades', 0):<5}")
        print(f"  Open Positions:   {metrics.get('open_positions', 0):>12}")
        print()

        if metrics.get('total_trades', 0) > 0:
            print("TRADE DETAILS:")
            print(f"  Avg Win:          ${metrics.get('avg_win', 0):>12,.2f}")
            print(f"  Avg Loss:         ${metrics.get('avg_loss', 0):>12,.2f}")
            print(f"  Largest Win:      ${metrics.get('largest_win', 0):>12,.2f}")
            print(f"  Largest Loss:     ${metrics.get('largest_loss', 0):>12,.2f}")
            print(f"  Max Consecutive Wins:   {metrics.get('max_consecutive_wins', 0):>6}")
            print(f"  Max Consecutive Losses: {metrics.get('max_consecutive_losses', 0):>6}")
            print()

    if logger:
        logger.info("=" * 80)
        logger.info("BACKTEST RESULTS")
        logger.info("=" * 80)
        logger.info("")
        logger.info("ACCOUNT PERFORMANCE:")
        logger.info(f"  Initial Balance:  ${initial_balance:>12,.2f}")
        logger.info(f"  Final Balance:    ${metrics.get('final_balance', 0):>12,.2f}")
        logger.info(f"  Final Equity:     ${metrics.get('final_equity', 0):>12,.2f}")
        logger.info(f"  Total Profit:     ${metrics.get('total_profit', 0):>12,.2f}")
        logger.info(f"  Total Return:     {metrics.get('total_return', 0):>12.2f}%")
        logger.info("")
        logger.info("RISK METRICS:")
        logger.info(f"  Max Drawdown:     {metrics.get('max_drawdown', 0):>12.2f}%")
        logger.info(f"  Sharpe Ratio:     {metrics.get('sharpe_ratio', 0):>12.2f}")
        pf = metrics.get('profit_factor', 0)
        pf_display = f"{pf:.2f}" if pf != float('inf') else "∞"
        logger.info(f"  Profit Factor:    {pf_display:>12}")
        logger.info("")
        logger.info("TRADE STATISTICS:")
        logger.info(f"  Total Trades:     {metrics.get('total_trades', 0):>12}")
        logger.info(f"  Winning Trades:   {metrics.get('winning_trades', 0):>12} ({metrics.get('win_rate', 0):.1f}%)")
        logger.info(f"  Losing Trades:    {metrics.get('losing_trades', 0):>12} ({100 - metrics.get('win_rate', 0):.1f}%)")
        logger.info(f"  Win/Loss Ratio:   {metrics.get('winning_trades', 0):>5} / {metrics.get('losing_trades', 0):<5}")
        logger.info(f"  Open Positions:   {metrics.get('open_positions', 0):>12}")
        logger.info("")
        if metrics.get('total_trades', 0) > 0:
            logger.info("TRADE DETAILS:")
            logger.info(f"  Avg Win:          ${metrics.get('avg_win', 0):>12,.2f}")
            logger.info(f"  Avg Loss:         ${metrics.get('avg_loss', 0):>12,.2f}")
            logger.info(f"  Largest Win:      ${metrics.get('largest_win', 0):>12,.2f}")
            logger.info(f"  Largest Loss:     ${metrics.get('largest_loss', 0):>12,.2f}")
            logger.info(f"  Max Consecutive Wins:   {metrics.get('max_consecutive_wins', 0):>6}")
            logger.info(f"  Max Consecutive Losses: {metrics.get('max_consecutive_losses', 0):>6}")
            logger.info("")
def progress_print(message: str, logger=None):
    """
    Print progress message to console and optionally log to file.

    This function ensures key progress messages are visible even when
    console logging is disabled for performance.

    Args:
        message: Message to print/log
        logger: Optional logger instance to also log to file
    """
    print(message)
    if logger:
        logger.info(message)
def main():
    """Run the backtest."""
    import cProfile
    import pstats
    from pathlib import Path

    ENABLE_CONSOLE_LOGS = False

    USE_ASYNC_LOGGING = True

    if DEBUG_DATA_LOADING:
        BACKTEST_LOG_LEVEL = "DEBUG"
    else:
        BACKTEST_LOG_LEVEL = "WARNING"

    init_logger(
        log_to_file=True,
        log_to_console=ENABLE_CONSOLE_LOGS,
        log_level=BACKTEST_LOG_LEVEL,
        use_async_logging=USE_ASYNC_LOGGING
    )
    logger = get_logger()

    if DEBUG_DATA_LOADING:
        logger.info("Debug logging enabled (log level: DEBUG) - comprehensive data loading diagnostics active")

    from src.utils.logging import set_backtest_mode
    set_backtest_mode(
        time_getter=lambda: START_DATE,
        start_time=START_DATE
    )

    from src.utils.logging import get_log_directory
    log_dir = get_log_directory()

    print("=" * 80)
    print("MULTI-STRATEGY TRADING BOT - BACKTESTING ENGINE")
    print("=" * 80)
    print()
    print(f"Backtest logs directory: {log_dir.absolute()}")
    print()

    logger.info("=" * 80)
    logger.info("MULTI-STRATEGY TRADING BOT - BACKTESTING ENGINE")
    logger.info("=" * 80)
    logger.info("")
    logger.info(f"Backtest logs directory: {log_dir.absolute()}")
    logger.info("")

    backtest_data_dir = Path("data/backtest")
    backtest_data_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Backtest data directory: {backtest_data_dir.absolute()}")
    logger.info("  (Isolated from live trading data in data/)")
    logger.info("")

    days = (END_DATE - START_DATE).days
    stop_threshold_amount = INITIAL_BALANCE * (STOP_LOSS_THRESHOLD / 100.0)
    stop_threshold_status = f"${stop_threshold_amount:,.2f} ({STOP_LOSS_THRESHOLD}%)" if STOP_LOSS_THRESHOLD > 0 else "DISABLED"
    tick_mode_status = f"ENABLED ({TICK_TYPE})" if USE_TICK_DATA else "DISABLED (candle mode)"
    slippage_status = f"ENABLED ({SLIPPAGE_POINTS} points base)" if ENABLE_SLIPPAGE else "DISABLED"

    config_data = {
        'date_range': f"{START_DATE.date()} to {END_DATE.date()}",
        'duration': f"{days} day(s)",
        'initial_balance': INITIAL_BALANCE,
        'stop_threshold': stop_threshold_status,
        'timeframes': ', '.join(TIMEFRAMES),
        'time_mode': TIME_MODE.value,
        'tick_data': tick_mode_status,
        'spreads': "Read from MT5 (per-symbol actual spreads)",
        'slippage': slippage_status,
        'leverage': f"{LEVERAGE:.0f}:1"
    }

    if USE_TICK_DATA and days > 3:
        config_data['tick_warning'] = f"{days} days with tick data may use significant memory!"
        config_data['tick_warning_detail'] = "Consider reducing to 1-3 days for tick mode"

    print_configuration_panel(config_data, logger)

    if START_DATE >= END_DATE:
        progress_print("ERROR: START_DATE must be before END_DATE", logger)
        logger.error("START_DATE must be before END_DATE")
        return False

    duration = END_DATE - START_DATE
    progress_print(f"Backtest Duration: {duration.days} days", logger)
    progress_print("", logger)

    progress_print("=" * 80, logger)
    progress_print("STEP 1: Loading Symbols", logger)
    progress_print("=" * 80, logger)

    symbols = load_symbols(logger)
    if not symbols:
        progress_print("ERROR: No symbols to backtest", logger)
        logger.error("No symbols to backtest")
        return False

    progress_print(f"Symbols to backtest: {', '.join(symbols)}", logger)
    progress_print("", logger)

    progress_print("=" * 80, logger)
    progress_print("STEP 2: Loading Historical Data", logger)
    progress_print("=" * 80, logger)

    data_load_start = START_DATE - timedelta(days=HISTORICAL_BUFFER_DAYS)
    logger.info(f"Loading data from {data_load_start.date()} ({HISTORICAL_BUFFER_DAYS} day buffer)")
    logger.info(f"Backtest execution: {START_DATE.date()} to {END_DATE.date()}")
    logger.info("")
    logger.info(f"NOTE: Loading {len(TIMEFRAMES)} timeframes for accurate simulation")
    logger.info(f"  Timeframes: {', '.join(TIMEFRAMES)}")
    logger.info("  - M1: Base timeframe for breakout detection and HFT")
    logger.info("  - M5: Breakout detection (4H_5M), ATR, HFT trend filter")
    logger.info("  - M15: Reference candle (15M_1M range)")
    logger.info("  - H4: Reference candle (4H_5M range)")
    logger.info("")

    logger.info(f"Data caching: {'ENABLED' if USE_CACHE else 'DISABLED'}")
    if USE_CACHE:
        logger.info(f"  Cache directory: {CACHE_DIR}")
        logger.info(f"  Force refresh: {'YES' if FORCE_REFRESH else 'NO'}")
    logger.info("")

    if USE_TICK_DATA:
        import MetaTrader5 as mt5
        tick_cache_dir = Path(CACHE_DIR)
        tick_cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Tick data mode: ENABLED ({TICK_TYPE})")
        logger.info(f"  Tick cache directory: {tick_cache_dir.absolute()}")
        logger.info(f"  (Ticks organized by date: YYYY/MM/DD/ticks/SYMBOL_TICKTYPE.parquet)")
        logger.info("")

        tick_type_map = {
            "INFO": mt5.COPY_TICKS_INFO,
            "ALL": mt5.COPY_TICKS_ALL,
            "TRADE": mt5.COPY_TICKS_TRADE
        }
        tick_type_flag = tick_type_map.get(TICK_TYPE.upper(), mt5.COPY_TICKS_INFO)
        tick_cache_files = {}
    else:
        logger.info("Tick data mode: DISABLED (candle-based backtesting)")
        logger.info("")

    data_loader = BacktestDataLoader(
        use_cache=USE_CACHE,
        cache_dir=CACHE_DIR,
        cache_ttl_days=CACHE_TTL_DAYS
    )
    symbol_data = {}
    symbol_info = {}
    symbols_with_all_timeframes = []

    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text

    console = Console()

    def create_loading_table(current_symbol, current_tf, symbol_status):
        """Create a table showing loading progress - only shows actively loading symbols."""
        from rich.layout import Layout
        from rich.panel import Panel

        total_symbols = len(symbols)
        completed_symbols = 0
        failed_symbols = 0
        total_items = 0
        completed_items = 0

        active_symbols = []

        for sym in symbols:
            items_for_symbol = len(TIMEFRAMES) + (1 if USE_TICK_DATA else 0)
            total_items += items_for_symbol

            completed_for_symbol = 0
            failed_for_symbol = 0
            has_loading = False

            for tf in TIMEFRAMES:
                status = symbol_status.get((sym, tf), {}).get('status', 'pending')
                if status == 'success':
                    completed_for_symbol += 1
                    completed_items += 1
                elif status == 'error':
                    failed_for_symbol += 1
                elif status in ['loading', 'building']:
                    has_loading = True

            if USE_TICK_DATA:
                tick_status = symbol_status.get((sym, 'TICKS'), {}).get('status', 'pending')
                if tick_status == 'success':
                    completed_for_symbol += 1
                    completed_items += 1
                elif tick_status == 'error':
                    failed_for_symbol += 1
                elif tick_status in ['loading', 'building']:
                    has_loading = True

            if completed_for_symbol == items_for_symbol:
                completed_symbols += 1
            elif failed_for_symbol > 0 and not has_loading:
                failed_symbols += 1
            else:
                active_symbols.append(sym)

        summary = Text()
        summary.append("Completed: ", style="bold")
        summary.append(f"{completed_symbols}/{total_symbols}", style="green")

        if failed_symbols > 0:
            summary.append("  |  Failed: ", style="bold")
            summary.append(f"{failed_symbols}", style="red")

        summary.append("  |  Items: ", style="bold")
        summary.append(f"{completed_items}/{total_items}", style="yellow")

        if active_symbols:
            summary.append("  |  Active: ", style="bold")
            summary.append(f"{len(active_symbols)}", style="cyan")

            if USE_TICK_DATA:
                loading_ticks = 0
                for sym in active_symbols:
                    tick_key = (sym, 'TICKS')
                    tick_info = symbol_status.get(tick_key, {})
                    if tick_info.get('status') == 'loading':
                        loading_ticks += 1

                if loading_ticks > 0:
                    summary.append("  |  Parallel: ", style="bold")
                    summary.append(f"{PARALLEL_TICK_DAYS} days/symbol", style="magenta")

        table = Table(show_header=True, header_style="bold cyan",
                     box=None, padding=(0, 1), expand=False)
        table.add_column("Symbol", style="cyan", width=10)
        table.add_column("Current", style="yellow", width=12)
        table.add_column("Status", width=40)
        table.add_column("Done", justify="right", width=8)

        for sym in active_symbols:
            completed_tfs = []
            failed_tfs = []
            current_status = "pending"
            current_item = ""
            status_message = ""

            for tf in TIMEFRAMES:
                key = (sym, tf)
                status_info = symbol_status.get(key, {})
                status = status_info.get('status', 'pending')

                if status == 'success':
                    completed_tfs.append(tf)
                elif status == 'error':
                    failed_tfs.append(tf)
                elif status in ['loading', 'building']:
                    current_status = status
                    current_item = tf
                    status_message = status_info.get('message', '')

            tick_status = 'pending'
            tick_count = 0
            tick_day_progress = ''
            tick_current_day = ''
            tick_substatus = ''
            tick_metadata = {}
            if USE_TICK_DATA:
                tick_key = (sym, 'TICKS')
                tick_info = symbol_status.get(tick_key, {})
                tick_status = tick_info.get('status', 'pending')
                tick_count = tick_info.get('bars', 0)
                tick_day_progress = tick_info.get('day_progress', '')
                tick_current_day = tick_info.get('current_day', '')
                tick_substatus = tick_info.get('tick_status', '')
                tick_metadata = tick_info.get('metadata', {})

                if tick_status in ['loading', 'building']:
                    current_status = tick_status
                    current_item = 'TICKS'
                    status_message = tick_info.get('message', '')

            total_items = len(TIMEFRAMES) + (1 if USE_TICK_DATA else 0)
            completed_items = len(completed_tfs) + (1 if tick_status == 'success' else 0)

            if current_item:
                if current_item == 'TICKS' and tick_day_progress:
                    current_display = f"[yellow]{current_item} [{tick_day_progress}][/yellow]"
                else:
                    current_display = f"[yellow]{current_item}[/yellow]"
            elif completed_items == total_items:
                current_display = "[green]✓ Complete[/green]"
            elif failed_tfs:
                current_display = f"[red]✗ {failed_tfs[0]}[/red]"
            else:
                current_display = "[dim]Waiting...[/dim]"

            if current_status == 'loading':
                if current_item == 'TICKS' and tick_substatus:
                    if tick_substatus == 'cached':
                        status_icon = "✓"
                        status_color = "green"
                        file_size = tick_metadata.get('file_size_mb', 0)
                        load_time = tick_metadata.get('load_time', 0)
                        status_text = f"[green]{status_message}[/green]"
                    elif tick_substatus == 'checking_mt5':
                        status_icon = "🔍"
                        status_color = "yellow"
                        status_text = f"Checking MT5 for [{tick_current_day}]..."
                    elif tick_substatus == 'fetching_archive':
                        status_icon = "📥"
                        status_color = "yellow"
                        status_text = f"Fetching from archive [{tick_current_day}]..."
                    elif tick_substatus == 'parsing_archive':
                        status_icon = "⚙️"
                        status_color = "cyan"
                        pct = tick_metadata.get('percent', 0)
                        status_text = f"[cyan]Parsing archive ({pct:.0f}%) [{tick_current_day}]...[/cyan]"
                    elif tick_substatus == 'caching':
                        status_icon = "💾"
                        status_color = "cyan"
                        status_text = f"[cyan]Caching to disk [{tick_current_day}]...[/cyan]"
                    elif tick_substatus == 'downloaded':
                        status_icon = "✓"
                        status_color = "green"
                        source = tick_metadata.get('source', 'unknown')
                        file_size = tick_metadata.get('file_size_mb', 0)
                        download_time = tick_metadata.get('download_time', 0)
                        status_text = f"[green]{status_message}[/green]"
                    elif tick_substatus == 'no_data':
                        status_icon = "✗"
                        status_color = "red"
                        status_text = f"[red]No data available for [{tick_current_day}][/red]"
                    else:
                        status_icon = "⏳"
                        status_color = "yellow"
                        status_text = f"Loading {current_item} [{tick_current_day}]... {status_message}"
                else:
                    status_icon = "⏳"
                    status_color = "yellow"
                    if current_item == 'TICKS' and tick_current_day:
                        status_text = f"Loading {current_item} [{tick_current_day}]... {status_message}"
                    else:
                        status_text = f"Loading {current_item}... {status_message}"
            elif current_status == 'building':
                status_icon = "⚡"
                status_color = "magenta"
                status_text = f"Building {current_item} from ticks... {status_message}"
            elif failed_tfs:
                status_icon = "✗"
                status_color = "red"
                status_text = f"Failed: {', '.join(failed_tfs)}"
            elif completed_items == total_items:
                status_icon = "✓"
                status_color = "green"
                if USE_TICK_DATA:
                    status_text = f"All data loaded ({len(TIMEFRAMES)} TFs + {tick_count:,} ticks)"
                else:
                    status_text = f"All {len(TIMEFRAMES)} timeframes loaded"
            elif completed_tfs:
                status_icon = "⏳"
                status_color = "yellow"
                status_text = f"Loaded: {', '.join(completed_tfs)}"
            else:
                status_icon = "○"
                status_color = "dim"
                status_text = "Waiting to start..."

            progress_text = f"{completed_items}/{total_items}"
            if completed_items == total_items:
                progress_color = "green"
            elif completed_items > 0:
                progress_color = "yellow"
            else:
                progress_color = "dim"

            if sym == current_symbol:
                sym_style = "bold cyan"
            else:
                sym_style = "cyan" if completed_items > 0 else "dim"

            table.add_row(
                f"[{sym_style}]{sym}[/{sym_style}]",
                current_display,
                f"[{status_color}]{status_icon} {status_text}[/{status_color}]",
                f"[{progress_color}]{progress_text}[/{progress_color}]"
            )

        if not active_symbols:
            if completed_symbols == total_symbols:
                completion_msg = Text()
                completion_msg.append("✓ All symbols loaded successfully!", style="bold green")
                table.add_row("", "", completion_msg, "")
            elif failed_symbols > 0:
                completion_msg = Text()
                completion_msg.append(f"⚠ Loading complete with {failed_symbols} failed symbol(s)", style="bold yellow")
                table.add_row("", "", completion_msg, "")

        from rich.console import Group
        layout = Group(
            Panel(summary, title="📊 Data Loading Progress", border_style="cyan"),
            table
        )

        return layout

    symbol_status = {}

    import time
    load_times = {}

    import asyncio
    import concurrent.futures
    from functools import partial

    async def load_timeframe_async(executor, symbol, timeframe, data_load_start, END_DATE, FORCE_REFRESH, preloaded_ticks=None):
        """Load a single timeframe asynchronously with timeout."""
        loop = asyncio.get_event_loop()
        load_start = time.time()

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    executor,
                    partial(data_loader.load_from_mt5, symbol, timeframe, data_load_start, END_DATE,
                           force_refresh=FORCE_REFRESH, preloaded_ticks=preloaded_ticks,
                           use_incremental_loading=USE_INCREMENTAL_LOADING)
                ),
                timeout=300.0
            )

            load_time = time.time() - load_start
            return timeframe, result, load_time
        except asyncio.TimeoutError:
            logger.error(f"{symbol} {timeframe}: Load timeout after 5 minutes")
            return timeframe, None, time.time() - load_start
        except asyncio.CancelledError:
            logger.warning(f"{symbol} {timeframe}: Load cancelled")
            raise
        except Exception as e:
            logger.error(f"{symbol} {timeframe}: Load error: {e}")
            return timeframe, None, time.time() - load_start

    async def load_ticks_async(executor, symbol, START_DATE, END_DATE, tick_type_flag, tick_cache_dir, progress_callback=None):
        """Load tick data asynchronously."""
        loop = asyncio.get_event_loop()

        ticks_df = await loop.run_in_executor(
            executor,
            partial(data_loader.load_ticks_from_mt5, symbol, START_DATE, END_DATE, tick_type_flag,
                   str(tick_cache_dir), progress_callback, PARALLEL_TICK_DAYS)
        )

        return ticks_df

    async def load_symbol_data_async(executor, symbol, TIMEFRAMES, data_load_start, END_DATE, FORCE_REFRESH,
                                     USE_TICK_DATA, START_DATE, tick_type_flag, tick_cache_dir, live, symbol_status):
        """Load all data for a single symbol asynchronously."""
        loaded_timeframes = []
        has_insufficient_data = False
        symbol_data_local = {}
        symbol_info_local = None
        tick_cache_file = None
        ticks_df = None

        if USE_TICK_DATA:
            symbol_status[(symbol, 'TICKS')] = {'status': 'loading', 'bars': 0, 'message': 'Loading ticks...',
                                               'day_progress': '0/0', 'current_day': ''}
            live.update(create_loading_table(symbol, 'TICKS', symbol_status))

            logger.info(f"[STEP 1] Loading tick data for {symbol}...")

            def tick_progress_callback(day_idx, total_days, day_date, status, ticks_count, message, metadata=None):
                """Update tick loading progress in the live table."""
                symbol_status[(symbol, 'TICKS')] = {
                    'status': 'loading',
                    'bars': ticks_count,
                    'message': message,
                    'day_progress': f'{day_idx}/{total_days}',
                    'current_day': str(day_date),
                    'tick_status': status,
                    'metadata': metadata or {}
                }
                live.update(create_loading_table(symbol, 'TICKS', symbol_status))

            ticks_df = await load_ticks_async(executor, symbol, START_DATE, END_DATE, tick_type_flag,
                                             tick_cache_dir, tick_progress_callback)

            if ticks_df is not None and len(ticks_df) > 0:
                logger.info(f"{symbol}: {len(ticks_df):,} ticks loaded")
                symbol_status[(symbol, 'TICKS')] = {
                    'status': 'success',
                    'bars': len(ticks_df),
                    'message': f'{len(ticks_df):,} ticks',
                    'day_progress': '',
                    'current_day': ''
                }
                live.update(create_loading_table(symbol, 'TICKS', symbol_status))
            else:
                logger.warning(f"{symbol}: No tick data available")
                symbol_status[(symbol, 'TICKS')] = {
                    'status': 'error',
                    'bars': 0,
                    'message': 'No tick data',
                    'day_progress': '',
                    'current_day': ''
                }
                live.update(create_loading_table(symbol, 'TICKS', symbol_status))
                has_insufficient_data = True

        logger.info(f"[STEP 2] Loading candles for {symbol}...")
        tasks = [
            load_timeframe_async(executor, symbol, tf, data_load_start, END_DATE, FORCE_REFRESH, ticks_df)
            for tf in TIMEFRAMES
        ]

        for tf in TIMEFRAMES:
            symbol_status[(symbol, tf)] = {'status': 'loading', 'bars': 0, 'message': ''}
        live.update(create_loading_table(symbol, TIMEFRAMES[0], symbol_status))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                logger.error(f"{symbol}: Error loading data: {result}")
                has_insufficient_data = True
                continue

            timeframe, data_result, load_time = result
            load_times[(symbol, timeframe)] = load_time
            logger.info(f"{symbol} {timeframe}: Load time = {load_time:.2f}s")

            if data_result is None:
                logger.error(f"Failed to load {timeframe} data for {symbol}")
                symbol_status[(symbol, timeframe)] = {
                    'status': 'error',
                    'bars': 0,
                    'message': 'Failed to load'
                }
                live.update(create_loading_table(symbol, timeframe, symbol_status))
                has_insufficient_data = True
                continue

            df, info = data_result

            min_bars_expected = {
                'M1': duration.days * 1000,
                'M5': duration.days * 200,
                'M15': duration.days * 60,
                'H4': duration.days * 5,
            }

            min_required = min_bars_expected.get(timeframe, 10)
            if len(df) < min_required:
                logger.warning(
                    f"{symbol} {timeframe}: Only {len(df)} bars loaded "
                    f"(expected at least {min_required} for {duration.days} days)"
                )
                if len(df) < 10:
                    logger.error(f"{symbol} {timeframe}: Insufficient data (< 10 bars)")
                    symbol_status[(symbol, timeframe)] = {
                        'status': 'error',
                        'bars': len(df),
                        'message': 'Insufficient data'
                    }
                    live.update(create_loading_table(symbol, timeframe, symbol_status))
                    has_insufficient_data = True
                    continue

            symbol_data_local[(symbol, timeframe)] = df
            loaded_timeframes.append(timeframe)

            if symbol_info_local is None:
                symbol_info_local = info

            logger.info(f"{symbol} {timeframe}: {len(df):,} bars loaded")
            symbol_status[(symbol, timeframe)] = {
                'status': 'success',
                'bars': len(df),
                'message': 'Loaded'
            }
            live.update(create_loading_table(symbol, timeframe, symbol_status))

        if USE_TICK_DATA and ticks_df is not None and len(ticks_df) > 0:
            tick_cache_files[symbol] = True

            del ticks_df

        return symbol, loaded_timeframes, has_insufficient_data, symbol_data_local, symbol_info_local, tick_cache_file

    async def load_all_data_async():
        """Load all symbol data asynchronously."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            with Live(create_loading_table(None, None, symbol_status), console=console, refresh_per_second=1) as live:
                tasks = [
                    load_symbol_data_async(
                        executor, symbol, TIMEFRAMES, data_load_start, END_DATE, FORCE_REFRESH,
                        USE_TICK_DATA, START_DATE, tick_type_flag if USE_TICK_DATA else None,
                        tick_cache_dir if USE_TICK_DATA else None, live, symbol_status
                    )
                    for symbol in symbols
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        if isinstance(result, asyncio.CancelledError):
                            raise result
                        logger.error(f"Error loading symbol data: {result}")
                        continue

                    symbol, loaded_timeframes, has_insufficient_data, symbol_data_local, symbol_info_local, tick_cache_file = result

                    if has_insufficient_data or len(loaded_timeframes) != len(TIMEFRAMES):
                        if has_insufficient_data:
                            logger.warning(f"Skipping {symbol} - insufficient historical data")
                        else:
                            missing = set(TIMEFRAMES) - set(loaded_timeframes)
                            logger.warning(f"Skipping {symbol} - missing timeframes: {', '.join(missing)}")
                    else:
                        symbol_data.update(symbol_data_local)
                        if symbol_info_local:
                            symbol_info[symbol] = symbol_info_local
                        if tick_cache_file:
                            tick_cache_files[symbol] = tick_cache_file
                        symbols_with_all_timeframes.append(symbol)
                        logger.info(f"{symbol}: All {len(TIMEFRAMES)} timeframes loaded successfully")

    try:
        asyncio.run(load_all_data_async())
    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("=" * 80)
        logger.warning("Data loading interrupted by user (Ctrl+C)")
        logger.warning("=" * 80)
        logger.warning("")
        return False
    except Exception as e:
        logger.error(f"Error during async data loading: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

    if not symbol_data:
        logger.error("No data loaded for any symbols")
        return False

    symbols = symbols_with_all_timeframes
    logger.info("")
    logger.info(f"Successfully loaded {len(symbols)} symbols with all {len(TIMEFRAMES)} timeframes")
    if symbols:
        logger.info(f"Symbols to backtest: {', '.join(symbols)}")

    if USE_TICK_DATA:
        logger.info("")
        logger.info(f"Tick data loaded for {len(tick_cache_files)}/{len(symbols)} symbols")

        if tick_cache_files:
            logger.info(f"  Tick data ready for {len(tick_cache_files)} symbols")
            logger.info(f"  Cache organized by date: {tick_cache_dir}/YYYY/MM/DD/ticks/")

        log_memory(logger, "after tick data loading")

    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 2 TIMING SUMMARY:")
    logger.info("=" * 60)
    total_load_time = sum(load_times.values())
    logger.info(f"Total load time: {total_load_time:.2f}s")
    logger.info("")
    logger.info("Per symbol/timeframe:")
    for (sym, tf), load_time in sorted(load_times.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {sym:10s} {tf:5s}: {load_time:6.2f}s")
    logger.info("=" * 60)
    logger.info("")

    console.print("\n[bold cyan]" + "=" * 80 + "[/bold cyan]")
    console.print("[bold cyan]STEP 2.5: Loading Currency Conversion Pairs[/bold cyan]")
    console.print("[bold cyan]" + "=" * 80 + "[/bold cyan]\n")

    needed_conversions = set()
    for symbol in symbols:
        if symbol in symbol_info:
            currency_profit = symbol_info[symbol].get('currency_profit', 'USD')
            if currency_profit != 'USD' and currency_profit != 'UNKNOWN':
                direct_pair = f"{currency_profit}USD"
                inverse_pair = f"USD{currency_profit}"
                needed_conversions.add((currency_profit, direct_pair, inverse_pair))

    if len(needed_conversions) == 0:
        console.print("[green]✓ All symbols use USD - no conversion pairs needed[/green]\n")
    else:
        console.print(f"[yellow]Detected {len(needed_conversions)} currencies needing conversion to USD:[/yellow]")
        for currency, direct, inverse in sorted(needed_conversions):
            console.print(f"  [dim]• {currency} → USD (will try {direct} or {inverse})[/dim]")
        console.print("")

        conversion_pairs_loaded = 0

        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Loading conversion pairs...", total=len(needed_conversions))

            for currency, direct_pair, inverse_pair in needed_conversions:
                if direct_pair in symbols or inverse_pair in symbols:
                    loaded_pair = direct_pair if direct_pair in symbols else inverse_pair
                    progress.update(task, advance=1, description=f"[green]✓ {currency}USD (already loaded)[/green]")
                    logger.info(f"{currency}USD: Already loaded as trading symbol ({loaded_pair})")
                    conversion_pairs_loaded += 1
                    continue

                progress.update(task, description=f"[cyan]Loading {direct_pair}...[/cyan]")
                result = data_loader.load_from_mt5(
                    direct_pair, 'M1', data_load_start, END_DATE,
                    force_refresh=FORCE_REFRESH
                )

                if result is not None:
                    df, info = result
                    if len(df) >= 10:
                        symbol_data[(direct_pair, 'M1')] = df
                        symbol_info[direct_pair] = info
                        progress.update(task, advance=1, description=f"[green]✓ {currency}USD ({direct_pair})[/green]")
                        logger.info(f"{currency}USD: {len(df):,} bars loaded ({direct_pair})")
                        conversion_pairs_loaded += 1
                        continue

                progress.update(task, description=f"[cyan]Loading {inverse_pair}...[/cyan]")
                result = data_loader.load_from_mt5(
                    inverse_pair, 'M1', data_load_start, END_DATE,
                    force_refresh=FORCE_REFRESH
                )

                if result is not None:
                    df, info = result
                    if len(df) >= 10:
                        symbol_data[(inverse_pair, 'M1')] = df
                        symbol_info[inverse_pair] = info
                        progress.update(task, advance=1, description=f"[green]✓ {currency}USD ({inverse_pair}, inverted)[/green]")
                        logger.info(f"{currency}USD: {len(df):,} bars loaded ({inverse_pair}, will invert)")
                        conversion_pairs_loaded += 1
                    else:
                        progress.update(task, advance=1, description=f"[red]✗ {currency}USD (insufficient data)[/red]")
                        logger.warning(f"{currency}USD: Insufficient data for {inverse_pair} ({len(df)} bars)")
                else:
                    progress.update(task, advance=1, description=f"[red]✗ {currency}USD (not available)[/red]")
                    logger.warning(f"{currency}USD: Neither {direct_pair} nor {inverse_pair} available in MT5")

        console.print(f"\n[green]✓ Loaded {conversion_pairs_loaded}/{len(needed_conversions)} conversion pairs[/green]")
        if conversion_pairs_loaded < len(needed_conversions):
            console.print("[yellow]⚠ Some conversion pairs missing - profit calculations may be inaccurate[/yellow]")
        console.print("[dim]Note: Inverse pairs will be automatically inverted during backtest (e.g., JPY rate = 1/USDJPY)[/dim]\n")

    if USE_CACHE:
        cache_stats = data_loader.get_cache_stats()
        logger.info("Cache Statistics:")
        logger.info(f"  Total symbols cached: {cache_stats.get('total_symbols', 0)}")
        logger.info(f"  Total cache files: {cache_stats.get('total_files', 0)}")
        logger.info(f"  Total cache size: {cache_stats.get('total_size_mb', 0):.2f} MB")
        logger.info("")

    logger.info("=" * 80)
    logger.info("STEP 3: Initializing Position Persistence")
    logger.info("=" * 80)

    from src.execution.position_persistence import PositionPersistence
    backtest_persistence = PositionPersistence(data_dir=str(backtest_data_dir))

    backtest_persistence.clear_all()
    logger.info(f"  ✓ Position persistence initialized (using {backtest_data_dir})")
    logger.info(f"  ✓ Cleared stale positions from previous runs")
    logger.info("")

    logger.info("=" * 80)
    logger.info("STEP 4: Initializing Simulated Broker")
    logger.info("=" * 80)

    broker = SimulatedBroker(
        initial_balance=INITIAL_BALANCE,
        persistence=backtest_persistence,
        enable_slippage=ENABLE_SLIPPAGE,
        slippage_points=SLIPPAGE_POINTS,
        leverage=LEVERAGE
    )

    logger.info("Converting tick_value to USD for all symbols...")

    def get_conversion_rate_from_data(from_currency: str, to_currency: str) -> Optional[float]:
        """Get conversion rate from loaded symbol_data."""
        if from_currency == to_currency:
            return 1.0

        direct_pair = f"{from_currency}{to_currency}"
        if (direct_pair, 'M1') in symbol_data:
            df = symbol_data[(direct_pair, 'M1')]
            if len(df) > 0:
                return float(df.iloc[0]['close'])

        inverse_pair = f"{to_currency}{from_currency}"
        if (inverse_pair, 'M1') in symbol_data:
            df = symbol_data[(inverse_pair, 'M1')]
            if len(df) > 0:
                price = float(df.iloc[0]['close'])
                if price > 0:
                    return 1.0 / price

        return None

    converted_symbol_info = {}
    for symbol, info in symbol_info.items():
        converted_info = info.copy()

        currency_profit = info.get('currency_profit', 'USD')
        tick_value_raw = info.get('tick_value', 1.0)

        if currency_profit != 'USD' and currency_profit != 'UNKNOWN':
            conversion_rate = get_conversion_rate_from_data(currency_profit, 'USD')
            if conversion_rate is not None:
                tick_value_usd = tick_value_raw * conversion_rate
                converted_info['tick_value'] = tick_value_usd
                converted_info['currency_profit'] = 'USD'
                logger.info(
                    f"  ✓ {symbol}: tick_value converted {currency_profit}→USD: "
                    f"{tick_value_raw:.5f} × {conversion_rate:.5f} = {tick_value_usd:.5f}"
                )
            else:
                logger.warning(
                    f"  ⚠ {symbol}: Failed to convert tick_value from {currency_profit} to USD, "
                    f"using raw value {tick_value_raw:.5f}"
                )

        converted_symbol_info[symbol] = converted_info

    loaded_count = 0
    conversion_count = 0
    for (symbol, timeframe), df in symbol_data.items():
        if symbol in symbols:
            broker.load_symbol_data(symbol, df, converted_symbol_info[symbol], timeframe)
            loaded_count += 1
        elif symbol in converted_symbol_info and timeframe == 'M1':
            broker.load_symbol_data(symbol, df, converted_symbol_info[symbol], timeframe)
            conversion_count += 1

    logger.info(f"  ✓ SimulatedBroker initialized (with position persistence)")
    logger.info(
        f"  ✓ Loaded {loaded_count} symbol-timeframe combinations ({len(symbols)} symbols x {len(TIMEFRAMES)} timeframes)")
    if conversion_count > 0:
        logger.info(f"  ✓ Loaded {conversion_count} currency conversion pairs (M1 only)")
    logger.info(f"  ✓ Initial balance: ${INITIAL_BALANCE:,.2f}")
    logger.info("")

    logger.info(f"Setting backtest start time to {START_DATE.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    logger.info(
        f"  (Historical buffer from {data_load_start.strftime('%Y-%m-%d %H:%M:%S')} will be available for lookback)")
    broker.set_start_time(START_DATE)
    logger.info("")

    if USE_TICK_DATA:
        console.print("\n[bold cyan]" + "=" * 80 + "[/bold cyan]")
        console.print("[bold cyan]STEP 4.5: Early Strategy Initialization (for timeframe collection)[/bold cyan]")
        console.print("[bold cyan]" + "=" * 80 + "[/bold cyan]\n")

        logger.info("=" * 80)
        logger.info("STEP 4.5: Early Strategy Initialization (for timeframe collection)")
        logger.info("=" * 80)
        logger.info("  PERFORMANCE OPTIMIZATION: Initializing strategies early to collect required timeframes")
        logger.info("  This allows us to only build candles for timeframes that strategies actually use")
        logger.info("")

        time_granularity = TimeGranularity.TICK
        time_controller = TimeController(
            symbols,
            mode=TIME_MODE,
            granularity=time_granularity,
            include_position_monitor=True,
            broker=broker
        )
        logger.info(f"  ✓ TimeController initialized (early)")

        risk_manager = RiskManager(
            connector=broker,
            risk_config=config.risk,
            persistence=backtest_persistence
        )
        logger.info("  ✓ RiskManager initialized (early)")

        order_manager = OrderManager(
            connector=broker,
            magic_number=config.advanced.magic_number,
            trade_comment=config.advanced.trade_comment,
            persistence=backtest_persistence,
            risk_manager=risk_manager
        )
        logger.info("  ✓ OrderManager initialized (early)")

        indicators = TechnicalIndicators()
        logger.info("  ✓ TechnicalIndicators initialized (early)")

        trade_manager = TradeManager(
            connector=broker,
            order_manager=order_manager,
            trailing_config=config.trailing_stop,
            use_breakeven=config.advanced.use_breakeven,
            breakeven_trigger_rr=config.advanced.breakeven_trigger_rr,
            indicators=indicators,
            range_configs=config.range_config.ranges
        )
        logger.info("  ✓ TradeManager initialized (early)")

        backtest_controller = BacktestController(
            simulated_broker=broker,
            time_controller=time_controller,
            order_manager=order_manager,
            risk_manager=risk_manager,
            trade_manager=trade_manager,
            indicators=indicators,
            stop_loss_threshold=STOP_LOSS_THRESHOLD
        )

        if not backtest_controller.initialize(symbols):
            logger.error("Failed to initialize BacktestController")
            logger.error("Check your .env configuration and strategy settings")
            return False

        logger.info("  ✓ Strategies initialized (early)")
        logger.info("")

        logger.info("  Collecting required timeframes from strategies...")
        required_timeframes_set = set()
        for symbol, strategy in backtest_controller.trading_controller.strategies.items():
            if hasattr(strategy, 'strategies') and isinstance(strategy.strategies, dict):
                for strategy_key, sub_strategy in strategy.strategies.items():
                    timeframes = sub_strategy.get_required_timeframes()
                    if timeframes:
                        required_timeframes_set.update(timeframes)
                        logger.info(f"    {symbol} - {strategy_key}: {timeframes}")
                    else:
                        logger.info(f"    {symbol} - {strategy_key}: [] (tick-only)")
            else:
                timeframes = strategy.get_required_timeframes()
                if timeframes:
                    required_timeframes_set.update(timeframes)
                    strategy_name = strategy.get_strategy_name() if hasattr(strategy, 'get_strategy_name') else type(strategy).__name__
                    logger.info(f"    {symbol} - {strategy_name}: {timeframes}")
                else:
                    strategy_name = strategy.get_strategy_name() if hasattr(strategy, 'get_strategy_name') else type(strategy).__name__
                    logger.info(f"    {symbol} - {strategy_name}: [] (tick-only)")

        required_timeframes = sorted(list(required_timeframes_set))
        if required_timeframes:
            logger.info("")
            logger.info(f"  ⚡ OPTIMIZATION: Will build only {len(required_timeframes)} timeframes: {required_timeframes}")
            logger.info(f"  ⚡ SPEEDUP: Skipping {5 - len(required_timeframes)} unused timeframes")
            console.print(f"\n[green]⚡ OPTIMIZATION: Building only {len(required_timeframes)} timeframes: {required_timeframes}[/green]")
            console.print(f"[green]⚡ SPEEDUP: Skipping {5 - len(required_timeframes)} unused timeframes[/green]\n")
        else:
            logger.info("")
            logger.info(f"  ⚡ OPTIMIZATION: No candles required (all strategies are tick-only)")
            logger.info(f"  ⚡ SPEEDUP: Skipping ALL candle building (maximum performance)")
            console.print(f"\n[green]⚡ OPTIMIZATION: No candles required (all strategies are tick-only)[/green]")
            console.print(f"[green]⚡ SPEEDUP: Skipping ALL candle building (maximum performance)[/green]\n")
        logger.info("=" * 80)
        logger.info("")
    else:
        required_timeframes = None

    if USE_TICK_DATA:
        console.print("\n[bold cyan]" + "=" * 80 + "[/bold cyan]")
        console.print("[bold cyan]STEP 4.5: Loading Tick Timeline[/bold cyan]")
        console.print("[bold cyan]" + "=" * 80 + "[/bold cyan]\n")

        logger.info("=" * 80)
        logger.info("STEP 4.5: Loading Tick Timeline")
        logger.info("=" * 80)
        logger.info(f"  Symbols with tick data: {len(tick_cache_files)}/{len(symbols)}")
        log_memory(logger, "before timeline loading")
        logger.info("")

        if STREAM_TICKS_FROM_DISK:
            console.print("[yellow]Using STREAMING mode (ticks read from disk on-demand)[/yellow]")
            console.print("[dim]  Memory usage: ~2-3 GB (vs ~20-30 GB for loading all ticks)[/dim]\n")

            logger.info("Using STREAMING mode (ticks read from disk on-demand)")
            logger.info("  Memory usage: ~2-3 GB (vs ~20-30 GB for loading all ticks)")
            logger.info("")

            tick_type_name = {
                mt5.COPY_TICKS_INFO: "INFO",
                mt5.COPY_TICKS_ALL: "ALL",
                mt5.COPY_TICKS_TRADE: "TRADE"
            }.get(tick_type_flag, "INFO")

            broker.load_ticks_streaming(
                cache_files={},
                chunk_size=100000,
                required_timeframes=required_timeframes,
                start_date=START_DATE,
                end_date=END_DATE,
                cache_dir=str(tick_cache_dir),
                tick_type_name=tick_type_name
            )
        else:
            console.print("[yellow]Using TRADITIONAL mode (all ticks loaded into memory)[/yellow]")
            console.print("[dim]  Memory usage: ~20-30 GB for full year backtest[/dim]\n")

            logger.info("Using TRADITIONAL mode (all ticks loaded into memory)")
            logger.info("  Memory usage: ~20-30 GB for full year backtest")
            logger.info("")

            from rich.table import Table
            from rich.live import Live
            from rich.panel import Panel
            from rich.text import Text

            tick_load_status = {}

            def create_tick_loading_table():
                """Create a table showing tick loading progress."""
                total_symbols = len(tick_cache_files)
                completed_symbols = 0
                total_ticks = 0
                loaded_ticks = 0

                for symbol in tick_cache_files.keys():
                    status = tick_load_status.get(symbol, {})
                    if status.get('status') == 'complete':
                        completed_symbols += 1
                    tick_count = status.get('ticks', 0)
                    loaded_ticks += tick_count
                    if status.get('total_ticks'):
                        total_ticks += status['total_ticks']

                summary = Text()
                summary.append("Symbols: ", style="bold")
                summary.append(f"{completed_symbols}/{total_symbols}", style="green")
                summary.append("  |  Ticks: ", style="bold")
                if total_ticks > 0:
                    summary.append(f"{loaded_ticks:,}/{total_ticks:,}", style="yellow")
                else:
                    summary.append(f"{loaded_ticks:,}", style="yellow")

                table = Table(show_header=True, header_style="bold cyan",
                             box=None, padding=(0, 1), expand=False)
                table.add_column("Symbol", style="cyan", width=12)
                table.add_column("Status", width=50)
                table.add_column("Ticks", justify="right", width=15)

                for symbol in tick_cache_files.keys():
                    status = tick_load_status.get(symbol, {})
                    state = status.get('status', 'pending')
                    tick_count = status.get('ticks', 0)
                    message = status.get('message', '')

                    if state == 'loading':
                        status_text = f"[yellow]⏳ Loading from cache...[/yellow]"
                    elif state == 'converting':
                        status_text = f"[magenta]⚡ Converting to timeline... {message}[/magenta]"
                    elif state == 'complete':
                        status_text = f"[green]✓ {message}[/green]"
                    elif state == 'error':
                        status_text = f"[red]✗ {message}[/red]"
                    else:
                        status_text = "[dim]○ Waiting...[/dim]"

                    tick_display = f"[cyan]{tick_count:,}[/cyan]" if tick_count > 0 else "[dim]0[/dim]"

                    table.add_row(symbol, status_text, tick_display)

                from rich.console import Group
                layout = Group(
                    Panel(summary, title="📊 Tick Timeline Loading", border_style="cyan"),
                    table
                )

                return layout

            def progress_callback(symbol, status, ticks=0, message='', total_ticks=None):
                """Callback to update progress display."""
                tick_load_status[symbol] = {
                    'status': status,
                    'ticks': ticks,
                    'message': message,
                    'total_ticks': total_ticks
                }

            with Live(create_tick_loading_table(), console=console, refresh_per_second=4) as live:
                broker.load_ticks_from_cache_files(tick_cache_files, progress_callback=progress_callback, live_display=live, table_creator=create_tick_loading_table, required_timeframes=required_timeframes)

        console.print("[green]✓ Global tick timeline initialized[/green]\n")
        logger.info("  ✓ Global tick timeline initialized")
        log_memory(logger, "after timeline loading")
        logger.info("")

    if not USE_TICK_DATA:
        logger.info("=" * 80)
        logger.info("STEP 5: Initializing Time Controller")
        logger.info("=" * 80)

        time_granularity = TimeGranularity.MINUTE

        time_controller = TimeController(
            symbols,
            mode=TIME_MODE,
            granularity=time_granularity,
            include_position_monitor=True,
            broker=broker
        )
        logger.info(f"  ✓ TimeController initialized")
        logger.info(f"  ✓ Time mode: {TIME_MODE.value}")
        logger.info(f"  ✓ Time granularity: {time_granularity.value}")
        logger.info(f"  ✓ Barrier participants: {len(symbols)} symbols + 1 position monitor")
        logger.info(f"  ✓ Global time advancement: minute-by-minute")
        logger.info("")

        logger.info("=" * 80)
        logger.info("STEP 6: Initializing Trading Components")
        logger.info("=" * 80)

        risk_manager = RiskManager(
            connector=broker,
            risk_config=config.risk,
            persistence=backtest_persistence
        )
        logger.info("  ✓ RiskManager initialized")

        order_manager = OrderManager(
            connector=broker,
            magic_number=config.advanced.magic_number,
            trade_comment=config.advanced.trade_comment,
            persistence=backtest_persistence,
            risk_manager=risk_manager
        )
        logger.info("  ✓ OrderManager initialized (with position limit checks enabled)")

        indicators = TechnicalIndicators()
        logger.info("  ✓ TechnicalIndicators initialized")

        trade_manager = TradeManager(
            connector=broker,
            order_manager=order_manager,
            trailing_config=config.trailing_stop,
            use_breakeven=config.advanced.use_breakeven,
            breakeven_trigger_rr=config.advanced.breakeven_trigger_rr,
            indicators=indicators,
            range_configs=config.range_config.ranges
        )
        logger.info("  ✓ TradeManager initialized (with range-specific ATR timeframes)")
        logger.info("")

        logger.info("=" * 80)
        logger.info("STEP 6: Initializing Backtest Controller")
        logger.info("=" * 80)

        backtest_controller = BacktestController(
            simulated_broker=broker,
            time_controller=time_controller,
            order_manager=order_manager,
            risk_manager=risk_manager,
            trade_manager=trade_manager,
            indicators=indicators,
            stop_loss_threshold=STOP_LOSS_THRESHOLD
        )

        if not backtest_controller.initialize(symbols):
            logger.error("Failed to initialize BacktestController")
            logger.error("Check your .env configuration and strategy settings")
            return False

        logger.info("  ✓ BacktestController initialized")
        logger.info("  ✓ Strategies loaded from .env configuration")
        logger.info("")
    else:
        logger.info("=" * 80)
        logger.info("STEP 5-6: Components Already Initialized (in Step 4.5)")
        logger.info("=" * 80)
        logger.info("  ✓ TimeController, trading components, and strategies already initialized")
        logger.info("  ✓ Skipping duplicate initialization")

        if USE_TICK_DATA:
            total_ticks = len(broker.global_tick_timeline)
            logger.info(f"  ✓ Global time advancement: tick-by-tick ({total_ticks:,} ticks)")
            logger.info(f"  ⚠ Performance: ~{total_ticks:,} time steps (slower but highest fidelity)")
        logger.info("=" * 80)
        logger.info("")

    progress_print("=" * 80, logger)
    progress_print("STEP 7: Running Backtest", logger)
    progress_print("=" * 80, logger)
    progress_print("", logger)
    progress_print("Backtest is now running...", logger)
    progress_print("", logger)
    progress_print("This may take a while depending on:", logger)
    progress_print("  - Number of symbols", logger)
    progress_print("  - Date range", logger)
    progress_print("  - Number of enabled strategies", logger)
    progress_print("  - Time mode (MAX_SPEED is fastest)", logger)
    progress_print("", logger)
    if not ENABLE_CONSOLE_LOGS:
        progress_print("NOTE: Console logging is DISABLED for maximum speed.", logger)
        progress_print(f"      Detailed logs are being saved to: {log_dir.absolute()}", logger)
        progress_print("", logger)
    progress_print("=" * 80, logger)
    progress_print("", logger)

    profiler = cProfile.Profile()
    profiler.enable()

    try:
        if USE_SEQUENTIAL_MODE:
            backtest_controller.run_sequential(backtest_start_time=START_DATE)
        else:
            backtest_controller.run(backtest_start_time=START_DATE)

    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("=" * 80)
        logger.warning("Backtest interrupted by user (Ctrl+C)")
        logger.warning("=" * 80)
        logger.warning("")
        logger.warning("Partial results may be available")
        logger.warning("")

        from src.utils.logging import set_live_mode
        set_live_mode()
        return False

    except Exception as e:
        logger.error("")
        logger.error("=" * 80)
        logger.error("Backtest failed with error:")
        logger.error("=" * 80)
        logger.error(f"{type(e).__name__}: {e}")
        logger.error("")
        import traceback
        logger.error(traceback.format_exc())

        from src.utils.logging import set_live_mode
        set_live_mode()
        return False

    progress_print("", logger)
    progress_print("=" * 80, logger)
    progress_print("STEP 8: Analyzing Results", logger)
    progress_print("=" * 80, logger)
    progress_print("", logger)

    try:
        results = backtest_controller.get_results()
        analyzer = ResultsAnalyzer()
        metrics = analyzer.analyze(results)

        import pickle
        trades = broker.get_closed_trades()
        pickle_file = "backtest_trades.pkl"
        with open(pickle_file, 'wb') as f:
            pickle.dump(trades, f)
        logger.info(f"  ✓ Saved {len(trades)} trades to {pickle_file} for detailed analysis")

    except Exception as e:
        progress_print(f"ERROR: Failed to analyze results: {e}", logger)
        logger.error(f"Failed to analyze results: {e}")
        return False

    print_results_table(metrics, INITIAL_BALANCE, logger)

    per_symbol = metrics.get('per_symbol', {})
    if per_symbol:
        logger.info("PER-SYMBOL PERFORMANCE:")
        logger.info("")
        for symbol in sorted(per_symbol.keys()):
            stats = per_symbol[symbol]
            logger.info(f"  {symbol}:")
            logger.info(f"    Trades:        {stats['total_trades']}")
            logger.info(f"    Profit:        ${stats['total_profit']:,.2f}")
            logger.info(f"    Win Rate:      {stats['win_rate']:.1f}%")
            logger.info(f"    Profit Factor: {stats['profit_factor']:.2f}")
            logger.info(f"    Avg Profit:    ${stats['avg_profit']:,.2f}")
            logger.info("")

    per_strategy = metrics.get('per_strategy', {})
    if per_strategy:
        logger.info("PER-STRATEGY PERFORMANCE:")
        logger.info("")
        for strategy_key in sorted(per_strategy.keys()):
            stats = per_strategy[strategy_key]
            logger.info(f"  {strategy_key}:")
            logger.info(f"    Trades:        {stats['total_trades']}")
            logger.info(f"    Profit:        ${stats['total_profit']:,.2f}")
            logger.info(f"    Win Rate:      {stats['win_rate']:.1f}%")
            logger.info(f"    Profit Factor: {stats['profit_factor']:.2f}")
            logger.info(f"    Avg Profit:    ${stats['avg_profit']:,.2f}")
            logger.info("")

    logger.info("=" * 80)
    logger.info("")

    logger.info("BACKTEST COMPLETE!")
    logger.info("")
    logger.info("Next steps:")
    logger.info(f"  1. Review the detailed logs in {log_dir}/")
    logger.info("  2. Run detailed analysis: python analyze_backtest_results.py")
    logger.info("  3. Analyze individual strategy performance")
    logger.info("  4. Compare results with live trading expectations")
    logger.info("  5. Adjust strategy parameters in .env if needed")
    logger.info("  6. Run additional backtests to validate changes")
    logger.info("")
    logger.info("Analysis tools:")
    logger.info("  - analyze_backtest_results.py  (Symbol/strategy pair analysis)")
    logger.info("  - backtest_trades.pkl          (Trade data for custom analysis)")
    logger.info("")
    logger.info("For more information, see docs/CUSTOM_BACKTEST_ENGINE.md")
    logger.info("=" * 80)

    from src.utils.logging import set_live_mode
    set_live_mode()

    logger.info("Flushing async logs...")
    logger.shutdown()

    profiler.disable()

    profile_dir = Path("profile_results")
    profile_dir.mkdir(exist_ok=True)

    profile_file = profile_dir / f"backtest_profile_{START_DATE.strftime('%Y%m%d')}.prof"
    profiler.dump_stats(str(profile_file))

    print("\n" + "=" * 80)
    print("PROFILING RESULTS - TOP 30 FUNCTIONS BY CUMULATIVE TIME")
    print("=" * 80)

    stats = pstats.Stats(profiler)
    stats.sort_stats('cumtime')
    stats.print_stats(30)

    text_file = profile_dir / f"backtest_profile_{START_DATE.strftime('%Y%m%d')}.txt"
    with open(text_file, 'w') as f:
        stats = pstats.Stats(profiler, stream=f)
        stats.sort_stats('cumtime')
        stats.print_stats(50)

    print(f"\nProfile saved to:")
    print(f"  Binary: {profile_file}")
    print(f"  Text:   {text_file}")
    print("=" * 80)

    return True
if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
