"""
Adaptive filter system based on performance.
Automatically enables/disables volume and divergence filters.
"""
from src.models.data_models import AdaptiveFilterState, SymbolParameters
from src.config.configs import AdaptiveFilterConfig
from src.utils.logger import get_logger


class AdaptiveFilter:
    """Manages adaptive filter activation/deactivation"""
    
    def __init__(self, symbol: str, config: AdaptiveFilterConfig,
                 symbol_params: SymbolParameters):
        """
        Initialize adaptive filter.
        
        Args:
            symbol: Symbol name
            config: Adaptive filter configuration
            symbol_params: Symbol-specific parameters
        """
        self.symbol = symbol
        self.config = config
        self.symbol_params = symbol_params
        self.logger = get_logger()
        
        # Filter state
        self.state = AdaptiveFilterState()
    
    def on_trade_result(self, is_win: bool):
        """
        Update filter state based on trade result.
        
        Args:
            is_win: True if trade was profitable
        """
        if not self.config.use_adaptive_filters:
            return
        
        if is_win:
            self.state.consecutive_wins += 1
            self.state.consecutive_losses = 0

            self.logger.info(
                f"Trade WIN - Consecutive wins: {self.state.consecutive_wins}",
                self.symbol
            )

            # Check if we should disable filters (winning streak)
            if self.state.consecutive_wins >= self.config.adaptive_win_recovery:
                self._disable_filters()
        else:
            self.state.consecutive_losses += 1
            self.state.consecutive_wins = 0

            self.logger.info(
                f"Trade LOSS - Consecutive losses: {self.state.consecutive_losses}",
                self.symbol
            )

            # Check if we should enable filters (losing streak)
            if self.state.consecutive_losses >= self.config.adaptive_loss_trigger:
                self._enable_filters()
    
    def _enable_filters(self):
        """Enable volume and divergence filters"""
        if not self.state.volume_confirmation_active or not self.state.divergence_confirmation_active:
            self.state.volume_confirmation_active = True
            self.state.divergence_confirmation_active = True
            
            # Update symbol parameters
            self.symbol_params.volume_confirmation_enabled = True
            self.symbol_params.divergence_confirmation_enabled = True
            
            self.logger.info("=" * 60, self.symbol)
            self.logger.info("*** ADAPTIVE FILTERS ENABLED ***", self.symbol)
            self.logger.info(
                f"Triggered by {self.state.consecutive_losses} consecutive losses",
                self.symbol
            )
            self.logger.info("Volume confirmation: ENABLED", self.symbol)
            self.logger.info("Divergence confirmation: ENABLED", self.symbol)
            self.logger.info("Filters will help improve trade quality", self.symbol)
            self.logger.info("=" * 60, self.symbol)
    
    def _disable_filters(self):
        """Disable volume and divergence filters

        NOTE: With dual strategy system (false + true breakout), volume confirmation
        should NOT be disabled as it's critical for strategy selection.
        Only divergence can be safely disabled.
        """
        # Check if both strategies are enabled (dual strategy mode)
        dual_strategy_mode = (self.symbol_params.enable_false_breakout_strategy and
                             self.symbol_params.enable_true_breakout_strategy)

        if dual_strategy_mode:
            # In dual strategy mode, NEVER disable volume confirmation
            # Only disable divergence confirmation
            if self.state.divergence_confirmation_active:
                self.state.divergence_confirmation_active = False
                self.symbol_params.divergence_confirmation_enabled = False

                self.logger.info("=" * 60, self.symbol)
                self.logger.info("*** ADAPTIVE FILTER: DIVERGENCE DISABLED ***", self.symbol)
                self.logger.info(
                    f"Triggered by {self.state.consecutive_wins} consecutive wins",
                    self.symbol
                )
                self.logger.info("Volume confirmation: ENABLED (required for dual strategy)", self.symbol)
                self.logger.info("Divergence confirmation: DISABLED", self.symbol)
                self.logger.info("=" * 60, self.symbol)
        else:
            # Single strategy mode - can disable both filters
            if self.state.volume_confirmation_active or self.state.divergence_confirmation_active:
                self.state.volume_confirmation_active = False
                self.state.divergence_confirmation_active = False

                # Update symbol parameters
                self.symbol_params.volume_confirmation_enabled = False
                self.symbol_params.divergence_confirmation_enabled = False

                self.logger.info("=" * 60, self.symbol)
                self.logger.info("*** ADAPTIVE FILTERS DISABLED ***", self.symbol)
                self.logger.info(
                    f"Triggered by {self.state.consecutive_wins} consecutive wins",
                    self.symbol
                )
                self.logger.info("Volume confirmation: DISABLED", self.symbol)
                self.logger.info("Divergence confirmation: DISABLED", self.symbol)
                self.logger.info("Strategy is performing well, filters not needed", self.symbol)
                self.logger.info("=" * 60, self.symbol)
    
    def get_filter_status(self) -> dict:
        """
        Get current filter status.

        Returns:
            Dictionary with filter status
        """
        return {
            'volume_active': self.state.volume_confirmation_active,
            'divergence_active': self.state.divergence_confirmation_active,
            'consecutive_wins': self.state.consecutive_wins,
            'consecutive_losses': self.state.consecutive_losses
        }
    
    def reset(self):
        """Reset filter state"""
        self.state = AdaptiveFilterState()
        self.logger.info("Adaptive filter reset", self.symbol)

