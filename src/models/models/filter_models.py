"""
Filter state tracking models.
"""
from dataclasses import dataclass


@dataclass
class AdaptiveFilterState:
    """Adaptive filter system state"""
    is_active: bool = False
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    volume_confirmation_active: bool = False
    divergence_confirmation_active: bool = False
    original_volume_confirmation: bool = False
    original_divergence_confirmation: bool = False
    last_closed_ticket: int = 0

