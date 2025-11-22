"""
Tick Archive Configuration for External Data Sources.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class TickArchiveConfig:
    """
    Configuration for external tick data archive downloads.
    
    Enables downloading historical tick data from external broker archives
    when MT5 doesn't have the requested data available.
    """
    # === Enable/Disable External Archive Downloads ===
    enabled: bool = False  # Disabled by default for safety
    
    # === Archive Source URLs ===
    # URL pattern template for day-based tick data archives
    # Supported placeholders: {SYMBOL}, {YEAR}, {MONTH}, {DAY}, {BROKER}

    # Day-based archive (single day) - SIMPLIFIED: Only day-based downloads
    # Example: "https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{MONTH}/{DAY}/{BROKER}_{SYMBOL}_{YEAR}_{MONTH}_{DAY}.zip"
    archive_url_pattern_day: str = "https://ticks.ex2archive.com/ticks/{SYMBOL}/{YEAR}/{MONTH}/{DAY}/{BROKER}_{SYMBOL}_{YEAR}_{MONTH}_{DAY}.zip"

    # Enable/disable day-based downloads (set to False to disable external archives entirely)
    use_granular_downloads: bool = True
    
    # List of trusted archive sources (for validation)
    trusted_sources: List[str] = field(default_factory=lambda: [
        "ticks.ex2archive.com",
        "tickdata.fxcorporate.com",
        "historical.dukascopy.com"
    ])
    
    # === Download Settings ===
    download_timeout_seconds: int = 300  # 5 minutes timeout for downloads
    max_retries: int = 3  # Maximum number of download retry attempts
    retry_delay_seconds: int = 5  # Delay between retry attempts
    
    # === Data Validation ===
    validate_tick_format: bool = True  # Validate downloaded data format before merging
    min_ticks_threshold: int = 1000  # Minimum number of ticks to consider download successful
    
    # === Cache Settings ===
    save_downloaded_archives: bool = True  # Keep downloaded ZIP files for future use
    archive_cache_dir: str = "data/archives"  # Directory for storing downloaded archives
    
    # === Broker Mapping ===
    # Map MT5 server names to broker names used in archive URLs
    # Example: "Exness-MT5Trial15" -> "Exness"
    broker_name_mapping: dict = field(default_factory=lambda: {
        "Exness-MT5Trial15": "Exness",
        "Exness-MT5Real": "Exness",
        "Exness-MT5Trial": "Exness",
        "ICMarkets-Demo": "ICMarkets",
        "ICMarkets-Live": "ICMarkets",
        "FTMO-Demo": "FTMO",
        "FTMO-Server": "FTMO",
        # Add more broker mappings as needed
    })
    
    # === Symbol Mapping ===
    # Map MT5 symbol names to archive symbol names if different
    # Example: "XAUUSD.a" -> "XAUUSD"
    symbol_name_mapping: dict = field(default_factory=lambda: {
        "XAUUSD.a": "XAUUSD",
        "EURUSD.a": "EURUSD",
        "GBPUSD.a": "GBPUSD",
        # Add more symbol mappings as needed
    })

