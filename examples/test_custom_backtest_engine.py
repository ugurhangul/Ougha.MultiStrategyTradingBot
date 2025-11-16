"""
Test Custom Backtesting Engine.

Demonstrates the custom multi-symbol, multi-strategy concurrent backtesting engine.
"""
from datetime import datetime, timezone, timedelta
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting.engine import SimulatedBroker, TimeController, TimeMode, BacktestController
from src.backtesting.engine.data_loader import BacktestDataLoader
from src.backtesting.engine.results_analyzer import ResultsAnalyzer
from src.execution.order_manager import OrderManager
from src.risk.risk_manager import RiskManager
from src.execution.trade_manager import TradeManager
from src.indicators.technical_indicators import TechnicalIndicators
from src.config import config
from src.utils.logger import get_logger


def main():
    """Run a simple backtest."""
    logger = get_logger()
    
    logger.info("=" * 80)
    logger.info("Custom Backtesting Engine - Test Run")
    logger.info("=" * 80)
    
    # Configuration
    symbols = ["EURUSD", "GBPUSD"]
    timeframe = "M1"  # 1-minute bars (finest granularity for 15M_1M and 4H_5M ranges)
    # Use a recent period with available data (last 7 days)
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=7)
    initial_balance = 10000.0

    logger.info(f"Symbols: {', '.join(symbols)}")
    logger.info(f"Timeframe: {timeframe}")
    logger.info(f"Period: {start_date.date()} to {end_date.date()}")
    logger.info(f"Initial Balance: ${initial_balance:,.2f}")
    logger.info("")
    logger.info("IMPORTANT: Using M1 (1-minute) data for accurate strategy execution")
    logger.info("  - 15M_1M range: Builds 15-minute reference candles from M1 bars")
    logger.info("  - 4H_5M range: Builds 4-hour reference candles from M1 bars")
    logger.info("  - Execution: Happens at 1-minute granularity (most accurate)")
    logger.info("=" * 80)
    
    # Step 1: Load historical data
    logger.info("Step 1: Loading historical data...")
    data_loader = BacktestDataLoader()

    # Load data starting 1 day before start_date to provide historical context
    # for reference candle lookback (strategies need past reference candles)
    data_load_start = start_date - timedelta(days=1)
    logger.info(f"Loading data from {data_load_start.date()} (1 day before start) to {end_date.date()}")
    logger.info(f"Backtest will execute from {start_date.date()} to {end_date.date()}")

    symbol_data = {}
    symbol_info = {}

    for symbol in symbols:
        result = data_loader.load_from_mt5(symbol, timeframe, data_load_start, end_date)
        if result is None:
            logger.error(f"Failed to load data for {symbol}")
            return

        df, info = result
        symbol_data[symbol] = df
        symbol_info[symbol] = info
        logger.info(f"  ✓ {symbol}: {len(df)} bars loaded")
    
    # Step 2: Initialize SimulatedBroker
    logger.info("\nStep 2: Initializing SimulatedBroker...")
    broker = SimulatedBroker(initial_balance=initial_balance, spread_points=10.0)
    
    for symbol in symbols:
        broker.load_symbol_data(symbol, symbol_data[symbol], symbol_info[symbol])
    
    logger.info(f"  ✓ SimulatedBroker initialized with {len(symbols)} symbols")
    
    # Step 3: Initialize TimeController
    logger.info("\nStep 3: Initializing TimeController...")
    time_controller = TimeController(symbols, mode=TimeMode.MAX_SPEED)
    logger.info(f"  ✓ TimeController initialized in {TimeMode.MAX_SPEED.value} mode")
    
    # Step 4: Initialize trading components
    logger.info("\nStep 4: Initializing trading components...")
    
    # OrderManager
    order_manager = OrderManager(
        connector=broker,
        magic_number=config.advanced.magic_number,
        trade_comment=config.advanced.trade_comment
    )
    
    # RiskManager
    risk_manager = RiskManager(
        connector=broker,
        risk_config=config.risk
    )
    
    # TechnicalIndicators
    indicators = TechnicalIndicators()
    
    # TradeManager
    trade_manager = TradeManager(
        connector=broker,
        order_manager=order_manager,
        trailing_config=config.trailing_stop,
        use_breakeven=config.advanced.use_breakeven,
        breakeven_trigger_rr=config.advanced.breakeven_trigger_rr,
        indicators=indicators
    )
    
    logger.info("  ✓ Trading components initialized")
    
    # Step 5: Initialize BacktestController
    logger.info("\nStep 5: Initializing BacktestController...")
    backtest_controller = BacktestController(
        simulated_broker=broker,
        time_controller=time_controller,
        order_manager=order_manager,
        risk_manager=risk_manager,
        trade_manager=trade_manager,
        indicators=indicators
    )
    
    # Initialize with symbols (this creates strategies)
    if not backtest_controller.initialize(symbols):
        logger.error("Failed to initialize BacktestController")
        return
    
    logger.info("  ✓ BacktestController initialized")
    
    # Step 6: Run backtest
    logger.info("\n" + "=" * 80)
    logger.info("Step 6: Running backtest...")
    logger.info("=" * 80)

    # Pass the original start_date for log directory naming
    # (data was loaded from 1 day before for reference candle lookback)
    backtest_controller.run(backtest_start_time=start_date)
    
    # Step 7: Analyze results
    logger.info("\n" + "=" * 80)
    logger.info("Step 7: Analyzing results...")
    logger.info("=" * 80)
    
    results = backtest_controller.get_results()
    analyzer = ResultsAnalyzer()
    metrics = analyzer.analyze(results)
    
    # Print results
    logger.info("\n" + "=" * 80)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 80)
    logger.info(f"Final Balance:    ${metrics.get('final_balance', 0):,.2f}")
    logger.info(f"Final Equity:     ${metrics.get('final_equity', 0):,.2f}")
    logger.info(f"Total Profit:     ${metrics.get('total_profit', 0):,.2f}")
    logger.info(f"Total Return:     {metrics.get('total_return', 0):.2f}%")
    logger.info(f"Max Drawdown:     {metrics.get('max_drawdown', 0):.2f}%")
    logger.info(f"Sharpe Ratio:     {metrics.get('sharpe_ratio', 0):.2f}")
    logger.info(f"Total Trades:     {metrics.get('total_trades', 0)}")
    logger.info(f"Winning Trades:   {metrics.get('winning_trades', 0)}")
    logger.info(f"Losing Trades:    {metrics.get('losing_trades', 0)}")
    logger.info(f"Win Rate:         {metrics.get('win_rate', 0):.2f}%")
    logger.info(f"Profit Factor:    {metrics.get('profit_factor', 0):.2f}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()

