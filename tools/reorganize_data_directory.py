"""
Reorganize Data Directory

This script reorganizes the cluttered data directory into a clean structure:

OLD STRUCTURE:
data/
├── EURUSD/           # 70+ symbol directories with candle files
├── GBPUSD/
├── ...
├── ticks/            # Tick cache files
├── tick_archives/    # Archived tick data
└── backtest/         # Backtest results

NEW STRUCTURE:
data/
├── cache/
│   ├── candles/      # All candle cache files (OHLCV data)
│   │   ├── EURUSD/
│   │   ├── GBPUSD/
│   │   └── ...
│   └── ticks/        # All tick cache files
│       ├── EURUSD_20250101_20251120_INFO.parquet
│       └── ...
├── archives/         # External tick archives (zip files)
│   ├── Exness_EURUSD_2025.zip
│   └── ...
├── backtest/         # Backtest results
│   └── positions.json
├── active.set        # Active symbols list
└── positions.json    # Live trading positions

Usage:
    python tools/reorganize_data_directory.py [--dry-run] [--backup]

Options:
    --dry-run    Show what would be done without actually moving files
    --backup     Create a backup of the data directory before reorganizing
"""

import os
import shutil
import argparse
from pathlib import Path
from datetime import datetime


def create_backup(data_dir: Path) -> Path:
    """Create a backup of the data directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = data_dir.parent / f"data_backup_{timestamp}"
    
    print(f"\n📦 Creating backup: {backup_dir}")
    shutil.copytree(data_dir, backup_dir)
    print(f"✓ Backup created successfully")
    
    return backup_dir


def is_symbol_directory(path: Path) -> bool:
    """Check if a directory is a symbol directory (contains candle cache files)."""
    if not path.is_dir():
        return False
    
    # Check if it contains parquet files and symbol_info.json
    has_parquet = any(f.suffix == '.parquet' for f in path.iterdir() if f.is_file())
    has_symbol_info = (path / 'symbol_info.json').exists()
    
    return has_parquet or has_symbol_info


def get_file_size_mb(path: Path) -> float:
    """Get file size in MB."""
    if path.is_file():
        return path.stat().st_size / (1024 * 1024)
    elif path.is_dir():
        total = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        return total / (1024 * 1024)
    return 0


def reorganize_data_directory(data_dir: Path, dry_run: bool = False):
    """Reorganize the data directory into the new structure."""
    
    print("\n" + "=" * 80)
    print("DATA DIRECTORY REORGANIZATION")
    print("=" * 80)
    print(f"\nData directory: {data_dir.absolute()}")
    print(f"Mode: {'DRY RUN (no changes will be made)' if dry_run else 'LIVE (files will be moved)'}")
    print()
    
    # Define new structure
    new_candles_dir = data_dir / 'cache' / 'candles'
    new_ticks_dir = data_dir / 'cache' / 'ticks'
    new_archives_dir = data_dir / 'archives'
    
    # Statistics
    stats = {
        'symbol_dirs_moved': 0,
        'tick_files_moved': 0,
        'archive_files_moved': 0,
        'total_size_mb': 0,
        'errors': []
    }
    
    # Step 1: Create new directory structure
    print("Step 1: Creating new directory structure...")
    if not dry_run:
        new_candles_dir.mkdir(parents=True, exist_ok=True)
        new_ticks_dir.mkdir(parents=True, exist_ok=True)
        new_archives_dir.mkdir(parents=True, exist_ok=True)
        print(f"  ✓ Created: {new_candles_dir}")
        print(f"  ✓ Created: {new_ticks_dir}")
        print(f"  ✓ Created: {new_archives_dir}")
    else:
        print(f"  Would create: {new_candles_dir}")
        print(f"  Would create: {new_ticks_dir}")
        print(f"  Would create: {new_archives_dir}")
    
    # Step 2: Move symbol directories (candle cache)
    print("\nStep 2: Moving symbol directories to cache/candles/...")
    symbol_dirs = [d for d in data_dir.iterdir() if is_symbol_directory(d)]
    
    for symbol_dir in sorted(symbol_dirs):
        symbol_name = symbol_dir.name
        target_dir = new_candles_dir / symbol_name
        size_mb = get_file_size_mb(symbol_dir)
        
        # Skip if already in new location
        if symbol_dir.parent == new_candles_dir:
            continue
        
        print(f"  {symbol_name:15s} ({size_mb:8.1f} MB) -> cache/candles/{symbol_name}")
        
        if not dry_run:
            try:
                shutil.move(str(symbol_dir), str(target_dir))
                stats['symbol_dirs_moved'] += 1
                stats['total_size_mb'] += size_mb
            except Exception as e:
                error_msg = f"Error moving {symbol_name}: {e}"
                stats['errors'].append(error_msg)
                print(f"    ✗ {error_msg}")
        else:
            stats['symbol_dirs_moved'] += 1
            stats['total_size_mb'] += size_mb
    
    # Step 3: Move tick cache files
    print("\nStep 3: Moving tick cache files to cache/ticks/...")
    old_ticks_dir = data_dir / 'ticks'
    
    if old_ticks_dir.exists() and old_ticks_dir.is_dir():
        tick_files = list(old_ticks_dir.glob('*.parquet'))
        
        for tick_file in sorted(tick_files):
            target_file = new_ticks_dir / tick_file.name
            size_mb = get_file_size_mb(tick_file)
            
            print(f"  {tick_file.name:50s} ({size_mb:8.1f} MB)")
            
            if not dry_run:
                try:
                    shutil.move(str(tick_file), str(target_file))
                    stats['tick_files_moved'] += 1
                    stats['total_size_mb'] += size_mb
                except Exception as e:
                    error_msg = f"Error moving {tick_file.name}: {e}"
                    stats['errors'].append(error_msg)
                    print(f"    ✗ {error_msg}")
            else:
                stats['tick_files_moved'] += 1
                stats['total_size_mb'] += size_mb
        
        # Remove old ticks directory if empty
        if not dry_run and old_ticks_dir.exists():
            try:
                if not any(old_ticks_dir.iterdir()):
                    old_ticks_dir.rmdir()
                    print(f"  ✓ Removed empty directory: {old_ticks_dir}")
            except Exception as e:
                print(f"  ⚠ Could not remove {old_ticks_dir}: {e}")
    else:
        print("  No tick cache files found")
    
    # Step 4: Move tick archives
    print("\nStep 4: Moving tick archives to archives/...")
    old_archives_dir = data_dir / 'tick_archives'
    
    if old_archives_dir.exists() and old_archives_dir.is_dir():
        archive_files = list(old_archives_dir.glob('*.zip'))
        
        for archive_file in sorted(archive_files):
            target_file = new_archives_dir / archive_file.name
            size_mb = get_file_size_mb(archive_file)
            
            print(f"  {archive_file.name:50s} ({size_mb:8.1f} MB)")
            
            if not dry_run:
                try:
                    shutil.move(str(archive_file), str(target_file))
                    stats['archive_files_moved'] += 1
                    stats['total_size_mb'] += size_mb
                except Exception as e:
                    error_msg = f"Error moving {archive_file.name}: {e}"
                    stats['errors'].append(error_msg)
                    print(f"    ✗ {error_msg}")
            else:
                stats['archive_files_moved'] += 1
                stats['total_size_mb'] += size_mb
        
        # Remove old tick_archives directory if empty
        if not dry_run and old_archives_dir.exists():
            try:
                if not any(old_archives_dir.iterdir()):
                    old_archives_dir.rmdir()
                    print(f"  ✓ Removed empty directory: {old_archives_dir}")
            except Exception as e:
                print(f"  ⚠ Could not remove {old_archives_dir}: {e}")
    else:
        print("  No tick archives found")
    
    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Symbol directories moved:  {stats['symbol_dirs_moved']}")
    print(f"Tick files moved:          {stats['tick_files_moved']}")
    print(f"Archive files moved:       {stats['archive_files_moved']}")
    print(f"Total data moved:          {stats['total_size_mb']:.1f} MB")
    
    if stats['errors']:
        print(f"\n⚠ Errors encountered:      {len(stats['errors'])}")
        for error in stats['errors']:
            print(f"  - {error}")
    
    if dry_run:
        print("\n⚠ DRY RUN MODE - No files were actually moved")
        print("  Run without --dry-run to perform the reorganization")
    else:
        print("\n✓ Reorganization complete!")
    
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Reorganize data directory into a clean structure',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually moving files'
    )
    parser.add_argument(
        '--backup',
        action='store_true',
        help='Create a backup of the data directory before reorganizing'
    )
    parser.add_argument(
        '--data-dir',
        type=str,
        default='data',
        help='Path to data directory (default: data)'
    )
    
    args = parser.parse_args()
    
    data_dir = Path(args.data_dir)
    
    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        return 1
    
    # Create backup if requested
    if args.backup and not args.dry_run:
        create_backup(data_dir)
    
    # Reorganize
    reorganize_data_directory(data_dir, dry_run=args.dry_run)
    
    return 0


if __name__ == '__main__':
    exit(main())

