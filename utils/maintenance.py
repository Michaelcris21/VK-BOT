"""
Scheduler de Mantenimiento del Bot
Gestiona tareas periódicas como limpieza de cache y optimización
"""

from datetime import datetime, timedelta
from typing import Dict, Any

from config import get_service_logger
from .cache import cleanup_all_caches


class MaintenanceScheduler:
    """Scheduler para tareas de mantenimiento del bot"""

    def __init__(self, cleanup_interval_hours: int = 4):
        self.logger = get_service_logger("maintenance")
        self.cleanup_interval = timedelta(hours=cleanup_interval_hours)
        self.last_cleanup = datetime.now()
        self.logger.info(f"🔧 Scheduler de mantenimiento inicializado (intervalo: {cleanup_interval_hours}h)")

    async def auto_cleanup_if_needed(self) -> None:
        """
        Ejecuta la limpieza de caches si ha pasado el intervalo de tiempo.
        Diseñado para ser llamado de forma asíncrona.
        """
        if datetime.now() - self.last_cleanup > self.cleanup_interval:
            self.logger.info("⏰ Iniciando limpieza automática de caches...")
            try:
                cleaned_count = cleanup_all_caches()
                if cleaned_count > 0:
                    self.logger.info(f"✅ Limpieza automática completada: {cleaned_count} entradas eliminadas.")
                else:
                    self.logger.info("✅ No se encontraron entradas de cache para limpiar.")
                self.last_cleanup = datetime.now()
            except Exception as e:
                self.logger.error(f"❌ Error durante la limpieza automática de caches: {e}", exc_info=True)

    def force_cleanup(self) -> Dict[str, Any]:
        """
        Fuerza una limpieza de todos los caches inmediatamente.

        Returns:
            Un diccionario con los resultados de la limpieza.
        """
        self.logger.info("⚙️ Forzando limpieza de todos los caches...")
        try:
            cleaned_count = cleanup_all_caches()
            self.last_cleanup = datetime.now()
            self.logger.info(f"✅ Limpieza forzada completada: {cleaned_count} entradas eliminadas.")
            return {"status": "success", "cleaned_entries": cleaned_count}
        except Exception as e:
            self.logger.error(f"❌ Error durante la limpieza forzada: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


# Instancia global para ser usada en toda la aplicación
maintenance_scheduler = MaintenanceScheduler()