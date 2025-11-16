"""
Order execution logic.
"""

import MetaTrader5 as mt5
from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone

from src.models.data_models import PositionType, TradeSignal, PositionInfo
from src.core.mt5_connector import MT5Connector
from src.execution.position_persistence import PositionPersistence
from src.execution.filling_mode_resolver import FillingModeResolver
from src.utils.logging import TradingLogger
from src.utils.autotrading_cooldown import AutoTradingCooldown
from src.utils.price_normalization_service import PriceNormalizationService
from src.execution.order_management.stop_validator import StopValidator
from src.execution.order_management.market_checker import MarketChecker
from src.constants import (
    DEFAULT_PRICE_DEVIATION,
    DEFAULT_RISK_REWARD_RATIO,
    RETCODE_MARKET_CLOSED,
    RETCODE_AUTOTRADING_DISABLED,
    RETCODE_ONLY_CLOSE_ALLOWED,
)

if TYPE_CHECKING:
    from src.risk.risk_manager import RiskManager


class OrderExecutor:
    """Handles order execution logic"""

    def __init__(self, connector: MT5Connector, magic_number: int,
                 persistence: PositionPersistence, cooldown: AutoTradingCooldown,
                 price_normalizer: PriceNormalizationService, logger: TradingLogger,
                 risk_manager: Optional['RiskManager'] = None):
        """
        Initialize order executor.

        Args:
            connector: MT5 connector instance
            magic_number: Magic number for orders
            persistence: Position persistence instance
            cooldown: AutoTrading cooldown manager
            price_normalizer: Price normalization service
            logger: Logger instance
            risk_manager: Risk manager instance (optional, for position limit checks)
        """
        self.connector = connector
        self.magic_number = magic_number
        self.persistence = persistence
        self.cooldown = cooldown
        self.price_normalizer = price_normalizer
        self.logger = logger
        self.risk_manager = risk_manager
        self.deviation = DEFAULT_PRICE_DEVIATION

        # Initialize specialized components
        self.stop_validator = StopValidator(connector, price_normalizer, logger)
        self.market_checker = MarketChecker(connector, cooldown, logger)
        self.filling_mode_resolver = FillingModeResolver(logger)

    def execute_signal(self, signal: TradeSignal) -> Optional[int]:
        """
        Execute a trade signal.

        Args:
            signal: TradeSignal object

        Returns:
            Ticket number if successful, None otherwise
        """
        symbol = signal.symbol

        # Check if market was closed and if it's time to verify if it reopened
        if self.cooldown.is_market_closed() and self.cooldown.should_check_market_status():
            self.market_checker.check_market_reopened(symbol)

        # Check if in cooldown period (includes market closed state)
        if self.cooldown.is_in_cooldown():
            remaining = self.cooldown.get_remaining_time()
            if remaining:
                minutes = int(remaining.total_seconds() / 60)
                seconds = int(remaining.total_seconds() % 60)
                self.logger.debug(
                    f"Trade rejected - cooldown active ({minutes}m {seconds}s remaining)",
                    symbol
                )
            return None

        # Check if AutoTrading is enabled in terminal
        if not self.connector.is_autotrading_enabled():
            self.logger.trade_error(
                symbol=symbol,
                error_type="AutoTrading Check",
                error_message="AutoTrading is DISABLED in MT5 terminal",
                context={"action": "Trade rejected - Enable AutoTrading in MT5"}
            )
            return None

        # Check if trading is enabled for this symbol
        if not self.connector.is_trading_enabled(symbol):
            self.logger.symbol_condition_warning(
                symbol=symbol,
                condition="Trading Disabled",
                details="Trading is disabled for this symbol in MT5 - Trade rejected"
            )
            return None

        # Check position limits (1 position per strategy and direction)
        if self.risk_manager is not None:
            # Parse strategy type and range_id from signal comment
            # New comment format: "STRATEGY|RANGE_ID|VALIDATIONS" for TB/FB or "STRATEGY|VALIDATIONS" for HFT
            # Examples: "HFT|MV" or "TB|15M_1M|BV" or "FB|4H_5M|RT"
            strategy_type = None
            range_id = None

            if signal.comment:
                parts = signal.comment.split('|')
                if len(parts) > 0 and parts[0]:
                    strategy_type = parts[0]  # "HFT", "TB", "FB"
                # For TB/FB: parts[1] is range_id, parts[2] is confirmations
                # For HFT: parts[1] is confirmations (no range_id)
                if len(parts) >= 3 and strategy_type in ["TB", "FB"]:
                    range_id = parts[1] if parts[1] else None  # "15M_1M", "4H_5M", etc.

            # Check if we can open a new position
            can_open, reason = self.risk_manager.can_open_new_position(
                magic_number=self.magic_number,
                symbol=symbol,
                position_type=signal.signal_type,
                all_confirmations_met=False,  # TODO: Extract from signal if needed
                strategy_type=strategy_type,
                range_id=range_id
            )

            if not can_open:
                self.logger.warning(
                    f"Position limit check failed: {reason}",
                    symbol
                )
                return None

        # Normalize prices and volume
        sl = self.price_normalizer.normalize_price(symbol, signal.stop_loss)
        volume = self.price_normalizer.normalize_volume(symbol, signal.lot_size)

        # Determine order type and get current market price
        if signal.signal_type == PositionType.BUY:
            order_type = mt5.ORDER_TYPE_BUY
            price = self.connector.get_current_price(symbol, 'ask')
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = self.connector.get_current_price(symbol, 'bid')

        if price is None:
            self.logger.trade_error(
                symbol=symbol,
                error_type="Price Retrieval",
                error_message="Failed to get current market price",
                context={
                    "order_type": "BUY" if signal.signal_type == PositionType.BUY else "SELL",
                    "action": "Trade rejected"
                }
            )
            return None

        # PRE-TRADE RISK VALIDATION (TIER 1): Reject trade if individual risk exceeds configured limit
        if self.risk_manager is not None and volume > 0:
            # Validate actual risk before executing trade
            risk_valid = self._validate_pre_trade_risk(symbol, volume, price, sl)
            if not risk_valid:
                return None

        # PORTFOLIO RISK VALIDATION (TIER 2): Reject trade if total portfolio risk exceeds limit
        if self.risk_manager is not None and volume > 0:
            # Validate total portfolio risk including this new trade
            portfolio_risk_valid = self._validate_portfolio_risk(symbol, volume, price, sl)
            if not portfolio_risk_valid:
                return None

        # Recalculate TP based on actual execution price (market price)
        # This ensures the R:R ratio is maintained with the actual entry
        # Use the configured R:R ratio from constants
        risk = abs(price - sl)
        reward = risk * DEFAULT_RISK_REWARD_RATIO

        self.logger.debug(f"TP Calculation: Entry={price:.5f}, SL={sl:.5f}, Risk={risk:.5f}, Reward={reward:.5f}, R:R={DEFAULT_RISK_REWARD_RATIO}", symbol)

        if signal.signal_type == PositionType.BUY:
            tp = price + reward
        else:
            tp = price - reward

        # Normalize the recalculated TP
        tp = self.price_normalizer.normalize_price(symbol, tp)

        self.logger.debug(f"Final TP: {tp:.5f} (before normalize: {price + reward if signal.signal_type == PositionType.BUY else price - reward:.5f})", symbol)

        # Get symbol info to validate stops
        symbol_info = self.connector.get_symbol_info(symbol)
        if symbol_info is None:
            self.logger.trade_error(
                symbol=symbol,
                error_type="Symbol Info Retrieval",
                error_message="Failed to get symbol information from MT5",
                context={"action": "Trade rejected"}
            )
            return None

        # Validate and adjust SL/TP to meet minimum stop level requirements
        sl, tp = self.stop_validator.validate_stops(symbol, price, sl, tp, signal.signal_type, symbol_info)

        # Log signal
        self.logger.trade_signal(
            signal_type=signal.signal_type.value.upper(),
            symbol=symbol,
            entry=price,
            sl=sl,
            tp=tp,
            lot_size=volume
        )

        # Determine filling mode based on symbol's supported modes
        filling_mode = self.filling_mode_resolver.resolve_filling_mode(symbol_info, symbol)
        filling_mode_name = self.filling_mode_resolver.get_filling_mode_name(filling_mode)
        self.logger.debug(f"Using filling mode: {filling_mode_name}", symbol)

        # Use trade comment from signal (already generated by strategy)
        trade_comment = signal.comment if signal.comment else "NO_COMMENT"
        self.logger.info(f"Trade Comment: {trade_comment}", symbol)

        # Create order request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": self.deviation,
            "magic": self.magic_number,
            "comment": trade_comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        # Send order
        return self._send_order(request, signal, symbol, volume, price, sl, tp, trade_comment)

    def _send_order(self, request: dict, signal: TradeSignal, symbol: str,
                   volume: float, price: float, sl: float, tp: float, trade_comment: str) -> Optional[int]:
        """
        Send order to MT5 and handle response.

        Args:
            request: MT5 order request dictionary
            signal: Original trade signal
            symbol: Symbol name
            volume: Order volume
            price: Entry price
            sl: Stop loss
            tp: Take profit
            trade_comment: Trade comment

        Returns:
            Ticket number if successful, None otherwise
        """
        try:
            # Log the order request for debugging
            self.logger.debug(f"Sending order request: {request}", symbol)

            # Check MT5 connection before sending order
            if not mt5.terminal_info():
                self.logger.trade_error(
                    symbol=symbol,
                    error_type="Trade Execution",
                    error_message="MT5 terminal not connected or not responding",
                    context={
                        "order_type": signal.signal_type.value.upper(),
                        "action": "Cannot send order - MT5 terminal not available"
                    }
                )
                return None

            result = mt5.order_send(request)

            if result is None:
                # Get last error from MT5
                last_error = mt5.last_error()
                self.logger.trade_error(
                    symbol=symbol,
                    error_type="Trade Execution",
                    error_message=f"order_send failed, no result returned from MT5. Last error: {last_error}",
                    context={
                        "order_type": signal.signal_type.value.upper(),
                        "volume": volume,
                        "price": price,
                        "sl": sl,
                        "tp": tp,
                        "request": str(request)
                    }
                )
                return None

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return self._handle_order_error(result, signal, symbol, volume, price, sl, tp)

            # Log success and persist position
            return self._handle_order_success(result, signal, symbol, volume, sl, tp, trade_comment)

        except Exception as e:
            self.logger.trade_error(
                symbol=symbol,
                error_type="Trade Execution",
                error_message=f"Exception during order execution: {str(e)}",
                context={
                    "order_type": signal.signal_type.value.upper(),
                    "volume": volume,
                    "exception_type": type(e).__name__
                }
            )
            return None

    def _handle_order_error(self, result, signal: TradeSignal, symbol: str,
                           volume: float, price: float, sl: float, tp: float) -> Optional[int]:
        """Handle order execution errors."""
        # Check for market closed error
        if result.retcode == RETCODE_MARKET_CLOSED:
            self.logger.warning(
                f"Trade rejected - Market is closed (retcode {RETCODE_MARKET_CLOSED})",
                symbol
            )
            # Activate market closed state to pause all trading
            self.cooldown.activate_market_closed(symbol)
            return None

        # Check for AutoTrading disabled by server
        elif result.retcode == RETCODE_AUTOTRADING_DISABLED:
            self.logger.warning(
                f"Trade rejected - AutoTrading disabled by server (retcode {RETCODE_AUTOTRADING_DISABLED})",
                symbol
            )
            # Activate cooldown to prevent spam
            self.cooldown.activate_cooldown(f"AutoTrading disabled by server (error {RETCODE_AUTOTRADING_DISABLED})")
            return None

        # Check for "Only position closing allowed" restriction
        elif result.retcode == RETCODE_ONLY_CLOSE_ALLOWED:
            self.logger.symbol_condition_warning(
                symbol=symbol,
                condition="Position Opening Restricted",
                details=f"Broker restriction: Only position closing allowed (retcode {RETCODE_ONLY_CLOSE_ALLOWED}) - {result.comment}"
            )
            # This is a symbol-specific broker restriction, not a global error
            # Don't activate cooldown, just skip this symbol for now
            return None

        # Other errors
        self.logger.trade_error(
            symbol=symbol,
            error_type="Trade Execution",
            error_message=f"Order rejected by broker: {result.comment}",
            context={
                "retcode": result.retcode,
                "order_type": signal.signal_type.value.upper(),
                "volume": volume,
                "price": price,
                "sl": sl,
                "tp": tp
            }
        )
        return None

    def _handle_order_success(self, result, signal: TradeSignal, symbol: str,
                             volume: float, sl: float, tp: float, trade_comment: str) -> int:
        """Handle successful order execution."""
        # Log success
        try:
            self.logger.position_opened(
                ticket=result.order,
                symbol=symbol,
                position_type=signal.signal_type.value.upper(),
                volume=volume,
                price=result.price,
                sl=sl,
                tp=tp
            )
        except Exception as log_error:
            self.logger.error(f"Failed to log position opened: {log_error}", symbol)
            # Continue anyway - logging failure shouldn't prevent position tracking

        # Add position to persistence
        try:
            position = PositionInfo(
                ticket=result.order,
                symbol=symbol,
                position_type=signal.signal_type,
                volume=volume,
                open_price=result.price,
                current_price=result.price,
                sl=sl,
                tp=tp,
                profit=0.0,
                open_time=datetime.now(timezone.utc),
                magic_number=self.magic_number,
                comment=trade_comment
            )
            self.persistence.add_position(position)
        except Exception as persist_error:
            self.logger.error(f"Failed to add position to persistence: {persist_error}", symbol)
            self.logger.error(f"Position {result.order} opened in MT5 but not tracked in bot!", symbol)

        return result.order

    def _validate_pre_trade_risk(self, symbol: str, lot_size: float,
                                  entry_price: float, stop_loss: float) -> bool:
        """
        Validate that the trade's risk does not exceed the configured risk limit.

        This is a STRICT validation that rejects trades if risk exceeds the limit,
        unlike validate_trade_risk() which automatically adjusts lot size.

        Args:
            symbol: Symbol name
            lot_size: Proposed lot size
            entry_price: Entry price
            stop_loss: Stop loss price

        Returns:
            True if risk is within limits, False if trade should be rejected
        """
        # Get account balance
        balance = self.connector.get_account_balance()
        if balance <= 0:
            self.logger.trade_error(
                symbol=symbol,
                error_type="Pre-Trade Risk Validation",
                error_message="Invalid account balance",
                context={"balance": balance, "action": "Trade rejected"}
            )
            return False

        # Get symbol info
        symbol_info = self.connector.get_symbol_info(symbol)
        if symbol_info is None:
            self.logger.trade_error(
                symbol=symbol,
                error_type="Pre-Trade Risk Validation",
                error_message="Failed to get symbol information",
                context={"action": "Trade rejected"}
            )
            return False

        # Calculate stop loss distance
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0:
            self.logger.trade_error(
                symbol=symbol,
                error_type="Pre-Trade Risk Validation",
                error_message="Invalid stop loss distance",
                context={
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "sl_distance": sl_distance,
                    "action": "Trade rejected"
                }
            )
            return False

        # Get symbol specifications
        point = symbol_info['point']
        tick_value = symbol_info['tick_value']
        currency_profit = symbol_info.get('currency_profit', 'UNKNOWN')
        account_currency = self.connector.get_account_currency()

        # Convert tick value to account currency if needed
        from src.utils.currency_conversion_service import CurrencyConversionService
        currency_service = CurrencyConversionService(self.logger)
        tick_value, conversion_rate = currency_service.convert_tick_value(
            tick_value=tick_value,
            currency_profit=currency_profit,
            account_currency=account_currency,
            symbol=symbol
        )

        # Calculate SL distance in points
        sl_distance_in_points = sl_distance / point if point > 0 else sl_distance

        # Calculate actual risk amount and percentage
        risk_amount = sl_distance_in_points * tick_value * lot_size
        risk_percent = (risk_amount / balance) * 100.0 if balance > 0 else 0

        # Get configured risk limit
        configured_risk_percent = self.risk_manager.risk_config.risk_percent_per_trade

        # Check if risk exceeds configured limit
        if risk_percent > configured_risk_percent:
            # REJECT THE TRADE - Risk exceeds limit
            self.logger.warning(
                f"⚠️  PRE-TRADE RISK VALIDATION FAILED - Trade REJECTED",
                symbol
            )
            self.logger.warning(
                f"Calculated Risk: ${risk_amount:.2f} ({risk_percent:.2f}%)",
                symbol
            )
            self.logger.warning(
                f"Configured Limit: {configured_risk_percent:.2f}%",
                symbol
            )
            self.logger.warning(
                f"Risk Exceeds Limit By: {risk_percent - configured_risk_percent:.2f}%",
                symbol
            )
            self.logger.warning(
                f"Trade Details: Lot Size={lot_size:.2f}, Entry={entry_price:.5f}, "
                f"SL={stop_loss:.5f}, SL Distance={sl_distance_in_points:.1f} points",
                symbol
            )
            self.logger.warning(
                f"Reason: Position size ({lot_size:.2f} lots) with SL distance "
                f"({sl_distance_in_points:.1f} points) creates {risk_percent:.2f}% risk, "
                f"which exceeds the configured {configured_risk_percent:.2f}% limit.",
                symbol
            )
            self.logger.warning(
                f"Action: Trade NOT executed. Consider reducing position size, "
                f"tightening stop loss, or increasing account balance.",
                symbol
            )
            return False

        # Risk is within acceptable limits
        self.logger.debug(
            f"✓ Pre-trade risk validation passed: ${risk_amount:.2f} ({risk_percent:.2f}%) "
            f"<= {configured_risk_percent:.2f}% limit",
            symbol
        )

        return True

    def _validate_portfolio_risk(self, symbol: str, lot_size: float,
                                  entry_price: float, stop_loss: float) -> bool:
        """
        Validate that adding this trade won't exceed the maximum portfolio risk limit.

        This is a TIER 2 validation that checks total portfolio risk across all open positions
        plus the proposed new trade. Individual trade risk is validated separately in TIER 1.

        Args:
            symbol: Symbol name
            lot_size: Proposed lot size for new trade
            entry_price: Entry price for new trade
            stop_loss: Stop loss price for new trade

        Returns:
            True if portfolio risk is within limits, False if trade should be rejected
        """
        # Get account balance
        balance = self.connector.get_account_balance()
        if balance <= 0:
            self.logger.trade_error(
                symbol=symbol,
                error_type="Portfolio Risk Validation",
                error_message="Invalid account balance",
                context={"balance": balance, "action": "Trade rejected"}
            )
            return False

        # Get all open positions for this magic number
        open_positions = self.connector.get_positions(magic_number=self.magic_number)

        # Calculate total risk from existing positions
        total_existing_risk = 0.0
        position_risks = []

        for position in open_positions:
            # Get symbol info for this position
            pos_symbol_info = self.connector.get_symbol_info(position.symbol)
            if pos_symbol_info is None:
                self.logger.warning(
                    f"Could not get symbol info for position {position.ticket} ({position.symbol}), "
                    f"skipping in portfolio risk calculation",
                    symbol
                )
                continue

            # Calculate SL distance for this position
            pos_sl_distance = abs(position.current_price - position.sl)
            if pos_sl_distance <= 0:
                # Position has no SL or invalid SL, skip it
                continue

            # Get symbol specifications
            pos_point = pos_symbol_info['point']
            pos_tick_value = pos_symbol_info['tick_value']
            pos_currency_profit = pos_symbol_info.get('currency_profit', 'UNKNOWN')
            account_currency = self.connector.get_account_currency()

            # Convert tick value to account currency if needed
            from src.utils.currency_conversion_service import CurrencyConversionService
            currency_service = CurrencyConversionService(self.logger)
            pos_tick_value, _ = currency_service.convert_tick_value(
                tick_value=pos_tick_value,
                currency_profit=pos_currency_profit,
                account_currency=account_currency,
                symbol=position.symbol
            )

            # Calculate risk for this position
            pos_sl_distance_points = pos_sl_distance / pos_point if pos_point > 0 else pos_sl_distance
            pos_risk_amount = pos_sl_distance_points * pos_tick_value * position.volume

            total_existing_risk += pos_risk_amount
            position_risks.append({
                'ticket': position.ticket,
                'symbol': position.symbol,
                'volume': position.volume,
                'risk_amount': pos_risk_amount
            })

        # Calculate risk for the proposed new trade
        # Get symbol info
        symbol_info = self.connector.get_symbol_info(symbol)
        if symbol_info is None:
            self.logger.trade_error(
                symbol=symbol,
                error_type="Portfolio Risk Validation",
                error_message="Failed to get symbol information",
                context={"action": "Trade rejected"}
            )
            return False

        # Calculate SL distance
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0:
            self.logger.trade_error(
                symbol=symbol,
                error_type="Portfolio Risk Validation",
                error_message="Invalid stop loss distance",
                context={
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "sl_distance": sl_distance,
                    "action": "Trade rejected"
                }
            )
            return False

        # Get symbol specifications
        point = symbol_info['point']
        tick_value = symbol_info['tick_value']
        currency_profit = symbol_info.get('currency_profit', 'UNKNOWN')
        account_currency = self.connector.get_account_currency()

        # Convert tick value to account currency if needed
        from src.utils.currency_conversion_service import CurrencyConversionService
        currency_service = CurrencyConversionService(self.logger)
        tick_value, _ = currency_service.convert_tick_value(
            tick_value=tick_value,
            currency_profit=currency_profit,
            account_currency=account_currency,
            symbol=symbol
        )

        # Calculate new trade risk
        sl_distance_in_points = sl_distance / point if point > 0 else sl_distance
        new_trade_risk = sl_distance_in_points * tick_value * lot_size

        # Calculate total portfolio risk
        total_portfolio_risk = total_existing_risk + new_trade_risk
        portfolio_risk_percent = (total_portfolio_risk / balance) * 100.0 if balance > 0 else 0

        # Calculate existing portfolio risk percentage
        existing_risk_percent = (total_existing_risk / balance) * 100.0 if balance > 0 else 0
        new_trade_risk_percent = (new_trade_risk / balance) * 100.0 if balance > 0 else 0

        # Get configured portfolio risk limit
        max_portfolio_risk = self.risk_manager.risk_config.max_portfolio_risk_percent

        # Check if portfolio risk exceeds limit
        if portfolio_risk_percent > max_portfolio_risk:
            # REJECT THE TRADE - Portfolio risk exceeds limit
            self.logger.warning(
                f"⚠️  PORTFOLIO RISK VALIDATION FAILED - Trade REJECTED",
                symbol
            )
            self.logger.warning(
                f"Current Portfolio Risk: ${total_existing_risk:.2f} ({existing_risk_percent:.2f}%) "
                f"across {len(open_positions)} open position(s)",
                symbol
            )
            self.logger.warning(
                f"Proposed New Trade Risk: ${new_trade_risk:.2f} ({new_trade_risk_percent:.2f}%)",
                symbol
            )
            self.logger.warning(
                f"Combined Portfolio Risk: ${total_portfolio_risk:.2f} ({portfolio_risk_percent:.2f}%)",
                symbol
            )
            self.logger.warning(
                f"Portfolio Risk Limit: {max_portfolio_risk:.2f}%",
                symbol
            )
            self.logger.warning(
                f"Risk Exceeds Limit By: {portfolio_risk_percent - max_portfolio_risk:.2f}%",
                symbol
            )

            # Log details of existing positions
            if position_risks:
                self.logger.warning(
                    f"Existing Position Risks:",
                    symbol
                )
                for pos_risk in position_risks:
                    self.logger.warning(
                        f"  - Ticket {pos_risk['ticket']} ({pos_risk['symbol']}): "
                        f"{pos_risk['volume']:.2f} lots = ${pos_risk['risk_amount']:.2f} risk",
                        symbol
                    )

            self.logger.warning(
                f"Reason: Adding this trade (${new_trade_risk:.2f} risk) to existing portfolio "
                f"(${total_existing_risk:.2f} risk) would create {portfolio_risk_percent:.2f}% total risk, "
                f"which exceeds the configured {max_portfolio_risk:.2f}% portfolio limit.",
                symbol
            )
            self.logger.warning(
                f"Action: Trade NOT executed. Consider closing some positions, reducing position sizes, "
                f"or waiting for existing positions to close before opening new trades.",
                symbol
            )
            return False

        # Portfolio risk is within acceptable limits
        self.logger.debug(
            f"✓ Portfolio risk validation passed: ${total_portfolio_risk:.2f} ({portfolio_risk_percent:.2f}%) "
            f"<= {max_portfolio_risk:.2f}% limit "
            f"[Existing: ${total_existing_risk:.2f} ({existing_risk_percent:.2f}%), "
            f"New: ${new_trade_risk:.2f} ({new_trade_risk_percent:.2f}%)]",
            symbol
        )

        return True

