"""
Trade Comment Parser Utility

Provides utilities for parsing and generating trade comment strings.
Comment format: "{strategy}|{range_id}|{confirmations}" for TB/FB or "{strategy}|{confirmations}" for HFT
Example: "TB|15M_1M|BV" or "FB|4H_5M|RT" or "HFT|MV"

Note: Direction is not included in comments as it's already visible in MT5 position type.

This eliminates duplication in comment parsing logic across the codebase.
"""
from typing import Optional, Tuple
from dataclasses import dataclass
from src.constants import (
    STRATEGY_TYPE_FALSE_BREAKOUT,
    STRATEGY_TYPE_TRUE_BREAKOUT,
    STRATEGY_TYPE_HFT_MOMENTUM
)


@dataclass
class ParsedComment:
    """Parsed trade comment information."""
    strategy_type: str  # "TB", "FB", or "HFT"
    direction: str  # "buy" or "sell" (lowercase) - deprecated, kept for backward compatibility
    confirmations: str  # "BV", "RT", "CV", "MV", etc.
    range_id: str  # "4H_5M", "15M_1M" (with underscores), or empty string for HFT

    @property
    def is_true_breakout(self) -> bool:
        """Check if this is a true breakout strategy."""
        return self.strategy_type == STRATEGY_TYPE_TRUE_BREAKOUT

    @property
    def is_false_breakout(self) -> bool:
        """Check if this is a false breakout strategy."""
        return self.strategy_type == STRATEGY_TYPE_FALSE_BREAKOUT

    @property
    def is_hft_momentum(self) -> bool:
        """Check if this is an HFT momentum strategy."""
        return self.strategy_type == STRATEGY_TYPE_HFT_MOMENTUM
    
    @property
    def has_volume_confirmation(self) -> bool:
        """Check if volume confirmation is present."""
        return "V" in self.confirmations
    
    @property
    def has_divergence_confirmation(self) -> bool:
        """Check if divergence confirmation is present."""
        return "D" in self.confirmations
    
    @property
    def has_range_id(self) -> bool:
        """Check if range ID is present."""
        return bool(self.range_id)
    
    @property
    def normalized_range_id(self) -> str:
        """
        Get normalized range ID with underscores.
        Converts "4H5M" -> "4H_5M", "15M1M" -> "15M_1M"
        If already normalized (contains underscore), returns as-is.
        """
        if not self.range_id:
            return ""

        # If already contains underscore, it's already normalized
        if '_' in self.range_id:
            return self.range_id

        # Try to insert underscore before the last 'M'
        # "4H5M" -> "4H_5M", "15M1M" -> "15M_1M"
        if 'M' in self.range_id:
            # Find the last 'M' and insert underscore before the preceding character
            parts = self.range_id.split('M')
            if len(parts) >= 2:
                # Reconstruct with underscore
                # "4H5M" splits to ["4H5", ""] -> "4H_5M"
                # "15M1M" splits to ["15", "1", ""] -> "15M_1M"
                if len(parts) == 2:
                    # Simple case: "4H5M"
                    return f"{parts[0][:-1]}_{parts[0][-1]}M"
                else:
                    # Complex case: "15M1M"
                    return f"{parts[0]}M_{parts[1]}M"

        return self.range_id


class CommentParser:
    """
    Utility for parsing and generating trade comment strings.

    Comment format: "{strategy}|{range_id}|{confirmations}" for TB/FB or "{strategy}|{confirmations}" for HFT
    - strategy: "TB" (True Breakout), "FB" (False Breakout), or "HFT" (HFT Momentum)
    - range_id: Range identifier with underscores (e.g., "4H_5M", "15M_1M"), omitted for HFT
    - confirmations: "BV" (breakout volume), "RT" (retest), "CV" (continuation volume), "MV" (momentum+volume), etc.

    Examples:
    - "TB|15M_1M|BV" - True Breakout, 15M/1M range, breakout volume confirmation
    - "FB|4H_5M|RT" - False Breakout, 4H/5M range, retest confirmation
    - "HFT|MV" - HFT Momentum with momentum+volume (no range_id)

    Note: Direction is not included as it's already visible in MT5 position type.
    """

    @staticmethod
    def parse(comment: str) -> Optional[ParsedComment]:
        """
        Parse a trade comment string.

        New Format (without direction):
        - For TB/FB: "TB|15M_1M|BV" (3 parts: strategy|range_id|confirmations)
        - For HFT: "HFT|MV" (2 parts: strategy|confirmations, no range_id)

        Legacy Format (with direction - for backward compatibility):
        - For TB/FB: "TB|15M_1M|sell|N" (4 parts)
        - For HFT: "HFT|buy|MV" (3 parts)

        Args:
            comment: Comment string to parse

        Returns:
            ParsedComment object if parsing successful, None otherwise
        """
        if not comment or '|' not in comment:
            return None

        parts = comment.split('|')
        if len(parts) < 2:
            return None

        strategy_type = parts[0]

        # Validate strategy type first
        if strategy_type not in [STRATEGY_TYPE_TRUE_BREAKOUT, STRATEGY_TYPE_FALSE_BREAKOUT, STRATEGY_TYPE_HFT_MOMENTUM]:
            return None

        # New format (without direction)
        if strategy_type == STRATEGY_TYPE_HFT_MOMENTUM:
            # HFT new format: HFT|MV (2 parts)
            # HFT legacy format: HFT|buy|MV (3 parts)
            if len(parts) == 2:
                # New format
                confirmations = parts[1]
                range_id = ""
                direction = ""  # Not used in new format
            elif len(parts) == 3:
                # Legacy format with direction
                direction = parts[1].lower()
                confirmations = parts[2]
                range_id = ""
            else:
                return None
        else:
            # TB/FB new format: TB|15M_1M|BV (3 parts)
            # TB/FB legacy format: TB|15M_1M|sell|N (4 parts)
            if len(parts) == 3:
                # New format
                range_id = parts[1]
                confirmations = parts[2]
                direction = ""  # Not used in new format
            elif len(parts) == 4:
                # Legacy format with direction
                range_id = parts[1]
                direction = parts[2].lower()
                confirmations = parts[3]
            else:
                return None

        return ParsedComment(
            strategy_type=strategy_type,
            direction=direction,
            confirmations=confirmations,
            range_id=range_id
        )
    
    @staticmethod
    def extract_strategy_type(comment: str) -> str:
        """
        Extract strategy type from comment.
        
        Args:
            comment: Comment string
            
        Returns:
            Strategy type ("TB" or "FB"), or empty string if not found
        """
        parsed = CommentParser.parse(comment)
        return parsed.strategy_type if parsed else ""
    
    @staticmethod
    def extract_range_id(comment: str) -> str:
        """
        Extract range ID from comment.
        
        Args:
            comment: Comment string
            
        Returns:
            Range ID (e.g., "4H5M"), or empty string if not found
        """
        parsed = CommentParser.parse(comment)
        return parsed.range_id if parsed else ""
    
    @staticmethod
    def extract_normalized_range_id(comment: str) -> str:
        """
        Extract normalized range ID with underscores from comment.
        
        Args:
            comment: Comment string
            
        Returns:
            Normalized range ID (e.g., "4H_5M"), or empty string if not found
        """
        parsed = CommentParser.parse(comment)
        return parsed.normalized_range_id if parsed else ""
    
    @staticmethod
    def extract_strategy_and_range(comment: str) -> Tuple[str, str]:
        """
        Extract both strategy type and range ID from comment.
        
        Args:
            comment: Comment string
            
        Returns:
            Tuple of (strategy_type, range_id), or ("", "") if parsing fails
        """
        parsed = CommentParser.parse(comment)
        if parsed:
            return (parsed.strategy_type, parsed.range_id)
        return ("", "")
    
    @staticmethod
    def normalize_range_id(range_id: str) -> str:
        """
        Normalize a range ID by removing underscores.
        Converts "4H_5M" -> "4H5M", "15M_1M" -> "15M1M"
        
        Args:
            range_id: Range ID with or without underscores
            
        Returns:
            Normalized range ID without underscores
        """
        return range_id.replace("_", "") if range_id else ""
    
    @staticmethod
    def denormalize_range_id(range_id: str) -> str:
        """
        Denormalize a range ID by adding underscores.
        Converts "4H5M" -> "4H_5M", "15M1M" -> "15M_1M"
        
        Args:
            range_id: Range ID without underscores
            
        Returns:
            Denormalized range ID with underscores
        """
        if not range_id or '_' in range_id:
            return range_id
        
        # Try to insert underscore before the last 'M'
        if 'M' in range_id:
            parts = range_id.split('M')
            if len(parts) >= 2:
                if len(parts) == 2:
                    # Simple case: "4H5M" -> "4H_5M"
                    return f"{parts[0][:-1]}_{parts[0][-1]}M"
                else:
                    # Complex case: "15M1M" -> "15M_1M"
                    return f"{parts[0]}M_{parts[1]}M"
        
        return range_id

