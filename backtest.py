"""Backtesting entry point for Ougha Multi Strategy Trading Bot.

This script mirrors main.py but runs the strategies against historical tick
 data using the backtesting framework.

Usage:
    python backtest.py
"""

import os
import sys
import signal
from datetime import datetime
from pathlib import Path
from typing import List

from src.config import config
from src.backtesting.engine import BacktestEngine, BacktestConfig
from src.backtesting.adapters import (
    FakeoutStrategyAdapter,
    TrueBreakoutStrategyAdapter,
    HFTMomentumStrategyAdapter,
)
from src.utils.logger import init_logger


class BacktestBot:
    """Main controller for running backtests.

    Structure intentionally mirrors TradingBot in main.py: initialization,
    configuration logging, strategy setup, execution, and result reporting.
    """

    def __init__(self) -> None:
        # Initialize logger using same settings as live bot
        self.logger = init_logger(
            log_to_file=config.logging.log_to_file,
            log_to_console=config.logging.log_to_console,
            log_level=config.logging.log_level,
            enable_detailed=config.logging.enable_detailed_logging,
        )

        self.logger.header("Ougha Multi Strategy Trading Bot - Backtesting")
        self.logger.info("Initializing backtesting system...")

        # Validate configuration (symbols are not required for backtest)
        try:
            config.validate(check_symbols=False)
            self.logger.info("Configuration validated successfully")
        except ValueError as e:
            self.logger.error(f"Configuration error: {e}")
            sys.exit(1)

        self.is_running = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame) -> None:  # pragma: no cover - signal handler
        self.logger.warning("Shutdown signal received")
        self.is_running = False

    def start(self) -> bool:
        """Run backtests for all enabled strategies."""
        self.logger.info("Starting backtest run...")

        project_root = Path(__file__).parent
        data_dir = project_root / "data" / "backtest"

        # Look for any tick data file (supports both *_tick.npz and *_ticks.npz)
        tick_files: List[Path] = list(data_dir.glob("*tick*.npz"))
        if not tick_files:
            self.logger.error("No tick data files found in data/backtest")
            self.logger.info("Run: python examples/export_sample_data.py")
            return False

        data_files = [str(p) for p in tick_files]
        symbol = "EURUSD"  # Matches export_sample_data.py and examples/test_backtest.py

        # Backtest configuration (can be tuned or parameterized later)
        bt_config = BacktestConfig(
            tick_size=0.00001,
            lot_size=0.01,
            contract_size=100000,
            maker_fee=0.0,
            taker_fee=0.0,
            order_latency=0,
            response_latency=0,
            queue_model="risk_adverse",
            partial_fill=False,
            recorder_capacity=100000,
        )

        engine = BacktestEngine(symbol=symbol, data_files=data_files, config=bt_config)

        # Strategy setup (mirrors enabled strategies in live config)
        adapters = []
        rr = config.strategy.risk_reward_ratio

        if config.strategy_enable.fakeout_enabled:
            fakeout_params = {
                "min_consolidation_bars": 10,
                "breakout_threshold": 0.0005,
                "fakeout_reversal_threshold": 0.0003,
                "max_spread_percent": 0.001,
                "risk_reward_ratio": rr,
            }
            adapters.append(FakeoutStrategyAdapter(symbol=symbol, strategy_params=fakeout_params))

        if config.strategy_enable.true_breakout_enabled:
            breakout_params = {
                "min_consolidation_bars": 15,
                "breakout_threshold": 0.0008,
                "min_breakout_volume_multiplier": 1.5,
                "retest_tolerance_percent": 0.0005,
                "max_spread_percent": 0.001,
                "risk_reward_ratio": rr,
            }
            adapters.append(TrueBreakoutStrategyAdapter(symbol=symbol, strategy_params=breakout_params))

        # For backtesting we always include the HFT momentum strategy with
        # aggressively permissive parameters so that at least one strategy
        # typically produces trades on sample data. This does not affect
        # the live trading configuration.
        hft_rr = config.hft_momentum.risk_reward_ratio
        hft_params = {
            "tick_momentum_count": 2,
            "min_momentum_strength": 0.0,
            "min_volume_multiplier": 0.5,
            "max_spread_multiplier": 5.0,
            "max_spread_percent": 0.01,
            "risk_reward_ratio": hft_rr,
            "sl_pips": 5,
            "trade_cooldown_seconds": 1,
            "disable_validation": True,

        }
        adapters.append(HFTMomentumStrategyAdapter(symbol=symbol, strategy_params=hft_params))

        if not adapters:
            self.logger.error("No strategies enabled for backtesting.")
            self.logger.info("Enable TRUE_BREAKOUT_ENABLED/FAKEOUT_ENABLED/HFT_MOMENTUM_ENABLED in .env")
            return False

        for adapter in adapters:
            engine.add_strategy(adapter)

        initial_balance = float(os.getenv("BACKTEST_INITIAL_BALANCE", "10000"))

        self._log_configuration(symbol, data_files, initial_balance, len(adapters))

        try:
            self.is_running = True
            engine.run(initial_balance=initial_balance)
        except Exception as e:  # pragma: no cover - runtime protection
            self.logger.error(f"Error during backtest: {e}", exc_info=True)
            self.is_running = False
            return False

        self.is_running = False
        self._display_results(engine, adapters, initial_balance)
        self.logger.info("Backtest run completed.")
        return True

    def _log_configuration(self, symbol: str, data_files: List[str], initial_balance: float, n_strategies: int) -> None:
        self.logger.info("=== Backtest Configuration ===")
        self.logger.info(f"Symbol: {symbol}")
        self.logger.info(f"Data files: {len(data_files)}")
        self.logger.info(f"Initial balance: ${initial_balance:.2f}")
        self.logger.info(f"Risk per trade: {config.risk.risk_percent_per_trade}%")
        self.logger.info(f"Risk/Reward Ratio: 1:{config.strategy.risk_reward_ratio}")
        self.logger.info(f"Strategies enabled: {n_strategies}")
        self.logger.separator()

    def _display_results(self, engine: BacktestEngine, adapters: List, initial_balance: float) -> None:
        """Print PnL, trade statistics, and equity curve for each strategy."""
        contract_size = engine.config.contract_size
        self.logger.info("=== Backtest Results ===")

        for adapter in adapters:
            stats = adapter.get_statistics()
            closed = list(adapter.closed_positions)
            trades = []
            for pos in closed:
                if isinstance(pos, dict):
                    pnl_raw = pos.get("pnl", 0.0) or 0.0
                    exit_time = pos.get("exit_time")
                else:
                    pnl_raw = getattr(pos, "pnl", 0.0) or 0.0
                    exit_time = getattr(pos, "exit_time", None)
                if exit_time is None:
                    continue
                trades.append((exit_time, pnl_raw))

            trades.sort(key=lambda t: t[0])

            equity = initial_balance
            max_equity = initial_balance
            equity_curve = []
            total_pnl = 0.0
            max_drawdown = 0.0

            for ts, pnl_raw in trades:
                pnl = pnl_raw * contract_size
                total_pnl += pnl
                equity += pnl
                dt = datetime.fromtimestamp(ts / 1_000_000_000)
                equity_curve.append((dt, equity))
                if equity > max_equity:
                    max_equity = equity
                dd = max_equity - equity
                if dd > max_drawdown:
                    max_drawdown = dd

            self.logger.info("")
            self.logger.info(f"Strategy: {adapter.strategy_name}")
            self.logger.info(f"  Total trades: {stats['total_trades']}")
            self.logger.info(f"  Win rate: {stats['win_rate']:.2%}")
            self.logger.info(f"  Active positions: {stats['active_positions']}")
            self.logger.info(f"  Total PnL: ${total_pnl:.2f}")
            self.logger.info(f"  Max drawdown: ${max_drawdown:.2f}")
            if equity_curve:
                start_dt, start_eq = equity_curve[0]
                end_dt, end_eq = equity_curve[-1]
                self.logger.info("  Equity curve:")
                self.logger.info(f"    Start: {start_dt} -> ${start_eq:.2f}")
                self.logger.info(f"    End:   {end_dt} -> ${end_eq:.2f}")
                self.logger.info(f"    Points: {len(equity_curve)}")
            else:
                self.logger.info("  Equity curve: no closed trades (flat curve)")

        self.logger.separator()


def main() -> None:
    """Main entry point for backtesting."""
    print(
        """
    ╔════════════════════════════════════════════════════════════╗
    ║                                                            ║
    ║              Ougha Multi Strategy - Backtesting            ║
    ║                                                            ║
    ╚════════════════════════════════════════════════════════════╝
    """
    )

    bot = BacktestBot()
    bot.start()


if __name__ == "__main__":
    main()

