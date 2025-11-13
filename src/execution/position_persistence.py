"""
Position persistence mechanism to prevent duplicate positions on bot restart.

This module provides:
1. JSON-based position storage with atomic writes
2. Position reconciliation between saved state and MT5
3. Duplicate position prevention
4. Thread-safe file access
"""
import json
import os
import threading
from typing import Dict, List, Optional, Set
from datetime import datetime
from pathlib import Path

from src.models.data_models import PositionInfo, PositionType
from src.utils.logger import get_logger


class PositionPersistence:
    """Manages position persistence to prevent duplicates on restart"""
    
    def __init__(self, data_dir: str = "data"):
        """
        Initialize position persistence.
        
        Args:
            data_dir: Directory to store positions.json file
        """
        self.logger = get_logger()
        
        # Create data directory if it doesn't exist
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Position file path
        self.positions_file = self.data_dir / "positions.json"
        
        # Thread lock for file access
        self.lock = threading.Lock()
        
        # In-memory cache of persisted positions
        self.positions_cache: Dict[int, Dict] = {}
        
        # Load existing positions on initialization
        self._load_positions()
    
    def _load_positions(self):
        """Load positions from JSON file"""
        with self.lock:
            try:
                if self.positions_file.exists():
                    with open(self.positions_file, 'r') as f:
                        data = json.load(f)
                        # Convert ticket keys from string to int
                        self.positions_cache = {int(k): v for k, v in data.items()}
                    
                    self.logger.info(f"Loaded {len(self.positions_cache)} positions from persistence file")
                else:
                    self.positions_cache = {}
                    self.logger.info("No existing positions file found, starting fresh")
                    
            except json.JSONDecodeError as e:
                self.logger.error(f"Corrupted positions file: {e}")
                self.logger.warning("Starting with empty position cache")
                self.positions_cache = {}
                # Backup corrupted file
                if self.positions_file.exists():
                    backup_path = self.positions_file.with_suffix('.json.corrupted')
                    self.positions_file.rename(backup_path)
                    self.logger.info(f"Corrupted file backed up to: {backup_path}")
                    
            except Exception as e:
                self.logger.error(f"Error loading positions: {e}")
                self.positions_cache = {}
    
    def _save_positions(self):
        """
        Save positions to JSON file with atomic write.

        NOTE: This method does NOT acquire the lock - it must be called
        from a method that already holds the lock.
        """
        try:
            # Write to temporary file first (atomic write)
            temp_file = self.positions_file.with_suffix('.json.tmp')

            # Convert ticket keys to strings for JSON
            data = {str(k): v for k, v in self.positions_cache.items()}

            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)

            # Atomic rename (replaces old file)
            temp_file.replace(self.positions_file)

            self.logger.debug(f"Saved {len(self.positions_cache)} positions to persistence file")

        except Exception as e:
            self.logger.error(f"Error saving positions: {e}")
    
    def _add_position_internal(self, position: PositionInfo):
        """
        Internal method to add position without acquiring lock.
        Should only be called when lock is already held.
        """
        position_data = {
            'ticket': position.ticket,
            'symbol': position.symbol,
            'position_type': position.position_type.value,
            'volume': position.volume,
            'open_price': position.open_price,
            'sl': position.sl,
            'tp': position.tp,
            'open_time': position.open_time.isoformat(),
            'magic_number': position.magic_number,
            'comment': position.comment
        }

        self.positions_cache[position.ticket] = position_data
        self._save_positions()

        self.logger.info(
            f"Position {position.ticket} added to persistence ({position.symbol} {position.position_type.value})"
        )

    def add_position(self, position: PositionInfo):
        """
        Add a position to persistence.

        Args:
            position: Position information
        """
        with self.lock:
            self._add_position_internal(position)
    
    def _remove_position_internal(self, ticket: int):
        """
        Internal method to remove position without acquiring lock.
        Should only be called when lock is already held.
        """
        if ticket in self.positions_cache:
            position_data = self.positions_cache.pop(ticket)
            self._save_positions()

            self.logger.info(
                f"Position {ticket} removed from persistence ({position_data.get('symbol')})"
            )
        else:
            self.logger.debug(f"Position {ticket} not found in persistence (already removed)")

    def remove_position(self, ticket: int):
        """
        Remove a position from persistence.

        Args:
            ticket: Position ticket number
        """
        with self.lock:
            self._remove_position_internal(ticket)
    
    def _update_position_internal(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None):
        """
        Internal method to update position without acquiring lock.
        Should only be called when lock is already held.
        """
        if ticket in self.positions_cache:
            if sl is not None:
                self.positions_cache[ticket]['sl'] = sl
            if tp is not None:
                self.positions_cache[ticket]['tp'] = tp

            self._save_positions()

            self.logger.debug(f"Position {ticket} updated in persistence")
        else:
            self.logger.warning(f"Position {ticket} not found in persistence for update")

    def update_position(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None):
        """
        Update position SL/TP in persistence.

        Args:
            ticket: Position ticket number
            sl: New stop loss (None to keep current)
            tp: New take profit (None to keep current)
        """
        with self.lock:
            self._update_position_internal(ticket, sl, tp)
    
    def has_position(self, ticket: int) -> bool:
        """
        Check if position exists in persistence.
        
        Args:
            ticket: Position ticket number
            
        Returns:
            True if position exists in persistence
        """
        with self.lock:
            return ticket in self.positions_cache
    
    def get_all_tickets(self) -> Set[int]:
        """
        Get all persisted position tickets.
        
        Returns:
            Set of ticket numbers
        """
        with self.lock:
            return set(self.positions_cache.keys())
    
    def get_position(self, ticket: int) -> Optional[Dict]:
        """
        Get position data from persistence.
        
        Args:
            ticket: Position ticket number
            
        Returns:
            Position data dictionary or None
        """
        with self.lock:
            return self.positions_cache.get(ticket)
    
    def reconcile_with_mt5(self, mt5_positions: List[PositionInfo]) -> Dict[str, List[int]]:
        """
        Reconcile persisted positions with actual MT5 positions.
        
        This handles:
        - Positions in MT5 but not in persistence: add to tracking
        - Positions in persistence but not in MT5: remove from tracking (closed externally)
        - Positions in both: verify consistency
        
        Args:
            mt5_positions: List of actual MT5 positions
            
        Returns:
            Dictionary with reconciliation results:
            - 'added': Tickets added to persistence (found in MT5)
            - 'removed': Tickets removed from persistence (not in MT5)
            - 'updated': Tickets updated (SL/TP changed in MT5)
        """
        with self.lock:
            mt5_tickets = {pos.ticket for pos in mt5_positions}
            persisted_tickets = set(self.positions_cache.keys())
            
            # Positions in MT5 but not persisted
            to_add = mt5_tickets - persisted_tickets
            
            # Positions persisted but not in MT5 (closed externally)
            to_remove = persisted_tickets - mt5_tickets

            results = {
                'added': list(to_add),
                'removed': list(to_remove),
                'updated': []
            }

            # Add missing positions
            for pos in mt5_positions:
                if pos.ticket in to_add:
                    self._add_position_internal(pos)
                    self.logger.info(
                        f"Reconciliation: Added position {pos.ticket} to persistence "
                        f"({pos.symbol} {pos.position_type.value})"
                    )

                # Check for updates in existing positions
                elif pos.ticket in persisted_tickets:
                    persisted = self.positions_cache[pos.ticket]

                    # Check if SL/TP changed
                    if persisted['sl'] != pos.sl or persisted['tp'] != pos.tp:
                        self._update_position_internal(pos.ticket, sl=pos.sl, tp=pos.tp)
                        results['updated'].append(pos.ticket)
                        self.logger.info(
                            f"Reconciliation: Updated position {pos.ticket} "
                            f"(SL: {persisted['sl']:.5f} -> {pos.sl:.5f}, "
                            f"TP: {persisted['tp']:.5f} -> {pos.tp:.5f})"
                        )

            # Remove positions that no longer exist in MT5
            for ticket in to_remove:
                persisted = self.positions_cache[ticket]
                self._remove_position_internal(ticket)
                self.logger.info(
                    f"Reconciliation: Removed position {ticket} from persistence "
                    f"(closed externally: {persisted.get('symbol')})"
                )
            
            # Log summary
            if to_add or to_remove or results['updated']:
                self.logger.info("=" * 60)
                self.logger.info("POSITION RECONCILIATION COMPLETE")
                self.logger.info(f"Added: {len(to_add)}, Removed: {len(to_remove)}, Updated: {len(results['updated'])}")
                self.logger.info("=" * 60)
            else:
                self.logger.info("Position reconciliation: All positions in sync")
            
            return results
    
    def clear_all(self):
        """Clear all persisted positions (use with caution)"""
        with self.lock:
            self.positions_cache = {}
            self._save_positions()
            self.logger.warning("All persisted positions cleared")

