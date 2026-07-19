#config/settings.py
"""
Configuración central del bot multilingüe inteligente para VK
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

class Settings:
    """Configuración centralizada del bot"""
    
    # === TOKENS Y KEYS ===
    VK_GROUP_TOKEN = os.getenv("VK_GROUP_TOKEN")
    
    # Manejar de forma robusta la conversión a entero de VK_GROUP_ID (incluyendo comillas o placeholders)
    _vk_group_id_raw = os.getenv("VK_GROUP_ID", "0")
    if _vk_group_id_raw:
        _vk_group_id_raw = _vk_group_id_raw.strip('"\'')
    try:
        VK_GROUP_ID = int(_vk_group_id_raw)
    except ValueError:
        VK_GROUP_ID = 0
        
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    
    # === VALIDACIÓN DE KEYS ===
    @classmethod
    def validate_keys(cls) -> None:
        """Valida que todas las keys requeridas estén presentes"""
        if not cls.GOOGLE_API_KEY:
            raise ValueError("❌ GOOGLE_API_KEY no encontrada en variables de entorno")
        
        if not cls.VK_GROUP_TOKEN:
            raise ValueError("❌ VK_GROUP_TOKEN no encontrado en variables de entorno")
            
        if not cls.VK_GROUP_ID:
            raise ValueError("❌ VK_GROUP_ID no encontrado en variables de entorno")
    
    # === CONFIGURACIÓN DE IA ===
    class AI:
        # Rotación de modelos (en orden de prioridad)
        # Cuando un modelo agote su cuota, se rotará automáticamente al siguiente
        MODEL_TEXT_ROTATION = [
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
            "gemini-2.5-flash"
        ]
        MODEL_VIDEO_ROTATION = [
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
            "gemini-2.5-flash"
        ]
        
        # Modelos actuales
        MODEL_TEXT = MODEL_TEXT_ROTATION[0]
        MODEL_VIDEO = MODEL_VIDEO_ROTATION[0]
        
        # Configuraciones de generación
        TEMPERATURE_TRANSLATION = 0.3
        TEMPERATURE_INTENT = 0.1  # Muy baja para clasificación precisa
        
        # Tokens y timeouts
        MAX_OUTPUT_TOKENS = 3000
        API_TIMEOUT = 120
        
        # Configuración para clasificador de intenciones
        INTENT_CONFIDENCE_THRESHOLD = 0.7
    
    # === CONFIGURACIÓN DE TRADUCCIÓN ===
    class Translation:
        # Cache
        CACHE_MAX_SIZE = 100
        CACHE_EXPIRE_HOURS = 24
        
        # Procesamiento
        MAX_TRANSCRIPT_LENGTH = 50000
        LINK_PLACEHOLDER = "§LINK_URL§"
        
        # Idiomas eslavos soportados
        SLAVIC_LANGUAGES = {
            'ru': 'Ruso', 'uk': 'Ucraniano', 'bg': 'Búlgaro', 
            'sr': 'Serbio', 'hr': 'Croata', 'cs': 'Checo', 
            'mk': 'Macedonio', 'bs': 'Bosnio', 'sk': 'Eslovaco',
            'pl': 'Polaco', 'sl': 'Esloveno'
        }
    
    # === CONFIGURACIÓN DE VK ===
    class VK:
        # Límites de mensaje
        MAX_MESSAGE_LENGTH = 4096
        
        # Comandos del bot
        BOT_COMMANDS = [
            ("start", "Inicia el bot y ve la bienvenida"),
            ("help", "Muestra la guía completa de uso"),
            ("stats", "Consulta tus estadísticas de uso"),
            ("idiomas", "Lista los idiomas soportados"),
            ("mi_idioma", "Consulta tu perfil lingüístico detectado")
        ]
    
    # === INTENCIONES SOPORTADAS ===
    class Intents:
        TRANSLATE = "TRADUCIR"
        HELP = "AYUDA"
        STATS = "ESTADISTICAS"
        LANGUAGES = "IDIOMAS"
        CONVERSATION = "CONVERSACION"
        CONFIGURE_TRANSLATION = "CONFIGURAR_TRADUCCION"
        
        # Lista de todas las intenciones
        ALL_INTENTS = [TRANSLATE, HELP, STATS, LANGUAGES, CONVERSATION, CONFIGURE_TRANSLATION]

        # Intenciones que requieren procesamiento con IA
        AI_INTENTS = [TRANSLATE]
        
        # Intenciones de información
        INFO_INTENTS = [HELP, STATS, LANGUAGES]
    
    # === PATRONES Y REGEX ===
    class Patterns:
        # URLs generales
        URL_PATTERN = r'https?://\S+'
    
    # === MENSAJES DEL BOT ===
    class Messages:
        # Mensajes de estado
        PROCESSING_TRANSLATION = "🔄 Traduciendo..."
        
        # Mensajes de error
        ERROR_TRANSLATION = "❌ Error procesando la traducción."
        
        # Mensajes informativos
        CACHE_HIT = "Usando traducción desde cache"
        LANGUAGE_DETECTED = "Idioma detectado: {}"
        SAME_LANGUAGE = "🤔 El texto parece estar ya en el idioma de destino."
        TIMEOUT_TRANSLATION = "⏱️ La traducción está tardando demasiado. Intenta con un texto más corto."
        
    # === MENSAJES DE VOZ ===
    class Voice:
        PROCESSING_MESSAGE = "🔄 Procesando tu mensaje de voz..."
        SUCCESS_MESSAGE = "✅ Traducción del audio:"
        ERROR_MESSAGE = "❌ Error al procesar el audio. Intenta de nuevo."
        TRANSCRIPTION_TIMEOUT = 60  # Timeout para Gemini transcribe_audio
        
    # === CONFIGURACIÓN DE LOGGING ===
    class Logging:
        LEVEL = "INFO"
        FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        
        # Niveles para librerías externas
        EXTERNAL_LOGGERS = {
            "httpx": "WARNING",
            "vkbottle": "INFO"
        }
    
    @classmethod
    def get_bot_info(cls) -> dict:
        """Retorna información básica del bot para debugging"""
        return {
            "models": {
                "text": cls.AI.MODEL_TEXT,
                "video": cls.AI.MODEL_VIDEO
            },
            "limits": {
                "message_length": cls.VK.MAX_MESSAGE_LENGTH,
                "transcript_length": cls.Translation.MAX_TRANSCRIPT_LENGTH
            },
            "supported_languages": len(cls.Translation.SLAVIC_LANGUAGES),
            "intents": len(cls.Intents.ALL_INTENTS)
        }


# Instancia global de configuración
settings = Settings()

# Validar keys al importar (si ya están definidas)
try:
    settings.validate_keys()
except ValueError as e:
    # Mostramos warning pero permitimos importar para tests iniciales
    print(f"⚠️ Advertencia de configuración al inicializar: {e}")
