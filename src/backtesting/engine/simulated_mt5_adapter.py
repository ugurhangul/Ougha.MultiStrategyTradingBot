"""
Simulated MT5 Adapter.

Provides MT5-compatible functions that delegate to SimulatedBroker.
This allows OrderExecutor to work without modification in backtesting mode.
"""
from typing import Optional, NamedTuple
from datetime import datetime

from src.backtesting.engine.simulated_broker import SimulatedBroker
from src.models.data_models import PositionType


# MT5 Constants (matching real MT5)
TRADE_ACTION_DEAL = 1
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TIME_GTC = 0
TRADE_RETCODE_DONE = 10009


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


class SimulatedMT5Adapter:
    """
    Adapter that makes SimulatedBroker compatible with MT5 API.
    
    This allows existing code that calls mt5.order_send(), mt5.symbol_info(), etc.
    to work with SimulatedBroker without modification.
    """
    
    def __init__(self, broker: SimulatedBroker):
        """
        Initialize adapter.
        
        Args:
            broker: SimulatedBroker instance
        """
        self.broker = broker
        self._last_error = (0, "")
    
    def order_send(self, request: dict) -> Optional[OrderSendResult]:
        """
        Send order (MT5-compatible interface).
        
        Args:
            request: Order request dictionary
            
        Returns:
            OrderSendResult or None
        """
        # Extract parameters from request
        symbol = request.get('symbol')
        volume = request.get('volume')
        order_type = request.get('type')
        sl = request.get('sl', 0.0)
        tp = request.get('tp', 0.0)
        magic = request.get('magic', 0)
        comment = request.get('comment', '')
        
        # Convert MT5 order type to PositionType
        if order_type == ORDER_TYPE_BUY:
            position_type = PositionType.BUY
        elif order_type == ORDER_TYPE_SELL:
            position_type = PositionType.SELL
        else:
            self._last_error = (10013, "Invalid request")
            return None
        
        # Place order through simulated broker
        result = self.broker.place_market_order(
            symbol=symbol,
            order_type=position_type,
            volume=volume,
            sl=sl,
            tp=tp,
            magic_number=magic,
            comment=comment
        )
        
        if not result.success:
            self._last_error = (result.retcode, result.comment)
            return None
        
        # Return MT5-compatible result
        return OrderSendResult(
            retcode=result.retcode,
            deal=result.order,  # In MT5, deal and order can be same for market orders
            order=result.order,
            volume=volume,
            price=result.price,
            bid=result.price,  # Simplified
            ask=result.price,  # Simplified
            comment=result.comment,
            request_id=0,
            retcode_external=0
        )
    
    def terminal_info(self):
        """Check if terminal is connected (always True in simulation)."""
        return True  # Non-None value means connected
    
    def last_error(self):
        """Get last error."""
        return self._last_error
    
    def symbol_info(self, symbol: str):
        """Get symbol info (returns a mock object with attributes)."""
        info_dict = self.broker.get_symbol_info(symbol)
        if not info_dict:
            return None
        
        # Create a simple object with attributes matching MT5 symbol_info
        class SymbolInfo:
            def __init__(self, data):
                for key, value in data.items():
                    setattr(self, key, value)
        
        return SymbolInfo(info_dict)
    
    def symbol_info_tick(self, symbol: str):
        """Get current tick (returns a mock object with bid/ask)."""
        bid = self.broker.get_current_price(symbol, 'bid')
        ask = self.broker.get_current_price(symbol, 'ask')
        
        if bid is None or ask is None:
            return None
        
        class TickInfo:
            def __init__(self, bid_price, ask_price):
                self.bid = bid_price
                self.ask = ask_price
                self.last = bid_price
                self.volume = 0
                self.time = int(datetime.now().timestamp())
        
        return TickInfo(bid, ask)

