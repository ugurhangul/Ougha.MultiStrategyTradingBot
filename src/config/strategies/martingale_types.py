"""
Martingale progression type definitions.

Used by HFT Momentum and other martingale-based strategies.
"""
from enum import Enum


class MartingaleType(Enum):
    """Martingale progression types"""
    CLASSIC_MULTIPLIER = "classic_multiplier"  # new_lot = prev_lot × multiplier
    MULTIPLIER_WITH_SUM = "multiplier_with_sum"  # new_lot = (prev_lot × multiplier) + initial
    SUM_WITH_INITIAL = "sum_with_initial"  # new_lot = prev_lot + initial

