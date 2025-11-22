#!/usr/bin/env python3
"""
Cache Cleanup Utility

This script cleans up old/broken cache files from the backtesting data cache.
Use this after upgrading to the new cache validation system.

Usage:
    python scripts/cleanup_cache.py                    # Dry run (shows what would be deleted)
    python scripts/cleanup_cache.py --confirm          # Actually delete files
    python scripts/cleanup_cache.py --stats            # Show cache statistics only
"""

import argparse
import shutil
from pathlib import Path
from datetime import datetime
import pyarrow.parquet as pq


def get_cache_metadata(cache_file: Path) -> dict:
    """Read metadata from cache file."""
    try:
        pf = pq.ParquetFile(cache_file)
        metadata = pf.schema_arrow.metadata
        
        if not metadata:
            return {}
        
        return {k.decode(): v.decode() for k, v in metadata.items()}
    except Exception as e:
        return {}


def analyze_cache_directory(cache_dir: Path) -> dict:
    """Analyze cache directory and categorize files."""
    stats = {
        'total_files': 0,
        'total_size_mb': 0,
        'files_with_metadata': 0,
        'files_without_metadata': 0,
        'files_to_delete': [],
        'size_to_free_mb': 0
    }
    
    if not cache_dir.exists():
        print(f"❌ Cache directory not found: {cache_dir}")
        return stats
    
    # Find all parquet files
    parquet_files = list(cache_dir.rglob('*.parquet'))
    stats['total_files'] = len(parquet_files)
    
    print(f"\n📊 Analyzing {len(parquet_files)} cache files...")
    
    for cache_file in parquet_files:
        file_size_mb = cache_file.stat().st_size / (1024 * 1024)
        stats['total_size_mb'] += file_size_mb
        
        metadata = get_cache_metadata(cache_file)
        
        if metadata and 'cache_version' in metadata:
            stats['files_with_metadata'] += 1
        else:
            # File without metadata - mark for deletion
            stats['files_without_metadata'] += 1
            stats['files_to_delete'].append(cache_file)
            stats['size_to_free_mb'] += file_size_mb
    
    return stats


def print_statistics(stats: dict):
    """Print cache statistics."""
    print("\n" + "="*60)
    print("📊 CACHE STATISTICS")
    print("="*60)
    print(f"Total cache files:           {stats['total_files']}")
    print(f"Total cache size:            {stats['total_size_mb']:.2f} MB")
    print(f"Files with metadata:         {stats['files_with_metadata']} ✅")
    print(f"Files without metadata:      {stats['files_without_metadata']} ❌")
    print(f"Space to be freed:           {stats['size_to_free_mb']:.2f} MB")
    print("="*60)


def cleanup_cache(cache_dir: Path, confirm: bool = False):
    """Clean up cache files without metadata."""
    stats = analyze_cache_directory(cache_dir)
    
    print_statistics(stats)
    
    if stats['files_without_metadata'] == 0:
        print("\n✅ All cache files have metadata. No cleanup needed!")
        return
    
    print(f"\n🗑️  Files to be deleted ({len(stats['files_to_delete'])}):")
    print("-" * 60)
    
    # Group by symbol for better readability
    files_by_symbol = {}
    for file_path in stats['files_to_delete']:
        # Extract symbol from path (e.g., data/cache/2025/01/15/ticks/EURUSD.parquet)
        parts = file_path.parts
        if len(parts) >= 2:
            symbol = file_path.stem  # Filename without extension
            data_type = parts[-2] if len(parts) >= 2 else 'unknown'
            date_str = '/'.join(parts[-5:-2]) if len(parts) >= 5 else 'unknown'
            
            key = f"{symbol} ({data_type})"
            if key not in files_by_symbol:
                files_by_symbol[key] = []
            files_by_symbol[key].append(date_str)
    
    for symbol, dates in sorted(files_by_symbol.items()):
        print(f"  {symbol}: {len(dates)} files")
        if len(dates) <= 5:
            for date in dates:
                print(f"    - {date}")
        else:
            print(f"    - {dates[0]} ... {dates[-1]} (and {len(dates)-2} more)")
    
    print("-" * 60)
    
    if not confirm:
        print("\n⚠️  DRY RUN MODE - No files were deleted")
        print("   Run with --confirm to actually delete these files")
        print("\n💡 Tip: These files will be automatically rebuilt when you run backtests")
        return
    
    # Confirm deletion
    print("\n⚠️  WARNING: This will permanently delete cache files without metadata!")
    print("   These files will be automatically rebuilt when you run backtests.")
    response = input("\n   Type 'DELETE' to confirm: ")
    
    if response != 'DELETE':
        print("\n❌ Cleanup cancelled")
        return
    
    # Delete files
    print("\n🗑️  Deleting files...")
    deleted_count = 0
    
    for file_path in stats['files_to_delete']:
        try:
            file_path.unlink()
            deleted_count += 1
        except Exception as e:
            print(f"   ❌ Error deleting {file_path}: {e}")
    
    # Clean up empty directories
    print("\n🧹 Cleaning up empty directories...")
    for dirpath in sorted(cache_dir.rglob('*'), reverse=True):
        if dirpath.is_dir() and not any(dirpath.iterdir()):
            try:
                dirpath.rmdir()
            except Exception:
                pass
    
    print(f"\n✅ Cleanup complete!")
    print(f"   Deleted {deleted_count} files")
    print(f"   Freed {stats['size_to_free_mb']:.2f} MB")
    print("\n💡 Cache will be automatically rebuilt when you run backtests")


def main():
    parser = argparse.ArgumentParser(
        description='Clean up old/broken cache files from backtesting data cache',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/cleanup_cache.py                    # Dry run (shows what would be deleted)
  python scripts/cleanup_cache.py --confirm          # Actually delete files
  python scripts/cleanup_cache.py --stats            # Show statistics only
  python scripts/cleanup_cache.py --cache-dir ./data/cache  # Custom cache directory
        """
    )
    
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Actually delete files (default is dry run)'
    )
    
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show statistics only (no deletion)'
    )
    
    parser.add_argument(
        '--cache-dir',
        type=str,
        default='data/cache',
        help='Path to cache directory (default: data/cache)'
    )
    
    args = parser.parse_args()
    
    cache_dir = Path(args.cache_dir)
    
    print("="*60)
    print("🧹 CACHE CLEANUP UTILITY")
    print("="*60)
    print(f"Cache directory: {cache_dir.absolute()}")
    print(f"Mode: {'STATISTICS ONLY' if args.stats else 'DELETE' if args.confirm else 'DRY RUN'}")
    print("="*60)
    
    if args.stats:
        stats = analyze_cache_directory(cache_dir)
        print_statistics(stats)
    else:
        cleanup_cache(cache_dir, confirm=args.confirm)


if __name__ == '__main__':
    main()

