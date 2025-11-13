"""
Position modification and closing logic.
"""

import MetaTrader5 as mt5
from typing import Optional

from src.core.mt5_connector import MT5Connector
from src.execution.position_persistence import PositionPersistence
from src.execution.filling_mode_resolver import FillingModeResolver
from src.utils.logging import TradingLogger
from src.utils.autotrading_cooldown import AutoTradingCooldown
from src.utils.price_normalization_service import PriceNormalizationService
from src.execution.order_management.market_checker import MarketChecker
from src.constants import (
    DEFAULT_PRICE_DEVIATION,
    RETCODE_MARKET_CLOSED,
    RETCODE_AUTOTRADING_DISABLED,
)


class PositionModifier:
    """Handles position modification and closing"""

    def __init__(self, connector: MT5Connector, magic_number: int, trade_comment: str,
                 persistence: PositionPersistence, cooldown: AutoTradingCooldown,
                 price_normalizer: PriceNormalizationService, logger: TradingLogger):
        """
        Initialize position modifier.

        Args:
            connector: MT5 connector instance
            magic_number: Magic number for orders
            trade_comment: Comment for trades
            persistence: Position persistence instance
            cooldown: AutoTrading cooldown manager
            price_normalizer: Price normalization service
            logger: Logger instance
        """
        self.connector = connector
        self.magic_number = magic_number
        self.trade_comment = trade_comment
        self.persistence = persistence
        self.cooldown = cooldown
        self.price_normalizer = price_normalizer
        self.logger = logger
        self.deviation = DEFAULT_PRICE_DEVIATION

        # Initialize specialized components
        self.market_checker = MarketChecker(connector, cooldown, logger)
        self.filling_mode_resolver = FillingModeResolver(logger)

    def modify_position(self, ticket: int, sl: Optional[float] = None,
                       tp: Optional[float] = None):
        """
        Modify position SL/TP.

        Args:
            ticket: Position ticket
            sl: New stop loss (None to keep current)
            tp: New take profit (None to keep current)

        Returns:
            True if successful
            False if failed (permanent error)
            "RETRY" if temporarily blocked by server (should retry later)
        """
        try:
            # Get current position first to get symbol
            position = mt5.positions_get(ticket=ticket)
            if not position or len(position) == 0:
                self.logger.error(f"Position {ticket} not found")
                return False

            pos = position[0]
            symbol = pos.symbol

            # Check if market was closed and if it's time to verify if it reopened
            if self.cooldown.is_market_closed() and self.cooldown.should_check_market_status():
                self.market_checker.check_market_reopened(symbol)

            # Check if in cooldown period (includes market closed state)
            if self.cooldown.is_in_cooldown():
                # Return RETRY to keep position in tracking
                return "RETRY"

            # Use current values if not specified
            new_sl = sl if sl is not None else pos.sl
            new_tp = tp if tp is not None else pos.tp

            # Normalize prices
            # Ensure values are always float type for MT5 compatibility
            new_sl = self.price_normalizer.normalize_price(symbol, new_sl) if new_sl > 0 else 0.0
            new_tp = self.price_normalizer.normalize_price(symbol, new_tp) if new_tp > 0 else 0.0

            # Check if values actually changed after normalization
            # MT5 returns error 10025 "No changes" if SL/TP are identical
            # Use tolerance-based comparison to avoid floating-point precision issues
            symbol_info = self.connector.get_symbol_info(symbol)
            if symbol_info is None:
                self.logger.error(f"Failed to get symbol info for modifying position {ticket}")
                return False

            point = symbol_info['point']
            tolerance = point * 0.1  # Use 0.1 point as tolerance

            sl_unchanged = abs(new_sl - pos.sl) < tolerance
            tp_unchanged = abs(new_tp - pos.tp) < tolerance

            if sl_unchanged and tp_unchanged:
                self.logger.debug(
                    f"Position {ticket} modification skipped - no changes after normalization "
                    f"(SL: {new_sl:.5f}, TP: {new_tp:.5f})",
                    symbol
                )
                return True  # Return True since position is already in desired state

            # Get current market price for logging
            current_price = self.connector.get_current_price(symbol, 'bid' if pos.type == mt5.POSITION_TYPE_BUY else 'ask')
            if current_price is None:
                self.logger.error(f"Failed to get current price for modifying position {ticket}")
                return False

            # Log modification details
            self.logger.debug(
                f"Modifying position {ticket}: Current price={current_price:.5f}, "
                f"SL: {pos.sl:.5f} -> {new_sl:.5f}, TP: {pos.tp:.5f} -> {new_tp:.5f}",
                symbol
            )

            # Create modification request
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": symbol,
                "sl": new_sl,
                "tp": new_tp,
            }

            # Send modification
            result = mt5.order_send(request)

            if result is None:
                # Get last error from MT5
                last_error = mt5.last_error()
                self.logger.error(
                    f"Modify failed for position {ticket}, no result returned from MT5. "
                    f"Last error: {last_error}",
                    symbol
                )
                return False

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                # Log additional context for common errors
                if result.retcode == RETCODE_MARKET_CLOSED:
                    self.logger.warning(
                        f"Modify blocked - Market is closed (retcode {RETCODE_MARKET_CLOSED}) for position {ticket}",
                        symbol
                    )
                    # Activate market closed state to pause all trading
                    self.cooldown.activate_market_closed(symbol)
                    # Return RETRY to keep position in tracking
                    return "RETRY"
                elif result.retcode == 10016:  # Invalid stops
                    self.logger.error(
                        f"Modify failed for position {ticket}: retcode={result.retcode}, "
                        f"comment='{result.comment}'",
                        symbol
                    )
                    point = symbol_info['point']
                    stops_level = symbol_info.get('stops_level', 0)
                    freeze_level = symbol_info.get('freeze_level', 0)

                    sl_distance = abs(current_price - new_sl) if new_sl > 0 else 0
                    tp_distance = abs(current_price - new_tp) if new_tp > 0 else 0
                    sl_distance_points = sl_distance / point if point > 0 else 0
                    tp_distance_points = tp_distance / point if point > 0 else 0

                    self.logger.error(
                        f"  stops_level={stops_level} pts, freeze_level={freeze_level} pts",
                        symbol
                    )
                    self.logger.error(
                        f"  SL distance: {sl_distance_points:.0f} pts, TP distance: {tp_distance_points:.0f} pts",
                        symbol
                    )
                elif result.retcode == RETCODE_AUTOTRADING_DISABLED:
                    self.logger.warning(
                        f"Modify blocked - AutoTrading disabled by server (retcode {RETCODE_AUTOTRADING_DISABLED})",
                        symbol
                    )
                    # Activate cooldown to prevent spam
                    self.cooldown.activate_cooldown(f"AutoTrading disabled by server (error {RETCODE_AUTOTRADING_DISABLED})")
                    # Return RETRY to keep position in tracking
                    return "RETRY"
                elif result.retcode == 10027:  # Autotrading disabled by terminal
                    self.logger.error(
                        f"Modify failed for position {ticket}: retcode={result.retcode}, "
                        f"comment='{result.comment}'",
                        symbol
                    )
                    self.logger.error("  Autotrading is disabled on this account", symbol)
                elif result.retcode == 10025:  # No changes
                    self.logger.debug(
                        f"Modify skipped for position {ticket}: No changes detected by broker",
                        symbol
                    )
                    # Return True since position is already in desired state
                    return True
                else:
                    self.logger.error(
                        f"Modify failed for position {ticket}: retcode={result.retcode}, "
                        f"comment='{result.comment}'",
                        symbol
                    )

                return False

            self.logger.debug(
                f"Position {ticket} modified - SL: {new_sl:.5f} (was {pos.sl:.5f}), TP: {new_tp:.5f} (was {pos.tp:.5f})",
                symbol
            )

            # Update position in persistence
            self.persistence.update_position(ticket, sl=new_sl, tp=new_tp)

            return True

        except Exception as e:
            self.logger.error(f"Error modifying position {ticket}: {e}")
            return False

    def close_position(self, ticket: int) -> bool:
        """
        Close a position.

        Args:
            ticket: Position ticket

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get position
            position = mt5.positions_get(ticket=ticket)
            if not position or len(position) == 0:
                self.logger.error(f"Position {ticket} not found")
                return False

            pos = position[0]
            symbol = pos.symbol
            volume = pos.volume

            # Determine close order type (opposite of position type)
            if pos.type == mt5.ORDER_TYPE_BUY:
                order_type = mt5.ORDER_TYPE_SELL
                price = self.connector.get_current_price(symbol, 'bid')
            else:
                order_type = mt5.ORDER_TYPE_BUY
                price = self.connector.get_current_price(symbol, 'ask')

            if price is None:
                self.logger.error(f"Failed to get price for closing {ticket}")
                return False

            # Get symbol info to determine filling mode
            symbol_info = self.connector.get_symbol_info(symbol)
            if symbol_info is None:
                self.logger.error(f"Failed to get symbol info for closing {ticket}")
                return False

            filling_mode = self.filling_mode_resolver.resolve_filling_mode(symbol_info, symbol)

            # Create close request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "price": price,
                "deviation": self.deviation,
                "magic": self.magic_number,
                "comment": f"Close {self.trade_comment}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }

            # Send close order
            result = mt5.order_send(request)

            if result is None:
                self.logger.error(f"Close failed for position {ticket}, no result")
                return False

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                # Check for market closed error
                if result.retcode == RETCODE_MARKET_CLOSED:
                    self.logger.warning(
                        f"Close blocked - Market is closed (retcode {RETCODE_MARKET_CLOSED}) for position {ticket}",
                        symbol
                    )
                    # Activate market closed state to pause all trading
                    self.cooldown.activate_market_closed(symbol)
                    return False

                # Other errors
                self.logger.error(
                    f"Close failed for position {ticket}: {result.retcode} - {result.comment}"
                )
                return False

            self.logger.info(f"Position {ticket} closed at {price:.5f}", symbol)

            # Remove position from persistence
            self.persistence.remove_position(ticket)

            return True

        except Exception as e:
            self.logger.error(f"Error closing position {ticket}: {e}")
            return False

