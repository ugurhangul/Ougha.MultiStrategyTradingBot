"""
Integration tests for validation decorator with actual strategy classes.

Tests that the decorator works correctly with FakeoutStrategy, TrueBreakoutStrategy,
and HFTMomentumStrategy after refactoring.
"""
import unittest
from unittest.mock import Mock, MagicMock
from typing import Dict, Any

from src.strategy.fakeout_strategy import FakeoutStrategy
from src.strategy.true_breakout_strategy import TrueBreakoutStrategy
from src.strategy.hft_momentum_strategy import HFTMomentumStrategy
from src.strategy.validation_decorator import get_validation_methods


class TestStrategyDecoratorIntegration(unittest.TestCase):
    """Test validation decorator integration with actual strategies"""

    def setUp(self):
        """Set up mock dependencies for strategies"""
        self.symbol = "EURUSD"
        self.connector = Mock()
        self.order_manager = Mock()
        self.risk_manager = Mock()
        self.trade_manager = Mock()
        self.indicators = Mock()

        # Mock connector methods
        self.connector.get_symbol_info = Mock(return_value={'category': 'Forex'})
        self.connector.get_candles = Mock(return_value=None)

    def test_fakeout_strategy_decorator_integration(self):
        """Test FakeoutStrategy uses decorator correctly"""
        strategy = FakeoutStrategy(
            symbol=self.symbol,
            connector=self.connector,
            order_manager=self.order_manager,
            risk_manager=self.risk_manager,
            trade_manager=self.trade_manager,
            indicators=self.indicators
        )

        # Check that validation methods were auto-registered
        self.assertIsInstance(strategy._validation_methods, list)
        self.assertGreater(len(strategy._validation_methods), 0)

        # Check core validations are registered (order matters)
        self.assertIn("_check_breakout_volume", strategy._validation_methods)
        self.assertIn("_check_reversal_confirmation", strategy._validation_methods)
        self.assertIn("_check_reversal_volume", strategy._validation_methods)

        # Check abbreviations are registered
        self.assertEqual(strategy._validation_abbreviations.get("_check_breakout_volume"), "BV")
        self.assertEqual(strategy._validation_abbreviations.get("_check_reversal_confirmation"), "RV")
        self.assertEqual(strategy._validation_abbreviations.get("_check_reversal_volume"), "RVol")

        # Verify methods are decorated
        methods = get_validation_methods(strategy)
        self.assertIn("_check_breakout_volume", methods)
        self.assertEqual(methods["_check_breakout_volume"].abbreviation, "BV")
        self.assertEqual(methods["_check_breakout_volume"].order, 1)

    def test_true_breakout_strategy_decorator_integration(self):
        """Test TrueBreakoutStrategy uses decorator correctly"""
        strategy = TrueBreakoutStrategy(
            symbol=self.symbol,
            connector=self.connector,
            order_manager=self.order_manager,
            risk_manager=self.risk_manager,
            trade_manager=self.trade_manager,
            indicators=self.indicators
        )

        # Check that validation methods were auto-registered
        self.assertIsInstance(strategy._validation_methods, list)
        self.assertEqual(len(strategy._validation_methods), 3)

        # Check validations are registered in correct order
        self.assertEqual(strategy._validation_methods[0], "_check_breakout_volume")
        self.assertEqual(strategy._validation_methods[1], "_check_retest_confirmation")
        self.assertEqual(strategy._validation_methods[2], "_check_continuation_volume")

        # Check abbreviations
        self.assertEqual(strategy._validation_abbreviations.get("_check_breakout_volume"), "BV")
        self.assertEqual(strategy._validation_abbreviations.get("_check_retest_confirmation"), "RT")
        self.assertEqual(strategy._validation_abbreviations.get("_check_continuation_volume"), "CV")

        # Verify methods are decorated
        methods = get_validation_methods(strategy)
        self.assertEqual(len(methods), 3)
        self.assertEqual(methods["_check_retest_confirmation"].order, 2)

    def test_hft_momentum_strategy_decorator_integration(self):
        """Test HFTMomentumStrategy uses decorator correctly"""
        strategy = HFTMomentumStrategy(
            symbol=self.symbol,
            connector=self.connector,
            order_manager=self.order_manager,
            risk_manager=self.risk_manager,
            trade_manager=self.trade_manager,
            indicators=self.indicators
        )

        # Check that validation methods were auto-registered
        self.assertIsInstance(strategy._validation_methods, list)
        self.assertEqual(len(strategy._validation_methods), 5)

        # Check validations are registered in correct order
        self.assertEqual(strategy._validation_methods[0], "_check_momentum_strength")
        self.assertEqual(strategy._validation_methods[1], "_check_volume_confirmation")
        self.assertEqual(strategy._validation_methods[2], "_check_volatility_filter")
        self.assertEqual(strategy._validation_methods[3], "_check_trend_alignment")
        self.assertEqual(strategy._validation_methods[4], "_check_spread_filter")

        # Check abbreviations
        self.assertEqual(strategy._validation_abbreviations.get("_check_momentum_strength"), "M")
        self.assertEqual(strategy._validation_abbreviations.get("_check_volume_confirmation"), "V")
        self.assertEqual(strategy._validation_abbreviations.get("_check_volatility_filter"), "A")
        self.assertEqual(strategy._validation_abbreviations.get("_check_trend_alignment"), "T")
        self.assertEqual(strategy._validation_abbreviations.get("_check_spread_filter"), "S")

        # Verify methods are decorated with correct order
        methods = get_validation_methods(strategy)
        self.assertEqual(len(methods), 5)
        self.assertEqual(methods["_check_momentum_strength"].order, 1)
        self.assertEqual(methods["_check_spread_filter"].order, 5)

    def test_fakeout_strategy_conditional_divergence(self):
        """Test FakeoutStrategy hybrid approach with conditional divergence check"""
        # Test with divergence enabled (default)
        strategy_with_div = FakeoutStrategy(
            symbol=self.symbol,
            connector=self.connector,
            order_manager=self.order_manager,
            risk_manager=self.risk_manager,
            trade_manager=self.trade_manager,
            indicators=self.indicators
        )

        # Should have 4 validations (3 core + divergence, since check_divergence defaults to True)
        self.assertEqual(len(strategy_with_div._validation_methods), 4)
        self.assertIn("_check_divergence_confirmation", strategy_with_div._validation_methods)
        self.assertEqual(strategy_with_div._validation_abbreviations.get("_check_divergence_confirmation"), "DIV")

        # Verify the 3 core decorated validations are present
        self.assertIn("_check_breakout_volume", strategy_with_div._validation_methods)
        self.assertIn("_check_reversal_confirmation", strategy_with_div._validation_methods)
        self.assertIn("_check_reversal_volume", strategy_with_div._validation_methods)

    def test_optional_validation_integration(self):
        """Test that optional validations work correctly in actual strategy context"""
        # Create a custom config to test optional validations
        # We'll make volatility filter optional for this test
        strategy = HFTMomentumStrategy(
            symbol=self.symbol,
            connector=self.connector,
            order_manager=self.order_manager,
            risk_manager=self.risk_manager,
            trade_manager=self.trade_manager,
            indicators=self.indicators
        )

        # Manually override one validation to be optional for testing
        # In real usage, this would be done via the decorator
        if "_check_volatility_filter" in strategy._validation_requirements:
            strategy._validation_requirements["_check_volatility_filter"] = False

        # All validations should still be registered
        self.assertEqual(len(strategy._validation_methods), 5)

        # Verify the requirement was changed
        self.assertFalse(strategy._validation_requirements.get("_check_volatility_filter"))

        # Other validations should still be required
        self.assertTrue(strategy._validation_requirements.get("_check_momentum_strength"))
        self.assertTrue(strategy._validation_requirements.get("_check_volume_confirmation"))

    def test_mixed_required_optional_validations(self):
        """Test strategy with mix of required and optional validations"""
        # This test verifies the decorator metadata is properly stored
        strategy = HFTMomentumStrategy(
            symbol=self.symbol,
            connector=self.connector,
            order_manager=self.order_manager,
            risk_manager=self.risk_manager,
            trade_manager=self.trade_manager,
            indicators=self.indicators
        )

        # All current validations should be required by default
        for method_name in strategy._validation_methods:
            self.assertTrue(
                strategy._validation_requirements.get(method_name, True),
                f"Validation {method_name} should be required by default"
            )

        # Verify all validations have requirements defined
        self.assertEqual(
            len(strategy._validation_requirements),
            len(strategy._validation_methods)
        )



if __name__ == '__main__':
    unittest.main()

