"""
Unit tests for mt5.order_check() validation in OrderExecutor.
"""
import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone

from src.execution.order_management.order_executor import OrderExecutor
from src.models.data_models import TradeSignal, PositionType
import MetaTrader5 as mt5


class TestOrderCheckValidation(unittest.TestCase):
    """Test mt5.order_check() validation functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Create mocks
        self.connector = Mock()
        self.persistence = Mock()
        self.cooldown = Mock()
        self.price_normalizer = Mock()
        self.logger = Mock()
        self.risk_manager = Mock()

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

    @patch('MetaTrader5.order_check')
    def test_validation_passes(self, mock_order_check):
        """Test successful order validation"""
        # Mock successful validation
        mock_check_result = Mock()
        mock_check_result.retcode = mt5.TRADE_RETCODE_DONE
        mock_check_result.margin = 100.0
        mock_check_result.margin_free = 9900.0
        mock_check_result.margin_level = 10000.0
        mock_check_result.balance = 10000.0
        mock_check_result.equity = 10000.0
        mock_order_check.return_value = mock_check_result

        # Create test request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": "EURUSD",
            "volume": 0.1,
            "type": mt5.ORDER_TYPE_BUY,
            "price": 1.1000,
            "sl": 1.0950,
            "tp": 1.1100,
        }

        # Validate order
        is_valid, error_message = self.executor._validate_order_with_broker(request, "EURUSD")

        # Verify validation passed
        self.assertTrue(is_valid)
        self.assertEqual(error_message, "")
        self.assertEqual(self.executor.validation_stats['total_validations'], 1)
        self.assertEqual(self.executor.validation_stats['validation_passed'], 1)
        self.assertEqual(self.executor.validation_stats['validation_failed'], 0)

    @patch('MetaTrader5.order_check')
    def test_validation_fails_insufficient_margin(self, mock_order_check):
        """Test order validation failure due to insufficient margin"""
        # Mock validation failure
        mock_check_result = Mock()
        mock_check_result.retcode = mt5.TRADE_RETCODE_NO_MONEY
        mock_check_result.comment = "Not enough money"
        mock_check_result.margin = 10000.0
        mock_check_result.margin_free = 0.0
        mock_check_result.balance = 100.0
        mock_check_result.equity = 100.0
        mock_order_check.return_value = mock_check_result

        # Create test request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": "EURUSD",
            "volume": 10.0,  # Large volume
            "type": mt5.ORDER_TYPE_BUY,
            "price": 1.1000,
            "sl": 1.0950,
            "tp": 1.1100,
        }

        # Validate order
        is_valid, error_message = self.executor._validate_order_with_broker(request, "EURUSD")

        # Verify validation failed
        self.assertFalse(is_valid)
        self.assertIn("Not enough money", error_message)
        self.assertEqual(self.executor.validation_stats['total_validations'], 1)
        self.assertEqual(self.executor.validation_stats['validation_passed'], 0)
        self.assertEqual(self.executor.validation_stats['validation_failed'], 1)
        self.assertIn(str(mt5.TRADE_RETCODE_NO_MONEY), self.executor.validation_stats['rejection_reasons'])

    @patch('MetaTrader5.order_check')
    @patch('MetaTrader5.last_error')
    def test_validation_returns_none(self, mock_last_error, mock_order_check):
        """Test order validation when order_check returns None"""
        # Mock order_check returning None
        mock_order_check.return_value = None
        mock_last_error.return_value = (1, "Generic error")

        # Create test request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": "EURUSD",
            "volume": 0.1,
            "type": mt5.ORDER_TYPE_BUY,
            "price": 1.1000,
        }

        # Validate order
        is_valid, error_message = self.executor._validate_order_with_broker(request, "EURUSD")

        # Verify validation failed
        self.assertFalse(is_valid)
        self.assertIn("Order check failed", error_message)
        self.assertEqual(self.executor.validation_stats['validation_failed'], 1)

    def test_validation_statistics(self):
        """Test validation statistics tracking"""
        # Initial stats should be zero
        stats = self.executor.get_validation_stats()
        self.assertEqual(stats['total_validations'], 0)
        self.assertEqual(stats['validation_passed'], 0)
        self.assertEqual(stats['validation_failed'], 0)
        self.assertEqual(len(stats['rejection_reasons']), 0)

        # Manually update stats to test tracking
        self.executor.validation_stats['total_validations'] = 10
        self.executor.validation_stats['validation_passed'] = 7
        self.executor.validation_stats['validation_failed'] = 3
        self.executor.validation_stats['rejection_reasons']['10019'] = 2
        self.executor.validation_stats['rejection_reasons']['10016'] = 1

        # Get stats
        stats = self.executor.get_validation_stats()
        self.assertEqual(stats['total_validations'], 10)
        self.assertEqual(stats['validation_passed'], 7)
        self.assertEqual(stats['validation_failed'], 3)
        self.assertEqual(stats['rejection_reasons']['10019'], 2)
        self.assertEqual(stats['rejection_reasons']['10016'], 1)


if __name__ == '__main__':
    unittest.main()

