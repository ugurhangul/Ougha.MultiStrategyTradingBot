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
                 include_position_monitor: bool = True, broker=None,
                 coordinator_id: str = "position_monitor"):
        """
        Initialize time controller.

        Args:
            symbols: List of symbols to synchronize
            mode: Time advancement mode (REALTIME, FAST, MAX_SPEED)
            granularity: Time granularity (TICK or MINUTE)
            include_position_monitor: Whether to include position monitor in barrier (default: True)
            broker: SimulatedBroker instance for global time advancement (backtest only)
            coordinator_id: ID of the coordinator thread that advances time (default: "position_monitor")
        """
        self.logger = get_logger()
        self.symbols = symbols
        self.mode = mode
        self.granularity = granularity
        self.include_position_monitor = include_position_monitor
        self.broker = broker  # For global time advancement
        self.coordinator_id = coordinator_id  # Only this thread advances time

        # Time synchronization
        self.current_time: Optional[datetime] = None
        # Use RLock to allow reentrant acquisition
        self.time_lock = threading.RLock()

        # Barrier synchronization - Coordinator-based approach
        # Simple arrival counter instead of set (more efficient and clearer)
        self.barrier_lock = threading.Lock()
        self.barrier_condition = threading.Condition(self.barrier_lock)
        self.arrivals = 0  # Counter for barrier arrivals

        # Total participants in barrier = symbols + position_monitor (if enabled)
        self.total_participants = len(symbols) + (1 if include_position_monitor else 0)

        # Auto-select coordinator when position monitor is not participating
        # If coordinator is left as default ("position_monitor") but not included, pick first symbol
        if not include_position_monitor:
            if coordinator_id == "position_monitor" or coordinator_id not in symbols:
                # Fall back to first symbol as coordinator
                self.coordinator_id = symbols[0] if symbols else coordinator_id

        # Barrier generation: incremented each cycle to track progress
        # Threads wait for generation to change before proceeding
        self.barrier_generation = 0
        # Flag indicating that a completed barrier cycle needs coordinator advancement
        self.advance_needed = False

        # Control flags
        self.running = False
        self.paused = False

        # Statistics
        self.total_steps = 0
        self.start_time: Optional[datetime] = None

        participants_str = f"{len(symbols)} symbols"
        if include_position_monitor:
            participants_str += " + position monitor"
        coord_info = f" | coordinator: {self.coordinator_id}"
        self.logger.info(f"TimeController initialized for {participants_str} in {mode.value} mode{coord_info}")

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
        Wait for all participants to be ready for next time step (coordinator-based barrier).

        COORDINATOR-BASED APPROACH:
        - ONE designated thread (coordinator_id, usually "position_monitor") advances time
        - All other threads (workers) just increment counter and wait
        - Coordinator checks if all arrived, advances time, increments generation, notifies all
        - ALL threads (including coordinator) wait for generation change before proceeding

        This eliminates the race condition where multiple threads thought they were "last to arrive".

        Args:
            participant: Participant identifier (symbol name or "position_monitor")

        Returns:
            True if should continue, False if should stop
        """
        if not self.running:
            return False

        is_coordinator = (participant == self.coordinator_id)
        all_arrived = False
        arrival_generation = 0

        # Phase 1: Register arrival
        with self.barrier_condition:
            self.arrivals += 1
            arrival_generation = self.barrier_generation

            # Debug logging
            if self.total_steps < 3:
                role = "COORDINATOR" if is_coordinator else "worker"
                self.logger.info(
                    f"[BARRIER] {participant} ({role}) arrived "
                    f"(gen={arrival_generation}, arrivals={self.arrivals}/{self.total_participants})"
                )

            # Check if all participants have arrived
            if self.arrivals == self.total_participants:
                all_arrived = True
                # Reset counter for next cycle
                self.arrivals = 0
                self.total_steps += 1
                # Mark that the coordinator must advance time for this generation
                self.advance_needed = True

                if self.total_steps < 3:
                    self.logger.info(f"[BARRIER] All arrived! Steps={self.total_steps}")

                # Wake everyone immediately so the coordinator can proceed without timeout
                # Workers will re-wait until generation increments
                self.barrier_condition.notify_all()

        # Phase 2: ALL threads wait for generation change FIRST
        # Coordinator exits immediately if a completed cycle needs advancement
        with self.barrier_condition:
            if self.total_steps < 3:
                self.logger.info(
                    f"[BARRIER] {participant} waiting for gen change "
                    f"(arrival={arrival_generation}, current={self.barrier_generation})"
                )

            def _should_continue_waiting() -> bool:
                if not self.running or self.paused:
                    return False
                # Workers wait until generation changes
                if not is_coordinator:
                    return self.barrier_generation == arrival_generation
                # Coordinator waits unless it's time to advance for this generation
                if self.advance_needed and self.barrier_generation == arrival_generation:
                    return False
                return self.barrier_generation == arrival_generation

            while _should_continue_waiting():
                # No timeout needed in MAX_SPEED; rely on notify_all
                # Use a long timeout as a safety for non-max modes
                timeout = None if self.mode == TimeMode.MAX_SPEED else 1.0
                self.barrier_condition.wait(timeout=timeout)

            if self.total_steps < 3:
                self.logger.info(
                    f"[BARRIER] {participant} released from wait "
                    f"(gen={self.barrier_generation}, running={self.running})"
                )

        # Phase 3: Coordinator advances time (OUTSIDE lock to avoid deadlock)
        should_advance = False
        if is_coordinator:
            with self.barrier_condition:
                # Only advance if a cycle completed for the generation we arrived at
                if self.advance_needed and self.barrier_generation == arrival_generation:
                    self.advance_needed = False
                    should_advance = True

            if should_advance:
                if self.total_steps < 3:
                    self.logger.info(f"[BARRIER] Coordinator advancing time...")

                # Apply time delay
                self._apply_time_delay()

                # Advance global time
                if self.broker is not None:
                    if self.granularity == TimeGranularity.TICK:
                        if not hasattr(self.broker, 'global_tick_timeline') or len(self.broker.global_tick_timeline) == 0:
                            self.logger.error("TICK mode enabled but no tick timeline loaded!")
                            self.running = False
                        else:
                            if not self.broker.advance_global_time_tick_by_tick():
                                # All ticks processed
                                self.running = False
                    else:  # MINUTE
                        if not self.broker.advance_global_time():
                            # All symbols exhausted
                            self.running = False

                # Increment generation and notify all waiting threads
                with self.barrier_condition:
                    self.barrier_generation += 1
                    if self.total_steps < 3:
                        self.logger.info(f"[BARRIER] Generation incremented to {self.barrier_generation}, notifying all")
                    self.barrier_condition.notify_all()

        # Phase 4: ALL threads wait again for generation change (if coordinator just advanced)
        if is_coordinator and should_advance:
            # Coordinator already incremented generation, so we're done
            pass
        else:
            # Non-coordinators or coordinator that didn't advance: wait for generation change
            with self.barrier_condition:
                while self.running and self.barrier_generation == arrival_generation and not self.paused:
                    # Use short timeout for MAX_SPEED mode, longer for visual modes
                    timeout = 0.01 if self.mode == TimeMode.MAX_SPEED else 1.0
                    self.barrier_condition.wait(timeout=timeout)

        return self.running

    def remove_participant(self, participant: str):
        """
        Remove a participant from the barrier when it exits (e.g., runs out of data).

        This allows the remaining threads to continue without waiting for exited threads.

        Args:
            participant: The participant identifier (symbol name or "position_monitor")
        """
        # In the coordinator-based barrier, we track arrivals with a counter.
        # If a participant leaves in the middle of a barrier cycle, it's possible that
        # the remaining arrivals already equal the new total_participants. In that case
        # we must perform the coordinator's advancement work (time advance + generation increment)
        # to release all waiting threads. We emulate the coordinator here safely.

        should_advance = False
        with self.barrier_condition:
            # Decrease total participants for subsequent cycles
            self.total_participants -= 1

            # If after removal, the number of arrivals equals the new total participants,
            # the barrier for this generation is effectively complete.
            if self.running and self.arrivals == self.total_participants and self.total_participants >= 0:
                # Mark that we should advance time outside the lock
                should_advance = True
                # Prepare next cycle
                self.arrivals = 0
                self.total_steps += 1

        if should_advance:
            # Phase 2 work (coordinator) performed here by the remover thread
            if self.total_steps < 3:
                self.logger.info(f"[BARRIER] Participant '{participant}' removal completed a cycle - advancing time as coordinator surrogate...")

            # Apply time delay per mode
            self._apply_time_delay()

            # Advance global time
            if self.broker is not None:
                if self.granularity == TimeGranularity.TICK:
                    if not hasattr(self.broker, 'global_tick_timeline') or len(self.broker.global_tick_timeline) == 0:
                        self.logger.error("TICK mode enabled but no tick timeline loaded!")
                        self.running = False
                    else:
                        if not self.broker.advance_global_time_tick_by_tick():
                            # All ticks processed
                            self.running = False
                else:  # MINUTE
                    if not self.broker.advance_global_time():
                        # All symbols exhausted
                        self.running = False

            # Increment generation and notify waiting threads
            with self.barrier_condition:
                # Ensure no double-advance will be attempted by coordinator
                self.advance_needed = False
                self.barrier_generation += 1
                if self.total_steps < 3:
                    self.logger.info(f"[BARRIER] Generation incremented to {self.barrier_generation} after participant removal - notifying all")
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
        import threading
        tid = threading.current_thread().name
        with self.time_lock:
            self.current_time = current_time

    def get_current_time(self) -> Optional[datetime]:
        """Get current simulated time."""
        import threading
        tid = threading.current_thread().name
        with self.time_lock:
            result = self.current_time
        return result

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
            self.barrier_generation = 0
            self.total_steps = 0
            self.current_time = None
            self.start_time = None
            self.running = False
            self.paused = False

