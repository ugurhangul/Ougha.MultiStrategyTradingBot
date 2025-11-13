"""
Stop loss and take profit validation and adjustment.
"""

from src.models.data_models import PositionType
from src.core.mt5_connector import MT5Connector
from src.utils.logging import TradingLogger
from src.utils.price_normalization_service import PriceNormalizationService


class StopValidator:
    """Validates and adjusts stop loss and take profit levels"""

    def __init__(self, connector: MT5Connector, price_normalizer: PriceNormalizationService, logger: TradingLogger):
        """
        Initialize stop validator.

        Args:
            connector: MT5 connector instance
            price_normalizer: Price normalization service
            logger: Logger instance
        """
        self.connector = connector
        self.price_normalizer = price_normalizer
        self.logger = logger

    def validate_stops(self, symbol: str, price: float, sl: float, tp: float,
                      signal_type: PositionType, symbol_info: dict) -> tuple:
        """
        Validate and adjust SL/TP to meet MT5 minimum stop level requirements.

        Args:
            symbol: Symbol name
            price: Entry price
            sl: Stop loss price
            tp: Take profit price
            signal_type: BUY or SELL
            symbol_info: Symbol information dictionary

        Returns:
            Tuple of (adjusted_sl, adjusted_tp)
        """
        point = symbol_info['point']
        stops_level = symbol_info.get('stops_level', 0)
        freeze_level = symbol_info.get('freeze_level', 0)

        # Log broker requirements for debugging
        self.logger.debug(
            f"Broker Stop Requirements: stops_level={stops_level} points, "
            f"freeze_level={freeze_level} points, point={point}",
            symbol
        )

        # Calculate current distances
        sl_distance = abs(price - sl)
        tp_distance = abs(price - tp)
        sl_distance_points = sl_distance / point if point > 0 else 0
        tp_distance_points = tp_distance / point if point > 0 else 0

        self.logger.debug(
            f"Current Stops: Entry={price:.5f}, SL={sl:.5f} ({sl_distance_points:.0f} pts), "
            f"TP={tp:.5f} ({tp_distance_points:.0f} pts)",
            symbol
        )

        # If stops_level is 0, no minimum distance required
        if stops_level == 0:
            self.logger.debug("No minimum stop level required (stops_level=0)", symbol)
            return sl, tp

        # Calculate minimum distance in price
        min_distance = stops_level * point

        self.logger.debug(
            f"Minimum required distance: {min_distance:.5f} ({stops_level} points)",
            symbol
        )

        # Check and adjust SL
        if sl_distance < min_distance:
            self.logger.warning(
                f"SL too close to entry: {sl_distance:.5f} ({sl_distance_points:.0f} pts) < "
                f"{min_distance:.5f} ({stops_level} pts). Adjusting...",
                symbol
            )
            if signal_type == PositionType.BUY:
                sl = price - min_distance
            else:
                sl = price + min_distance
            sl = self.price_normalizer.normalize_price(symbol, sl)
            self.logger.info(f"Adjusted SL: {sl:.5f}", symbol)

        # Check and adjust TP
        if tp_distance < min_distance:
            self.logger.warning(
                f"TP too close to entry: {tp_distance:.5f} ({tp_distance_points:.0f} pts) < "
                f"{min_distance:.5f} ({stops_level} pts). Adjusting...",
                symbol
            )
            if signal_type == PositionType.BUY:
                tp = price + min_distance
            else:
                tp = price - min_distance
            tp = self.price_normalizer.normalize_price(symbol, tp)
            self.logger.info(f"Adjusted TP: {tp:.5f}", symbol)

        # Verify SL is on correct side
        if signal_type == PositionType.BUY:
            if sl >= price:
                self.logger.error(f"Invalid BUY SL: {sl:.5f} >= Entry: {price:.5f}", symbol)
                sl = price - min_distance
                sl = self.price_normalizer.normalize_price(symbol, sl)
                self.logger.info(f"Corrected SL: {sl:.5f}", symbol)
            if tp <= price:
                self.logger.error(f"Invalid BUY TP: {tp:.5f} <= Entry: {price:.5f}", symbol)
                tp = price + min_distance
                tp = self.price_normalizer.normalize_price(symbol, tp)
                self.logger.info(f"Corrected TP: {tp:.5f}", symbol)
        else:  # SELL
            if sl <= price:
                self.logger.error(f"Invalid SELL SL: {sl:.5f} <= Entry: {price:.5f}", symbol)
                sl = price + min_distance
                sl = self.price_normalizer.normalize_price(symbol, sl)
                self.logger.info(f"Corrected SL: {sl:.5f}", symbol)
            if tp >= price:
                self.logger.error(f"Invalid SELL TP: {tp:.5f} >= Entry: {price:.5f}", symbol)
                tp = price - min_distance
                tp = self.price_normalizer.normalize_price(symbol, tp)
                self.logger.info(f"Corrected TP: {tp:.5f}", symbol)

        # Log final validated stops
        final_sl_distance = abs(price - sl)
        final_tp_distance = abs(price - tp)
        final_sl_distance_points = final_sl_distance / point if point > 0 else 0
        final_tp_distance_points = final_tp_distance / point if point > 0 else 0

        self.logger.debug(
            f"Final Validated Stops: SL={sl:.5f} ({final_sl_distance_points:.0f} pts), "
            f"TP={tp:.5f} ({final_tp_distance_points:.0f} pts)",
            symbol
        )

        return sl, tp

