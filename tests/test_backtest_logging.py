"""Test backtest logging to verify no duplicates."""
from src.utils.logging import init_logger, get_logger, set_backtest_mode
from datetime import datetime, timezone
import tempfile
import shutil
from pathlib import Path

# Create a temporary directory for logs
temp_dir = Path(tempfile.mkdtemp())
print(f"Using temporary log directory: {temp_dir}")

try:
    # Simulate backtest.py initialization
    print("\n=== Step 1: Initialize logger (like backtest.py line 182) ===")
    logger = init_logger(log_to_file=True, log_to_console=False, log_level="INFO")
    
    print(f"Handlers after init_logger: {len(logger.logger.handlers)}")
    for i, h in enumerate(logger.logger.handlers):
        print(f"  Handler {i}: {type(h).__name__}")
    
    # Simulate backtest.py set_backtest_mode (line 190)
    print("\n=== Step 2: Set backtest mode (like backtest.py line 190) ===")
    START_DATE = datetime(2025, 11, 10, tzinfo=timezone.utc)
    set_backtest_mode(
        time_getter=lambda: START_DATE,
        start_time=START_DATE
    )
    
    print(f"Handlers after first set_backtest_mode: {len(logger.logger.handlers)}")
    for i, h in enumerate(logger.logger.handlers):
        print(f"  Handler {i}: {type(h).__name__}")
    
    # Log some messages
    logger.info("Test message 1")
    logger.info("Test message 2")
    logger.info("Test message 3")
    
    # Simulate BacktestController.run() set_backtest_mode (line 135)
    print("\n=== Step 3: Set backtest mode again (like backtest_controller.py line 135) ===")
    set_backtest_mode(
        lambda: START_DATE,
        START_DATE
    )
    
    print(f"Handlers after second set_backtest_mode: {len(logger.logger.handlers)}")
    for i, h in enumerate(logger.logger.handlers):
        print(f"  Handler {i}: {type(h).__name__}")
    
    # Log more messages
    logger.info("Test message 4")
    logger.info("Test message 5")
    logger.info("Test message 6")
    
    # Check the log file for duplicates
    print("\n=== Step 4: Check log file for duplicates ===")
    from src.utils.logging import get_log_directory
    log_dir = get_log_directory()
    log_file = log_dir / "main.log"
    
    if log_file.exists():
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        print(f"Log file: {log_file}")
        print(f"Total lines: {len(lines)}")
        print("\nLog contents:")
        for line in lines:
            print(f"  {line.rstrip()}")
        
        # Check for duplicates
        from collections import Counter
        line_counts = Counter(lines)
        duplicates = [(line.strip(), count) for line, count in line_counts.items() if count > 1]
        
        if duplicates:
            print("\n❌ DUPLICATES FOUND:")
            for line, count in duplicates:
                print(f"  {count}x: {line}")
        else:
            print("\n✅ NO DUPLICATES FOUND!")
    else:
        print(f"❌ Log file not found: {log_file}")

finally:
    # Clean up
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
        print(f"\nCleaned up temporary directory: {temp_dir}")

