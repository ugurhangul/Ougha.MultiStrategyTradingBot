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

    Logs location: logs/backtest/YYYY-MM-DD/

Documentation:
    See docs/CUSTOM_BACKTEST_ENGINE.md for detailed information
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional
import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.backtesting.engine import (
    SimulatedBroker,
    TimeController,
    TimeMode,
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

# ============================================================================
# CONFIGURATION - Customize these settings for your backtest
# ============================================================================

# Date Range
# Use recent dates for quick testing, or longer periods for comprehensive analysis
# IMPORTANT: Use recent dates (2025)! Some symbols are new and don't have 2024 data
# Recommended: Last 7-14 days for testing, last 1-3 months for full backtest
START_DATE = datetime(2025, 11, 10, tzinfo=timezone.utc)
END_DATE = datetime(2025, 11, 15, tzinfo=timezone.utc)

# Initial Balance
INITIAL_BALANCE = 10000.0  # Starting capital in USD

# Symbols
# Option 1: Specify symbols directly (recommended for testing)
# SYMBOLS: Optional[List[str]] = []  # Major pairs with good data
# Option 2: Set to None to load from active.set file (recommended for full backtest)
SYMBOLS = None  # Load from active.set - will auto-skip symbols with insufficient data

# Timeframes
# Load all timeframes needed by strategies from MT5 (more accurate than resampling)
# M1: Base timeframe for breakout detection (15M_1M, 4H_5M) and HFT
# M5: Breakout detection (4H_5M range), ATR calculation, HFT trend filter
# M15: Reference candle (15M_1M range)
# H4: Reference candle (4H_5M range)
TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4"]

# Time Mode
# - TimeMode.MAX_SPEED: Run as fast as possible (recommended for production)
# - TimeMode.FAST: 10x speed (100ms per bar) - for faster testing
# - TimeMode.REALTIME: 1x speed (1 second per bar) - for visual debugging
TIME_MODE = TimeMode.MAX_SPEED

# Historical Data Buffer
# Load extra days before START_DATE for reference candle lookback
HISTORICAL_BUFFER_DAYS = 10

# Data Caching
# Cache historical data to disk for faster subsequent runs and offline backtesting
USE_CACHE = True  # Set to False to always download from MT5
CACHE_DIR = "data"  # Directory for cached data
FORCE_REFRESH = False  # Set to True to re-download all data even if cached


# ============================================================================
# MAIN BACKTEST EXECUTION
# ============================================================================

def load_symbols(logger) -> List[str]:
    """
    Load symbols from configuration or active.set file.
    
    Returns:
        List of symbol names to backtest
    """
    # If symbols are specified directly, use them
    if SYMBOLS is not None and len(SYMBOLS) > 0:
        logger.info(f"Using {len(SYMBOLS)} symbols from configuration")
        return SYMBOLS

    # Otherwise, load from active.set file
    logger.info("Loading symbols from active.set file...")

    # Create temporary MT5 connector for symbol loading
    connector = MT5Connector(config.mt5)
    if not connector.connect():
        logger.error("Failed to connect to MT5 for symbol loading")
        logger.info("Falling back to default symbols: EURUSD, GBPUSD")
        return ["EURUSD", "GBPUSD"]

    try:
        # Load symbols with prioritization
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
    # Initialize logger
    # PERFORMANCE: Disable console logging for faster backtests (logs still saved to files)
    # Set log_to_console=True to see real-time output (useful for debugging, but slower)
    ENABLE_CONSOLE_LOGS = False  # Set to True for debugging, False for max speed

    init_logger(log_to_file=True, log_to_console=ENABLE_CONSOLE_LOGS, log_level="INFO")
    logger = get_logger()

    # Set backtest mode IMMEDIATELY to ensure all logs go to logs/backtest/
    # Use START_DATE for log directory naming
    # Don't pass time_getter yet - it will be set later by BacktestController
    # This ensures log directory uses START_DATE, not current system time
    from src.utils.logging import set_backtest_mode
    set_backtest_mode(
        time_getter=lambda: START_DATE,  # Return START_DATE until broker is initialized
        start_time=START_DATE
    )

    from src.utils.logging import get_log_directory
    log_dir = get_log_directory()

    # Print banner (direct to console for visibility even when console logging is disabled)
    print("=" * 80)
    print("MULTI-STRATEGY TRADING BOT - BACKTESTING ENGINE")
    print("=" * 80)
    print()
    print(f"Backtest logs directory: {log_dir.absolute()}")
    print()

    # Also log to file
    logger.info("=" * 80)
    logger.info("MULTI-STRATEGY TRADING BOT - BACKTESTING ENGINE")
    logger.info("=" * 80)
    logger.info("")
    logger.info(f"Backtest logs directory: {log_dir.absolute()}")
    logger.info("")

    # Create dedicated backtest data directory
    backtest_data_dir = Path("data/backtest")
    backtest_data_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Backtest data directory: {backtest_data_dir.absolute()}")
    logger.info("  (Isolated from live trading data in data/)")
    logger.info("")

    # Display configuration
    progress_print("BACKTEST CONFIGURATION:", logger)
    progress_print(f"  Date Range:       {START_DATE.date()} to {END_DATE.date()}", logger)
    progress_print(f"  Initial Balance:  ${INITIAL_BALANCE:,.2f}", logger)
    progress_print(f"  Timeframes:       {', '.join(TIMEFRAMES)}", logger)
    progress_print(f"  Time Mode:        {TIME_MODE.value}", logger)
    progress_print(f"  Spreads:          Read from MT5 (per-symbol actual spreads)", logger)
    progress_print("", logger)

    # Validate date range
    if START_DATE >= END_DATE:
        progress_print("ERROR: START_DATE must be before END_DATE", logger)
        logger.error("START_DATE must be before END_DATE")
        return False

    # Calculate backtest duration
    duration = END_DATE - START_DATE
    progress_print(f"Backtest Duration: {duration.days} days", logger)
    progress_print("", logger)

    # Step 1: Load symbols
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

    # Step 2: Load historical data
    progress_print("=" * 80, logger)
    progress_print("STEP 2: Loading Historical Data", logger)
    progress_print("=" * 80, logger)

    # Load data starting HISTORICAL_BUFFER_DAYS before START_DATE
    # This provides historical context for reference candle lookback
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

    # Initialize data loader with caching
    logger.info(f"Data caching: {'ENABLED' if USE_CACHE else 'DISABLED'}")
    if USE_CACHE:
        logger.info(f"  Cache directory: {CACHE_DIR}")
        logger.info(f"  Force refresh: {'YES' if FORCE_REFRESH else 'NO'}")
    logger.info("")

    data_loader = BacktestDataLoader(use_cache=USE_CACHE, cache_dir=CACHE_DIR)
    symbol_data = {}  # Key: (symbol, timeframe), Value: DataFrame
    symbol_info = {}  # Key: symbol, Value: symbol_info dict
    symbols_with_all_timeframes = []  # Track symbols that have all timeframes

    for symbol in symbols:
        progress_print(f"Loading {symbol}...", logger)
        loaded_timeframes = []
        has_insufficient_data = False

        for timeframe in TIMEFRAMES:
            result = data_loader.load_from_mt5(
                symbol, timeframe, data_load_start, END_DATE,
                force_refresh=FORCE_REFRESH
            )

            if result is None:
                logger.error(f"  ✗ Failed to load {timeframe} data for {symbol}")
                has_insufficient_data = True
                break

            df, info = result

            # Validate minimum data requirements
            # For M1: expect at least 1440 bars per day (1 per minute)
            # For the date range, we should have a reasonable amount of data
            min_bars_expected = {
                'M1': duration.days * 1000,  # At least 1000 bars per day (accounting for weekends)
                'M5': duration.days * 200,  # At least 200 bars per day
                'M15': duration.days * 60,  # At least 60 bars per day
                'H4': duration.days * 5,  # At least 5 bars per day
            }

            min_required = min_bars_expected.get(timeframe, 10)
            if len(df) < min_required:
                logger.warning(
                    f"  ⚠ {symbol} {timeframe}: Only {len(df)} bars loaded "
                    f"(expected at least {min_required} for {duration.days} days)"
                )
                # Don't fail immediately, but warn - some symbols might have gaps
                if len(df) < 10:  # Absolute minimum
                    logger.error(f"  ✗ {symbol} {timeframe}: Insufficient data (< 10 bars)")
                    has_insufficient_data = True
                    break

            symbol_data[(symbol, timeframe)] = df
            loaded_timeframes.append(timeframe)

            # Store symbol info only once (same for all timeframes)
            if symbol not in symbol_info:
                symbol_info[symbol] = info

            logger.info(f"  ✓ {symbol} {timeframe}: {len(df):,} bars loaded")

        # Check if all required timeframes were loaded and data is sufficient
        if has_insufficient_data or len(loaded_timeframes) != len(TIMEFRAMES):
            if has_insufficient_data:
                logger.warning(f"  ✗ Skipping {symbol} - insufficient historical data")
            else:
                missing = set(TIMEFRAMES) - set(loaded_timeframes)
                logger.warning(f"  ✗ Skipping {symbol} - missing timeframes: {', '.join(missing)}")

            # Remove partial data for this symbol
            for tf in loaded_timeframes:
                if (symbol, tf) in symbol_data:
                    del symbol_data[(symbol, tf)]
            if symbol in symbol_info:
                del symbol_info[symbol]
        else:
            symbols_with_all_timeframes.append(symbol)
            logger.info(f"  ✓ {symbol}: All {len(TIMEFRAMES)} timeframes loaded successfully")

    # Check if we have any data
    if not symbol_data:
        logger.error("No data loaded for any symbols")
        return False

    # Update symbols list to only include symbols with all timeframes
    symbols = symbols_with_all_timeframes
    logger.info("")
    logger.info(f"Successfully loaded {len(symbols)} symbols with all {len(TIMEFRAMES)} timeframes")
    if symbols:
        logger.info(f"Symbols to backtest: {', '.join(symbols)}")
    logger.info("")

    # Step 2.5: Load currency conversion pairs for risk calculation
    progress_print("=" * 80, logger)
    progress_print("STEP 2.5: Loading Currency Conversion Pairs", logger)
    progress_print("=" * 80, logger)
    logger.info("Loading common currency pairs for accurate risk calculation...")
    logger.info("")

    # Determine which conversion pairs we need based on loaded symbols
    needed_conversions = set()
    for symbol in symbols:
        if symbol in symbol_info:
            currency_profit = symbol_info[symbol].get('currency_profit', 'USD')
            if currency_profit != 'USD' and currency_profit != 'UNKNOWN':
                # We need to convert this currency to USD
                # Try both direct (XXXUSD) and inverse (USDXXX) pairs
                direct_pair = f"{currency_profit}USD"
                inverse_pair = f"USD{currency_profit}"
                needed_conversions.add((currency_profit, direct_pair, inverse_pair))

    logger.info(f"Detected {len(needed_conversions)} unique currencies needing conversion to USD:")
    for currency, direct, inverse in sorted(needed_conversions):
        logger.info(f"  - {currency} -> USD (will try {direct} or {inverse})")
    logger.info("")

    # Load conversion pairs (only M1 is needed for price data)
    conversion_pairs_loaded = 0
    for currency, direct_pair, inverse_pair in needed_conversions:
        # Skip if already loaded as a trading symbol
        if direct_pair in symbols or inverse_pair in symbols:
            loaded_pair = direct_pair if direct_pair in symbols else inverse_pair
            logger.info(f"  ✓ {currency}USD: Already loaded as trading symbol ({loaded_pair})")
            conversion_pairs_loaded += 1
            continue

        # Try direct pair first (e.g., EURUSD, GBPUSD)
        result = data_loader.load_from_mt5(
            direct_pair, 'M1', data_load_start, END_DATE,
            force_refresh=FORCE_REFRESH
        )

        if result is not None:
            df, info = result
            if len(df) >= 10:  # Minimum data check
                symbol_data[(direct_pair, 'M1')] = df
                symbol_info[direct_pair] = info
                logger.info(f"  ✓ {currency}USD: {len(df):,} bars loaded ({direct_pair})")
                conversion_pairs_loaded += 1
                continue

        # Direct pair failed, try inverse pair (e.g., USDJPY, USDCHF)
        result = data_loader.load_from_mt5(
            inverse_pair, 'M1', data_load_start, END_DATE,
            force_refresh=FORCE_REFRESH
        )

        if result is not None:
            df, info = result
            if len(df) >= 10:  # Minimum data check
                symbol_data[(inverse_pair, 'M1')] = df
                symbol_info[inverse_pair] = info
                logger.info(f"  ✓ {currency}USD: {len(df):,} bars loaded ({inverse_pair}, will invert)")
                conversion_pairs_loaded += 1
            else:
                logger.warning(f"  ⚠ {currency}USD: Insufficient data for {inverse_pair} ({len(df)} bars)")
        else:
            logger.warning(f"  ⚠ {currency}USD: Neither {direct_pair} nor {inverse_pair} available in MT5")

    logger.info("")
    logger.info(f"Loaded {conversion_pairs_loaded}/{len(needed_conversions)} conversion pairs")
    logger.info("Note: Inverse pairs will be automatically inverted during backtest (e.g., JPY rate = 1/USDJPY)")
    logger.info("")

    # Display cache statistics
    if USE_CACHE:
        cache_stats = data_loader.get_cache_stats()
        logger.info("Cache Statistics:")
        logger.info(f"  Total symbols cached: {cache_stats.get('total_symbols', 0)}")
        logger.info(f"  Total cache files: {cache_stats.get('total_files', 0)}")
        logger.info(f"  Total cache size: {cache_stats.get('total_size_mb', 0):.2f} MB")
        logger.info("")

    # Step 3: Initialize Position Persistence (before broker)
    logger.info("=" * 80)
    logger.info("STEP 3: Initializing Position Persistence")
    logger.info("=" * 80)

    # Initialize position persistence for backtest (isolated from live trading)
    from src.execution.position_persistence import PositionPersistence
    backtest_persistence = PositionPersistence(data_dir=str(backtest_data_dir))

    # CRITICAL: Clear any stale positions from previous backtest runs
    # This prevents duplicate position errors when starting a new backtest
    backtest_persistence.clear_all()
    logger.info(f"  ✓ Position persistence initialized (using {backtest_data_dir})")
    logger.info(f"  ✓ Cleared stale positions from previous runs")
    logger.info("")

    # Step 4: Initialize SimulatedBroker (with persistence)
    logger.info("=" * 80)
    logger.info("STEP 4: Initializing Simulated Broker")
    logger.info("=" * 80)

    # Pass persistence to broker so it can remove positions when they're closed
    # This ensures backtest behavior matches live trading
    broker = SimulatedBroker(
        initial_balance=INITIAL_BALANCE,
        persistence=backtest_persistence
    )

    # Load data for trading symbols (all timeframes) and conversion pairs (M1 only)
    loaded_count = 0
    conversion_count = 0
    for (symbol, timeframe), df in symbol_data.items():
        if symbol in symbols:
            # Trading symbol - load all timeframes
            broker.load_symbol_data(symbol, df, symbol_info[symbol], timeframe)
            loaded_count += 1
        elif symbol in symbol_info and timeframe == 'M1':
            # Conversion pair - only load M1 for price data
            broker.load_symbol_data(symbol, df, symbol_info[symbol], timeframe)
            conversion_count += 1

    logger.info(f"  ✓ SimulatedBroker initialized (with position persistence)")
    logger.info(
        f"  ✓ Loaded {loaded_count} symbol-timeframe combinations ({len(symbols)} symbols x {len(TIMEFRAMES)} timeframes)")
    if conversion_count > 0:
        logger.info(f"  ✓ Loaded {conversion_count} currency conversion pairs (M1 only)")
    logger.info(f"  ✓ Initial balance: ${INITIAL_BALANCE:,.2f}")
    logger.info("")

    # Set the starting time to skip the historical buffer period
    # This allows strategies to access historical data for lookback while starting simulation at START_DATE
    logger.info(f"Setting backtest start time to {START_DATE.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    logger.info(
        f"  (Historical buffer from {data_load_start.strftime('%Y-%m-%d %H:%M:%S')} will be available for lookback)")
    broker.set_start_time(START_DATE)
    logger.info("")

    # Step 5: Initialize TimeController
    logger.info("=" * 80)
    logger.info("STEP 5: Initializing Time Controller")
    logger.info("=" * 80)

    # Include position monitor in barrier synchronization
    # Pass broker for global time advancement
    time_controller = TimeController(symbols, mode=TIME_MODE, include_position_monitor=True, broker=broker)
    logger.info(f"  ✓ TimeController initialized")
    logger.info(f"  ✓ Time mode: {TIME_MODE.value}")
    logger.info(f"  ✓ Barrier participants: {len(symbols)} symbols + 1 position monitor")
    logger.info(f"  ✓ Global time advancement: minute-by-minute")
    logger.info("")

    # Step 6: Initialize trading components
    logger.info("=" * 80)
    logger.info("STEP 6: Initializing Trading Components")
    logger.info("=" * 80)

    # RiskManager (initialize first, needed by OrderManager)
    risk_manager = RiskManager(
        connector=broker,
        risk_config=config.risk,
        persistence=backtest_persistence
    )
    logger.info("  ✓ RiskManager initialized")

    # OrderManager (with risk_manager for position limit checks)
    order_manager = OrderManager(
        connector=broker,
        magic_number=config.advanced.magic_number,
        trade_comment=config.advanced.trade_comment,
        persistence=backtest_persistence,
        risk_manager=risk_manager  # ✅ Pass risk_manager for position limit checks
    )
    logger.info("  ✓ OrderManager initialized (with position limit checks enabled)")

    # TechnicalIndicators
    indicators = TechnicalIndicators()
    logger.info("  ✓ TechnicalIndicators initialized")

    # TradeManager
    trade_manager = TradeManager(
        connector=broker,
        order_manager=order_manager,
        trailing_config=config.trailing_stop,
        use_breakeven=config.advanced.use_breakeven,
        breakeven_trigger_rr=config.advanced.breakeven_trigger_rr,
        indicators=indicators,
        range_configs=config.range_config.ranges  # ✅ Pass range configs for ATR trailing
    )
    logger.info("  ✓ TradeManager initialized (with range-specific ATR timeframes)")
    logger.info("")

    # Step 6: Initialize BacktestController
    logger.info("=" * 80)
    logger.info("STEP 6: Initializing Backtest Controller")
    logger.info("=" * 80)

    backtest_controller = BacktestController(
        simulated_broker=broker,
        time_controller=time_controller,
        order_manager=order_manager,
        risk_manager=risk_manager,
        trade_manager=trade_manager,
        indicators=indicators
    )

    # Initialize with symbols (this creates strategies based on .env configuration)
    if not backtest_controller.initialize(symbols):
        logger.error("Failed to initialize BacktestController")
        logger.error("Check your .env configuration and strategy settings")
        return False

    logger.info("  ✓ BacktestController initialized")
    logger.info("  ✓ Strategies loaded from .env configuration")
    logger.info("")

    # Step 7: Run backtest
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

    try:
        # Run the backtest
        # Pass START_DATE for log directory naming (data was loaded from earlier for lookback)
        backtest_controller.run(backtest_start_time=START_DATE)

    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("=" * 80)
        logger.warning("Backtest interrupted by user (Ctrl+C)")
        logger.warning("=" * 80)
        logger.warning("")
        logger.warning("Partial results may be available")
        logger.warning("")

        # Restore live mode before exiting
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

        # Restore live mode before exiting
        from src.utils.logging import set_live_mode
        set_live_mode()
        return False

    # Step 8: Analyze results
    progress_print("", logger)
    progress_print("=" * 80, logger)
    progress_print("STEP 8: Analyzing Results", logger)
    progress_print("=" * 80, logger)
    progress_print("", logger)

    try:
        results = backtest_controller.get_results()
        analyzer = ResultsAnalyzer()
        metrics = analyzer.analyze(results)

        # Save trades to pickle file for detailed analysis
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

    # Step 9: Display results
    progress_print("", logger)
    progress_print("=" * 80, logger)
    progress_print("BACKTEST RESULTS", logger)
    progress_print("=" * 80, logger)
    progress_print("", logger)

    # Account metrics
    progress_print("ACCOUNT PERFORMANCE:", logger)
    progress_print(f"  Initial Balance:  ${INITIAL_BALANCE:>12,.2f}", logger)
    progress_print(f"  Final Balance:    ${metrics.get('final_balance', 0):>12,.2f}", logger)
    progress_print(f"  Final Equity:     ${metrics.get('final_equity', 0):>12,.2f}", logger)
    progress_print(f"  Total Profit:     ${metrics.get('total_profit', 0):>12,.2f}", logger)
    progress_print(f"  Total Return:     {metrics.get('total_return', 0):>12.2f}%", logger)
    progress_print("", logger)

    # Risk metrics
    progress_print("RISK METRICS:", logger)
    progress_print(f"  Max Drawdown:     {metrics.get('max_drawdown', 0):>12.2f}%", logger)
    progress_print(f"  Sharpe Ratio:     {metrics.get('sharpe_ratio', 0):>12.2f}", logger)

    # Format profit factor
    pf = metrics.get('profit_factor', 0)
    pf_display = f"{pf:.2f}" if pf != float('inf') else "∞"
    progress_print(f"  Profit Factor:    {pf_display:>12}", logger)
    progress_print("", logger)

    # Trade statistics
    progress_print("TRADE STATISTICS:", logger)
    progress_print(f"  Total Trades:     {metrics.get('total_trades', 0):>12}", logger)
    progress_print(f"  Winning Trades:   {metrics.get('winning_trades', 0):>12} ({metrics.get('win_rate', 0):.1f}%)",
                   logger)
    progress_print(
        f"  Losing Trades:    {metrics.get('losing_trades', 0):>12} ({100 - metrics.get('win_rate', 0):.1f}%)", logger)
    progress_print(f"  Win/Loss Ratio:   {metrics.get('winning_trades', 0):>5} / {metrics.get('losing_trades', 0):<5}",
                   logger)
    progress_print("", logger)

    # Additional metrics
    if metrics.get('total_trades', 0) > 0:
        progress_print("TRADE DETAILS:", logger)
        progress_print(f"  Avg Win:          ${metrics.get('avg_win', 0):>12,.2f}", logger)
        progress_print(f"  Avg Loss:         ${metrics.get('avg_loss', 0):>12,.2f}", logger)
        progress_print(f"  Largest Win:      ${metrics.get('largest_win', 0):>12,.2f}", logger)
        progress_print(f"  Largest Loss:     ${metrics.get('largest_loss', 0):>12,.2f}", logger)
        progress_print(f"  Max Consecutive Wins:   {metrics.get('max_consecutive_wins', 0):>6}", logger)
        progress_print(f"  Max Consecutive Losses: {metrics.get('max_consecutive_losses', 0):>6}", logger)
        progress_print("", logger)

    # Per-symbol breakdown
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

    # Per-strategy breakdown
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

    # Final summary
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

    # Restore live mode now that all backtest logging is complete
    from src.utils.logging import set_live_mode
    set_live_mode()

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
