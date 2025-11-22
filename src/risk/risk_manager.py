"""
Risk management and position sizing.
Ported from FMS_TradeExecution.mqh
"""
from typing import Optional, Tuple, Dict
from collections import defaultdict
from src.core.mt5_connector import MT5Connector
from src.config.configs import RiskConfig
from src.config.instrument_groups import get_instrument_group, get_group_risk_limit, InstrumentGroup
from src.models.data_models import PositionType
from src.utils.logger import get_logger
from src.utils.currency_conversion_service import CurrencyConversionService
from src.constants import (
    RISK_TOLERANCE_MULTIPLIER,
    ERROR_INVALID_BALANCE,
    ERROR_INVALID_SL_DISTANCE,
    ERROR_PRICE_RETRIEVAL_FAILED,
)


class RiskManager:
    """Manages risk and position sizing"""

    def __init__(self, connector: MT5Connector, risk_config: RiskConfig,
                 persistence=None):
        """
        Initialize risk manager.

        Args:
            connector: MT5 connector instance
            risk_config: Risk configuration
            persistence: Position persistence instance (optional)
        """
        self.connector = connector
        self.risk_config = risk_config
        self.logger = get_logger()
        self.persistence = persistence
        # Pass connector to currency service for backtest support
        self.currency_service = CurrencyConversionService(self.logger, connector)
    
    def calculate_lot_size(self, symbol: str, entry_price: float,
                          stop_loss: float) -> float:
        """
        Calculate lot size based on risk percentage.

        Args:
            symbol: Symbol name
            entry_price: Entry price
            stop_loss: Stop loss price

        Returns:
            Lot size (0.0 if calculation fails or instrument should be skipped)
        """
        # Get account balance
        balance = self.connector.get_account_balance()
        if balance <= 0:
            self.logger.error("Invalid account balance", symbol)
            return 0.0

        # Get symbol info
        symbol_info = self.connector.get_symbol_info(symbol)
        if symbol_info is None:
            self.logger.error("Failed to get symbol info", symbol)
            return 0.0

        # Calculate risk amount in account currency
        risk_amount = balance * (self.risk_config.risk_percent_per_trade / 100.0)

        # Calculate stop loss distance in points
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0:
            self.logger.error("Invalid stop loss distance", symbol)
            return 0.0
        
        # Get point value and contract size
        point = symbol_info['point']
        tick_value = symbol_info['tick_value']
        contract_size = symbol_info['contract_size']
        currency_profit = symbol_info.get('currency_profit', 'UNKNOWN')
        currency_base = symbol_info.get('currency_base', 'UNKNOWN')

        # Get account currency
        account_currency = self.connector.get_account_currency()

        # Log symbol info for debugging
        self.logger.debug(
            f"Symbol Info: Point={point}, TickValue={tick_value:.5f}, "
            f"ContractSize={contract_size}, Digits={symbol_info['digits']}, "
            f"CurrencyBase={currency_base}, CurrencyProfit={currency_profit}, "
            f"AccountCurrency={account_currency}",
            symbol
        )

        # Convert tick value to account currency if needed
        tick_value, conversion_rate = self.currency_service.convert_tick_value(
            tick_value=tick_value,
            currency_profit=currency_profit,
            account_currency=account_currency,
            symbol=symbol
        )

        # Calculate stop loss distance in points
        # This matches MQL5: stopLossPoints = MathAbs(entryPrice - stopLoss) / point
        sl_distance_in_points = sl_distance / point if point > 0 else sl_distance

        if tick_value <= 0 or sl_distance_in_points <= 0:
            self.logger.error("Invalid tick value or SL distance", symbol)
            return 0.0

        # Warn about extremely tight stop losses that may cause margin issues
        sl_percent = (sl_distance / entry_price) * 100.0
        if sl_percent < 0.5:  # Less than 0.5% stop loss
            self.logger.warning(
                f"Extremely tight stop loss detected: {sl_distance_in_points:.0f} points "
                f"({sl_percent:.2f}% of price). This may cause excessive lot sizes and margin issues.",
                symbol
            )

        # Calculate lot size
        # This matches MQL5: lotSize = riskAmount / (stopLossPoints * tickValue)
        # tick_value already represents the value per lot per point
        lot_size_raw = risk_amount / (sl_distance_in_points * tick_value)

        # Normalize to lot step
        min_lot = symbol_info['min_lot']
        max_lot = symbol_info['max_lot']
        lot_step = symbol_info['lot_step']

        self.logger.debug(
            f"Lot size calculation: raw={lot_size_raw:.4f}, lot_step={lot_step}, "
            f"symbol_min={min_lot}, symbol_max={max_lot}",
            symbol
        )

        # Round to lot step using Decimal for precise rounding
        from decimal import Decimal, ROUND_HALF_UP

        lot_size_decimal = Decimal(str(lot_size_raw))
        lot_step_decimal = Decimal(str(lot_step))
        steps = (lot_size_decimal / lot_step_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        lot_size = float(steps * lot_step_decimal)

        self.logger.debug(f"After rounding to lot_step: {lot_size:.4f}", symbol)

        # CRITICAL: Cap lot size based on available margin to prevent MT5 rejection
        # Use MT5's order_calc_margin() to get actual required margin
        margin_required = self.connector.calculate_margin(symbol, lot_size, entry_price)

        if margin_required is not None and margin_required > 0:
            # Get available margin (free margin)
            free_margin = self.connector.get_account_free_margin()

            if free_margin is not None and free_margin > 0:
                # If required margin exceeds 80% of free margin, reduce lot size
                max_safe_margin = free_margin * 0.8  # Use max 80% of free margin

                if margin_required > max_safe_margin:
                    # Calculate maximum safe lot size
                    margin_ratio = max_safe_margin / margin_required
                    max_safe_lot_size_raw = lot_size * margin_ratio

                    # Round to lot step using Decimal for precise rounding
                    from decimal import Decimal, ROUND_HALF_UP
                    max_safe_decimal = Decimal(str(max_safe_lot_size_raw))
                    lot_step_decimal = Decimal(str(lot_step))
                    steps = (max_safe_decimal / lot_step_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
                    max_safe_lot_size = float(steps * lot_step_decimal)

                    self.logger.warning(
                        f"Lot size {lot_size:.2f} requires ${margin_required:,.2f} margin "
                        f"(exceeds 80% of free margin ${free_margin:,.2f}). "
                        f"Reducing to {max_safe_lot_size:.2f} lots.",
                        symbol
                    )
                    lot_size = max_safe_lot_size

        # Check if calculated lot size is below symbol minimum
        # This happens for expensive instruments (BTC, gold) or when balance is low
        if lot_size_raw < min_lot:
            # Calculate what risk the minimum lot would create
            actual_risk_with_min_lot = sl_distance_in_points * tick_value * min_lot
            actual_risk_percent = (actual_risk_with_min_lot / balance) * 100.0

            # Define maximum acceptable risk multiplier (e.g., 3x configured risk)
            max_risk_multiplier = 3.0
            max_acceptable_risk = self.risk_config.risk_percent_per_trade * max_risk_multiplier

            if actual_risk_percent > max_acceptable_risk:
                self.logger.warning(
                    f"Instrument filtered: Minimum lot ({min_lot:.4f}) would create {actual_risk_percent:.2f}% risk "
                    f"(>{max_acceptable_risk:.2f}%). Calculated lot: {lot_size_raw:.6f}. Skipping trade.",
                    symbol
                )
                return 0.0
            else:
                self.logger.info(
                    f"Using minimum lot ({min_lot:.4f}) - actual risk: {actual_risk_percent:.2f}% "
                    f"(calculated: {lot_size_raw:.6f})",
                    symbol
                )
                lot_size = min_lot

        # Apply min/max constraints
        lot_size_before_symbol_clamp = lot_size
        lot_size = max(min_lot, min(max_lot, lot_size))
        if lot_size != lot_size_before_symbol_clamp:
            self.logger.debug(
                f"After symbol min/max clamp: {lot_size_before_symbol_clamp:.4f} -> {lot_size:.4f}",
                symbol
            )

        # Apply user-defined min/max
        # Note: If min_lot_size is 0 or negative, use symbol's min_lot
        user_min_lot = self.risk_config.min_lot_size if self.risk_config.min_lot_size > 0 else min_lot
        lot_size_before_user_min = lot_size
        lot_size = max(user_min_lot, lot_size)
        if lot_size != lot_size_before_user_min:
            self.logger.debug(
                f"After user min clamp ({user_min_lot:.4f}): {lot_size_before_user_min:.4f} -> {lot_size:.4f}",
                symbol
            )

        # Note: If max_lot_size is 0 or negative, use symbol's max_lot
        user_max_lot = self.risk_config.max_lot_size if self.risk_config.max_lot_size > 0 else max_lot
        lot_size_before_user_max = lot_size
        lot_size = min(user_max_lot, lot_size)
        if lot_size != lot_size_before_user_max:
            self.logger.debug(
                f"After user max clamp ({user_max_lot:.4f}): "
                f"{lot_size_before_user_max:.4f} -> {lot_size:.4f}",
                symbol
            )
        else:
            self.logger.debug(
                f"User max lot ({user_max_lot:.4f}) not applied - "
                f"lot size {lot_size:.4f} is already below max",
                symbol
            )
        
        # Log calculation
        self.logger.info("=== Position Sizing ===", symbol)
        self.logger.info(f"Account Balance: ${balance:.2f}", symbol)
        self.logger.info(f"Risk Per Trade: {self.risk_config.risk_percent_per_trade}%", symbol)
        self.logger.info(f"Risk Amount: ${risk_amount:.2f}", symbol)
        self.logger.info(f"Entry Price: {entry_price:.5f}", symbol)
        self.logger.info(f"Stop Loss: {stop_loss:.5f}", symbol)
        self.logger.info(f"SL Distance: {sl_distance:.5f} ({sl_distance_in_points:.1f} points)", symbol)
        self.logger.info(f"Tick Value: ${tick_value:.2f}", symbol)
        self.logger.info(f"Calculated Lot Size: {lot_size:.2f}", symbol)
        self.logger.info(f"Symbol Min/Max Lot: {min_lot:.2f} / {max_lot:.2f}", symbol)
        if self.risk_config.min_lot_size > 0:
            self.logger.info(f"User Min Lot: {self.risk_config.min_lot_size:.2f}", symbol)
        else:
            self.logger.info(f"User Min Lot: MIN (using symbol minimum)", symbol)
        if self.risk_config.max_lot_size > 0:
            self.logger.info(f"User Max Lot: {self.risk_config.max_lot_size:.2f}", symbol)
        else:
            self.logger.info(f"User Max Lot: MIN (using symbol minimum)", symbol)
        self.logger.separator()
        
        return lot_size
    
    def calculate_stop_loss(self, symbol: str, entry_price: float, 
                           is_buy: bool, offset_points: int) -> float:
        """
        Calculate stop loss price.
        
        Args:
            symbol: Symbol name
            entry_price: Entry price
            is_buy: True for BUY, False for SELL
            offset_points: Offset in points from entry
            
        Returns:
            Stop loss price
        """
        symbol_info = self.connector.get_symbol_info(symbol)
        if symbol_info is None:
            return 0.0
        
        point = symbol_info['point']
        offset = offset_points * point
        
        if is_buy:
            # For BUY, SL is below entry
            sl = entry_price - offset
        else:
            # For SELL, SL is above entry
            sl = entry_price + offset
        
        # Normalize
        digits = symbol_info['digits']
        sl = round(sl, digits)
        
        return sl

    def calculate_group_risk(self, positions: list, balance: float) -> Dict[InstrumentGroup, float]:
        """
        Calculate current risk exposure by instrument group.

        Args:
            positions: List of open positions
            balance: Account balance

        Returns:
            Dictionary mapping InstrumentGroup to risk percentage
        """
        group_risk: Dict[InstrumentGroup, float] = defaultdict(float)

        for pos in positions:
            # Get symbol info for risk calculation
            symbol_info = self.connector.get_symbol_info(pos.symbol)
            if symbol_info is None:
                continue

            # Calculate risk for this position
            point = symbol_info['point']
            tick_value = symbol_info['tick_value']

            # Convert tick value to account currency if needed
            currency_profit = symbol_info.get('currency_profit', 'USD')
            account_currency = self.connector.get_account_currency()

            tick_value_converted, _ = self.currency_service.convert_tick_value(
                tick_value=tick_value,
                currency_profit=currency_profit,
                account_currency=account_currency,
                symbol=pos.symbol
            )

            # Calculate SL distance
            if pos.position_type == PositionType.BUY:
                sl_distance = abs(pos.open_price - pos.sl) if pos.sl > 0 else 0
            else:
                sl_distance = abs(pos.sl - pos.open_price) if pos.sl > 0 else 0

            sl_distance_points = sl_distance / point if point > 0 else 0

            # Calculate risk amount
            risk_amount = sl_distance_points * tick_value_converted * pos.volume
            risk_percent = (risk_amount / balance) * 100.0 if balance > 0 else 0

            # Add to group total
            group = get_instrument_group(pos.symbol)
            group_risk[group] += risk_percent

        return dict(group_risk)

    def calculate_take_profit(self, symbol: str, entry_price: float,
                             stop_loss: float, risk_reward_ratio: float) -> float:
        """
        Calculate take profit based on R:R ratio.
        
        Args:
            symbol: Symbol name
            entry_price: Entry price
            stop_loss: Stop loss price
            risk_reward_ratio: Risk/reward ratio (e.g., 2.0 for 1:2)
            
        Returns:
            Take profit price
        """
        symbol_info = self.connector.get_symbol_info(symbol)
        if symbol_info is None:
            return 0.0
        
        # Calculate risk distance
        risk_distance = abs(entry_price - stop_loss)
        
        # Calculate reward distance
        reward_distance = risk_distance * risk_reward_ratio
        
        # Determine TP based on direction
        if entry_price > stop_loss:
            # BUY position
            tp = entry_price + reward_distance
        else:
            # SELL position
            tp = entry_price - reward_distance
        
        # Normalize
        digits = symbol_info['digits']
        tp = round(tp, digits)
        
        return tp
    
    def validate_trade_risk(self, symbol: str, lot_size: float,
                           entry_price: float, stop_loss: float) -> Tuple[bool, str, float]:
        """
        Validate if trade meets risk requirements.
        If risk exceeds maximum, automatically recalculates a smaller lot size.

        Args:
            symbol: Symbol name
            lot_size: Lot size
            entry_price: Entry price
            stop_loss: Stop loss price

        Returns:
            Tuple of (is_valid, error_message, adjusted_lot_size)
            - is_valid: True if trade can proceed (possibly with adjusted lot size)
            - error_message: Error description if is_valid is False, empty string otherwise
            - adjusted_lot_size: The lot size to use (may be reduced from original)
        """
        # Check lot size
        symbol_info = self.connector.get_symbol_info(symbol)
        if symbol_info is None:
            return False, "Failed to get symbol info", 0.0

        min_lot = symbol_info['min_lot']
        max_lot = symbol_info['max_lot']
        lot_step = symbol_info['lot_step']

        if lot_size < min_lot:
            return False, f"Lot size {lot_size:.2f} below minimum {min_lot:.2f}", 0.0

        if lot_size > max_lot:
            return False, f"Lot size {lot_size:.2f} above maximum {max_lot:.2f}", 0.0

        # Check SL distance
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0:
            return False, "Invalid stop loss distance", 0.0

        # Calculate risk amount
        balance = self.connector.get_account_balance()
        point = symbol_info['point']
        tick_value = symbol_info['tick_value']
        currency_profit = symbol_info.get('currency_profit', 'UNKNOWN')

        # Get account currency and convert tick value if needed
        account_currency = self.connector.get_account_currency()

        tick_value, conversion_rate = self.currency_service.convert_tick_value(
            tick_value=tick_value,
            currency_profit=currency_profit,
            account_currency=account_currency,
            symbol=symbol
        )

        # Log conversion for debugging (if conversion occurred)
        if conversion_rate is not None:
            self.logger.debug(
                f"Risk validation currency conversion applied (rate: {conversion_rate:.5f})",
                symbol
            )

        # Calculate SL distance in points (matches MQL5 formula)
        sl_distance_in_points = sl_distance / point if point > 0 else sl_distance

        # Calculate risk amount: stopLossPoints * tickValue * lotSize
        # This matches the inverse of the lot size calculation
        risk_amount = sl_distance_in_points * tick_value * lot_size
        risk_percent = (risk_amount / balance) * 100.0 if balance > 0 else 0

        # Log detailed risk calculation for debugging
        self.logger.debug(
            f"Risk Validation: Balance={balance:.2f}, Entry={entry_price:.5f}, "
            f"SL={stop_loss:.5f}, SL_Dist={sl_distance:.5f}, Point={point}, "
            f"SL_Points={sl_distance_in_points:.2f}, TickValue={tick_value:.5f}, "
            f"LotSize={lot_size:.2f}, RiskAmount={risk_amount:.2f}, "
            f"RiskPercent={risk_percent:.2f}%",
            symbol
        )

        # Check if risk exceeds maximum
        max_risk = self.risk_config.risk_percent_per_trade * RISK_TOLERANCE_MULTIPLIER
        if risk_percent > max_risk:
            # Instead of rejecting, recalculate lot size to target the configured risk percent
            self.logger.warning(
                f"Risk {risk_percent:.2f}% exceeds maximum {max_risk:.2f}%. "
                f"Automatically reducing lot size...",
                symbol
            )

            # Calculate new lot size targeting the configured risk percent (not the max tolerance)
            target_risk_amount = balance * (self.risk_config.risk_percent_per_trade / 100.0)

            # Recalculate lot size: lotSize = riskAmount / (stopLossPoints * tickValue)
            adjusted_lot_size_raw = target_risk_amount / (sl_distance_in_points * tick_value)

            # Normalize to lot step using Decimal for precise rounding
            from decimal import Decimal, ROUND_HALF_UP
            adjusted_decimal = Decimal(str(adjusted_lot_size_raw))
            lot_step_decimal = Decimal(str(lot_step))
            steps = (adjusted_decimal / lot_step_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            adjusted_lot_size = float(steps * lot_step_decimal)

            # Apply min/max constraints
            adjusted_lot_size = max(min_lot, min(max_lot, adjusted_lot_size))

            # Apply user-defined minimum and maximum
            user_min_lot = self.risk_config.min_lot_size if self.risk_config.min_lot_size > 0 else min_lot
            user_max_lot = self.risk_config.max_lot_size if self.risk_config.max_lot_size > 0 else min_lot
            adjusted_lot_size = max(user_min_lot, min(user_max_lot, adjusted_lot_size))

            # Check if adjusted lot size is still below minimum
            if adjusted_lot_size < min_lot or adjusted_lot_size < user_min_lot:
                return False, f"Adjusted lot size {adjusted_lot_size:.2f} below minimum {max(min_lot, user_min_lot):.2f}", 0.0

            # Recalculate risk with adjusted lot size
            adjusted_risk_amount = sl_distance_in_points * tick_value * adjusted_lot_size
            adjusted_risk_percent = (adjusted_risk_amount / balance) * 100.0 if balance > 0 else 0

            # Log the adjustment
            self.logger.warning(
                f"Lot size adjusted: {lot_size:.2f} -> {adjusted_lot_size:.2f} | "
                f"Risk: {risk_percent:.2f}% -> {adjusted_risk_percent:.2f}% | "
                f"Target: {self.risk_config.risk_percent_per_trade:.2f}%",
                symbol
            )

            return True, "", adjusted_lot_size

        # Risk is within acceptable limits, return original lot size
        return True, "", lot_size
    
    def get_max_positions(self) -> int:
        """
        Get maximum number of concurrent positions allowed.
        
        Returns:
            Maximum positions
        """
        return self.risk_config.max_positions
    
    def can_open_new_position(self, magic_number: int, symbol: Optional[str] = None,
                             position_type: Optional[PositionType] = None,
                             all_confirmations_met: bool = False,
                             strategy_type: Optional[str] = None,
                             range_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Check if we can open a new position.

        Checks:
        1. Max positions limit
        2. Persistence duplicate prevention
        3. Account balance validation
        4. Direction (position_type) and strategy (strategy_type) duplicate check

        Args:
            magic_number: Magic number to filter positions
            symbol: Symbol to check for existing positions (optional)
            position_type: Position type (BUY/SELL) to check for duplicates (optional)
            all_confirmations_met: Not used (kept for backward compatibility)
            strategy_type: Strategy type ("TB" for True Breakout, "FB" for False Breakout, "HFT") (optional)
            range_id: Not used (kept for backward compatibility)

        Returns:
            Tuple of (can_open, reason)
        """
        # Get current positions from MT5
        positions = self.connector.get_positions(magic_number=magic_number)

        # Check max positions
        if len(positions) >= self.risk_config.max_positions:
            return False, f"Maximum positions ({self.risk_config.max_positions}) reached"

        # DUPLICATE PREVENTION: Also check persisted positions
        # This prevents creating duplicate positions after bot restart
        if self.persistence and symbol and position_type and strategy_type:
            persisted_tickets = self.persistence.get_all_tickets()

            # Check if any persisted position matches this symbol, direction, and strategy
            for ticket in persisted_tickets:
                pos_data = self.persistence.get_position(ticket)
                if pos_data and pos_data['symbol'] == symbol:
                    # Check if position type matches
                    persisted_type = PositionType(pos_data['position_type'])
                    if persisted_type == position_type:
                        # Extract strategy type from comment (new format: "TB|15M_1M|BV" or "HFT|MV")
                        comment = pos_data.get('comment', '')
                        parts = comment.split('|') if '|' in comment else []
                        persisted_strategy = parts[0] if len(parts) > 0 else ''

                        # Check if strategy matches
                        if persisted_strategy == strategy_type:
                            pos_type_str = "BUY" if position_type == PositionType.BUY else "SELL"
                            self.logger.warning(
                                f"Position found in persistence file: {ticket} ({symbol} {pos_type_str} {strategy_type}). "
                                f"Preventing duplicate creation.",
                                symbol
                            )
                            return False, f"{pos_type_str} {strategy_type} position already exists for {symbol} (in persistence)"

        # Check if position of same direction and strategy already exists for this symbol
        if symbol and position_type and strategy_type:
            # Filter by symbol, position type, and strategy
            for pos in positions:
                if pos.symbol == symbol and pos.position_type == position_type:
                    # Extract strategy type from comment (new format: "TB|15M_1M|BV" or "HFT|MV")
                    parts = pos.comment.split('|') if '|' in pos.comment else []
                    comment_strategy = parts[0] if len(parts) > 0 else ''

                    # Check if strategy matches
                    if comment_strategy == strategy_type:
                        pos_type_str = "BUY" if position_type == PositionType.BUY else "SELL"
                        return False, f"{pos_type_str} {strategy_type} position already exists for {symbol}"

        # Check account balance is valid
        balance = self.connector.get_account_balance()

        if balance <= 0:
            return False, "Invalid account balance"

        return True, ""

