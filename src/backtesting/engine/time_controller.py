"""
Time Controller for Backtesting.

Manages synchronized time advancement across all symbol threads.
Ensures all symbols advance chronologically together, simulating concurrent execution.
"""
from typing import Dict, List, Optional, Set
from datetime import datetime, timezone
import threading
import time
from enum import Enum

from src.utils.logger import get_logger


class TimeMode(Enum):
    """Time advancement mode."""
    REALTIME = "realtime"  # 1x speed (1 second = 1 second)
    FAST = "fast"  # 10x speed
    MAX_SPEED = "max"  # As fast as possible


class TimeController:
    """
    Controls synchronized time advancement across multiple symbol threads.

    In live trading, each symbol thread runs independently and processes ticks
    as they arrive. In backtesting, we need to synchronize time so that all
    symbols advance together chronologically.

    This controller acts as a "time barrier" - all symbol threads wait at each
    time step until all symbols have processed the current bar, then advance
    together to the next time step.
    """

    def __init__(self, symbols: List[str], mode: TimeMode = TimeMode.MAX_SPEED,
                 include_position_monitor: bool = True, broker=None):
        """
        Initialize time controller.

        Args:
            symbols: List of symbols to synchronize
            mode: Time advancement mode
            include_position_monitor: Whether to include position monitor in barrier (default: True)
            broker: SimulatedBroker instance for global time advancement (backtest only)
        """
        self.logger = get_logger()
        self.symbols = symbols
        self.mode = mode
        self.include_position_monitor = include_position_monitor
        self.broker = broker  # For global time advancement

        # Time synchronization
        self.current_time: Optional[datetime] = None
        self.time_lock = threading.Lock()

        # Barrier synchronization
        # Each symbol thread + position monitor signals when done processing current bar
        self.symbols_ready: Set[str] = set()
        self.barrier_lock = threading.Lock()
        self.barrier_condition = threading.Condition(self.barrier_lock)

        # Total participants in barrier = symbols + position_monitor (if enabled)
        self.total_participants = len(symbols) + (1 if include_position_monitor else 0)

        # Two-phase barrier: track current generation to prevent race conditions
        # When all threads arrive, we increment the generation number
        # Threads wait until generation changes before proceeding
        self.barrier_generation = 0

        # Control flags
        self.running = False
        self.paused = False

        # Statistics
        self.total_steps = 0
        self.start_time: Optional[datetime] = None

        participants_str = f"{len(symbols)} symbols"
        if include_position_monitor:
            participants_str += " + position monitor"
        self.logger.info(f"TimeController initialized for {participants_str} in {mode.value} mode")

    def start(self):
        """Start time controller."""
        self.running = True
        self.paused = False
        self.start_time = datetime.now(timezone.utc)
        self.logger.info("TimeController started")

    def stop(self):
        """Stop time controller."""
        self.running = False
        with self.barrier_condition:
            self.barrier_condition.notify_all()
        self.logger.info("TimeController stopped")

    def pause(self):
        """Pause time advancement."""
        self.paused = True
        self.logger.info("TimeController paused")

    def resume(self):
        """Resume time advancement."""
        self.paused = False
        with self.barrier_condition:
            self.barrier_condition.notify_all()
        self.logger.info("TimeController resumed")

    def wait_for_next_step(self, participant: str) -> bool:
        """
        Wait for all participants (symbols + position monitor) to be ready for next time step.

        Called by each symbol thread and position monitor after processing current bar.

        Uses a two-phase barrier to prevent race conditions:
        1. Phase 1: Thread marks itself as ready and waits for all others
        2. Phase 2: When all ready, barrier generation increments and all threads are released
        3. Each thread waits until it sees the new generation before proceeding

        This ensures no thread can loop back and process the next tick until ALL threads
        have been released from the current barrier.

        Args:
            participant: Participant identifier (symbol name or "position_monitor")

        Returns:
            True if should continue, False if should stop
        """
        if not self.running:
            return False

        with self.barrier_condition:
            # Mark this participant as ready
            self.symbols_ready.add(participant)

            # Remember the current generation when we arrived
            arrival_generation = self.barrier_generation

            # Check if all participants are ready
            if len(self.symbols_ready) == self.total_participants:
                # All participants ready - advance time
                self.total_steps += 1

                # Clear ready set for next step
                self.symbols_ready.clear()

                # Apply time delay based on mode
                self._apply_time_delay()

                # Advance global time by one minute (if broker is available)
                if self.broker is not None:
                    if not self.broker.advance_global_time():
                        # All symbols exhausted, stop backtest
                        self.running = False

                # Increment generation to signal barrier release
                # This is the key fix: all threads (including this one) must see the new generation
                self.barrier_generation += 1

                # Notify all waiting threads
                self.barrier_condition.notify_all()

                # IMPORTANT: The last thread to arrive must also wait for the barrier to be released
                # This prevents it from racing ahead and processing the next tick before others wake up
                # We wait until we see the new generation (which we just incremented)
                # Since we just incremented it, we'll see it immediately and exit the loop
                # But this ensures consistent behavior for all threads

            # Wait for barrier to be released (generation to change)
            # All threads (including the last one to arrive) wait here
            while (self.running and
                   self.barrier_generation == arrival_generation and
                   not self.paused):
                self.barrier_condition.wait(timeout=1.0)

            return self.running

    def remove_participant(self, participant: str):
        """
        Remove a participant from the barrier when it exits (e.g., runs out of data).

        This allows the remaining threads to continue without waiting for exited threads.

        Args:
            participant: The participant identifier (symbol name or "position_monitor")
        """
        with self.barrier_condition:
            self.total_participants -= 1
            # Remove from ready set if present
            self.symbols_ready.discard(participant)

            # If we now have all remaining participants ready, notify them
            if len(self.symbols_ready) == self.total_participants:
                self.total_steps += 1
                self.symbols_ready.clear()
                self._apply_time_delay()
                # Increment generation to release waiting threads
                self.barrier_generation += 1
                self.barrier_condition.notify_all()

            self.logger.info(f"Removed participant '{participant}' from barrier. Remaining: {self.total_participants}")

    def _apply_time_delay(self):
        """Apply time delay based on mode."""
        if self.mode == TimeMode.REALTIME:
            time.sleep(1.0)  # 1 second per bar
        elif self.mode == TimeMode.FAST:
            time.sleep(0.1)  # 100ms per bar (10x speed)
        # MAX_SPEED: no delay

    def set_current_time(self, current_time: datetime):
        """
        Set current simulated time.

        Args:
            current_time: Current time
        """
        with self.time_lock:
            self.current_time = current_time

    def get_current_time(self) -> Optional[datetime]:
        """Get current simulated time."""
        with self.time_lock:
            return self.current_time

    def get_statistics(self) -> Dict:
        """Get time controller statistics."""
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds() if self.start_time else 0

        return {
            'total_steps': self.total_steps,
            'elapsed_seconds': elapsed,
            'steps_per_second': self.total_steps / elapsed if elapsed > 0 else 0,
            'current_time': self.current_time,
            'mode': self.mode.value,
            'running': self.running,
            'paused': self.paused,
        }

    def reset(self):
        """Reset time controller for new backtest."""
        with self.barrier_condition:
            self.symbols_ready.clear()
            self.barrier_generation = 0
            self.total_steps = 0
            self.current_time = None
            self.start_time = None
            self.running = False
            self.paused = False

