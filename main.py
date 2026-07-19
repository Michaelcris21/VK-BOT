"""
Bot Traductor Multilingüe para VK (vkbottle)
Punto de Entrada del Bot
"""
import sys
from vkbottle import API
from vkbottle.bot import Bot

from config import initialize_logging, settings
from handlers import command_labeler, message_labeler
from utils import user_stats, bot_caches

# 1. Configurar Logger
logger = initialize_logging("logs/bot.log")

# 2. Inicializar la API de VK y el Bot
api = API(token=settings.VK_GROUP_TOKEN)
api.api_version = "5.199"
bot = Bot(api=api)

# 3. Configurar los Controladores (Handlers)
# Cargamos el labeler de comandos primero para que tengan prioridad sobre el catch-all de mensajes.
bot.labeler.load(command_labeler)
bot.labeler.load(message_labeler)


def main():
    try:
        print("Bot Traductor Inteligente para VK (vkbottle)")
        print("==================================================")
        logger.info("⚡ Bot inicializándose con API v5.199...")
        
        # Verificar tokens
        settings.validate_keys()
        
        # Ejecutar Bot
        bot.run_forever()
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot detenido por el usuario (KeyboardInterrupt)")
        
    except Exception as e:
        logger.error(f"❌ Error fatal en ejecución: {e}", exc_info=True)
        sys.exit(1)
        
    finally:
        # Guardar estadísticas finales
        logger.info("💾 Guardando estadísticas y limpiando recursos...")
        try:
            if hasattr(user_stats, 'save_to_file'):
                user_stats.save_to_file()
                logger.info("✅ Estadísticas finales persistidas correctamente.")
        except Exception as e:
            logger.error(f"❌ Error al guardar estadísticas en el cierre: {e}")
            
        # Limpiar cachés
        try:
            bot_caches.clear_all_caches()
            logger.info("🗑️ Cachés de traducción liberadas.")
        except Exception as e:
            logger.error(f"❌ Error al limpiar cachés: {e}")
            
        logger.info("👋 Proceso terminado. ¡Hasta luego!")


if __name__ == "__main__":
    main()
