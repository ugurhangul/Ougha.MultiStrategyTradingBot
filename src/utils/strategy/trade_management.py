"""
Trade management utilities.

Provides utilities for managing open positions including breakeven,
trailing stops, and position adjustments.
"""


class TradeManagementHelper:
    """
    Trade management utilities for position management.

    Handles breakeven, trailing stops, and position adjustments.
    """

    @staticmethod
    def calculate_breakeven_level(entry_price: float, stop_loss: float,
                                  breakeven_trigger_ratio: float = 1.0) -> float:
        """
        Calculate the price level at which to move SL to breakeven.

        Args:
            entry_price: Entry price
            stop_loss: Initial stop loss price
            breakeven_trigger_ratio: R:R ratio to trigger breakeven (default 1:1)

        Returns:
            Price level for breakeven trigger
        """
        sl_distance = abs(entry_price - stop_loss)
        trigger_distance = sl_distance * breakeven_trigger_ratio

        if entry_price > stop_loss:  # BUY
            return entry_price + trigger_distance
        else:  # SELL
            return entry_price - trigger_distance

    @staticmethod
    def should_move_to_breakeven(current_price: float, entry_price: float,
                                stop_loss: float, breakeven_ratio: float = 1.0) -> bool:
        """
        Check if stop loss should be moved to breakeven.

        Args:
            current_price: Current market price
            entry_price: Entry price
            stop_loss: Current stop loss
            breakeven_ratio: R:R ratio to trigger breakeven

        Returns:
            True if should move to breakeven
        """
        breakeven_level = TradeManagementHelper.calculate_breakeven_level(
            entry_price, stop_loss, breakeven_ratio
        )

        if entry_price > stop_loss:  # BUY
            return current_price >= breakeven_level
        else:  # SELL
            return current_price <= breakeven_level

    @staticmethod
    def calculate_trailing_stop(current_price: float, entry_price: float,
                               highest_price: float, trailing_distance: float,
                               is_buy: bool) -> float:
        """
        Calculate trailing stop level.

        Args:
            current_price: Current market price
            entry_price: Entry price
            highest_price: Highest price since entry (for BUY) or lowest (for SELL)
            trailing_distance: Trailing distance in price units
            is_buy: True for BUY positions, False for SELL

        Returns:
            New trailing stop level
        """
        if is_buy:
            return highest_price - trailing_distance
        else:
            return highest_price + trailing_distance

    @staticmethod
    def should_update_trailing_stop(current_price: float, current_sl: float,
                                    trailing_distance: float, is_buy: bool) -> bool:
        """
        Check if trailing stop should be updated.

        Args:
            current_price: Current market price
            current_sl: Current stop loss
            trailing_distance: Trailing distance in price units
            is_buy: True for BUY positions, False for SELL

        Returns:
            True if trailing stop should update
        """
        new_sl = TradeManagementHelper.calculate_trailing_stop(
            current_price, 0, current_price, trailing_distance, is_buy
        )

        if is_buy:
            return new_sl > current_sl
        else:
            return new_sl < current_sl

