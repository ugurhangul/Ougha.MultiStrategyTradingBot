"""
MT5 position information provider.
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from src.models.data_models import PositionInfo, PositionType
from src.utils.logging import TradingLogger
from src.constants import HISTORY_LOOKBACK_DAYS


class PositionProvider:
    """Provides position information from MT5"""

    def __init__(self, connection_manager, logger: TradingLogger):
        """
        Initialize position provider.

        Args:
            connection_manager: ConnectionManager instance
            logger: Logger instance
        """
        self.connection_manager = connection_manager
        self.logger = logger

    def get_positions(self, symbol: Optional[str] = None, magic_number: Optional[int] = None) -> List[PositionInfo]:
        """
        Get open positions.

        Args:
            symbol: Filter by symbol (optional)
            magic_number: Filter by magic number (optional)

        Returns:
            List of PositionInfo objects
        """
        if not self.connection_manager.is_connected:
            return []

        try:
            # Get all positions or filter by symbol
            if symbol:
                positions = mt5.positions_get(symbol=symbol)
            else:
                positions = mt5.positions_get()

            if positions is None:
                return []

            result = []
            for pos in positions:
                # Filter by magic number if specified
                if magic_number is not None and pos.magic != magic_number:
                    continue

                pos_info = PositionInfo(
                    ticket=pos.ticket,
                    symbol=pos.symbol,
                    position_type=PositionType.BUY if pos.type == mt5.ORDER_TYPE_BUY else PositionType.SELL,
                    volume=pos.volume,
                    open_price=pos.price_open,
                    current_price=pos.price_current,
                    sl=pos.sl,
                    tp=pos.tp,
                    profit=pos.profit,
                    open_time=datetime.fromtimestamp(pos.time),
                    magic_number=pos.magic,
                    comment=pos.comment
                )
                result.append(pos_info)

            return result

        except Exception as e:
            self.logger.error(f"Error getting positions: {e}")
            return []

    def get_closed_position_info(self, ticket: int) -> Optional[Tuple[str, float, float, str]]:
        """
        Get information about a closed position from history.

        Args:
            ticket: Position ticket

        Returns:
            Tuple of (symbol, profit, volume, comment) or None if not found
        """
        if not self.connection_manager.is_connected:
            return None

        try:
            # Request history for the configured lookback period
            from_date = datetime.now() - timedelta(days=HISTORY_LOOKBACK_DAYS)
            to_date = datetime.now()

            # Get history deals
            if not mt5.history_deals_get(from_date, to_date):
                self.logger.warning(f"Failed to get history deals for ticket {ticket}")
                return None

            # Get all deals
            deals = mt5.history_deals_get(from_date, to_date)
            if deals is None or len(deals) == 0:
                return None

            # Find both IN and OUT deals for this position
            # MT5 overwrites the comment on ENTRY_OUT with [sl X.XXX] or [tp X.XXX]
            # The original strategy comment is preserved in the ENTRY_IN deal
            in_deal = None
            out_deal = None

            for deal in deals:
                if deal.position_id == ticket:
                    if deal.entry == mt5.DEAL_ENTRY_IN:
                        in_deal = deal
                    elif deal.entry == mt5.DEAL_ENTRY_OUT:
                        out_deal = deal

            # We need the OUT deal for profit/volume, and IN deal for the original comment
            if out_deal is not None:
                symbol = out_deal.symbol
                profit = out_deal.profit
                volume = out_deal.volume

                # Get comment from IN deal if available (preserves original strategy comment)
                # Otherwise fall back to OUT deal comment
                if in_deal is not None:
                    comment = in_deal.comment if hasattr(in_deal, 'comment') else ""
                else:
                    comment = out_deal.comment if hasattr(out_deal, 'comment') else ""

                return (symbol, profit, volume, comment)

            return None

        except Exception as e:
            self.logger.error(f"Error getting closed position info for ticket {ticket}: {e}")
            return None

