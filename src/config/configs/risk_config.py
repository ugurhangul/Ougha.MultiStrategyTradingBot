"""
Risk management configuration settings.
"""
from dataclasses import dataclass


@dataclass
class RiskConfig:
    """Risk management settings"""
    risk_percent_per_trade: float = 1.0
    max_lot_size: float = 10.0
    min_lot_size: float = 0.01
    max_positions: int = 10
    max_portfolio_risk_percent: float = 20.0  # Maximum total portfolio risk across all positions


@dataclass
class TrailingStopConfig:
    """Trailing stop settings"""
    use_trailing_stop: bool = False
    trailing_stop_trigger_rr: float = 1.5
    trailing_stop_distance: float = 50.0

    # ATR-based trailing stop
    use_atr_trailing: bool = False
    atr_period: int = 14
    atr_multiplier: float = 1.5
    atr_timeframe: str = "H4"

