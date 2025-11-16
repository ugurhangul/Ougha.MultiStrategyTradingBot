"""
MT5 Monkey Patch for Backtesting.

Replaces MT5 module functions with simulated versions during backtesting.
This allows existing code (OrderExecutor, strategies) to work unchanged.
"""
import MetaTrader5 as mt5
from typing import Optional, NamedTuple

from src.backtesting.engine.simulated_broker import SimulatedBroker
from src.models.data_models import PositionType


# Store original MT5 functions
_original_order_send = mt5.order_send
_original_terminal_info = mt5.terminal_info
_original_last_error = mt5.last_error
_original_positions_get = mt5.positions_get
_original_symbol_info_tick = mt5.symbol_info_tick

# Global reference to SimulatedBroker (set by apply_mt5_patch)
_simulated_broker: Optional[SimulatedBroker] = None


class OrderSendResult(NamedTuple):
    """Result of order_send (matching MT5 structure)."""
    retcode: int
    deal: int
    order: int
    volume: float
    price: float
    bid: float
    ask: float
    comment: str
    request_id: int
    retcode_external: int


def _patched_order_send(request: dict) -> Optional[OrderSendResult]:
    """
    Patched version of mt5.order_send() that uses SimulatedBroker.

    Handles both new orders and position modifications.

    Args:
        request: Order request dictionary

    Returns:
        OrderSendResult or None
    """
    if _simulated_broker is None:
        raise RuntimeError("SimulatedBroker not set. Call apply_mt5_patch() first.")

    # Check action type
    action = request.get('action')

    # Handle position modification (TRADE_ACTION_SLTP)
    if action == mt5.TRADE_ACTION_SLTP:
        ticket = request.get('position')
        sl = request.get('sl')
        tp = request.get('tp')

        # Modify position through simulated broker
        success = _simulated_broker.modify_position(ticket=ticket, sl=sl, tp=tp)

        if not success:
            return None

        # Return MT5-compatible result for modification
        return OrderSendResult(
            retcode=10009,  # TRADE_RETCODE_DONE
            deal=0,
            order=0,
            volume=0.0,
            price=0.0,
            bid=0.0,
            ask=0.0,
            comment="Position modified",
            request_id=0,
            retcode_external=0
        )

    # Handle new order (TRADE_ACTION_DEAL)
    # Extract parameters from request
    symbol = request.get('symbol')
    volume = request.get('volume')
    order_type = request.get('type')
    sl = request.get('sl', 0.0)
    tp = request.get('tp', 0.0)
    magic = request.get('magic', 0)
    comment = request.get('comment', '')

    # Convert MT5 order type to PositionType
    if order_type == mt5.ORDER_TYPE_BUY:
        position_type = PositionType.BUY
    elif order_type == mt5.ORDER_TYPE_SELL:
        position_type = PositionType.SELL
    else:
        return None

    # Place order through simulated broker
    result = _simulated_broker.place_market_order(
        symbol=symbol,
        order_type=position_type,
        volume=volume,
        sl=sl,
        tp=tp,
        magic_number=magic,
        comment=comment
    )

    if not result.success:
        return None

    # Return MT5-compatible result
    return OrderSendResult(
        retcode=result.retcode,
        deal=result.order,
        order=result.order,
        volume=volume,
        price=result.price,
        bid=result.price,
        ask=result.price,
        comment=result.comment,
        request_id=0,
        retcode_external=0
    )


def _patched_terminal_info():
    """Patched version of mt5.terminal_info() - always returns True in backtest."""
    return True  # Non-None value means connected


def _patched_last_error():
    """Patched version of mt5.last_error() - returns (0, 'Success') in backtest."""
    return (0, "Success")


def _patched_positions_get(ticket: Optional[int] = None, symbol: Optional[str] = None, group: Optional[str] = None):
    """
    Patched version of mt5.positions_get() that uses SimulatedBroker.

    Args:
        ticket: Position ticket (optional)
        symbol: Symbol name (optional)
        group: Symbol group (optional)

    Returns:
        Tuple of position objects (matching MT5 structure)
    """
    if _simulated_broker is None:
        raise RuntimeError("SimulatedBroker not set. Call apply_mt5_patch() first.")

    # Get positions from simulated broker
    if ticket is not None:
        # Get specific position by ticket
        positions = _simulated_broker.get_positions()
        matching = [p for p in positions if p.ticket == ticket]
        if not matching:
            return ()  # Empty tuple if not found

        # Convert PositionInfo to MT5-compatible object
        pos = matching[0]

        # Create a simple object with MT5 position attributes
        class MT5Position:
            def __init__(self, pos_info):
                self.ticket = pos_info.ticket
                self.symbol = pos_info.symbol
                self.type = mt5.POSITION_TYPE_BUY if pos_info.position_type == PositionType.BUY else mt5.POSITION_TYPE_SELL
                self.volume = pos_info.volume
                self.price_open = pos_info.open_price
                self.price_current = pos_info.current_price
                self.sl = pos_info.sl
                self.tp = pos_info.tp
                self.profit = pos_info.profit
                self.time = int(pos_info.open_time.timestamp())
                self.magic = pos_info.magic_number
                self.comment = pos_info.comment

        return (MT5Position(pos),)

    elif symbol is not None:
        # Get positions for specific symbol
        positions = _simulated_broker.get_positions(symbol=symbol)
    else:
        # Get all positions
        positions = _simulated_broker.get_positions()

    # Convert all positions to MT5-compatible objects
    class MT5Position:
        def __init__(self, pos_info):
            self.ticket = pos_info.ticket
            self.symbol = pos_info.symbol
            self.type = mt5.POSITION_TYPE_BUY if pos_info.position_type == PositionType.BUY else mt5.POSITION_TYPE_SELL
            self.volume = pos_info.volume
            self.price_open = pos_info.open_price
            self.price_current = pos_info.current_price
            self.sl = pos_info.sl
            self.tp = pos_info.tp
            self.profit = pos_info.profit
            self.time = int(pos_info.open_time.timestamp())
            self.magic = pos_info.magic_number
            self.comment = pos_info.comment

    return tuple(MT5Position(p) for p in positions)


def _patched_symbol_info_tick(symbol: str):
    """
    Patched version of mt5.symbol_info_tick() that uses SimulatedBroker.

    This is critical for currency conversion during backtesting.
    The CurrencyConversionService uses mt5.symbol_info_tick() to get
    conversion rates for different currency pairs.

    Args:
        symbol: Symbol name

    Returns:
        Tick info object with bid/ask prices or None
    """
    if _simulated_broker is None:
        raise RuntimeError("SimulatedBroker not set. Call apply_mt5_patch() first.")

    # Get current prices from simulated broker
    bid = _simulated_broker.get_current_price(symbol, 'bid')
    ask = _simulated_broker.get_current_price(symbol, 'ask')

    if bid is None or ask is None:
        return None

    # Create tick info object matching MT5 structure
    class TickInfo:
        def __init__(self, bid_price, ask_price):
            self.bid = bid_price
            self.ask = ask_price
            self.last = bid_price
            self.volume = 0
            self.time = int(_simulated_broker.get_current_time().timestamp())

    return TickInfo(bid, ask)


def apply_mt5_patch(broker: SimulatedBroker):
    """
    Apply monkey patch to MT5 module to use SimulatedBroker.

    This replaces mt5.order_send(), mt5.terminal_info(), mt5.last_error(),
    mt5.positions_get(), and mt5.symbol_info_tick() with simulated versions
    that work with the backtesting engine.

    Args:
        broker: SimulatedBroker instance to use for order execution
    """
    global _simulated_broker
    _simulated_broker = broker

    # Replace MT5 functions with patched versions
    mt5.order_send = _patched_order_send
    mt5.terminal_info = _patched_terminal_info
    mt5.last_error = _patched_last_error
    mt5.positions_get = _patched_positions_get
    mt5.symbol_info_tick = _patched_symbol_info_tick


def restore_mt5_functions():
    """
    Restore original MT5 functions.

    Call this after backtesting to restore normal MT5 functionality.
    """
    global _simulated_broker
    _simulated_broker = None

    # Restore original MT5 functions
    mt5.order_send = _original_order_send
    mt5.terminal_info = _original_terminal_info
    mt5.last_error = _original_last_error
    mt5.positions_get = _original_positions_get
    mt5.symbol_info_tick = _original_symbol_info_tick

