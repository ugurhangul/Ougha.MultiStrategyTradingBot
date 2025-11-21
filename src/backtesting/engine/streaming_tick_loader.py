"""
Streaming Tick Loader for Memory-Efficient Backtesting.

Instead of loading all ticks into memory, this module streams ticks from disk
in chunks, significantly reducing memory usage for long backtests.

Memory comparison for 1-year backtest with 2 symbols:
- Traditional: ~20-30 GB (all ticks in memory)
- Streaming: ~2-3 GB (only current chunk in memory)
"""

from typing import Dict, List, Iterator, Tuple
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
import heapq
from src.utils.logger import get_logger


@dataclass
class GlobalTick:
    """Single tick in the global timeline."""
    time: datetime
    symbol: str
    bid: float
    ask: float
    last: float
    volume: int
    spread: float


class StreamingTickLoader:
    """
    Streams ticks from parquet files in chronological order without loading all into memory.
    
    Uses a heap-based merge algorithm to efficiently merge multiple sorted tick streams.
    """
    
    def __init__(self, cache_files: Dict[str, str], chunk_size: int = 100000):
        """
        Initialize streaming tick loader.

        Args:
            cache_files: Dict mapping symbol -> parquet file path
            chunk_size: Number of ticks to read per chunk from each file
        """
        self.cache_files = cache_files
        self.chunk_size = chunk_size
        self.logger = get_logger()

        # Statistics
        self.total_ticks_streamed = 0
        self.symbols = list(cache_files.keys())
        
    def stream_ticks(self) -> Iterator[GlobalTick]:
        """
        Stream ticks in chronological order from all symbol files.
        
        Yields:
            GlobalTick objects in chronological order
        """
        # Open iterators for each symbol
        symbol_iterators = {}
        for symbol, cache_file in self.cache_files.items():
            cache_path = Path(cache_file)
            if not cache_path.exists():
                self.logger.warning(f"Cache file not found: {cache_file}")
                continue
            
            symbol_iterators[symbol] = self._read_symbol_chunks(symbol, cache_path)
        
        if not symbol_iterators:
            self.logger.error("No valid cache files found!")
            return
        
        # Use heap to merge sorted streams
        # Heap contains tuples: (tick_time, symbol, tick_data)
        heap = []
        
        # Initialize heap with first tick from each symbol
        for symbol, iterator in symbol_iterators.items():
            try:
                tick = next(iterator)
                heapq.heappush(heap, (tick.time, symbol, tick, iterator))
            except StopIteration:
                self.logger.warning(f"No ticks found for {symbol}")
        
        # Merge streams in chronological order
        while heap:
            tick_time, symbol, tick, iterator = heapq.heappop(heap)
            
            # Yield this tick
            yield tick
            self.total_ticks_streamed += 1
            
            # Get next tick from this symbol's stream
            try:
                next_tick = next(iterator)
                heapq.heappush(heap, (next_tick.time, symbol, next_tick, iterator))
            except StopIteration:
                # This symbol's stream is exhausted
                pass
    
    def _read_symbol_chunks(self, symbol: str, cache_path: Path) -> Iterator[GlobalTick]:
        """
        Read ticks for a symbol in chunks WITHOUT loading entire file into memory.

        Args:
            symbol: Symbol name
            cache_path: Path to parquet file

        Yields:
            GlobalTick objects for this symbol
        """
        import pyarrow.parquet as pq

        # Open parquet file for streaming (doesn't load into memory)
        parquet_file = pq.ParquetFile(cache_path)
        total_rows = parquet_file.metadata.num_rows

        self.logger.info(f"Streaming {total_rows:,} ticks for {symbol} from {cache_path.name}")

        # Read in batches using pyarrow (true streaming, no full load)
        # This reads directly from disk in chunks
        for batch in parquet_file.iter_batches(batch_size=self.chunk_size):
            # Convert batch to pandas DataFrame (only this chunk in memory)
            chunk_df = batch.to_pandas()

            # Convert chunk to GlobalTick objects using vectorized approach
            for idx in range(len(chunk_df)):
                row = chunk_df.iloc[idx]
                yield GlobalTick(
                    time=row['time'],
                    symbol=symbol,
                    bid=row['bid'],
                    ask=row['ask'],
                    last=row['last'],
                    volume=row['volume'],
                    spread=row.get('spread', row['ask'] - row['bid'])
                )

            # Free chunk memory immediately
            del chunk_df
            del batch
    
    def get_statistics(self) -> Dict:
        """Get streaming statistics."""
        return {
            'total_ticks_streamed': self.total_ticks_streamed,
            'symbols': self.symbols,
            'chunk_size': self.chunk_size
        }


class StreamingTickTimeline:
    """
    Provides a timeline interface for streaming ticks.
    
    This class wraps StreamingTickLoader to provide a list-like interface
    that the backtest engine expects, while actually streaming from disk.
    """
    
    def __init__(self, cache_files: Dict[str, str], chunk_size: int = 100000):
        """
        Initialize streaming timeline.

        Args:
            cache_files: Dict mapping symbol -> parquet file path
            chunk_size: Number of ticks to read per chunk
        """
        self.loader = StreamingTickLoader(cache_files, chunk_size)
        self.logger = get_logger()

        # Pre-calculate total tick count for progress tracking
        self._total_ticks = self._count_total_ticks(cache_files)

        # Create iterator
        self._iterator = None
        
    def _count_total_ticks(self, cache_files: Dict[str, str]) -> int:
        """Count total ticks across all files WITHOUT loading them into memory."""
        import pyarrow.parquet as pq

        total = 0
        for symbol, cache_file in cache_files.items():
            cache_path = Path(cache_file)
            if cache_path.exists():
                # Read ONLY metadata (no data loaded into memory)
                parquet_file = pq.ParquetFile(cache_path)
                count = parquet_file.metadata.num_rows
                total += count
                self.logger.info(f"  {symbol}: {count:,} ticks")

        return total
    
    def __len__(self) -> int:
        """Return total number of ticks."""
        return self._total_ticks
    
    def __iter__(self) -> Iterator[GlobalTick]:
        """Return iterator over ticks."""
        return self.loader.stream_ticks()
    
    def get_statistics(self) -> Dict:
        """Get streaming statistics."""
        return self.loader.get_statistics()

