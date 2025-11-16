"""
Unit tests for pre-trade risk validation in OrderExecutor.
"""
import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone

from src.execution.order_management.order_executor import OrderExecutor
from src.models.data_models import TradeSignal, PositionType
from src.config.configs import RiskConfig


class TestPreTradeRiskValidation(unittest.TestCase):
    """Test pre-trade risk validation functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Create mocks
        self.connector = Mock()
        self.persistence = Mock()
        self.cooldown = Mock()
        self.price_normalizer = Mock()
        self.logger = Mock()
        self.risk_manager = Mock()

        # Configure risk manager
        self.risk_manager.risk_config = RiskConfig(
            risk_percent_per_trade=3.0,
            max_lot_size=10.0,
            min_lot_size=0.01,
            max_positions=10
        )

        # Create OrderExecutor
        self.executor = OrderExecutor(
            connector=self.connector,
            magic_number=123456,
            persistence=self.persistence,
            cooldown=self.cooldown,
            price_normalizer=self.price_normalizer,
            logger=self.logger,
            risk_manager=self.risk_manager
        )

        # Configure common mocks
        self.cooldown.is_market_closed.return_value = False
        self.cooldown.is_in_cooldown.return_value = False
        self.connector.is_autotrading_enabled.return_value = True
        self.connector.is_trading_enabled.return_value = True
        self.risk_manager.can_open_new_position.return_value = (True, "")

    def test_risk_validation_rejects_excessive_risk(self):
        """Test that trades with excessive risk are rejected"""
        # Setup: BTCAUD scenario with 20% risk
        symbol = "BTCAUD"
        
        # Mock account balance
        self.connector.get_account_balance.return_value = 577.57
        self.connector.get_account_currency.return_value = "USD"
        
        # Mock symbol info
        self.connector.get_symbol_info.return_value = {
            'point': 0.1,
            'tick_value': 0.04271,
            'contract_size': 1.0,
            'digits': 1,
            'currency_profit': 'USD',
            'currency_base': 'BTC',
            'min_lot': 0.5,
            'max_lot': 20.0,
            'lot_step': 0.5,
            'stops_level': 0,
            'freeze_level': 0,
            'filling_mode': 0
        }
        
        # Mock current price
        self.connector.get_current_price.return_value = 146652.10
        
        # Mock price normalizer
        self.price_normalizer.normalize_price.side_effect = lambda s, p: p
        self.price_normalizer.normalize_volume.side_effect = lambda s, v: v
        
        # Create signal with 0.5 lots and wide SL (5523 points = 20% risk)
        signal = TradeSignal(
            symbol=symbol,
            signal_type=PositionType.SELL,
            entry_price=146652.10,
            stop_loss=147204.40,  # 5523 points away
            take_profit=145547.50,
            lot_size=0.5,
            timestamp=datetime.now(timezone.utc),
            comment="TB|4H_5M|RTCV"
        )
        
        # Execute signal
        result = self.executor.execute_signal(signal)
        
        # Verify trade was rejected
        self.assertIsNone(result, "Trade should be rejected due to excessive risk")
        
        # Verify warning was logged
        self.logger.warning.assert_called()
        warning_calls = [str(call) for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any("PRE-TRADE RISK VALIDATION FAILED" in str(call) for call in warning_calls),
            "Should log risk validation failure"
        )

    def test_risk_validation_accepts_acceptable_risk(self):
        """Test that trades with acceptable risk are allowed"""
        # Setup: Trade with 2% risk (within 3% limit)
        symbol = "EURUSD"
        
        # Mock account balance
        self.connector.get_account_balance.return_value = 10000.0
        self.connector.get_account_currency.return_value = "USD"
        
        # Mock symbol info
        self.connector.get_symbol_info.return_value = {
            'point': 0.00001,
            'tick_value': 1.0,
            'contract_size': 100000.0,
            'digits': 5,
            'currency_profit': 'USD',
            'currency_base': 'EUR',
            'min_lot': 0.01,
            'max_lot': 100.0,
            'lot_step': 0.01,
            'stops_level': 0,
            'freeze_level': 0,
            'filling_mode': 0
        }
        
        # Mock current price
        self.connector.get_current_price.return_value = 1.10000
        
        # Mock price normalizer
        self.price_normalizer.normalize_price.side_effect = lambda s, p: p
        self.price_normalizer.normalize_volume.side_effect = lambda s, v: v
        
        # Create signal with acceptable risk
        signal = TradeSignal(
            symbol=symbol,
            signal_type=PositionType.BUY,
            entry_price=1.10000,
            stop_loss=1.09800,  # 20 pips = 2% risk with 1.0 lot
            take_profit=1.10400,
            lot_size=1.0,
            timestamp=datetime.now(timezone.utc),
            comment="TB|4H_5M|BV"
        )
        
        # Note: We need to mock the rest of execute_signal to avoid errors
        # For this test, we just verify the risk validation passes
        # The actual order execution will fail due to missing mocks, but that's OK
        
        # We'll test the validation method directly
        result = self.executor._validate_pre_trade_risk(
            symbol=symbol,
            lot_size=1.0,
            entry_price=1.10000,
            stop_loss=1.09800
        )
        
        # Verify validation passed
        self.assertTrue(result, "Trade with acceptable risk should pass validation")

    def test_portfolio_risk_validation_rejects_excessive_total_risk(self):
        """Test that trades are rejected when total portfolio risk exceeds 20%"""
        # Setup: Account with existing positions that already have 15% risk
        symbol = "EURUSD"

        # Mock account balance
        self.connector.get_account_balance.return_value = 10000.0
        self.connector.get_account_currency.return_value = "USD"

        # Mock existing positions with 15% total risk
        existing_position = Mock()
        existing_position.ticket = 12345
        existing_position.symbol = "GBPUSD"
        existing_position.volume = 1.0
        existing_position.current_price = 1.30000
        existing_position.sl = 1.29500  # 50 pips

        self.connector.get_positions.return_value = [existing_position]

        # Mock symbol info for existing position
        def get_symbol_info_side_effect(sym):
            if sym == "GBPUSD":
                return {
                    'point': 0.00001,
                    'tick_value': 1.0,
                    'contract_size': 100000.0,
                    'digits': 5,
                    'currency_profit': 'USD',
                    'currency_base': 'GBP',
                    'min_lot': 0.01,
                    'max_lot': 100.0,
                    'lot_step': 0.01,
                    'stops_level': 0,
                    'freeze_level': 0,
                    'filling_mode': 0
                }
            elif sym == "EURUSD":
                return {
                    'point': 0.00001,
                    'tick_value': 1.0,
                    'contract_size': 100000.0,
                    'digits': 5,
                    'currency_profit': 'USD',
                    'currency_base': 'EUR',
                    'min_lot': 0.01,
                    'max_lot': 100.0,
                    'lot_step': 0.01,
                    'stops_level': 0,
                    'freeze_level': 0,
                    'filling_mode': 0
                }
            return None

        self.connector.get_symbol_info.side_effect = get_symbol_info_side_effect

        # Test the validation method directly
        # Existing position: 1.0 lot × 5000 points × $1.0 = $5,000 risk (50% of account)
        # Wait, let me recalculate: 50 pips = 500 points, so 500 × $1.0 × 1.0 = $500 (5% risk)
        # Let's make it 15% by using 3 lots: 500 × $1.0 × 3.0 = $1,500 (15% risk)
        existing_position.volume = 3.0

        # New trade would add 10% more risk (total 25% > 20% limit)
        # 1000 points × $1.0 × 1.0 lot = $1,000 (10% risk)
        result = self.executor._validate_portfolio_risk(
            symbol="EURUSD",
            lot_size=1.0,
            entry_price=1.10000,
            stop_loss=1.09000  # 100 pips = 1000 points
        )

        # Verify validation failed
        self.assertFalse(result, "Trade should be rejected when portfolio risk exceeds 20%")

        # Verify warning was logged
        self.logger.warning.assert_called()
        warning_calls = [str(call) for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any("PORTFOLIO RISK VALIDATION FAILED" in str(call) for call in warning_calls),
            "Should log portfolio risk validation failure"
        )

    def test_portfolio_risk_validation_accepts_acceptable_total_risk(self):
        """Test that trades are accepted when total portfolio risk is within 20% limit"""
        # Setup: Account with existing positions that have 10% risk
        symbol = "EURUSD"

        # Mock account balance
        self.connector.get_account_balance.return_value = 10000.0
        self.connector.get_account_currency.return_value = "USD"

        # Mock existing positions with 10% total risk
        existing_position = Mock()
        existing_position.ticket = 12345
        existing_position.symbol = "GBPUSD"
        existing_position.volume = 2.0  # 500 points × $1.0 × 2.0 = $1,000 (10% risk)
        existing_position.current_price = 1.30000
        existing_position.sl = 1.29500  # 50 pips = 500 points

        self.connector.get_positions.return_value = [existing_position]

        # Mock symbol info
        def get_symbol_info_side_effect(sym):
            return {
                'point': 0.00001,
                'tick_value': 1.0,
                'contract_size': 100000.0,
                'digits': 5,
                'currency_profit': 'USD',
                'currency_base': 'GBP' if sym == "GBPUSD" else 'EUR',
                'min_lot': 0.01,
                'max_lot': 100.0,
                'lot_step': 0.01,
                'stops_level': 0,
                'freeze_level': 0,
                'filling_mode': 0
            }

        self.connector.get_symbol_info.side_effect = get_symbol_info_side_effect

        # New trade would add 5% more risk (total 15% < 20% limit)
        # 500 points × $1.0 × 1.0 lot = $500 (5% risk)
        result = self.executor._validate_portfolio_risk(
            symbol="EURUSD",
            lot_size=1.0,
            entry_price=1.10000,
            stop_loss=1.09500  # 50 pips = 500 points
        )

        # Verify validation passed
        self.assertTrue(result, "Trade should be accepted when portfolio risk is within 20% limit")


if __name__ == '__main__':
    unittest.main()

