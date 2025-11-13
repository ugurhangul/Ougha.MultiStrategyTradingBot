"""
MetaTrader 5 connection configuration.
"""
from dataclasses import dataclass


@dataclass
class MT5Config:
    """MetaTrader 5 connection settings"""
    login: int
    password: str
    server: str
    timeout: int = 60000
    portable: bool = False

