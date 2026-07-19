"""
Configuración centralizada de logging para el bot
"""
import logging
import sys
from pathlib import Path
from typing import Optional
from .settings import settings

class SafeStreamWrapper:
    """Evita fallos de codificación (UnicodeEncodeError) en consola reemplazando caracteres no admitidos"""
    def __init__(self, stream):
        self.stream = stream
        self.encoding = getattr(stream, "encoding", "utf-8")
        
    def write(self, data):
        try:
            self.stream.write(data)
        except UnicodeEncodeError:
            encoding = self.encoding or "utf-8"
            clean_data = data.encode(encoding, errors="replace").decode(encoding)
            self.stream.write(clean_data)
            
    def flush(self):
        if hasattr(self.stream, "flush"):
            self.stream.flush()

class BotLogger:
    """Configurador de logging para el bot"""
    
    def __init__(self):
        self.logger = None
        self.is_configured = False
    
    def setup_logging(self, 
                     log_file: Optional[str] = None,
                     log_level: str = None) -> logging.Logger:
        """
        Configura el sistema de logging del bot
        
        Args:
            log_file: Archivo donde guardar logs (opcional)
            log_level: Nivel de logging (opcional, usa settings por defecto)
        
        Returns:
            Logger configurado
        """
        if self.is_configured:
            return self.logger
        
        # Nivel de logging
        level = getattr(logging, (log_level or settings.Logging.LEVEL).upper())
        
        # Configuración básica
        logging.basicConfig(
            level=level,
            format=settings.Logging.FORMAT,
            handlers=self._get_handlers(log_file)
        )
        
        # Configurar loggers de librerías externas
        self._configure_external_loggers()
        
        # Logger principal del bot
        self.logger = logging.getLogger("bot")
        self.is_configured = True
        
        # Log inicial
        self.logger.info("🚀 Sistema de logging configurado")
        self.logger.info(f"📊 Nivel de logging: {settings.Logging.LEVEL}")
        
        if log_file:
            self.logger.info(f"📁 Logs guardándose en: {log_file}")
        
        return self.logger
    
    def _get_handlers(self, log_file: Optional[str]) -> list:
        """Crea handlers para console y archivo"""
        handlers = []
        
        # Handler para consola
        console_handler = logging.StreamHandler(SafeStreamWrapper(sys.stdout))
        console_handler.setFormatter(
            logging.Formatter(settings.Logging.FORMAT)
        )
        handlers.append(console_handler)
        
        # Handler para archivo (opcional)
        if log_file:
            # Crear directorio si no existe
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(
                logging.Formatter(settings.Logging.FORMAT)
            )
            handlers.append(file_handler)
        
        return handlers
    
    def _configure_external_loggers(self) -> None:
        """Configura niveles de logging para librerías externas"""
        for logger_name, level in settings.Logging.EXTERNAL_LOGGERS.items():
            external_logger = logging.getLogger(logger_name)
            external_logger.setLevel(getattr(logging, level))
    
    def get_logger(self, name: str) -> logging.Logger:
        """
        Obtiene un logger específico para un módulo
        
        Args:
            name: Nombre del módulo/servicio
            
        Returns:
            Logger configurado para el módulo
        """
        if not self.is_configured:
            self.setup_logging()
        
        return logging.getLogger(f"bot.{name}")
    
    def log_bot_info(self) -> None:
        """Registra información del bot al inicio"""
        if not self.logger:
            return
        
        info = settings.get_bot_info()
        
        self.logger.info("🤖 === INFORMACIÓN DEL BOT ===")
        self.logger.info(f"📝 Modelo para texto: {info['models']['text']}")
        self.logger.info(f"🎥 Modelo para video: {info['models']['video']}")
        self.logger.info(f"💬 Límite de mensaje: {info['limits']['message_length']} chars")
        self.logger.info(f"🌍 Idiomas soportados: {info['supported_languages']}")
        self.logger.info(f"🎯 Intenciones configuradas: {info['intents']}")
        self.logger.info("🤖 === FIN INFORMACIÓN ===")


class ServiceLogger:
    """Logger contextual para servicios específicos"""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.logger = bot_logger.get_logger(service_name)
    
    def info(self, message: str, user_id: Optional[int] = None) -> None:
        """Log de información con contexto de usuario"""
        if user_id:
            self.logger.info(f"[User {user_id}] {message}")
        else:
            self.logger.info(message)
    
    def error(self, message: str, error: Optional[Exception] = None, 
              user_id: Optional[int] = None) -> None:
        """Log de error con contexto"""
        prefix = f"[User {user_id}] " if user_id else ""
        
        if error:
            self.logger.error(f"{prefix}{message}: {str(error)}", exc_info=True)
        else:
            self.logger.error(f"{prefix}{message}")
    
    def warning(self, message: str, user_id: Optional[int] = None) -> None:
        """Log de warning con contexto"""
        if user_id:
            self.logger.warning(f"[User {user_id}] {message}")
        else:
            self.logger.warning(message)
    
    def debug(self, message: str, user_id: Optional[int] = None) -> None:
        """Log de debug con contexto"""
        if user_id:
            self.logger.debug(f"[User {user_id}] {message}")
        else:
            self.logger.debug(message)


# Instancia global del logger del bot
bot_logger = BotLogger()

# Función de conveniencia para obtener loggers de servicios
def get_service_logger(service_name: str) -> ServiceLogger:
    """
    Obtiene un logger contextual para un servicio
    
    Args:
        service_name: Nombre del servicio (ej: "translation", "youtube", etc.)
        
    Returns:
        ServiceLogger configurado
    """
    return ServiceLogger(service_name)

# Función para inicializar logging (llamar desde main.py)
def initialize_logging(log_file: Optional[str] = None, 
                      log_level: Optional[str] = None) -> logging.Logger:
    """
    Inicializa el sistema de logging completo
    
    Args:
        log_file: Archivo donde guardar logs (opcional)
        log_level: Nivel de logging (opcional)
        
    Returns:
        Logger principal del bot
    """
    logger = bot_logger.setup_logging(log_file, log_level)
    bot_logger.log_bot_info()
    return logger