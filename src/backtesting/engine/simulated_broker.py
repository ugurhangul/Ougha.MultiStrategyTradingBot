"""
Simulated Broker for Backtesting.

Replaces MT5Connector with historical data replay and simulated order execution.
Maintains the same interface as MT5Connector so strategies can run unchanged.
"""
from typing import List, Optional, Dict, Tuple, Set
from datetime import datetime, timezone
from dataclasses import dataclass
import threading
import pandas as pd
import numpy as np

from src.models.data_models import CandleData, PositionInfo, PositionType
from src.utils.logger import get_logger
from src.backtesting.engine.candle_builder import MultiTimeframeCandleBuilder


class MockSymbolInfoCache:
    """
    Mock symbol info cache for backtesting.

    In backtest mode, we don't need to cache symbol info from MT5,
    but we need to provide the same interface as SymbolInfoCache
    for compatibility with TradingController.
    """

    def get_cache_age(self, symbol: str) -> Optional[float]:
        """
        Get age of cache entry in seconds.

        In backtest mode, we always return None to indicate no cache,
        which will cause the code to fetch fresh symbol info.

        Args:
            symbol: Symbol name

        Returns:
            None (no cache in backtest mode)
        """
        return None


@dataclass
class SimulatedSymbolInfo:
    """Simulated symbol information matching MT5 symbol_info structure."""
    point: float
    digits: int
    tick_value: float
    tick_size: float
    min_lot: float
    max_lot: float
    lot_step: float
    contract_size: float
    filling_mode: int
    stops_level: int
    freeze_level: int
    trade_mode: int
    currency_base: str
    currency_profit: str
    currency_margin: str
    category: str


@dataclass
class SimulatedTick:
    """Simulated tick data."""
    time: datetime
    bid: float
    ask: float
    last: float
    volume: int


@dataclass
class GlobalTick:
    """
    Single tick in the global tick timeline.

    Used for tick-by-tick backtesting where all ticks from all symbols
    are merged into a single chronologically-sorted timeline.
    """
    time: datetime
    symbol: str
    bid: float
    ask: float
    last: float
    volume: int

    @property
    def spread(self) -> float:
        """Calculate spread from bid/ask."""
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        """Calculate mid price."""
        return (self.bid + self.ask) / 2.0


@dataclass
class TickData:
    """
    Tick data for a specific symbol at a specific time.

    Used to store the current tick for each symbol during backtesting.
    """
    time: datetime
    bid: float
    ask: float
    last: float
    volume: int
    spread: float

    @property
    def mid(self) -> float:
        """Calculate mid price."""
        return (self.bid + self.ask) / 2.0


@dataclass
class OrderResult:
    """Result of order execution."""
    success: bool
    order: Optional[int]  # Ticket number
    price: Optional[float]  # Execution price
    retcode: int
    comment: str


class SimulatedBroker:
    """
    Simulated broker that replaces MT5Connector for backtesting.
    
    Maintains the same interface as MT5Connector so existing strategies
    can run without modification.
    """
    
    def __init__(self, initial_balance: float = 10000.0, spread_points: float = 10.0,
                 persistence=None, enable_slippage: bool = True, slippage_points: float = 0.5,
                 leverage: float = 100.0):
        """
        Initialize simulated broker.

        Args:
            initial_balance: Starting account balance
            spread_points: Default spread in points (used as fallback if symbol has no spread info)
            persistence: Optional PositionPersistence instance for tracking positions
            enable_slippage: Whether to simulate slippage on order execution (default: True)
            slippage_points: Base slippage in points for normal market conditions (default: 0.5)
            leverage: Leverage ratio (e.g., 100.0 for 100:1 leverage, default: 100.0)
        """
        self.logger = get_logger()

        # Marker to identify this as a simulated broker (for backtest mode detection)
        self.is_simulated = True

        # Mock symbol cache for compatibility with TradingController
        self.symbol_cache = MockSymbolInfoCache()

        # Account state
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        self.currency = "USD"

        # Spread simulation (default fallback, actual spreads come from symbol_info)
        self.default_spread_points = spread_points

        # Per-symbol spread tracking (loaded from MT5 symbol_info)
        self.symbol_spreads: Dict[str, float] = {}

        # Slippage simulation
        self.enable_slippage = enable_slippage
        self.base_slippage_points = slippage_points  # Base slippage for normal conditions

        # Leverage (for margin calculation)
        self.leverage = leverage

        # PERFORMANCE OPTIMIZATION: Progress printing throttle
        self.last_progress_print_time = None
        self.progress_print_interval_seconds = 1.0  # Print every 1 second of simulated time
        self.progress_print_tick_interval = 100  # Also print every N ticks as fallback

        # Position persistence (optional, for synchronization with live trading behavior)
        self.persistence = persistence

        # Position tracking
        self.positions: Dict[int, PositionInfo] = {}  # ticket -> PositionInfo
        self.next_ticket = 1
        self.position_lock = threading.Lock()

        # Historical data for each symbol and timeframe
        # Key: (symbol, timeframe), Value: DataFrame with OHLC
        self.symbol_data: Dict[Tuple[str, str], pd.DataFrame] = {}

        # Current indices for each symbol (based on M1 timeframe)
        self.current_indices: Dict[str, int] = {}  # symbol -> current bar index

        # Symbol information
        self.symbol_info: Dict[str, SimulatedSymbolInfo] = {}

        # OPTIMIZATION #1: Pre-computed timestamp arrays for fast access
        # These are populated during load_symbol_data() and are read-only during backtest
        self.symbol_timestamps: Dict[str, np.ndarray] = {}  # symbol -> sorted datetime array
        self.symbol_data_lengths: Dict[str, int] = {}       # symbol -> data length (cached)

        # OPTIMIZATION #3b (Phase 2): Double-buffering for lock-free bitmap reads
        # Two buffers: one for reading (stable), one for writing (updated during barrier)
        # Threads read from 'current' buffer without lock (lock-free reads)
        # Barrier updates 'next' buffer and swaps atomically
        self.symbols_with_data_current: Set[str] = set()  # Read by threads (stable)
        self.symbols_with_data_next: Set[str] = set()     # Written during barrier
        self.bitmap_swap_lock = threading.Lock()          # Only for atomic swap

        # TICK-LEVEL BACKTESTING: Global tick timeline
        # All ticks from all symbols merged into single chronologically-sorted timeline
        self.global_tick_timeline: List[GlobalTick] = []  # Merged tick timeline
        self.global_tick_index: int = 0                   # Current position in timeline
        self.use_tick_data: bool = False                  # Flag to enable tick-level mode
        self.current_tick_symbol: Optional[str] = None    # Symbol that owns current tick

        # TICK-LEVEL BACKTESTING: Per-symbol tick data
        self.symbol_ticks: Dict[str, pd.DataFrame] = {}   # symbol -> tick DataFrame
        self.current_ticks: Dict[str, TickData] = {}      # symbol -> current tick
        self.tick_timestamps: Dict[str, np.ndarray] = {}  # symbol -> tick timestamps (for fast lookup)

        # TICK-LEVEL BACKTESTING: Statistics
        self.tick_sl_hits: int = 0   # Count of SL hits detected on ticks
        self.tick_tp_hits: int = 0   # Count of TP hits detected on ticks

        # TICK-LEVEL BACKTESTING: Real-time candle builders
        # Build candles from ticks in real-time (M1, M5, M15, H1, H4)
        self.candle_builders: Dict[str, MultiTimeframeCandleBuilder] = {}  # symbol -> builder

        # Current simulated time
        self.current_time: Optional[datetime] = None
        # Non-blocking snapshot of current simulated time for logging/time provider
        # Updated whenever current_time changes while holding time_lock
        self.current_time_snapshot: Optional[datetime] = None
        # Use RLock (reentrant lock) instead of Lock to allow same thread to acquire multiple times
        # This prevents deadlock if a method that holds the lock calls another method that also needs the lock
        self.time_lock = threading.RLock()
        
        # Instance ID for debugging multiple instances
        self.instance_id = id(self)

        # Trading status
        self.autotrading_enabled = True
        self.trading_enabled_symbols: Dict[str, bool] = {}  # symbol -> enabled

        # Connection status
        self.is_connected = True

        # Trade history for results analysis
        self.closed_trades: List[Dict] = []  # List of closed trade records

        self.logger.info(f"SimulatedBroker initialized with balance: ${initial_balance:,.2f} [Instance: {self.instance_id}]")
    
    def load_symbol_data(self, symbol: str, data: pd.DataFrame, symbol_info: Dict, timeframe: str = "M1"):
        """
        Load historical data for a symbol and timeframe.

        IMPORTANT: tick_value in symbol_info MUST be converted to account currency (USD)
        before calling this method! The SimulatedBroker uses tick_value directly for
        profit calculations and assumes it's already in USD.

        Args:
            symbol: Symbol name
            data: DataFrame with columns [time, open, high, low, close, volume]
            symbol_info: Dictionary with symbol information (point, digits, tick_value in USD, etc.)
            timeframe: Timeframe of the data (e.g., "M1", "M5", "M15", "H4")
        """
        # Store data with (symbol, timeframe) key
        self.symbol_data[(symbol, timeframe)] = data.copy()

        # OPTIMIZATION #1: For M1 timeframe, pre-compute timestamps and cache data length
        # This eliminates repeated Pandas access and timestamp conversions during backtest
        if timeframe == 'M1':
            # Convert timestamps to NumPy array of datetime objects
            timestamps = pd.to_datetime(data['time'], utc=True)

            # Convert to native Python datetime objects (not Timestamp)
            # This is done once here instead of thousands of times during backtest
            timestamp_array = np.array([
                ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts
                for ts in timestamps
            ])

            self.symbol_timestamps[symbol] = timestamp_array
            self.symbol_data_lengths[symbol] = len(timestamp_array)

        # Initialize current index only once (based on M1)
        # Start at 0 by default - will be updated by set_start_time() to skip historical buffer
        if symbol not in self.current_indices:
            self.current_indices[symbol] = 0
            self.trading_enabled_symbols[symbol] = True

        # Convert symbol_info dict to SimulatedSymbolInfo (only once per symbol)
        if symbol not in self.symbol_info:
            self.symbol_info[symbol] = SimulatedSymbolInfo(
                point=symbol_info.get('point', 0.00001),
                digits=symbol_info.get('digits', 5),
                tick_value=symbol_info.get('tick_value', 1.0),
                tick_size=symbol_info.get('tick_size', 0.00001),
                min_lot=symbol_info.get('min_lot', 0.01),
                max_lot=symbol_info.get('max_lot', 100.0),
            lot_step=symbol_info.get('lot_step', 0.01),
            contract_size=symbol_info.get('contract_size', 100000.0),
            filling_mode=symbol_info.get('filling_mode', 1),
            stops_level=symbol_info.get('stops_level', 0),
            freeze_level=symbol_info.get('freeze_level', 0),
            trade_mode=symbol_info.get('trade_mode', 4),
            currency_base=symbol_info.get('currency_base', 'EUR'),
            currency_profit=symbol_info.get('currency_profit', 'USD'),
            currency_margin=symbol_info.get('currency_margin', 'USD'),
                category=symbol_info.get('category', 'Forex')
            )

            # Store actual spread from MT5 (in points)
            spread = symbol_info.get('spread', None)
            if spread is not None and spread > 0:
                self.symbol_spreads[symbol] = float(spread)
                self.logger.info(f"Loaded {len(data)} bars for {symbol} {timeframe} | Spread: {spread:.1f} points")
            else:
                # Use default spread as fallback
                self.symbol_spreads[symbol] = self.default_spread_points
                self.logger.info(f"Loaded {len(data)} bars for {symbol} {timeframe} | Using default spread: {self.default_spread_points:.1f} points")
        else:
            self.logger.info(f"Loaded {len(data)} bars for {symbol} {timeframe}")

    def load_tick_data(self, symbol: str, ticks: pd.DataFrame, symbol_info: Dict):
        """
        Load tick data for a symbol (for tick-level backtesting).

        Args:
            symbol: Symbol name
            ticks: DataFrame with columns [time, bid, ask, last, volume]
            symbol_info: Dictionary with symbol information
        """
        # Store tick data
        self.symbol_ticks[symbol] = ticks.copy()

        # Pre-compute timestamps for fast lookup
        timestamps = pd.to_datetime(ticks['time'], utc=True)
        self.tick_timestamps[symbol] = np.array([
            ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts
            for ts in timestamps
        ])

        # Store symbol info (same as load_symbol_data)
        if symbol not in self.symbol_info:
            self.symbol_info[symbol] = SimulatedSymbolInfo(
                point=symbol_info.get('point', 0.00001),
                digits=symbol_info.get('digits', 5),
                tick_value=symbol_info.get('tick_value', 1.0),
                tick_size=symbol_info.get('tick_size', 0.00001),
                min_lot=symbol_info.get('min_lot', 0.01),
                max_lot=symbol_info.get('max_lot', 100.0),
                lot_step=symbol_info.get('lot_step', 0.01),
                contract_size=symbol_info.get('contract_size', 100000.0),
                filling_mode=symbol_info.get('filling_mode', 1),
                stops_level=symbol_info.get('stops_level', 0),
                freeze_level=symbol_info.get('freeze_level', 0),
                trade_mode=symbol_info.get('trade_mode', 4),
                currency_base=symbol_info.get('currency_base', 'EUR'),
                currency_profit=symbol_info.get('currency_profit', 'USD'),
                currency_margin=symbol_info.get('currency_margin', 'USD'),
                category=symbol_info.get('category', 'Forex')
            )

            # Store spread from symbol_info
            spread = symbol_info.get('spread', None)
            if spread is not None and spread > 0:
                self.symbol_spreads[symbol] = float(spread)
            else:
                self.symbol_spreads[symbol] = self.default_spread_points

        # Enable trading for this symbol
        self.trading_enabled_symbols[symbol] = True

        self.logger.info(f"Loaded {len(ticks):,} ticks for {symbol}")

    def load_ticks_from_cache_files(self, cache_files: dict):
        """
        Load ticks directly from cached parquet files and merge into global timeline.

        This is more memory-efficient than load_tick_data() + merge_global_tick_timeline()
        because it doesn't store DataFrames in memory.

        Args:
            cache_files: Dict mapping symbol -> parquet file path
        """
        import psutil
        import os
        from pathlib import Path

        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / 1024 / 1024  # MB

        self.logger.info("=" * 60)
        self.logger.info("Loading ticks from cache files (memory-efficient mode)...")
        self.logger.info(f"  Memory before loading: {mem_before:.1f} MB")

        all_ticks = []

        # Load ticks from each cache file
        for symbol, cache_file in cache_files.items():
            cache_path = Path(cache_file)
            if not cache_path.exists():
                self.logger.warning(f"  Cache file not found: {cache_file}")
                continue

            self.logger.info(f"  Loading {symbol} from {cache_path.name}...")

            # Read parquet file in chunks to reduce memory usage
            df = pd.read_parquet(cache_path)

            self.logger.info(f"    {len(df):,} ticks loaded")

            # Convert to GlobalTick objects
            for _, row in df.iterrows():
                tick_time = row['time']
                if isinstance(tick_time, pd.Timestamp):
                    tick_time = tick_time.to_pydatetime()
                if tick_time.tzinfo is None:
                    tick_time = tick_time.replace(tzinfo=timezone.utc)

                all_ticks.append(GlobalTick(
                    time=tick_time,
                    symbol=symbol,
                    bid=float(row['bid']),
                    ask=float(row['ask']),
                    last=float(row['last']),
                    volume=int(row['volume'])
                ))

            # Clear DataFrame to free memory immediately
            del df

        # Sort by timestamp
        self.logger.info(f"  Sorting {len(all_ticks):,} ticks chronologically...")
        all_ticks.sort(key=lambda t: t.time)

        self.global_tick_timeline = all_ticks
        self.global_tick_index = 0
        self.use_tick_data = True

        # Initialize candle builders for each symbol and pre-seed with historical data
        self.logger.info("  Initializing real-time candle builders...")
        timeframes = ['M1', 'M5', 'M15', 'H1', 'H4']
        for symbol in cache_files.keys():
            self.candle_builders[symbol] = MultiTimeframeCandleBuilder(symbol, timeframes)

            # Pre-seed with historical OHLC data from cache
            # This gives strategies enough candle history from the start
            first_tick_time = all_ticks[0].time if len(all_ticks) > 0 else None
            if first_tick_time:
                for tf in timeframes:
                    data_key = (symbol, tf)
                    if data_key in self.symbol_data:
                        # Get all candles before the first tick
                        historical_df = self.symbol_data[data_key]
                        historical_df = historical_df[historical_df['time'] < first_tick_time].copy()

                        if len(historical_df) > 0:
                            self.candle_builders[symbol].seed_historical_candles(tf, historical_df)
                            self.logger.info(f"    ✓ {symbol} {tf}: Seeded with {len(historical_df)} historical candles")

            self.logger.info(f"    ✓ {symbol}: Candle builder initialized for {len(timeframes)} timeframes")

        # Set initial time and initialize current_ticks with first tick of each symbol
        if len(all_ticks) > 0:
            self.current_time = all_ticks[0].time
            # Also update snapshot for non-blocking time provider
            self.current_time_snapshot = self.current_time

            # Initialize current_ticks with first tick of each symbol for get_current_price()
            # This ensures strategies can get prices during initialization
            first_ticks_by_symbol = {}
            for tick in all_ticks:
                if tick.symbol not in first_ticks_by_symbol:
                    first_ticks_by_symbol[tick.symbol] = tick

            for symbol, tick in first_ticks_by_symbol.items():
                self.current_ticks[symbol] = TickData(
                    time=tick.time,
                    bid=tick.bid,
                    ask=tick.ask,
                    last=tick.last,
                    volume=tick.volume,
                    spread=tick.spread
                )

            self.logger.info(f"  Initialized current_ticks for {len(self.current_ticks)} symbols")

            mem_after = process.memory_info().rss / 1024 / 1024  # MB
            mem_used = mem_after - mem_before

            self.logger.info(f"  ✓ Global timeline created: {len(all_ticks):,} ticks")
            self.logger.info(f"  Time range: {all_ticks[0].time} to {all_ticks[-1].time}")
            self.logger.info(f"  Memory after loading: {mem_after:.1f} MB")
            self.logger.info(f"  Memory used: {mem_used:.1f} MB")

            # Calculate statistics
            time_span = (all_ticks[-1].time - all_ticks[0].time).total_seconds()
            ticks_per_second = len(all_ticks) / time_span if time_span > 0 else 0
            self.logger.info(f"  Duration: {time_span/3600:.1f} hours")
            self.logger.info(f"  Average: {ticks_per_second:.1f} ticks/second")

            # Symbol distribution
            symbol_counts = {}
            for tick in all_ticks:
                symbol_counts[tick.symbol] = symbol_counts.get(tick.symbol, 0) + 1

            self.logger.info("  Symbol distribution:")
            for symbol, count in sorted(symbol_counts.items()):
                pct = 100.0 * count / len(all_ticks)
                self.logger.info(f"    {symbol}: {count:,} ticks ({pct:.1f}%)")
        else:
            self.logger.warning("  No ticks loaded!")

        self.logger.info("=" * 60)

    def merge_global_tick_timeline(self):
        """
        Merge all symbol tick data into a single chronologically-sorted global timeline.

        This creates the global tick timeline used for tick-by-tick backtesting.
        Each tick in the timeline contains: time, symbol, bid, ask, last, volume.

        Must be called after all symbols' tick data has been loaded via load_tick_data().

        MEMORY OPTIMIZATION: Clears symbol_ticks DataFrames after merging to free memory.
        """
        import psutil
        import os

        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / 1024 / 1024  # MB

        self.logger.info("=" * 60)
        self.logger.info("Merging global tick timeline...")
        self.logger.info(f"  Memory before merge: {mem_before:.1f} MB")

        all_ticks = []

        # Collect ticks from all symbols
        for symbol, ticks_df in self.symbol_ticks.items():
            self.logger.info(f"  Adding {len(ticks_df):,} ticks from {symbol}")

            # Convert each tick to GlobalTick object
            for _, row in ticks_df.iterrows():
                tick_time = row['time']
                if isinstance(tick_time, pd.Timestamp):
                    tick_time = tick_time.to_pydatetime()
                if tick_time.tzinfo is None:
                    tick_time = tick_time.replace(tzinfo=timezone.utc)

                all_ticks.append(GlobalTick(
                    time=tick_time,
                    symbol=symbol,
                    bid=float(row['bid']),
                    ask=float(row['ask']),
                    last=float(row['last']),
                    volume=int(row['volume'])
                ))

        # MEMORY OPTIMIZATION: Clear DataFrames - we don't need them anymore
        self.logger.info(f"  Clearing {len(self.symbol_ticks)} symbol DataFrames to free memory...")
        self.symbol_ticks.clear()

        mem_after_clear = process.memory_info().rss / 1024 / 1024  # MB
        mem_freed = mem_before - mem_after_clear
        self.logger.info(f"  Memory after clearing DataFrames: {mem_after_clear:.1f} MB (freed {mem_freed:.1f} MB)")

        # Sort by timestamp (CRITICAL for tick-by-tick replay!)
        self.logger.info(f"  Sorting {len(all_ticks):,} ticks chronologically...")
        all_ticks.sort(key=lambda t: t.time)

        self.global_tick_timeline = all_ticks
        self.global_tick_index = 0
        self.use_tick_data = True

        # Initialize candle builders for each symbol and pre-seed with historical data
        self.logger.info("  Initializing real-time candle builders...")
        timeframes = ['M1', 'M5', 'M15', 'H1', 'H4']
        symbols = set(tick.symbol for tick in all_ticks)
        first_tick_time = all_ticks[0].time if len(all_ticks) > 0 else None

        for symbol in symbols:
            self.candle_builders[symbol] = MultiTimeframeCandleBuilder(symbol, timeframes)

            # Pre-seed with historical OHLC data from cache
            # This gives strategies enough candle history from the start
            if first_tick_time:
                for tf in timeframes:
                    data_key = (symbol, tf)
                    if data_key in self.symbol_data:
                        # Get all candles before the first tick
                        historical_df = self.symbol_data[data_key]
                        historical_df = historical_df[historical_df['time'] < first_tick_time].copy()

                        if len(historical_df) > 0:
                            self.candle_builders[symbol].seed_historical_candles(tf, historical_df)
                            self.logger.info(f"    ✓ {symbol} {tf}: Seeded with {len(historical_df)} historical candles")

            self.logger.info(f"    ✓ {symbol}: Candle builder initialized for {len(timeframes)} timeframes")

        # Set initial time to first tick and initialize current_ticks
        if len(all_ticks) > 0:
            self.current_time = all_ticks[0].time
            # Also update snapshot for non-blocking time provider
            self.current_time_snapshot = self.current_time

            # Initialize current_ticks with first tick of each symbol for get_current_price()
            # This ensures strategies can get prices during initialization
            first_ticks_by_symbol = {}
            for tick in all_ticks:
                if tick.symbol not in first_ticks_by_symbol:
                    first_ticks_by_symbol[tick.symbol] = tick

            for symbol, tick in first_ticks_by_symbol.items():
                self.current_ticks[symbol] = TickData(
                    time=tick.time,
                    bid=tick.bid,
                    ask=tick.ask,
                    last=tick.last,
                    volume=tick.volume,
                    spread=tick.spread
                )

            self.logger.info(f"  Initialized current_ticks for {len(self.current_ticks)} symbols")

            mem_after_merge = process.memory_info().rss / 1024 / 1024  # MB

            self.logger.info(f"  Global timeline created: {len(all_ticks):,} ticks")
            self.logger.info(f"  Time range: {all_ticks[0].time} to {all_ticks[-1].time}")
            self.logger.info(f"  Memory after merge: {mem_after_merge:.1f} MB")
            self.logger.info(f"  Memory used by timeline: ~{mem_after_merge - mem_after_clear:.1f} MB")

            # Calculate statistics
            time_span = (all_ticks[-1].time - all_ticks[0].time).total_seconds()
            ticks_per_second = len(all_ticks) / time_span if time_span > 0 else 0
            self.logger.info(f"  Duration: {time_span/3600:.1f} hours")
            self.logger.info(f"  Average: {ticks_per_second:.1f} ticks/second")

            # Symbol distribution
            symbol_counts = {}
            for tick in all_ticks:
                symbol_counts[tick.symbol] = symbol_counts.get(tick.symbol, 0) + 1

            self.logger.info("  Symbol distribution:")
            for symbol, count in sorted(symbol_counts.items()):
                pct = 100.0 * count / len(all_ticks)
                self.logger.info(f"    {symbol}: {count:,} ticks ({pct:.1f}%)")
        else:
            self.logger.warning("  No ticks loaded - global timeline is empty!")

        self.logger.info("=" * 60)

    def set_start_time(self, start_time: datetime):
        """
        Set the starting time for the backtest.

        This moves all symbols' current_indices to the first bar at or after start_time.
        This allows loading historical buffer data before start_time for indicator warmup
        and reference candle lookback, while starting the actual simulation at start_time.

        Args:
            start_time: The time to start the backtest (should be after historical buffer period)
        """
        earliest_bar_time = None

        for symbol in self.current_indices.keys():
            # Get M1 data for this symbol
            m1_data_key = (symbol, 'M1')
            if m1_data_key not in self.symbol_data:
                continue

            m1_data = self.symbol_data[m1_data_key]

            # Find the first bar at or after start_time
            for idx, row in m1_data.iterrows():
                bar_time = row['time']
                if isinstance(bar_time, pd.Timestamp):
                    bar_time = bar_time.to_pydatetime()
                if bar_time.tzinfo is None:
                    bar_time = bar_time.replace(tzinfo=timezone.utc)

                if bar_time >= start_time:
                    self.current_indices[symbol] = idx
                    self.logger.info(
                        f"  {symbol}: Starting at index {idx} (time: {bar_time.strftime('%Y-%m-%d %H:%M:%S')})"
                    )

                    # Track the earliest bar time across all symbols
                    if earliest_bar_time is None or bar_time < earliest_bar_time:
                        earliest_bar_time = bar_time

                    break
            else:
                # If no bar found at or after start_time, start at the end (no data to process)
                self.current_indices[symbol] = len(m1_data) - 1
                self.logger.warning(
                    f"  {symbol}: No data at or after {start_time}, starting at last bar"
                )

        # Initialize current_time with the earliest bar time
        # This ensures logs show simulated time instead of system time
        if earliest_bar_time is not None:
            import threading
            tid = threading.current_thread().name
            self.logger.info(f"[LOCK_DEBUG] {tid} [Broker:{self.instance_id}]: Acquiring time_lock (init current_time)")
            with self.time_lock:
                self.logger.info(f"[LOCK_DEBUG] {tid} [Broker:{self.instance_id}]: Acquired time_lock (init current_time)")
                self.current_time = earliest_bar_time
                # Update non-blocking snapshot as well
                self.current_time_snapshot = self.current_time
            self.logger.info(f"[LOCK_DEBUG] {tid} [Broker:{self.instance_id}]: Released time_lock (init current_time)")
            self.logger.info(f"  Initialized simulated time to: {earliest_bar_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")

    # ========================================================================
    # Connection Management (MT5Connector interface)
    # ========================================================================

    def connect(self) -> bool:
        """Simulate connection to broker."""
        self.is_connected = True
        return True

    def disconnect(self):
        """Simulate disconnection from broker."""
        self.is_connected = False

    # ========================================================================
    # Data Provider Methods (MT5Connector interface)
    # ========================================================================

    def get_candles(self, symbol: str, timeframe: str, count: int = 100) -> Optional[pd.DataFrame]:
        """
        Get historical candles for a symbol and timeframe.

        TICK MODE: Returns dynamically-built candles from tick data (real-time candle building)
        CANDLE MODE: Returns pre-loaded data for the requested timeframe up to current simulation time

        Args:
            symbol: Symbol name
            timeframe: Timeframe (e.g., 'M1', 'M5', 'M15', 'H1', 'H4')
            count: Number of candles to return

        Returns:
            DataFrame with OHLC data or None
        """
        # TICK MODE: Use real-time candle builders
        if self.use_tick_data and symbol in self.candle_builders:
            return self.candle_builders[symbol].get_candles(timeframe, count)

        # CANDLE MODE: Use pre-loaded data
        # Check if we have data for this symbol and timeframe
        data_key = (symbol, timeframe)
        if data_key not in self.symbol_data:
            return None

        # Get the full dataset for this timeframe
        full_data = self.symbol_data[data_key]

        # For M1 (base timeframe), use current_indices to limit data
        if timeframe == 'M1':
            current_idx = self.current_indices.get(symbol, 0)
            start_idx = max(0, current_idx - count + 1)
            df = full_data.iloc[start_idx:current_idx + 1].copy()
            return df

        # For higher timeframes, filter by current simulation time
        if symbol not in self.current_indices:
            return None

        # Get current M1 time
        m1_data_key = (symbol, 'M1')
        if m1_data_key not in self.symbol_data:
            # Fallback: return all data up to count
            return full_data.tail(count).copy()

        m1_data = self.symbol_data[m1_data_key]
        current_idx = self.current_indices.get(symbol, 0)

        if current_idx >= len(m1_data):
            current_time = m1_data.iloc[-1]['time']
        else:
            current_time = m1_data.iloc[current_idx]['time']

        # Filter higher timeframe data up to current time
        filtered_data = full_data[full_data['time'] <= current_time]

        if len(filtered_data) == 0:
            return None

        # Return the last 'count' candles
        df = filtered_data.tail(count).copy()
        return df

    def get_latest_candle(self, symbol: str, timeframe: str) -> Optional[CandleData]:
        """
        Get the latest closed candle for a symbol and timeframe.

        TICK MODE: Returns latest closed candle from real-time candle builder
        CANDLE MODE: Returns latest candle from pre-loaded data

        Args:
            symbol: Symbol name
            timeframe: Timeframe (e.g., 'M1', 'M5', 'M15') or empty string for M1

        Returns:
            CandleData or None
        """
        # TICK MODE: Use real-time candle builders
        if self.use_tick_data and symbol in self.candle_builders:
            # Default to M1 if timeframe is empty
            tf = timeframe if timeframe else 'M1'
            return self.candle_builders[symbol].get_latest_candle(tf)

        # CANDLE MODE: Use pre-loaded data
        # Default to M1 if timeframe is empty or not specified
        if not timeframe or timeframe == 'M1':
            data_key = (symbol, 'M1')
            if data_key not in self.symbol_data:
                return None

            current_idx = self.current_indices.get(symbol, 0)
            m1_data = self.symbol_data[data_key]

            if current_idx >= len(m1_data):
                return None

            row = m1_data.iloc[current_idx]
        else:
            # For higher timeframes, get the latest candle up to current time
            candles = self.get_candles(symbol, timeframe, count=1)
            if candles is None or len(candles) == 0:
                return None

            row = candles.iloc[-1]

        return CandleData(
            time=row['time'] if isinstance(row['time'], datetime) else pd.to_datetime(row['time']).to_pydatetime(),
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=int(row.get('volume', row.get('tick_volume', 0)))
        )

    # ========================================================================
    # Symbol Info Methods (MT5Connector interface)
    # ========================================================================

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """
        Get symbol information.

        Args:
            symbol: Symbol name

        Returns:
            Dictionary with symbol info or None
        """
        if symbol not in self.symbol_info:
            return None

        info = self.symbol_info[symbol]
        return {
            'point': info.point,
            'digits': info.digits,
            'tick_value': info.tick_value,
            'tick_size': info.tick_size,
            'min_lot': info.min_lot,
            'max_lot': info.max_lot,
            'lot_step': info.lot_step,
            'contract_size': info.contract_size,
            'filling_mode': info.filling_mode,
            'stops_level': info.stops_level,
            'freeze_level': info.freeze_level,
            'trade_mode': info.trade_mode,
            'currency_base': info.currency_base,
            'currency_profit': info.currency_profit,
            'currency_margin': info.currency_margin,
            'category': info.category,
        }

    def clear_symbol_info_cache(self, symbol: Optional[str] = None):
        """Clear symbol info cache (no-op in simulation)."""
        pass

    # ========================================================================
    # Account Info Methods (MT5Connector interface)
    # ========================================================================

    def get_account_balance(self) -> float:
        """Get current account balance."""
        return self.balance

    def get_account_equity(self) -> float:
        """Get current account equity (balance + floating P&L)."""
        with self.position_lock:
            floating_pnl = sum(pos.profit for pos in self.positions.values())
        return self.balance + floating_pnl

    def get_account_currency(self) -> str:
        """Get account currency."""
        return self.currency

    def get_account_free_margin(self) -> Optional[float]:
        """
        Get account free margin (available for new positions).

        In backtest mode, we use a simplified calculation:
        Free Margin = Equity - Used Margin

        For simplicity, we assume 100:1 leverage and calculate used margin
        as the sum of all open position notional values / 100.
        """
        equity = self.get_account_equity()

        # Calculate used margin from open positions
        used_margin = 0.0
        with self.position_lock:
            for pos in self.positions.values():
                # Get symbol info
                if pos.symbol not in self.symbol_info:
                    continue

                info = self.symbol_info[pos.symbol]
                # Notional value = volume * contract_size * current_price
                notional = pos.volume * info.contract_size * pos.price_open
                # Assume 100:1 leverage
                used_margin += notional / 100.0

        free_margin = equity - used_margin
        return max(0.0, free_margin)  # Can't be negative

    def calculate_margin(self, symbol: str, volume: float, price: float) -> Optional[float]:
        """
        Calculate required margin for opening a position.

        In backtest mode, we use a simplified calculation:
        Margin = (volume * contract_size * price) / leverage

        Args:
            symbol: Symbol name
            volume: Lot size
            price: Entry price

        Returns:
            Required margin in account currency
        """
        if symbol not in self.symbol_info:
            return None

        info = self.symbol_info[symbol]
        # Notional value = volume * contract_size * price
        notional = volume * info.contract_size * price
        # Assume 100:1 leverage
        margin = notional / 100.0

        return margin

    def get_currency_conversion_rate(self, from_currency: str, to_currency: str) -> Optional[float]:
        """Get currency conversion rate (simplified - returns 1.0)."""
        if from_currency == to_currency:
            return 1.0
        # Simplified: assume all conversions are 1:1 for now
        # In a more sophisticated version, this would use actual FX rates
        return 1.0

    # ========================================================================
    # Position Provider Methods (MT5Connector interface)
    # ========================================================================

    def get_positions(self, symbol: Optional[str] = None, magic_number: Optional[int] = None) -> List[PositionInfo]:
        """
        Get open positions.

        Args:
            symbol: Filter by symbol (optional)
            magic_number: Filter by magic number (optional)

        Returns:
            List of PositionInfo
        """
        with self.position_lock:
            positions = list(self.positions.values())

        # Filter by symbol
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]

        # Filter by magic number
        if magic_number is not None:
            positions = [p for p in positions if p.magic_number == magic_number]

        return positions

    def get_closed_position_info(self, ticket: int) -> Optional[Tuple[str, float, float, str]]:
        """
        Get closed position info from history.

        Args:
            ticket: Position ticket

        Returns:
            Tuple of (symbol, profit, volume, comment) or None
        """
        # Search for the closed trade in history
        for trade in self.closed_trades:
            if trade['ticket'] == ticket:
                return (
                    trade['symbol'],
                    trade['profit'],
                    trade['volume'],
                    trade['comment']
                )

        # Not found in closed trades
        return None

    # ========================================================================
    # Price Provider Methods (MT5Connector interface)
    # ========================================================================

    def _try_inverse_pair_price(self, symbol: str, price_type: str) -> Optional[float]:
        """
        Try to get price from inverse currency pair.

        This is used for currency conversion when the direct pair isn't loaded.
        For example, if JPYUSD is requested but not loaded, try USDJPY and invert.

        Args:
            symbol: Symbol name (e.g., 'JPYUSD')
            price_type: 'bid' or 'ask'

        Returns:
            Inverted price or None
        """
        # Only try for 6-character currency pairs
        if len(symbol) != 6:
            return None

        # Extract currencies (e.g., 'JPYUSD' -> 'JPY', 'USD')
        from_currency = symbol[:3]
        to_currency = symbol[3:]

        # Try inverse pair (e.g., 'USDJPY')
        inverse_symbol = f"{to_currency}{from_currency}"
        inverse_candle = self.get_latest_candle(inverse_symbol, "")

        if inverse_candle is None:
            return None

        # Get inverse price
        inverse_price = inverse_candle.close

        if inverse_price <= 0:
            return None

        # Calculate inverted price
        # For bid: use 1/ask of inverse (conservative)
        # For ask: use 1/bid of inverse (conservative)
        if inverse_symbol in self.symbol_info:
            point = self.symbol_info[inverse_symbol].point
            # Use actual spread for inverse symbol
            spread_points = self.symbol_spreads.get(inverse_symbol, self.default_spread_points)
            spread = spread_points * point

            if price_type == 'bid':
                # Bid of JPYUSD = 1 / Ask of USDJPY
                inverse_ask = inverse_price + spread
                return 1.0 / inverse_ask if inverse_ask > 0 else None
            else:  # ask
                # Ask of JPYUSD = 1 / Bid of USDJPY
                inverse_bid = inverse_price
                return 1.0 / inverse_bid if inverse_bid > 0 else None
        else:
            # No spread info, just invert
            return 1.0 / inverse_price

    def get_current_price(self, symbol: str, price_type: str = 'bid') -> Optional[float]:
        """
        Get current price for symbol.

        Args:
            symbol: Symbol name
            price_type: 'bid' or 'ask'

        Returns:
            Current price or None
        """
        # TICK-LEVEL MODE: Return price from current tick
        if self.use_tick_data and symbol in self.current_ticks:
            tick = self.current_ticks[symbol]
            if price_type == 'bid':
                return tick.bid
            elif price_type == 'ask':
                return tick.ask
            elif price_type == 'mid':
                return tick.mid
            else:
                return tick.bid  # Default to bid

        # CANDLE MODE: Return price from latest candle
        candle = self.get_latest_candle(symbol, "")
        if not candle:
            # Try to get price from inverse pair for currency conversion
            # This is useful for pairs like JPYUSD (inverse of USDJPY)
            inverse_price = self._try_inverse_pair_price(symbol, price_type)
            if inverse_price is not None:
                return inverse_price
            return None

        # Use close price as base
        base_price = candle.close

        # Apply spread
        if symbol in self.symbol_info:
            point = self.symbol_info[symbol].point
            # Use actual spread for this symbol
            spread_points = self.symbol_spreads.get(symbol, self.default_spread_points)
            spread = spread_points * point

            if price_type == 'bid':
                return base_price
            else:  # ask
                return base_price + spread

        return base_price

    def get_spread(self, symbol: str) -> Optional[float]:
        """Get spread in points for the specified symbol."""
        return self.symbol_spreads.get(symbol, self.default_spread_points)

    def get_spread_percent(self, symbol: str) -> Optional[float]:
        """Get spread as percentage of price."""
        price = self.get_current_price(symbol, 'bid')
        if not price or symbol not in self.symbol_info:
            return None

        point = self.symbol_info[symbol].point
        spread_points = self.symbol_spreads.get(symbol, self.default_spread_points)
        spread_price = spread_points * point
        return (spread_price / price) * 100.0

    # ========================================================================
    # Trading Status Methods (MT5Connector interface)
    # ========================================================================

    def is_autotrading_enabled(self) -> bool:
        """Check if AutoTrading is enabled."""
        return self.autotrading_enabled

    def is_trading_enabled(self, symbol: str) -> bool:
        """Check if trading is enabled for symbol."""
        return self.trading_enabled_symbols.get(symbol, True)

    def is_market_open(self, symbol: str) -> bool:
        """Check if market is open (always True in simulation)."""
        return True

    def is_in_trading_session(self, symbol: str, suppress_logs: bool = False) -> bool:
        """Check if symbol is in active trading session (always True in simulation)."""
        return True

    # ========================================================================
    # Market Watch Methods (MT5Connector interface)
    # ========================================================================

    def get_market_watch_symbols(self) -> List[str]:
        """Get Market Watch symbols."""
        return list(self.symbol_data.keys())

    # ========================================================================
    # Order Execution Methods (Simulated)
    # ========================================================================

    def _calculate_slippage(self, symbol: str, volume: float) -> float:
        """
        Calculate realistic slippage in points based on volume and market conditions.

        Slippage factors:
        - Base slippage: 0.5 points for normal conditions
        - Volume impact: Larger orders get more slippage
        - Volatility impact: Higher volatility = more slippage (simulated via volume)

        Args:
            symbol: Symbol name
            volume: Order volume in lots

        Returns:
            Slippage in points (always >= 0)
        """
        if not self.enable_slippage:
            return 0.0

        try:
            # Base slippage for normal market conditions
            slippage = self.base_slippage_points

            # Volume impact: Larger orders experience more slippage
            # Standard lot = 1.0, mini lot = 0.1, micro lot = 0.01
            # For every 1.0 lot, add 0.3 points of slippage
            volume_impact = (volume - 0.01) * 0.3  # Subtract micro lot baseline
            slippage += max(0, volume_impact)

            # Get current candle to check for volatility (high volume = high volatility)
            candle = self.get_latest_candle(symbol, "M1")
            if candle and candle.volume > 0:
                # Get average volume from recent bars
                candles = self.get_candles(symbol, "M1", count=20)
                if candles is not None and len(candles) >= 10:
                    # Use 'tick_volume' or 'volume' column (MT5 uses 'tick_volume')
                    volume_col = 'tick_volume' if 'tick_volume' in candles.columns else 'volume'
                    avg_volume = candles[volume_col].mean()

                    # If current volume is significantly higher than average, add volatility slippage
                    if candle.volume > avg_volume * 1.5:
                        volatility_multiplier = min(candle.volume / avg_volume, 3.0)  # Cap at 3x
                        slippage *= volatility_multiplier

            # Round to 1 decimal place
            return round(slippage, 1)

        except Exception as e:
            # If slippage calculation fails, fall back to base slippage
            # This ensures order execution continues even if there's a data issue
            self.logger.debug(f"[BACKTEST] Slippage calculation failed for {symbol}: {e}. Using base slippage.")
            return self.base_slippage_points

    def place_market_order(self, symbol: str, order_type: PositionType, volume: float,
                          sl: float, tp: float, magic_number: int, comment: str = "") -> OrderResult:
        """
        Place a market order (simulated).

        Args:
            symbol: Symbol name
            order_type: BUY or SELL
            volume: Lot size
            sl: Stop loss price
            tp: Take profit price
            magic_number: Magic number
            comment: Order comment

        Returns:
            OrderResult with execution details
        """
        try:
            return self._place_market_order_impl(symbol, order_type, volume, sl, tp, magic_number, comment)
        except Exception as e:
            self.logger.error(
                f"[BACKTEST] EXCEPTION in place_market_order for {symbol}: {type(e).__name__}: {e}"
            )
            import traceback
            self.logger.error(f"[BACKTEST] Traceback:\n{traceback.format_exc()}")
            return OrderResult(
                success=False,
                order=None,
                price=None,
                retcode=10018,
                comment=f"Exception: {type(e).__name__}: {e}"
            )

    def _place_market_order_impl(self, symbol: str, order_type: PositionType, volume: float,
                                 sl: float, tp: float, magic_number: int, comment: str = "") -> OrderResult:
        """Internal implementation of place_market_order with exception handling wrapper."""
        with self.position_lock:
            # Check if autotrading is enabled
            if not self.autotrading_enabled:
                return OrderResult(
                    success=False,
                    order=None,
                    price=None,
                    retcode=10027,  # TRADE_RETCODE_AUTOTRADING_DISABLED
                    comment="AutoTrading is disabled"
                )

            # Check if trading is enabled for symbol
            if not self.is_trading_enabled(symbol):
                return OrderResult(
                    success=False,
                    order=None,
                    price=None,
                    retcode=10018,  # TRADE_RETCODE_MARKET_CLOSED
                    comment=f"Trading disabled for {symbol}"
                )

            # Validate symbol info exists
            if symbol not in self.symbol_info:
                return OrderResult(
                    success=False,
                    order=None,
                    price=None,
                    retcode=10018,  # TRADE_RETCODE_MARKET_CLOSED
                    comment=f"Symbol info not available for {symbol}"
                )

            info = self.symbol_info[symbol]

            # Validate volume
            if volume < info.min_lot:
                error_msg = f"Volume {volume} below minimum {info.min_lot}"
                self.logger.warning(f"[BACKTEST] Order rejected: {error_msg}")
                return OrderResult(
                    success=False,
                    order=None,
                    price=None,
                    retcode=10014,  # TRADE_RETCODE_INVALID_VOLUME
                    comment=error_msg
                )

            if volume > info.max_lot:
                error_msg = f"Volume {volume} above maximum {info.max_lot}"
                self.logger.warning(f"[BACKTEST] Order rejected: {error_msg}")
                return OrderResult(
                    success=False,
                    order=None,
                    price=None,
                    retcode=10014,  # TRADE_RETCODE_INVALID_VOLUME
                    comment=error_msg
                )

            # Get execution price
            price_type = 'ask' if order_type == PositionType.BUY else 'bid'
            execution_price = self.get_current_price(symbol, price_type)

            if execution_price is None:
                return OrderResult(
                    success=False,
                    order=None,
                    price=None,
                    retcode=10018,  # TRADE_RETCODE_MARKET_CLOSED
                    comment="No price data available"
                )

            # Validate SL/TP distance (stops_level check)
            if info.stops_level > 0:
                min_distance = info.stops_level * info.point

                # Check SL distance
                if sl > 0:
                    sl_distance = abs(execution_price - sl)
                    if sl_distance < min_distance:
                        error_msg = f"SL too close: {sl_distance:.5f} < min {min_distance:.5f} ({info.stops_level} points)"
                        self.logger.warning(f"[BACKTEST] Order rejected for {symbol}: {error_msg}")
                        return OrderResult(
                            success=False,
                            order=None,
                            price=None,
                            retcode=10016,  # TRADE_RETCODE_INVALID_STOPS
                            comment=error_msg
                        )

                # Check TP distance
                if tp > 0:
                    tp_distance = abs(execution_price - tp)
                    if tp_distance < min_distance:
                        error_msg = f"TP too close: {tp_distance:.5f} < min {min_distance:.5f} ({info.stops_level} points)"
                        self.logger.warning(f"[BACKTEST] Order rejected for {symbol}: {error_msg}")
                        return OrderResult(
                            success=False,
                            order=None,
                            price=None,
                            retcode=10016,  # TRADE_RETCODE_INVALID_STOPS
                            comment=error_msg
                        )

            # Check for sufficient margin (simplified)
            # Margin is calculated in BASE currency, then converted to account currency
            # For EURUSD: margin in EUR, convert to USD
            # For CHFJPY: margin in CHF, convert to USD
            # Uses configurable leverage (e.g., 100:1, 200:1, 500:1)

            # Calculate margin in base currency
            # Margin = (volume * contract_size) / leverage
            margin_in_base_currency = (volume * info.contract_size) / self.leverage

            # Convert to account currency (USD)
            # For simplicity, use a rough conversion rate
            # In reality, we'd need to get the conversion rate from broker
            base_currency = info.currency_base

            if base_currency == "USD":
                # Already in USD
                required_margin = margin_in_base_currency
            elif base_currency in ["EUR", "GBP", "AUD", "NZD"]:
                # These are typically worth more than USD
                # Rough estimate: 1 EUR/GBP/AUD/NZD ≈ 1.0-1.5 USD
                required_margin = margin_in_base_currency * 1.1
            elif base_currency == "CHF":
                # CHF ≈ 1.1 USD
                required_margin = margin_in_base_currency * 1.1
            elif base_currency == "JPY":
                # JPY ≈ 0.0067 USD (1 USD ≈ 150 JPY)
                required_margin = margin_in_base_currency * 0.0067
            elif base_currency == "CAD":
                # CAD ≈ 0.72 USD
                required_margin = margin_in_base_currency * 0.72
            else:
                # Default: assume 1:1
                required_margin = margin_in_base_currency
                self.logger.warning(
                    f"[BACKTEST] Unknown base currency {base_currency} for {symbol}, "
                    f"assuming 1:1 conversion to USD"
                )

            # Check if we have enough free margin (balance - used margin)
            # Allow using up to 95% of balance for margin
            # This leaves 5% as safety buffer (more aggressive but realistic for backtest)
            max_margin = self.balance * 0.95

            if required_margin > max_margin:
                error_msg = f"Insufficient margin: required ${required_margin:.2f}, available ${max_margin:.2f}"
                self.logger.warning(f"[BACKTEST] Order rejected for {symbol}: {error_msg}")
                self.logger.warning(
                    f"[BACKTEST]   Balance: ${self.balance:.2f}, Volume: {volume}, "
                    f"Contract Size: {info.contract_size}, Price: {execution_price:.5f}"
                )
                return OrderResult(
                    success=False,
                    order=None,
                    price=None,
                    retcode=10019,  # TRADE_RETCODE_NO_MONEY
                    comment=error_msg
                )

            # Apply slippage (realistic market execution)
            slippage_points = self._calculate_slippage(symbol, volume)
            if slippage_points > 0 and symbol in self.symbol_info:
                point = self.symbol_info[symbol].point
                slippage_price = slippage_points * point

                # Slippage always works against the trader
                if order_type == PositionType.BUY:
                    execution_price += slippage_price  # Pay more for BUY
                else:
                    execution_price -= slippage_price  # Get less for SELL

                self.logger.debug(
                    f"[BACKTEST] Applied slippage: {slippage_points:.1f} points "
                    f"({slippage_price:.5f} price) to {symbol} {order_type.name}"
                )

            # Create position
            ticket = self.next_ticket
            self.next_ticket += 1

            position = PositionInfo(
                ticket=ticket,
                symbol=symbol,
                position_type=order_type,
                volume=volume,
                open_price=execution_price,
                current_price=execution_price,
                sl=sl,
                tp=tp,
                profit=0.0,
                open_time=self.current_time or datetime.now(timezone.utc),
                magic_number=magic_number,
                comment=comment
            )

            self.positions[ticket] = position

            # WARNING: Check for missing SL (TP can be 0.0 legitimately)
            if sl == 0.0:
                self.logger.warning(
                    f"[BACKTEST] ⚠️ Position opened WITHOUT Stop Loss: {symbol} {order_type.name} "
                    f"| SL: {sl:.5f} | TP: {tp:.5f} | Ticket: {ticket} - THIS POSITION WILL NEVER CLOSE!"
                )

            # Log order execution with slippage info
            slippage_info = f" (slippage: {slippage_points:.1f}pts)" if slippage_points > 0 else ""
            self.logger.info(
                f"[BACKTEST] Order executed: {symbol} {order_type.name} {volume} lots @ {execution_price:.5f}{slippage_info} "
                f"| SL: {sl:.5f} | TP: {tp:.5f} | Ticket: {ticket}"
            )

            return OrderResult(
                success=True,
                order=ticket,
                price=execution_price,
                retcode=10009,  # TRADE_RETCODE_DONE
                comment="Order executed successfully"
            )

    def modify_position(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None) -> bool:
        """
        Modify position SL/TP.

        Args:
            ticket: Position ticket
            sl: New stop loss (None to keep current)
            tp: New take profit (None to keep current)

        Returns:
            True if successful
        """
        with self.position_lock:
            if ticket not in self.positions:
                self.logger.warning(f"[BACKTEST] Position {ticket} not found for modification")
                return False

            position = self.positions[ticket]

            if sl is not None:
                position.sl = sl
            if tp is not None:
                position.tp = tp

            self.logger.info(
                f"[BACKTEST] Position {ticket} modified: SL={position.sl:.5f}, TP={position.tp:.5f}"
            )

            return True

    def close_position(self, ticket: int) -> bool:
        """
        Close a position.

        Args:
            ticket: Position ticket

        Returns:
            True if successful
        """
        # Get current time BEFORE acquiring lock to avoid deadlock
        # (get_current_time acquires time_lock)
        close_time = self.get_current_time()

        with self.position_lock:
            return self._close_position_internal(ticket, close_time=close_time)

    def _close_position_internal(self, ticket: int, close_price: Optional[float] = None, close_time: Optional[datetime] = None) -> bool:
        """
        Internal method to close a position without acquiring lock.

        IMPORTANT: This method assumes the caller already holds self.position_lock.

        Args:
            ticket: Position ticket

        Returns:
            True if successful
        """
        if ticket not in self.positions:
            self.logger.warning(f"[BACKTEST] Position {ticket} not found for closing")
            return False

        position = self.positions[ticket]

        # Calculate final profit
        self._update_position_profit(position)

        # Update balance
        self.balance += position.profit

        # Record closed trade for analysis
        if close_time is None:
            # Fallback if not provided (though it should be to avoid deadlock)
            # We can't call get_current_time() here if we hold time_lock!
            # But if we are here, we might hold position_lock.
            # If we don't hold time_lock, this is safe.
            # If we DO hold time_lock (e.g. from advance_global_time), we MUST pass close_time.
            close_time = self.get_current_time()

        trade_record = {
            'ticket': ticket,
            'symbol': position.symbol,
            'type': position.position_type.name,
            'volume': position.volume,
            'open_price': position.open_price,
            'close_price': position.current_price,
            'open_time': position.open_time,
            'close_time': close_time,
            'profit': position.profit,
            'sl': position.sl,
            'tp': position.tp,
            'magic': position.magic_number,
            'comment': position.comment,
        }
        self.closed_trades.append(trade_record)

        self.logger.info(
            f"[BACKTEST] Position {ticket} closed: {position.symbol} {position.position_type.name} "
            f"| Profit: ${position.profit:.2f} | Balance: ${self.balance:.2f}"
        )

        # Remove from open positions
        del self.positions[ticket]

        # Remove from persistence (if available)
        # This ensures backtest behavior matches live trading where positions are removed from persistence when closed
        if self.persistence:
            try:
                self.persistence.remove_position(ticket)
            except Exception as e:
                self.logger.error(f"[BACKTEST] Failed to remove position {ticket} from persistence: {e}")

        return True

    # ========================================================================
    # Position Update Methods (Internal)
    # ========================================================================

    def update_positions(self):
        """
        Update all open positions with current prices and check for SL/TP hits.
        Called by TimeController on each time step.
        """
        # Get current time BEFORE acquiring position_lock to avoid deadlock
        # (get_current_time acquires time_lock)
        current_time = self.get_current_time()

        with self.position_lock:
            positions_to_close = []

            for ticket, position in self.positions.items():
                # Update current price and profit
                self._update_position_profit(position)

                # Check for SL/TP hits
                if self._check_sl_tp_hit(position):
                    positions_to_close.append(ticket)

            # Close positions that hit SL/TP (using internal method to avoid deadlock)
            for ticket in positions_to_close:
                self._close_position_internal(ticket, close_time=current_time)

    def _update_position_profit(self, position: PositionInfo):
        """Update position's current price and profit."""
        # Get current price (opposite of entry)
        price_type = 'bid' if position.position_type == PositionType.BUY else 'ask'
        current_price = self.get_current_price(position.symbol, price_type)

        if current_price is None:
            return

        position.current_price = current_price

        # Calculate profit
        if position.symbol in self.symbol_info:
            info = self.symbol_info[position.symbol]

            if position.position_type == PositionType.BUY:
                price_diff = current_price - position.open_price
            else:  # SELL
                price_diff = position.open_price - current_price

            # Profit = price_diff * volume * contract_size * tick_value / tick_size
            position.profit = (price_diff / info.tick_size) * info.tick_value * position.volume

    def _check_sl_tp_hit(self, position: PositionInfo) -> bool:
        """
        Check if position hit SL or TP using intra-bar accuracy.

        TICK MODE: Uses the current (incomplete) M1 candle for real-time high/low
        CANDLE MODE: Uses the latest closed M1 bar to detect SL/TP hits

        This is more realistic than only checking the close price, as it
        accounts for price wicks that touch SL/TP levels.

        Returns:
            True if SL or TP was hit
        """
        # Get the current M1 candle for intra-bar high/low
        # In tick mode, use current (incomplete) candle for real-time accuracy
        if self.use_tick_data and position.symbol in self.candle_builders:
            candle = self.candle_builders[position.symbol].get_current_candle('M1')
        else:
            candle = self.get_latest_candle(position.symbol, "M1")

        if candle is None:
            # Fallback to close price if candle not available
            current_price = position.current_price

            if position.position_type == PositionType.BUY:
                if position.sl > 0 and current_price <= position.sl:
                    self.logger.info(f"[BACKTEST] Position {position.ticket} hit SL: {current_price:.5f} <= {position.sl:.5f}")
                    return True
                if position.tp > 0 and current_price >= position.tp:
                    self.logger.info(f"[BACKTEST] Position {position.ticket} hit TP: {current_price:.5f} >= {position.tp:.5f}")
                    return True
            else:  # SELL
                if position.sl > 0 and current_price >= position.sl:
                    self.logger.info(f"[BACKTEST] Position {position.ticket} hit SL: {current_price:.5f} >= {position.sl:.5f}")
                    return True
                if position.tp > 0 and current_price <= position.tp:
                    self.logger.info(f"[BACKTEST] Position {position.ticket} hit TP: {current_price:.5f} <= {position.tp:.5f}")
                    return True
            return False

        # Use intra-bar high/low for more accurate SL/TP detection
        if position.position_type == PositionType.BUY:
            # For BUY positions:
            # - SL is below entry, check if low touched it
            # - TP is above entry, check if high touched it

            # Check SL hit (price went down to SL level)
            if position.sl > 0 and candle.low <= position.sl:
                # Update position price to SL for accurate profit calculation
                position.current_price = position.sl
                self.logger.info(
                    f"[BACKTEST] Position {position.ticket} hit SL (intra-bar): "
                    f"bar_low={candle.low:.5f} <= SL={position.sl:.5f}"
                )
                return True

            # Check TP hit (price went up to TP level)
            if position.tp > 0 and candle.high >= position.tp:
                # Update position price to TP for accurate profit calculation
                position.current_price = position.tp
                self.logger.info(
                    f"[BACKTEST] Position {position.ticket} hit TP (intra-bar): "
                    f"bar_high={candle.high:.5f} >= TP={position.tp:.5f}"
                )
                return True

        else:  # SELL
            # For SELL positions:
            # - SL is above entry, check if high touched it
            # - TP is below entry, check if low touched it

            # Check SL hit (price went up to SL level)
            if position.sl > 0 and candle.high >= position.sl:
                # Update position price to SL for accurate profit calculation
                position.current_price = position.sl
                self.logger.info(
                    f"[BACKTEST] Position {position.ticket} hit SL (intra-bar): "
                    f"bar_high={candle.high:.5f} >= SL={position.sl:.5f}"
                )
                return True

            # Check TP hit (price went down to TP level)
            if position.tp > 0 and candle.low <= position.tp:
                # Update position price to TP for accurate profit calculation
                position.current_price = position.tp
                self.logger.info(
                    f"[BACKTEST] Position {position.ticket} hit TP (intra-bar): "
                    f"bar_low={candle.low:.5f} <= TP={position.tp:.5f}"
                )
                return True

        return False

    # ========================================================================
    # Time Management Methods (For TimeController)
    # ========================================================================

    def has_data_at_current_time(self, symbol: str) -> bool:
        """
        Check if a symbol has data at the current global time.

        TICK MODE: Returns True only if this symbol owns the current tick
        CANDLE MODE: Returns True if symbol has a bar at current_time

        OPTIMIZATIONS APPLIED:
        - #1: Uses pre-computed timestamps (no Pandas access, no timestamp conversion)
        - #3b: Lock-free bitmap read using double-buffering (Phase 2)

        THREAD-SAFE (LOCK-FREE):
        - Reads from stable 'current' buffer (not being modified)
        - Swap happens atomically during barrier (with bitmap_swap_lock)
        - Threads always see consistent state (either old or new buffer)
        - No lock acquisition needed (eliminates 2.9M lock operations per backtest)

        Args:
            symbol: Symbol to check

        Returns:
            True if symbol has data at current_time, False otherwise
        """
        # TICK MODE: Check if this symbol owns the current tick
        if self.use_tick_data:
            # In tick mode, only the symbol that owns the current tick should process it
            # All other symbols wait at the barrier without processing
            return symbol == self.current_tick_symbol

        # CANDLE MODE: Check bitmap for bar at current time
        # OPTIMIZATION #3b: Lock-free read from stable buffer
        # No lock needed - we read from the 'current' buffer which is stable
        # The swap happens atomically, so we always see a consistent state
        return symbol in self.symbols_with_data_current

    def has_more_data(self, symbol: str) -> bool:
        """
        Check if a symbol has any more data available.

        TICK MODE: Checks if there are more ticks in the global timeline
        CANDLE MODE: Uses cached data length for fast check

        Args:
            symbol: Symbol to check

        Returns:
            True if symbol has more data, False if at end
        """
        import threading
        tid = threading.current_thread().name
        self.logger.debug(f"[LOCK_DEBUG] {tid}: Acquiring time_lock (has_more_data)")
        with self.time_lock:
            self.logger.debug(f"[LOCK_DEBUG] {tid}: Acquired time_lock (has_more_data)")

            # TICK MODE: Check global tick timeline
            if self.use_tick_data:
                # In tick mode, all symbols share the same global timeline
                # Check if there are more ticks to process
                result = self.global_tick_index < len(self.global_tick_timeline)
                self.logger.debug(f"[LOCK_DEBUG] {tid}: Releasing time_lock (has_more_data TICK mode - result={result})")
                return result

            # CANDLE MODE: Check per-symbol data
            if symbol not in self.current_indices:
                self.logger.debug(f"[LOCK_DEBUG] {tid}: Releasing time_lock (has_more_data - no indices)")
                return False

            # Fast bounds check using cached length
            current_idx = self.current_indices[symbol]
            data_length = self.symbol_data_lengths.get(symbol, 0)

            # Check if there's more data after current index
            result = current_idx < data_length - 1
            self.logger.debug(f"[LOCK_DEBUG] {tid}: Releasing time_lock (has_more_data CANDLE mode - result={result})")
            return result

    def advance_global_time(self) -> bool:
        """
        Advance global time by one minute.

        This is called once per barrier cycle (not per symbol).
        After advancing time, each symbol's index is updated if it had data at the current time.

        Thread-safe: Should only be called by one thread (e.g., the last to reach barrier).

        OPTIMIZATIONS APPLIED:
        - #1: Uses pre-computed timestamps (no Pandas access, no timestamp conversion)
        - #2: Single loop instead of two (50% reduction in iterations)
        - #3b: Double-buffering for lock-free bitmap reads (Phase 2)

        Returns:
            True if time advanced successfully, False if all symbols exhausted
        """
        with self.time_lock:
            if self.current_time is None:
                return False

            has_any_data = False

            # OPTIMIZATION #2: Combined loop - advance indices AND check for remaining data
            for symbol in self.current_indices.keys():
                current_idx = self.current_indices[symbol]

                # OPTIMIZATION #1: Fast bounds check using cached length
                data_length = self.symbol_data_lengths.get(symbol, 0)
                if current_idx >= data_length:
                    continue  # Symbol exhausted

                # OPTIMIZATION #1: Fast timestamp check using pre-computed array
                bar_time = self.symbol_timestamps[symbol][current_idx]

                # If bar time matches current global time, advance index
                if bar_time == self.current_time:
                    self.current_indices[symbol] = current_idx + 1
                    current_idx += 1  # Update local variable

                # Check if symbol has more data (after potential advancement)
                if current_idx < data_length:
                    has_any_data = True
                    # Don't break - we need to advance ALL symbols

            if not has_any_data:
                # All symbols exhausted
                return False

            # Advance global time by 1 minute
            from datetime import timedelta
            self.current_time = self.current_time + timedelta(minutes=1)
            # Update non-blocking snapshot as well
            self.current_time_snapshot = self.current_time

            # OPTIMIZATION #3b: Update NEXT buffer (not visible to threads yet)
            # Threads are still reading from 'current' buffer (stable, no lock needed)
            self.symbols_with_data_next.clear()

            for symbol in self.current_indices.keys():
                current_idx = self.current_indices[symbol]
                data_length = self.symbol_data_lengths.get(symbol, 0)

                if current_idx < data_length:
                    bar_time = self.symbol_timestamps[symbol][current_idx]
                    if bar_time == self.current_time:
                        self.symbols_with_data_next.add(symbol)

            # Atomic swap: make next buffer current
            # This is the ONLY place where bitmap_swap_lock is needed
            # Very short critical section (just pointer swap)
            with self.bitmap_swap_lock:
                self.symbols_with_data_current, self.symbols_with_data_next = \
                    self.symbols_with_data_next, self.symbols_with_data_current

            return True

    def advance_global_time_tick_by_tick(self) -> bool:
        """
        Advance global time by one tick (tick-by-tick mode).

        This method processes the next tick in the global tick timeline.
        Only the symbol that owns the current tick will have its current_ticks updated.

        Thread-safe: Should only be called by one thread (the last to reach barrier).

        Returns:
            True if time advanced successfully, False if no more ticks
        """
        if self.global_tick_index < 3:
            import threading
            self.logger.info(f"[TICK] advance_global_time_tick_by_tick() called by {threading.current_thread().name} (index={self.global_tick_index})")
            self.logger.info(f"[TICK] Attempting to acquire time_lock...")

        import threading
        tid = threading.current_thread().name
        self.logger.info(f"[LOCK_DEBUG] {tid} [Broker:{self.instance_id}]: Attempting to acquire time_lock (advance_tick, index={self.global_tick_index})")
        acquired = self.time_lock.acquire(timeout=1)
        if not acquired:
            self.logger.error(f"[LOCK_DEBUG] {tid} [Broker:{self.instance_id}]: DEADLOCK! Could not acquire time_lock after 1 second!")
            self.logger.error(f"[TICK] This means another thread is holding time_lock and not releasing it")
            return False

        try:
            self.logger.info(f"[LOCK_DEBUG] {tid} [Broker:{self.instance_id}]: Acquired time_lock (advance_tick, index={self.global_tick_index})")
            if self.global_tick_index < 3:
                self.logger.info(f"[TICK] Acquired time_lock (index={self.global_tick_index})")
            # Log start of tick-by-tick processing (first tick only)
            if self.global_tick_index == 0 and len(self.global_tick_timeline) > 0:
                first_tick = self.global_tick_timeline[0]
                last_tick = self.global_tick_timeline[-1]
                self.logger.info("=" * 80)
                self.logger.info("STARTING TICK-BY-TICK BACKTEST")
                self.logger.info("=" * 80)
                self.logger.info(f"Total ticks: {len(self.global_tick_timeline):,}")
                self.logger.info(f"First tick: {first_tick.time.strftime('%Y-%m-%d %H:%M:%S')} ({first_tick.symbol})")
                self.logger.info(f"Last tick: {last_tick.time.strftime('%Y-%m-%d %H:%M:%S')} ({last_tick.symbol})")
                self.logger.info(f"Status updates every 1,000 ticks (file logs)")
                self.logger.info(f"Console progress updates every 1 second (via BacktestController)")
                self.logger.info("=" * 80)

                # Initialize timing for ETA calculation
                import time
                self.backtest_start_time = time.time()

            # Check if we have more ticks
            if self.global_tick_index >= len(self.global_tick_timeline):
                self.logger.info("=" * 80)
                self.logger.info("TICK-BY-TICK BACKTEST COMPLETE")
                self.logger.info("=" * 80)
                self.logger.info(f"Total ticks processed: {self.global_tick_index:,}")
                self.logger.info(f"Stop-Loss hits detected on ticks: {self.tick_sl_hits}")
                self.logger.info(f"Take-Profit hits detected on ticks: {self.tick_tp_hits}")
                self.logger.info(f"Total SL/TP hits on ticks: {self.tick_sl_hits + self.tick_tp_hits}")
                self.logger.info("=" * 80)
                return False

            # Get next tick from global timeline
            next_tick = self.global_tick_timeline[self.global_tick_index]

            # Advance global time to this tick's timestamp
            self.current_time = next_tick.time
            # Update non-blocking snapshot as well
            self.current_time_snapshot = self.current_time

            # Set which symbol owns this tick (for has_data_at_current_time check)
            self.current_tick_symbol = next_tick.symbol

            # Update current tick for the symbol that owns this tick
            self.current_ticks[next_tick.symbol] = TickData(
                time=next_tick.time,
                bid=next_tick.bid,
                ask=next_tick.ask,
                last=next_tick.last,
                volume=next_tick.volume,
                spread=next_tick.spread
            )

            # Build candles from this tick in real-time
            if next_tick.symbol in self.candle_builders:
                # Use 'last' price if available, otherwise use 'bid'
                price = next_tick.last if next_tick.last > 0 else next_tick.bid
                self.candle_builders[next_tick.symbol].add_tick(price, next_tick.volume, next_tick.time)

            # Update floating P&L for all open positions
            # This ensures floating P&L is updated on every tick, not just when SL/TP is checked
            with self.position_lock:
                for position in self.positions.values():
                    self._update_position_profit(position)

            # Check SL/TP for positions of this symbol
            # Pass current time to avoid re-acquiring time_lock
            self._check_sl_tp_for_tick(next_tick.symbol, next_tick, self.current_time)

            # Advance index
            self.global_tick_index += 1

            # Print backtest results to console on EVERY tick
            progress_pct = 100.0 * self.global_tick_index / len(self.global_tick_timeline)

            # Get current statistics
            stats = self.get_statistics()
            total_trades = len(self.closed_trades)

            # Calculate win/loss
            wins = sum(1 for t in self.closed_trades if t['profit'] > 0)
            losses = sum(1 for t in self.closed_trades if t['profit'] < 0)
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

            # Calculate profit factor
            gross_profit = sum(t['profit'] for t in self.closed_trades if t['profit'] > 0)
            gross_loss = abs(sum(t['profit'] for t in self.closed_trades if t['profit'] < 0))
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)
            pf_display = f"{profit_factor:.2f}" if profit_factor != float('inf') else "∞"

            # Get open positions count
            open_positions = len(self.positions)

            # Calculate ETA (Estimated Time to Finish)
            eta_display = "calculating..."
            if hasattr(self, 'backtest_start_time') and self.global_tick_index > 100:
                import time
                elapsed_time = time.time() - self.backtest_start_time
                ticks_per_second = self.global_tick_index / elapsed_time
                remaining_ticks = len(self.global_tick_timeline) - self.global_tick_index
                eta_seconds = remaining_ticks / ticks_per_second if ticks_per_second > 0 else 0

                # Format ETA
                if eta_seconds < 60:
                    eta_display = f"{int(eta_seconds)}s"
                elif eta_seconds < 3600:
                    eta_display = f"{int(eta_seconds / 60)}m {int(eta_seconds % 60)}s"
                else:
                    hours = int(eta_seconds / 3600)
                    minutes = int((eta_seconds % 3600) / 60)
                    eta_display = f"{hours}h {minutes}m"

            import sys
            message = (
                f"[{progress_pct:5.1f}%] {self.current_time.strftime('%Y-%m-%d %H:%M')} | "
                f"Tick: {self.global_tick_index:,}/{len(self.global_tick_timeline):,} | "
                f"ETA: {eta_display:>10} | "
                f"Equity: ${stats['equity']:>10,.2f} | "
                f"P&L: ${stats['profit']:>8,.2f} ({stats['profit_percent']:>+6.2f}%) | "
                f"Floating: ${stats['floating_pnl']:>8,.2f} | "
                f"Trades: {total_trades:>4} ({wins}W/{losses}L) | "
                f"WR: {win_rate:>5.1f}% | "
                f"PF: {pf_display:>6} | "
                f"Open: {open_positions:>2}"
            )
            # Get terminal width, truncate message if needed, then pad to clear old text
            import shutil
            terminal_width = shutil.get_terminal_size(fallback=(120, 24)).columns
            if len(message) > terminal_width - 1:
                message = message[:terminal_width - 4] + "..."
            sys.stdout.write("\r" + message.ljust(terminal_width - 1))
            sys.stdout.flush()

            # Log progress periodically to file only (every 1,000 ticks)
            if self.global_tick_index % 1000 == 0:
                self.logger.info(
                    f"[TICK {self.global_tick_index:,}/{len(self.global_tick_timeline):,}] "
                    f"Progress: {progress_pct:.2f}% | Symbol: {next_tick.symbol} | "
                    f"Time: {self.current_time.strftime('%Y-%m-%d %H:%M:%S')} | "
                    f"Equity: ${stats['equity']:.2f} | P&L: ${stats['profit']:.2f} | "
                    f"Trades: {total_trades} ({wins}W/{losses}L)"
                )

            return True
        finally:
            import threading
            tid = threading.current_thread().name
            self.logger.info(f"[LOCK_DEBUG] {tid} [Broker:{self.instance_id}]: Releasing time_lock (advance_tick, index={self.global_tick_index})")
            self.time_lock.release()

    def _check_sl_tp_for_tick(self, symbol: str, tick: GlobalTick, current_time: datetime):
        """
        Check if any positions for this symbol hit SL/TP on this tick.

        Args:
            symbol: Symbol to check
            tick: The tick that just arrived
        """
        with self.position_lock:
            positions_to_close = []

            for ticket, position in self.positions.items():
                # Only check positions for this symbol
                if position.symbol != symbol:
                    continue

                # Check SL/TP hit
                if position.position_type == PositionType.BUY:
                    # For BUY: check if bid hit SL or TP
                    if position.sl > 0 and tick.bid <= position.sl:
                        # Stop loss hit
                        positions_to_close.append((ticket, tick.bid, 'SL'))
                    elif position.tp > 0 and tick.bid >= position.tp:
                        # Take profit hit
                        positions_to_close.append((ticket, tick.bid, 'TP'))

                elif position.position_type == PositionType.SELL:
                    # For SELL: check if ask hit SL or TP
                    if position.sl > 0 and tick.ask >= position.sl:
                        # Stop loss hit
                        positions_to_close.append((ticket, tick.ask, 'SL'))
                    elif position.tp > 0 and tick.ask <= position.tp:
                        # Take profit hit
                        positions_to_close.append((ticket, tick.ask, 'TP'))

            # Close positions that hit SL/TP
            for ticket, close_price, reason in positions_to_close:
                position = self.positions.get(ticket)
                if position:
                    # Track statistics
                    if reason == 'SL':
                        self.tick_sl_hits += 1
                    elif reason == 'TP':
                        self.tick_tp_hits += 1

                    self.logger.info(
                        f"[{position.symbol}] {reason} hit on tick at {tick.time.strftime('%Y-%m-%d %H:%M:%S')} | "
                        f"Ticket: {ticket} | Close price: {close_price:.5f} | "
                        f"Total {reason} hits: {self.tick_sl_hits if reason == 'SL' else self.tick_tp_hits}"
                    )
                    self._close_position_internal(ticket, close_price=close_price, close_time=current_time)

    def advance_time(self, symbol: str) -> bool:
        """
        DEPRECATED: This method is kept for backward compatibility.

        In the new architecture, time advancement is global (advance_global_time).
        This method now just checks if the symbol has more data.

        Args:
            symbol: Symbol to check

        Returns:
            True if symbol has more data, False otherwise
        """
        return self.has_more_data(symbol)

    def get_current_time(self) -> Optional[datetime]:
        """Get current simulated time."""
        with self.time_lock:
            return self.current_time

    def get_current_time_nonblocking(self) -> Optional[datetime]:
        """Get current simulated time snapshot without acquiring time_lock.

        This is safe for logging/time provider to avoid lock contention.
        """
        return self.current_time_snapshot

    def get_start_time(self) -> Optional[datetime]:
        """
        Get the earliest time from all loaded symbol data.
        This is the backtest start time.

        Returns:
            The earliest timestamp from all loaded symbols, or None if no data loaded
        """
        if not self.symbol_data:
            return None

        earliest_time = None
        for (symbol, timeframe), df in self.symbol_data.items():
            if len(df) > 0:
                first_time = df.iloc[0]['time']
                # Ensure timezone aware
                if first_time.tzinfo is None:
                    first_time = first_time.replace(tzinfo=timezone.utc)

                if earliest_time is None or first_time < earliest_time:
                    earliest_time = first_time

        return earliest_time

    def get_end_time(self) -> Optional[datetime]:
        """
        Get the latest time from all loaded symbol data.
        This is the backtest end time.

        Returns:
            The latest timestamp from all loaded symbols, or None if no data loaded
        """
        if not self.symbol_data:
            return None

        latest_time = None
        for (symbol, timeframe), df in self.symbol_data.items():
            if len(df) > 0:
                last_time = df.iloc[-1]['time']
                # Ensure timezone aware
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=timezone.utc)

                if latest_time is None or last_time > latest_time:
                    latest_time = last_time

        return latest_time

    def get_progress(self, symbol: str) -> Tuple[int, int]:
        """
        Get progress for a symbol.

        Args:
            symbol: Symbol name

        Returns:
            Tuple of (current_index, total_bars)
        """
        if symbol not in self.current_indices:
            return (0, 0)

        # Get M1 data for this symbol
        m1_data_key = (symbol, 'M1')
        if m1_data_key not in self.symbol_data:
            return (0, 0)

        m1_data = self.symbol_data[m1_data_key]
        return (self.current_indices[symbol], len(m1_data))

    def is_data_available(self, symbol: str) -> bool:
        """
        Check if more data is available for a symbol.

        TICK MODE: Checks if there are more ticks in the global timeline
        CANDLE MODE: Checks if symbol has more M1 candles
        """
        # TICK MODE: Check global tick timeline
        if self.use_tick_data:
            # In tick mode, all symbols share the same global timeline
            return self.global_tick_index < len(self.global_tick_timeline)

        # CANDLE MODE: Check per-symbol M1 data
        if symbol not in self.current_indices:
            return False

        # Get M1 data for this symbol
        m1_data_key = (symbol, 'M1')
        if m1_data_key not in self.symbol_data:
            return False

        m1_data = self.symbol_data[m1_data_key]
        return self.current_indices[symbol] < len(m1_data) - 1

    # ========================================================================
    # Statistics Methods
    # ========================================================================

    def get_statistics(self) -> Dict:
        """Get backtesting statistics."""
        with self.position_lock:
            open_positions = len(self.positions)
            floating_pnl = sum(pos.profit for pos in self.positions.values())

        return {
            'balance': self.balance,
            'equity': self.balance + floating_pnl,
            'profit': self.balance - self.initial_balance,
            'profit_percent': ((self.balance - self.initial_balance) / self.initial_balance) * 100,
            'open_positions': open_positions,
            'floating_pnl': floating_pnl,
        }

    def get_closed_trades(self) -> List[Dict]:
        """Get list of all closed trades."""
        return self.closed_trades.copy()

