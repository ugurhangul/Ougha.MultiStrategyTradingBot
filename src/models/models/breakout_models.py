"""
Breakout state tracking models.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict


@dataclass
class UnifiedBreakoutState:
    """
    Unified breakout state tracking.

    Stage 1: Unified breakout detection
    Stage 2: Strategy classification (both strategies can evaluate simultaneously)
    """
    # === STAGE 1: UNIFIED BREAKOUT DETECTION ===
    # Breakout above 4H high
    breakout_above_detected: bool = False
    breakout_above_volume: int = 0
    breakout_above_time: Optional[datetime] = None

    # Breakout below 4H low
    breakout_below_detected: bool = False
    breakout_below_volume: int = 0
    breakout_below_time: Optional[datetime] = None

    # === STAGE 2: STRATEGY CLASSIFICATION ===
    # FALSE BREAKOUT - Reversal from BELOW (BUY signal)
    false_buy_qualified: bool = False  # Low volume breakout below
    false_buy_reversal_detected: bool = False  # Reversed back above
    false_buy_reversal_confirmed: bool = False  # Next candle confirmed reversal direction
    false_buy_reversal_volume: int = 0
    false_buy_confirmation_detected: bool = False  # Confirmation candle detected
    false_buy_confirmation_volume: int = 0  # Confirmation candle volume
    false_buy_volume_ok: bool = False  # Breakout volume was low (tracked, not required)
    false_buy_reversal_volume_ok: bool = False  # Reversal volume was high (tracked, not required)
    false_buy_confirmation_volume_ok: bool = False  # Confirmation volume was high (tracked, not required)
    false_buy_divergence_ok: bool = False  # Divergence present (tracked, not required)
    false_buy_rejected: bool = False  # Strategy explicitly rejected this setup

    # FALSE BREAKOUT - Reversal from ABOVE (SELL signal)
    false_sell_qualified: bool = False  # Low volume breakout above
    false_sell_reversal_detected: bool = False  # Reversed back below
    false_sell_reversal_confirmed: bool = False  # Next candle confirmed reversal direction
    false_sell_reversal_volume: int = 0
    false_sell_confirmation_detected: bool = False  # Confirmation candle detected
    false_sell_confirmation_volume: int = 0  # Confirmation candle volume
    false_sell_volume_ok: bool = False  # Breakout volume was low (tracked, not required)
    false_sell_reversal_volume_ok: bool = False  # Reversal volume was high (tracked, not required)
    false_sell_confirmation_volume_ok: bool = False  # Confirmation volume was high (tracked, not required)
    false_sell_divergence_ok: bool = False  # Divergence present (tracked, not required)
    false_sell_rejected: bool = False  # Strategy explicitly rejected this setup

    # TRUE BREAKOUT - Continuation ABOVE (BUY signal)
    true_buy_qualified: bool = False  # High volume breakout above
    true_buy_retest_detected: bool = False  # Price retested breakout level (pulled back to 4H high)
    true_buy_continuation_detected: bool = False  # Continued above after retest
    true_buy_continuation_volume: int = 0
    true_buy_volume_ok: bool = False  # Breakout volume was high (tracked, not required)
    true_buy_retest_ok: bool = False  # Retest occurred (tracked, not required)
    true_buy_continuation_volume_ok: bool = False  # Continuation volume was high (tracked, not required)
    true_buy_rejected: bool = False  # Strategy explicitly rejected this setup

    # TRUE BREAKOUT - Continuation BELOW (SELL signal)
    true_sell_qualified: bool = False  # High volume breakout below
    true_sell_retest_detected: bool = False  # Price retested breakout level (pulled back to 4H low)
    true_sell_continuation_detected: bool = False  # Continued below after retest
    true_sell_continuation_volume: int = 0
    true_sell_volume_ok: bool = False  # Breakout volume was high (tracked, not required)
    true_sell_retest_ok: bool = False  # Retest occurred (tracked, not required)
    true_sell_continuation_volume_ok: bool = False  # Continuation volume was high (tracked, not required)
    true_sell_rejected: bool = False  # Strategy explicitly rejected this setup

    def has_active_breakout(self) -> bool:
        """Check if there's an active breakout being tracked"""
        return self.breakout_above_detected or self.breakout_below_detected

    def both_strategies_rejected(self) -> bool:
        """Check if both strategies have rejected the current setup"""
        if self.breakout_above_detected:
            # For breakout above: check TRUE BUY and FALSE SELL
            return self.true_buy_rejected and self.false_sell_rejected
        elif self.breakout_below_detected:
            # For breakout below: check TRUE SELL and FALSE BUY
            return self.true_sell_rejected and self.false_buy_rejected
        return False

    def reset_breakout_above(self):
        """Reset breakout above 4H high"""
        self.breakout_above_detected = False
        self.breakout_above_volume = 0
        self.breakout_above_time = None
        # Reset associated strategies
        self.true_buy_qualified = False
        self.true_buy_retest_detected = False
        self.true_buy_continuation_detected = False
        self.true_buy_continuation_volume = 0
        self.true_buy_volume_ok = False
        self.true_buy_retest_ok = False
        self.true_buy_continuation_volume_ok = False
        self.true_buy_rejected = False
        self.false_sell_qualified = False
        self.false_sell_reversal_detected = False
        self.false_sell_reversal_volume = 0
        self.false_sell_volume_ok = False
        self.false_sell_reversal_volume_ok = False
        self.false_sell_divergence_ok = False
        self.false_sell_rejected = False

    def reset_breakout_below(self):
        """Reset breakout below 4H low"""
        self.breakout_below_detected = False
        self.breakout_below_volume = 0
        self.breakout_below_time = None
        # Reset associated strategies
        self.true_sell_qualified = False
        self.true_sell_retest_detected = False
        self.true_sell_continuation_detected = False
        self.true_sell_continuation_volume = 0
        self.true_sell_volume_ok = False
        self.true_sell_retest_ok = False
        self.true_sell_continuation_volume_ok = False
        self.true_sell_rejected = False
        self.false_buy_qualified = False
        self.false_buy_reversal_detected = False
        self.false_buy_reversal_volume = 0
        self.false_buy_volume_ok = False
        self.false_buy_reversal_volume_ok = False
        self.false_buy_divergence_ok = False
        self.false_buy_rejected = False

    def reset_all(self):
        """Reset all tracking"""
        self.reset_breakout_above()
        self.reset_breakout_below()


@dataclass
class MultiRangeBreakoutState:
    """
    Multi-range breakout state tracking.

    Manages independent breakout detection and strategy classification for multiple
    range configurations simultaneously (e.g., 4H/5M and 15M/1M).

    Each range configuration has its own UnifiedBreakoutState instance.
    """
    # Dictionary mapping range_id to UnifiedBreakoutState
    range_states: Dict[str, UnifiedBreakoutState] = field(default_factory=dict)

    def get_or_create_state(self, range_id: str) -> UnifiedBreakoutState:
        """Get or create state for a specific range configuration"""
        if range_id not in self.range_states:
            self.range_states[range_id] = UnifiedBreakoutState()
        return self.range_states[range_id]

    def get_state(self, range_id: str) -> Optional[UnifiedBreakoutState]:
        """Get state for a specific range configuration (returns None if not exists)"""
        return self.range_states.get(range_id)

    def has_active_breakout(self, range_id: Optional[str] = None) -> bool:
        """
        Check if there's an active breakout.

        Args:
            range_id: Specific range to check, or None to check all ranges

        Returns:
            True if any range has an active breakout
        """
        if range_id:
            state = self.get_state(range_id)
            return state.has_active_breakout() if state else False

        # Check all ranges
        return any(state.has_active_breakout() for state in self.range_states.values())

    def reset_range(self, range_id: str):
        """Reset state for a specific range configuration"""
        if range_id in self.range_states:
            self.range_states[range_id].reset_all()

    def reset_all(self):
        """Reset all range states"""
        for state in self.range_states.values():
            state.reset_all()

