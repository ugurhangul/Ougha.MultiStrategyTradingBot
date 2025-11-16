"""
Advanced trading configuration settings.
"""
from dataclasses import dataclass


@dataclass
class AdvancedConfig:
    """Advanced settings"""
    use_breakeven: bool = True
    breakeven_trigger_rr: float = 1.0
    magic_number: int = 123456
    trade_comment: str = "5MinScalper"
    enable_order_prevalidation: bool = True  # Use mt5.order_check() before order_send()

