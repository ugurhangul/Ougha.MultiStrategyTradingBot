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

        # Current simulated time
        self.current_time: Optional[datetime] = None
        self.time_lock = threading.Lock()
        
        # Trading status
        self.autotrading_enabled = True
        self.trading_enabled_symbols: Dict[str, bool] = {}  # symbol -> enabled
        
        # Connection status
        self.is_connected = True

        # Trade history for results analysis
        self.closed_trades: List[Dict] = []  # List of closed trade records

        self.logger.info(f"SimulatedBroker initialized with balance: ${initial_balance:,.2f}")
    
    def load_symbol_data(self, symbol: str, data: pd.DataFrame, symbol_info: Dict, timeframe: str = "M1"):
        """
        Load historical data for a symbol and timeframe.

        Args:
            symbol: Symbol name
            data: DataFrame with columns [time, open, high, low, close, volume]
            symbol_info: Dictionary with symbol information (point, digits, etc.)
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
            with self.time_lock:
                self.current_time = earliest_bar_time
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

        Returns pre-loaded data for the requested timeframe up to current simulation time.

        Args:
            symbol: Symbol name
            timeframe: Timeframe (e.g., 'M1', 'M5', 'M15', 'H1', 'H4')
            count: Number of candles to return

        Returns:
            DataFrame with OHLC data or None
        """
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

        Args:
            symbol: Symbol name
            timeframe: Timeframe (e.g., 'M1', 'M5', 'M15') or empty string for M1

        Returns:
            CandleData or None
        """
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
        with self.position_lock:
            return self._close_position_internal(ticket)

    def _close_position_internal(self, ticket: int) -> bool:
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
                self._close_position_internal(ticket)

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

        Uses the high/low prices of the current M1 bar to detect SL/TP hits
        that may have occurred during the bar, not just at the close.

        This is more realistic than only checking the close price, as it
        accounts for price wicks that touch SL/TP levels.

        Returns:
            True if SL or TP was hit
        """
        # Get the current M1 candle for intra-bar high/low
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
            True if symbol has a bar at current_time, False otherwise
        """
        # OPTIMIZATION #3b: Lock-free read from stable buffer
        # No lock needed - we read from the 'current' buffer which is stable
        # The swap happens atomically, so we always see a consistent state
        return symbol in self.symbols_with_data_current

    def has_more_data(self, symbol: str) -> bool:
        """
        Check if a symbol has any more data available.

        OPTIMIZATION #1: Uses cached data length for fast check.

        Args:
            symbol: Symbol to check

        Returns:
            True if symbol has more data, False if at end
        """
        with self.time_lock:
            if symbol not in self.current_indices:
                return False

            # Fast bounds check using cached length
            current_idx = self.current_indices[symbol]
            data_length = self.symbol_data_lengths.get(symbol, 0)

            # Check if there's more data after current index
            return current_idx < data_length - 1

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
        """Check if more data is available for a symbol."""
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

