"""
Backtest Engine for Multi-Strategy Trading Bot.

This module provides the core backtesting engine that:
- Loads historical data from .npz files
- Runs multiple strategy adapters
- Simulates order execution with realistic latency and slippage
- Collects performance metrics
- Generates backtest reports

Uses hftbacktest library for high-performance backtesting.
"""

from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from datetime import datetime
import numpy as np

from hftbacktest import (
    BacktestAsset,
    HashMapMarketDepthBacktest,
    ROIVectorMarketDepthBacktest,
    Recorder,
    LIMIT,
    GTC,
    BUY,
    SELL
)
import hftbacktest.types as hbt_types


from src.backtesting.adapters import BaseStrategyAdapter
from src.utils.logger import get_logger


class BacktestConfig:
    """Configuration for backtest execution."""

    def __init__(
        self,
        # Asset configuration
        tick_size: float = 0.00001,  # For forex (5 decimal places)
        lot_size: float = 0.01,      # Minimum lot size
        contract_size: float = 100000.0,  # Standard lot size for forex

        # Latency configuration (in nanoseconds)
        order_latency: int = 100_000_000,  # 100ms order entry latency
        response_latency: int = 100_000_000,  # 100ms response latency

        # Fee configuration
        maker_fee: float = 0.0,      # No maker fee for forex
        taker_fee: float = 0.0,      # No taker fee for forex
        spread_cost: float = 0.0001,  # Typical spread cost (1 pip for EUR/USD)

        # Queue model
        queue_model: str = "risk_adverse",  # or "power_prob"

        # Exchange model
        partial_fill: bool = False,  # No partial fills for simplicity

        # Recorder capacity
        recorder_capacity: int = 10_000_000,  # 10M records
    ):
        """
        Initialize backtest configuration.

        Args:
            tick_size: Minimum price increment
            lot_size: Minimum trading quantity
            contract_size: Value per lot
            order_latency: Order entry latency in nanoseconds
            response_latency: Order response latency in nanoseconds
            maker_fee: Maker fee (negative for rebate)
            taker_fee: Taker fee
            spread_cost: Typical spread cost
            queue_model: Queue position model type
            partial_fill: Whether to allow partial fills
            recorder_capacity: Capacity for recording trades
        """
        self.tick_size = tick_size
        self.lot_size = lot_size
        self.contract_size = contract_size
        self.order_latency = order_latency
        self.response_latency = response_latency
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.spread_cost = spread_cost
        self.queue_model = queue_model
        self.partial_fill = partial_fill
        self.recorder_capacity = recorder_capacity


class BacktestEngine:
    """
    Multi-strategy backtest engine using hftbacktest.

    This engine:
    - Manages multiple strategy adapters
    - Feeds historical data to strategies
    - Simulates realistic order execution
    - Tracks performance metrics
    - Generates comprehensive reports
    """

    def __init__(
        self,
        symbol: str,
        data_files: List[str],
        config: Optional[BacktestConfig] = None,
        initial_snapshot: Optional[str] = None
    ):
        """
        Initialize backtest engine.

        Args:
            symbol: Trading symbol
            data_files: List of .npz data file paths
            config: Backtest configuration
            initial_snapshot: Optional initial market snapshot file
        """
        self.symbol = symbol
        self.data_files = data_files
        self.config = config or BacktestConfig()
        self.initial_snapshot = initial_snapshot
        self.logger = get_logger()

        # Strategy adapters
        self.adapters: List[BaseStrategyAdapter] = []

        # Backtest instance
        self.hbt = None
        self.recorder = None

        # Results
        self.results: Dict[str, Any] = {}

    def add_strategy(self, adapter: BaseStrategyAdapter) -> None:
        """
        Add a strategy adapter to the backtest.

        Args:
            adapter: Strategy adapter instance
        """
        self.adapters.append(adapter)
        self.logger.info(
            f"Added strategy adapter: {adapter.strategy_name} for {adapter.symbol}"
        )

    def _build_initial_snapshot(self) -> Optional[np.ndarray]:
        """Build an initial depth snapshot from the first data file.

        hftbacktest requires an initial depth snapshot to populate the order
        book before processing incremental depth updates. If an explicit
        ``initial_snapshot`` was provided when constructing the engine, this
        helper is not used.

        Returns
        -------
        Optional[np.ndarray]
            Two-row ``event_dtype`` array (bid and ask snapshot) or ``None``
            if the snapshot cannot be constructed.
        """
        try:
            if not self.data_files:
                self.logger.warning(
                    "No data files provided; cannot build initial snapshot."
                )
                return None

            first_file = self.data_files[0]
            npz = np.load(first_file)
            if "data" not in npz:
                self.logger.warning(
                    "File %s is missing 'data' array; cannot build initial snapshot.",
                    first_file,
                )
                return None

            arr = npz["data"]
            if arr.size == 0:
                self.logger.warning(
                    "File %s contains no events; cannot build initial snapshot.",
                    first_file,
                )
                return None

            ev = arr["ev"]
            px = arr["px"]
            qty = arr["qty"]
            exch_ts = arr["exch_ts"]
            local_ts = arr["local_ts"]

            is_bid = (ev & hbt_types.BUY_EVENT) != 0
            is_ask = (ev & hbt_types.SELL_EVENT) != 0

            if not np.any(is_bid) or not np.any(is_ask):
                self.logger.warning(
                    "Could not find both bid and ask events in %s to build snapshot.",
                    first_file,
                )
                return None

            bid_idx = int(np.argmax(is_bid))
            ask_idx = int(np.argmax(is_ask))

            ts = int(min(exch_ts[bid_idx], exch_ts[ask_idx]))
            ts_local = int(min(local_ts[bid_idx], local_ts[ask_idx]))

            snapshot = np.zeros(2, dtype=hbt_types.event_dtype)

            snapshot[0]["ev"] = (
                hbt_types.DEPTH_SNAPSHOT_EVENT
                | hbt_types.EXCH_EVENT
                | hbt_types.BUY_EVENT
            )
            snapshot[0]["exch_ts"] = ts
            snapshot[0]["local_ts"] = ts_local
            snapshot[0]["px"] = float(px[bid_idx])
            snapshot[0]["qty"] = float(qty[bid_idx])

            snapshot[1]["ev"] = (
                hbt_types.DEPTH_SNAPSHOT_EVENT
                | hbt_types.EXCH_EVENT
                | hbt_types.SELL_EVENT
            )
            snapshot[1]["exch_ts"] = ts
            snapshot[1]["local_ts"] = ts_local
            snapshot[1]["px"] = float(px[ask_idx])
            snapshot[1]["qty"] = float(qty[ask_idx])

            self.logger.info(
                "Initial snapshot built from %s: bid=%.5f ask=%.5f",
                first_file,
                snapshot[0]["px"],
                snapshot[1]["px"],
            )

            return snapshot
        except Exception as e:  # pragma: no cover - defensive
            self.logger.error(f"Failed to build initial snapshot: {e}")
            return None


    def _create_asset(self) -> BacktestAsset:
        """
        Create BacktestAsset configuration.

        Returns:
            Configured BacktestAsset
        """
        asset = BacktestAsset()

        # Set data files
        asset = asset.data(self.data_files)

        # Set initial snapshot: explicit value takes precedence, otherwise
        # build one from the first data file so that hftbacktest's depth book
        # is properly initialized.
        snapshot = None
        if self.initial_snapshot is not None:
            snapshot = self.initial_snapshot
        else:
            snapshot = self._build_initial_snapshot()

        if snapshot is not None:
            asset = asset.initial_snapshot(snapshot)

        # Set asset type (linear for forex)
        asset = asset.linear_asset(self.config.contract_size)

        # Set latency model
        asset = asset.constant_latency(
            self.config.order_latency,
            self.config.response_latency
        )

        # Set queue model
        if self.config.queue_model == "risk_adverse":
            asset = asset.risk_adverse_queue_model()
        elif self.config.queue_model == "power_prob":
            asset = asset.power_prob_queue_model(3.0)  # Default power parameter

        # Set exchange model
        if self.config.partial_fill:
            asset = asset.partial_fill_exchange()
        else:
            asset = asset.no_partial_fill_exchange()

        # Set fee model
        asset = asset.trading_value_fee_model(
            self.config.maker_fee,
            self.config.taker_fee
        )

        # Set tick and lot sizes
        asset = asset.tick_size(self.config.tick_size)
        asset = asset.lot_size(self.config.lot_size)

        return asset

    def run(
        self,
        initial_balance: float = 10000.0,
        use_roi_vector: bool = True
    ) -> Dict[str, Any]:
        """
        Run the backtest.

        Args:
            initial_balance: Starting account balance
            use_roi_vector: Use ROIVectorMarketDepthBacktest (faster) vs HashMap

        Returns:
            Dictionary containing backtest results
        """
        self.logger.info(f"Starting backtest for {self.symbol}")
        self.logger.info(f"Data files: {len(self.data_files)}")
        self.logger.info(f"Strategies: {len(self.adapters)}")

        # Create asset
        asset = self._create_asset()

        # Create backtest instance
        if use_roi_vector:
            self.hbt = ROIVectorMarketDepthBacktest([asset])
            self.logger.info("Using ROIVectorMarketDepthBacktest")
        else:
            self.hbt = HashMapMarketDepthBacktest([asset])
            self.logger.info("Using HashMapMarketDepthBacktest")

        # Initialize recorder (1 asset, configurable record size)
        self.recorder = Recorder(1, self.config.recorder_capacity)

        # Initialize all strategy adapters
        for adapter in self.adapters:
            adapter.initialize(self.hbt, 0)  # Asset index 0

        # Run backtest loop
        try:
            self._run_backtest_loop()
        except Exception as e:
            # Log the error and re-raise so callers can handle it
            self.logger.error(f"Backtest error: {e}")
            raise
        finally:
            # Close backtest
            if self.hbt:
                self.hbt.close()

        # Compile results
        self.results = self._compile_results()

        self.logger.info("Backtest completed successfully")
        return self.results

    def _run_backtest_loop(self) -> None:
        """
        Main backtest loop - processes tick data and executes strategies.
        """
        tick_count = 0

        # Elapse time in small increments (e.g., 1 second = 1e9 nanoseconds)
        time_increment = 1_000_000_000  # 1 second

        while self.hbt.elapse(time_increment) == 0:
            tick_count += 1

            # Get current market depth
            depth = self.hbt.depth(0)

            # Get current timestamp
            current_time = self.hbt.current_timestamp

            # Process tick for each strategy adapter
            for adapter in self.adapters:
                try:
                    # Call adapter's on_tick method
                    adapter.on_tick(
                        timestamp=current_time,
                        bid=depth.best_bid,
                        ask=depth.best_ask,
                        bid_qty=depth.bid_qty_at_tick(depth.best_bid_tick),
                        ask_qty=depth.ask_qty_at_tick(depth.best_ask_tick)
                    )
                except Exception as e:
                    # Log adapter errors but continue the backtest loop
                    self.logger.error(
                        f"Error in {adapter.strategy_name}.on_tick: {e}"
                    )

            # Record state periodically (every 60 seconds)
            if tick_count % 60 == 0 and self.recorder is not None:
                # Use the underlying numba-jitted recorder to capture state
                self.recorder.recorder.record(self.hbt)

            # Log progress periodically
            if tick_count % 3600 == 0:  # Every hour
                self.logger.info(
                    f"Processed {tick_count} ticks, "
                    f"timestamp: {datetime.fromtimestamp(current_time / 1e9)}"
                )

        self.logger.info(f"Backtest loop completed. Total ticks: {tick_count}")

    def _compile_results(self) -> Dict[str, Any]:
        """
        Compile backtest results from all strategies.

        Returns:
            Dictionary containing comprehensive results
        """
        results = {
            'symbol': self.symbol,
            'config': {
                'tick_size': self.config.tick_size,
                'lot_size': self.config.lot_size,
                'order_latency_ms': self.config.order_latency / 1_000_000,
                'response_latency_ms': self.config.response_latency / 1_000_000,
                'maker_fee': self.config.maker_fee,
                'taker_fee': self.config.taker_fee,
            },
            'strategies': {}
        }

        # Collect results from each strategy adapter
        for adapter in self.adapters:
            stats = adapter.get_statistics()

            trades = []
            for pos in adapter.closed_positions:
                if isinstance(pos, dict):
                    trades.append(
                        {
                            'entry_time': pos.get('entry_time'),
                            'exit_time': pos.get('exit_time'),
                            'side': pos.get('side'),
                            'entry_price': pos.get('entry_price'),
                            'exit_price': pos.get('exit_price'),
                            'quantity': pos.get('quantity'),
                            'pnl': pos.get('pnl'),
                        }
                    )
                else:
                    trades.append(
                        {
                            'entry_time': getattr(pos, 'entry_time', None),
                            'exit_time': getattr(pos, 'exit_time', None),
                            'side': 'BUY' if pos.side == BUY else 'SELL',
                            'entry_price': getattr(pos, 'entry_price', None),
                            'exit_price': getattr(pos, 'exit_price', None),
                            'quantity': getattr(pos, 'quantity', None),
                            'pnl': getattr(pos, 'pnl', None),
                        }
                    )

            results['strategies'][adapter.strategy_name] = {
                'total_trades': stats['total_trades'],
                'winning_trades': stats['winning_trades'],
                'losing_trades': stats['losing_trades'],
                'win_rate': stats['win_rate'],
                'active_positions': stats['active_positions'],
                'closed_positions': len(adapter.closed_positions),
                'trades': trades,
            }

        # Add recorder data if available
        if self.recorder:
            try:
                # Get equity curve and other metrics from recorder
                # Note: This requires hftbacktest's Recorder API
                results['equity_curve'] = self._extract_equity_curve()
            except Exception as e:
                self.logger.warning(f"Could not extract equity curve: {e}")

        return results

    def _extract_equity_curve(self) -> List[Dict[str, float]]:
        """
        Extract equity curve from recorder.

        Returns:
            List of equity snapshots
        """
        # This is a placeholder - actual implementation depends on
        # hftbacktest's Recorder API
        equity_curve = []

        # TODO: Implement equity curve extraction from recorder
        # The recorder stores snapshots of account state over time

        return equity_curve

    def get_summary(self) -> str:
        """
        Get a human-readable summary of backtest results.

        Returns:
            Formatted summary string
        """
        if not self.results:
            return "No results available. Run backtest first."

        summary = []
        summary.append(f"\n{'='*60}")
        summary.append(f"Backtest Summary: {self.symbol}")
        summary.append(f"{'='*60}\n")

        for strategy_name, stats in self.results['strategies'].items():
            summary.append(f"Strategy: {strategy_name}")
            summary.append(f"  Total Trades: {stats['total_trades']}")
            summary.append(f"  Winning Trades: {stats['winning_trades']}")
            summary.append(f"  Losing Trades: {stats['losing_trades']}")
            summary.append(f"  Win Rate: {stats['win_rate']:.2%}")
            summary.append(f"  Active Positions: {stats['active_positions']}")
            summary.append("")

        summary.append(f"{'='*60}\n")

        return "\n".join(summary)

