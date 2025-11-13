"""
Position Sizer Factory and Registry

Provides plugin registration and dynamic loading for position sizing strategies.
"""

from typing import Dict, Type, Optional, Any, Callable
from dataclasses import dataclass

from src.risk.position_sizing.base_position_sizer import BasePositionSizer
from src.utils.logger import get_logger


@dataclass
class PositionSizerMetadata:
    """Metadata for a registered position sizer"""
    name: str
    sizer_class: Type[BasePositionSizer]
    description: str
    default: bool = False


class PositionSizerRegistry:
    """
    Registry for position sizing plugins.
    
    Manages registration and creation of position sizers.
    """
    
    _registry: Dict[str, PositionSizerMetadata] = {}
    _logger = get_logger()
    
    @classmethod
    def register(cls, name: str, sizer_class: Type[BasePositionSizer],
                 description: str = "", default: bool = False) -> None:
        """
        Register a position sizer plugin.
        
        Args:
            name: Unique name for the position sizer
            sizer_class: Position sizer class
            description: Description of the position sizer
            default: Whether this is the default position sizer
        """
        if name in cls._registry:
            cls._logger.warning(f"Position sizer '{name}' already registered, overwriting")
        
        metadata = PositionSizerMetadata(
            name=name,
            sizer_class=sizer_class,
            description=description,
            default=default
        )
        
        cls._registry[name] = metadata
        cls._logger.info(f"Registered position sizer: {name} ({sizer_class.__name__})")
    
    @classmethod
    def get(cls, name: str) -> Optional[PositionSizerMetadata]:
        """
        Get metadata for a registered position sizer.
        
        Args:
            name: Position sizer name
            
        Returns:
            Position sizer metadata or None if not found
        """
        return cls._registry.get(name)
    
    @classmethod
    def list_all(cls) -> list[str]:
        """
        List all registered position sizers.
        
        Returns:
            List of position sizer names
        """
        return list(cls._registry.keys())
    
    @classmethod
    def get_default(cls) -> Optional[str]:
        """
        Get the default position sizer name.
        
        Returns:
            Default position sizer name or None
        """
        for name, metadata in cls._registry.items():
            if metadata.default:
                return name
        return None
    
    @classmethod
    def create(cls, name: str, symbol: str, **kwargs) -> Optional[BasePositionSizer]:
        """
        Create a position sizer instance.
        
        Args:
            name: Position sizer name
            symbol: Trading symbol
            **kwargs: Additional parameters for the position sizer
            
        Returns:
            Position sizer instance or None if not found
        """
        metadata = cls.get(name)
        if metadata is None:
            cls._logger.error(f"Position sizer '{name}' not found in registry")
            return None
        
        try:
            sizer = metadata.sizer_class(symbol=symbol, **kwargs)
            cls._logger.info(f"Created position sizer: {name} for {symbol}")
            return sizer
        except Exception as e:
            cls._logger.error(f"Failed to create position sizer '{name}': {e}")
            return None


def register_position_sizer(name: str, description: str = "", 
                            default: bool = False) -> Callable:
    """
    Decorator for registering position sizer plugins.
    
    Args:
        name: Unique name for the position sizer
        description: Description of the position sizer
        default: Whether this is the default position sizer
        
    Returns:
        Decorator function
    
    Example:
        @register_position_sizer("fixed", description="Fixed lot size", default=True)
        class FixedPositionSizer(BasePositionSizer):
            ...
    """
    def decorator(cls: Type[BasePositionSizer]) -> Type[BasePositionSizer]:
        PositionSizerRegistry.register(name, cls, description, default)
        return cls
    return decorator


def create_position_sizer(name: str, symbol: str, **kwargs) -> Optional[BasePositionSizer]:
    """
    Convenience function to create a position sizer.
    
    Args:
        name: Position sizer name
        symbol: Trading symbol
        **kwargs: Additional parameters
        
    Returns:
        Position sizer instance or None
    """
    return PositionSizerRegistry.create(name, symbol, **kwargs)

