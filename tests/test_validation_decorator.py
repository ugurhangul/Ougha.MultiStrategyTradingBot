"""
Unit tests for validation decorator.

Tests the @validation_check decorator and related utility functions.
"""
import unittest
from typing import Dict, Any
from unittest.mock import Mock

from src.strategy.base_strategy import BaseStrategy, ValidationResult
from src.strategy.validation_decorator import (
    validation_check,
    get_validation_methods,
    auto_register_validations,
    ValidationMetadata
)


class MockStrategy(BaseStrategy):
    """Mock strategy for testing"""

    def __init__(self):
        # Minimal initialization for testing
        self.symbol = "TEST"
        self.connector = Mock()
        self.order_manager = Mock()
        self.risk_manager = Mock()
        self.trade_manager = Mock()
        self.indicators = Mock()
        self.position_sizer = None
        self.logger = Mock()
        self.is_initialized = False
        self.category = None
        self.symbol_params = None
        self.key = "test_strategy"
        self._validation_methods = []
        self._validation_mode = "all"
        self._last_validation_results = []
        self._validation_abbreviations = {}
        self._validation_requirements = {}

    def initialize(self) -> bool:
        return True

    def on_tick(self):
        return None

    def on_position_closed(self, symbol: str, profit: float, volume: float, comment: str) -> None:
        pass

    def get_status(self) -> Dict[str, Any]:
        return {}

    def shutdown(self) -> None:
        pass


class TestValidationDecorator(unittest.TestCase):
    """Test validation decorator functionality"""

    def test_decorator_marks_method(self):
        """Test that decorator marks methods correctly"""

        @validation_check(abbreviation="T", order=1, description="Test validation")
        def test_method(self, signal_data: Dict[str, Any]) -> ValidationResult:
            return ValidationResult(passed=True, method_name="test_method", reason="OK")

        # Check that method is marked
        self.assertTrue(hasattr(test_method, '_is_validation_check'))
        self.assertTrue(test_method._is_validation_check)

        # Check metadata
        self.assertTrue(hasattr(test_method, '_validation_metadata'))
        metadata = test_method._validation_metadata
        self.assertEqual(metadata.method_name, "test_method")
        self.assertEqual(metadata.abbreviation, "T")
        self.assertEqual(metadata.order, 1)
        self.assertEqual(metadata.description, "Test validation")

    def test_decorator_preserves_functionality(self):
        """Test that decorated methods still work correctly"""

        class TestStrategy(MockStrategy):
            @validation_check(abbreviation="M", order=1)
            def _check_momentum(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(
                    passed=signal_data.get('momentum', 0) > 0,
                    method_name="_check_momentum",
                    reason="Momentum check"
                )

        strategy = TestStrategy()

        # Test with passing data
        result = strategy._check_momentum({'momentum': 10})
        self.assertTrue(result.passed)
        self.assertEqual(result.method_name, "_check_momentum")

        # Test with failing data
        result = strategy._check_momentum({'momentum': -5})
        self.assertFalse(result.passed)

    def test_get_validation_methods(self):
        """Test discovery of validation methods"""

        class TestStrategy(MockStrategy):
            @validation_check(abbreviation="M", order=1)
            def _check_momentum(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=True, method_name="_check_momentum", reason="OK")

            @validation_check(abbreviation="V", order=2)
            def _check_volume(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=True, method_name="_check_volume", reason="OK")

            # Non-decorated method should not be discovered
            def _some_other_method(self):
                pass

        strategy = TestStrategy()
        methods = get_validation_methods(strategy)

        # Should find exactly 2 validation methods
        self.assertEqual(len(methods), 2)
        self.assertIn("_check_momentum", methods)
        self.assertIn("_check_volume", methods)
        self.assertNotIn("_some_other_method", methods)

        # Check metadata
        self.assertEqual(methods["_check_momentum"].abbreviation, "M")
        self.assertEqual(methods["_check_momentum"].order, 1)
        self.assertEqual(methods["_check_volume"].abbreviation, "V")
        self.assertEqual(methods["_check_volume"].order, 2)

    def test_auto_register_validations(self):
        """Test automatic registration of validation methods"""

        class TestStrategy(MockStrategy):
            def __init__(self):
                super().__init__()
                auto_register_validations(self)

            @validation_check(abbreviation="M", order=2)
            def _check_momentum(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=True, method_name="_check_momentum", reason="OK")

            @validation_check(abbreviation="V", order=1)
            def _check_volume(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=True, method_name="_check_volume", reason="OK")

            @validation_check(abbreviation="S", order=3)
            def _check_spread(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=True, method_name="_check_spread", reason="OK")

        strategy = TestStrategy()

        # Check that _validation_methods is populated in correct order
        self.assertEqual(len(strategy._validation_methods), 3)
        self.assertEqual(strategy._validation_methods[0], "_check_volume")  # order=1
        self.assertEqual(strategy._validation_methods[1], "_check_momentum")  # order=2
        self.assertEqual(strategy._validation_methods[2], "_check_spread")  # order=3

        # Check that _validation_abbreviations is populated
        self.assertEqual(len(strategy._validation_abbreviations), 3)
        self.assertEqual(strategy._validation_abbreviations["_check_momentum"], "M")
        self.assertEqual(strategy._validation_abbreviations["_check_volume"], "V")
        self.assertEqual(strategy._validation_abbreviations["_check_spread"], "S")

    def test_decorator_without_abbreviation(self):
        """Test decorator when abbreviation is not provided"""

        class TestStrategy(MockStrategy):
            def __init__(self):
                super().__init__()
                auto_register_validations(self)

            @validation_check(order=1)  # No abbreviation
            def _check_something(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=True, method_name="_check_something", reason="OK")

        strategy = TestStrategy()

        # Method should be registered
        self.assertIn("_check_something", strategy._validation_methods)

        # But abbreviation should not be in the dict (empty string)
        self.assertNotIn("_check_something", strategy._validation_abbreviations)

    def test_hybrid_approach(self):
        """Test hybrid approach with decorator + manual override"""

        class TestStrategy(MockStrategy):
            def __init__(self, enable_extra_check: bool = False):
                super().__init__()

                # Auto-register decorated methods
                auto_register_validations(self)

                # Conditionally add extra validation
                if enable_extra_check:
                    self._validation_methods.append("_check_extra")
                    self._validation_abbreviations["_check_extra"] = "EX"

            @validation_check(abbreviation="M", order=1)
            def _check_momentum(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=True, method_name="_check_momentum", reason="OK")

            # Not decorated - only added manually when enabled
            def _check_extra(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=True, method_name="_check_extra", reason="OK")

        # Test without extra check
        strategy1 = TestStrategy(enable_extra_check=False)
        self.assertEqual(len(strategy1._validation_methods), 1)
        self.assertNotIn("_check_extra", strategy1._validation_methods)

        # Test with extra check
        strategy2 = TestStrategy(enable_extra_check=True)
        self.assertEqual(len(strategy2._validation_methods), 2)
        self.assertIn("_check_extra", strategy2._validation_methods)

    def test_required_parameter_default(self):
        """Test that required parameter defaults to True"""

        @validation_check(abbreviation="T", order=1)
        def test_method(self, signal_data: Dict[str, Any]) -> ValidationResult:
            return ValidationResult(passed=True, method_name="test_method", reason="OK")

        # Check metadata
        self.assertTrue(hasattr(test_method, '_validation_metadata'))
        metadata = test_method._validation_metadata
        self.assertTrue(metadata.required)  # Should default to True

    def test_required_parameter_explicit(self):
        """Test that required parameter can be set explicitly"""

        class TestStrategy(MockStrategy):
            def __init__(self):
                super().__init__()
                auto_register_validations(self)

            @validation_check(abbreviation="R", order=1, required=True)
            def _check_required(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=True, method_name="_check_required", reason="OK")

            @validation_check(abbreviation="O", order=2, required=False)
            def _check_optional(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=True, method_name="_check_optional", reason="OK")

        strategy = TestStrategy()

        # Check that both methods are registered
        self.assertEqual(len(strategy._validation_methods), 2)
        self.assertIn("_check_required", strategy._validation_methods)
        self.assertIn("_check_optional", strategy._validation_methods)

        # Check validation requirements
        self.assertTrue(strategy._validation_requirements.get("_check_required"))
        self.assertFalse(strategy._validation_requirements.get("_check_optional"))

        # Verify metadata
        methods = get_validation_methods(strategy)
        self.assertTrue(methods["_check_required"].required)
        self.assertFalse(methods["_check_optional"].required)

    def test_optional_validation_behavior(self):
        """Test that optional validations don't block signals"""

        class TestStrategy(MockStrategy):
            def __init__(self):
                super().__init__()
                auto_register_validations(self)

            @validation_check(abbreviation="R", order=1, required=True)
            def _check_required(self, signal_data: Dict[str, Any]) -> ValidationResult:
                # This will pass
                return ValidationResult(passed=True, method_name="_check_required", reason="Required passed")

            @validation_check(abbreviation="O", order=2, required=False)
            def _check_optional(self, signal_data: Dict[str, Any]) -> ValidationResult:
                # This will fail, but shouldn't block signal
                return ValidationResult(passed=False, method_name="_check_optional", reason="Optional failed")

        strategy = TestStrategy()

        # Validate signal
        is_valid, results = strategy._validate_signal({})

        # Signal should be valid because only required validation passed
        self.assertTrue(is_valid)
        self.assertEqual(len(results), 2)

        # Check individual results
        required_result = next(r for r in results if r.method_name == "_check_required")
        optional_result = next(r for r in results if r.method_name == "_check_optional")

        self.assertTrue(required_result.passed)
        self.assertFalse(optional_result.passed)

    def test_required_validation_blocks_signal(self):
        """Test that required validation failure blocks signal"""

        class TestStrategy(MockStrategy):
            def __init__(self):
                super().__init__()
                auto_register_validations(self)

            @validation_check(abbreviation="R", order=1, required=True)
            def _check_required(self, signal_data: Dict[str, Any]) -> ValidationResult:
                # This will fail and should block signal
                return ValidationResult(passed=False, method_name="_check_required", reason="Required failed")

            @validation_check(abbreviation="O", order=2, required=False)
            def _check_optional(self, signal_data: Dict[str, Any]) -> ValidationResult:
                # This passes but shouldn't matter
                return ValidationResult(passed=True, method_name="_check_optional", reason="Optional passed")

        strategy = TestStrategy()

        # Validate signal
        is_valid, results = strategy._validate_signal({})

        # Signal should be invalid because required validation failed
        self.assertFalse(is_valid)
        self.assertEqual(len(results), 2)

    def test_all_optional_validations(self):
        """Test strategy with only optional validations"""

        class TestStrategy(MockStrategy):
            def __init__(self):
                super().__init__()
                auto_register_validations(self)

            @validation_check(abbreviation="O1", order=1, required=False)
            def _check_optional1(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=False, method_name="_check_optional1", reason="Optional 1 failed")

            @validation_check(abbreviation="O2", order=2, required=False)
            def _check_optional2(self, signal_data: Dict[str, Any]) -> ValidationResult:
                return ValidationResult(passed=False, method_name="_check_optional2", reason="Optional 2 failed")

        strategy = TestStrategy()

        # Validate signal
        is_valid, results = strategy._validate_signal({})

        # Signal should be valid because all validations are optional
        self.assertTrue(is_valid)
        self.assertEqual(len(results), 2)

        # Both should have failed, but signal is still valid
        self.assertFalse(results[0].passed)
        self.assertFalse(results[1].passed)


if __name__ == '__main__':
    unittest.main()

