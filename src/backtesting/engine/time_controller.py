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


class TimeGranularity(Enum):
    """Time granularity for backtesting."""
    TICK = "tick"      # Advance tick-by-tick (highest fidelity)
    MINUTE = "minute"  # Advance minute-by-minute (candle-based)


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
                 granularity: TimeGranularity = TimeGranularity.MINUTE,
                 include_position_monitor: bool = True, broker=None):
        """
        Initialize time controller.

        Args:
            symbols: List of symbols to synchronize
            mode: Time advancement mode (REALTIME, FAST, MAX_SPEED)
            granularity: Time granularity (TICK or MINUTE)
            include_position_monitor: Whether to include position monitor in barrier (default: True)
            broker: SimulatedBroker instance for global time advancement (backtest only)
        """
        self.logger = get_logger()
        self.symbols = symbols
        self.mode = mode
        self.granularity = granularity
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
        # Validate tick timeline if in tick mode
        if self.granularity == TimeGranularity.TICK:
            if self.broker is None:
                self.logger.error("TICK mode requires broker to be set!")
                return
            if not hasattr(self.broker, 'global_tick_timeline'):
                self.logger.error("TICK mode enabled but broker has no global_tick_timeline!")
                self.logger.error("Make sure tick data is loaded before starting TimeController")
                return
            if len(self.broker.global_tick_timeline) == 0:
                self.logger.error("TICK mode enabled but global_tick_timeline is EMPTY!")
                self.logger.error("Check that tick data was loaded in STEP 2 and STEP 4.5")
                return

            self.logger.info(f"TICK mode validated: {len(self.broker.global_tick_timeline):,} ticks in timeline")

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

        # Determine if this thread should advance time (last to arrive)
        should_advance_time = False
        arrival_generation = 0

        with self.barrier_condition:
            # Mark this participant as ready
            self.symbols_ready.add(participant)

            # Remember the current generation when we arrived
            arrival_generation = self.barrier_generation

            # Debug logging for first few steps
            if self.total_steps < 3:
                self.logger.info(f"[BARRIER] {participant} arrived at barrier (gen={arrival_generation}, ready={len(self.symbols_ready)}/{self.total_participants})")

            # Check if all participants are ready
            if len(self.symbols_ready) == self.total_participants:
                # Debug logging for first few steps
                if self.total_steps < 3:
                    self.logger.info(f"[BARRIER] All {self.total_participants} participants ready! Advancing time...")

                # All participants ready - advance time
                self.total_steps += 1

                # CRITICAL: Increment generation FIRST, before clearing ready set
                # This prevents race condition where threads wake up and re-add themselves
                # to the ready set before seeing the new generation
                self.barrier_generation += 1

                # Debug logging
                if self.total_steps < 3:
                    self.logger.info(f"[BARRIER] Generation incremented to {self.barrier_generation}")

                # Clear ready set for next step
                self.symbols_ready.clear()

                # Mark that this thread should advance time (after releasing lock)
                should_advance_time = True

        # CRITICAL: Advance time OUTSIDE the barrier_condition lock to avoid deadlock
        # The time advancement acquires time_lock, which might be held by other threads
        # If we hold barrier_condition while trying to acquire time_lock, we can deadlock
        if should_advance_time:
            # Apply time delay based on mode
            self._apply_time_delay()

            # Advance global time (if broker is available)
            # Call appropriate method based on granularity
            if self.broker is not None:
                if self.total_steps < 3:
                    self.logger.info(f"[BARRIER] About to advance time (granularity={self.granularity.value})")

                if self.granularity == TimeGranularity.TICK:
                    # Tick-by-tick mode: advance to next tick in global timeline
                    # Check if tick timeline is loaded
                    if not hasattr(self.broker, 'global_tick_timeline') or len(self.broker.global_tick_timeline) == 0:
                        self.logger.error("TICK mode enabled but no tick timeline loaded!")
                        self.logger.error("Check that tick data was loaded in STEP 2")
                        self.running = False
                    else:
                        if self.total_steps < 3:
                            self.logger.info(f"[BARRIER] Calling advance_global_time_tick_by_tick()")
                        if not self.broker.advance_global_time_tick_by_tick():
                            # All ticks processed, stop backtest
                            self.running = False
                else:  # MINUTE
                    # Minute-by-minute mode: advance by 1 minute
                    if not self.broker.advance_global_time():
                        # All symbols exhausted, stop backtest
                        self.running = False

            # Re-acquire barrier_condition to notify waiting threads
            with self.barrier_condition:
                if self.total_steps < 3:
                    self.logger.info(f"[BARRIER] Notifying all threads (generation={self.barrier_generation})")
                # Notify all waiting threads
                self.barrier_condition.notify_all()

        # Wait for barrier to be released (generation to change)
        # All threads (including the last one to arrive) wait here
        with self.barrier_condition:
            wait_count = 0
            if self.total_steps < 3:
                self.logger.info(f"[BARRIER] {participant} entering wait loop (arrival={arrival_generation}, current={self.barrier_generation}, should_wait={self.barrier_generation == arrival_generation})")

            while (self.running and
                   self.barrier_generation == arrival_generation and
                   not self.paused):
                if self.total_steps < 3 and wait_count == 0:
                    self.logger.info(f"[BARRIER] {participant} waiting for generation change (arrival={arrival_generation}, current={self.barrier_generation})")
                self.barrier_condition.wait(timeout=1.0)
                wait_count += 1
                if self.total_steps < 3 and wait_count == 1:
                    self.logger.info(f"[BARRIER] {participant} woke up (arrival={arrival_generation}, current={self.barrier_generation}, running={self.running})")

            if self.total_steps < 3:
                self.logger.info(f"[BARRIER] {participant} exiting wait loop (arrival={arrival_generation}, current={self.barrier_generation})")

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

