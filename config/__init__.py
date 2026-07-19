"""
Configuración del bot multilingüe inteligente para VK
"""

from .settings import settings, Settings
from .logging_config import initialize_logging, get_service_logger, bot_logger

__all__ = [
    'settings',
    'Settings', 
    'initialize_logging',
    'get_service_logger',
    'bot_logger'
]

# Validación al importar
try:
    settings.validate_keys()
    print("INFO: Configuración de VK validada correctamente")
except ValueError as e:
    print(f"WARNING: Advertencia de configuración: {e}")
