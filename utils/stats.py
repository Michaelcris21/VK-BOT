"""
Sistema de Estadísticas de Usuario
Maneja tracking de acciones, análisis de uso y persistencia opcional
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from collections import defaultdict

from config import settings, get_service_logger


@dataclass
class UserActivity:
    """Actividad de un usuario específico"""
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    translations: int = 0
    summaries: int = 0
    downloads: int = 0
    conversations: int = 0
    help_requests: int = 0
    errors: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    total_actions: int = 0
    
    def __post_init__(self):
        """Calcula total de acciones después de inicialización"""
        self.total_actions = (
            self.translations + self.summaries + self.downloads + 
            self.conversations + self.help_requests
        )


@dataclass
class GlobalStats:
    """Estadísticas globales del bot"""
    total_users: int = 0
    total_actions: int = 0
    translations_total: int = 0
    summaries_total: int = 0
    downloads_total: int = 0
    conversations_total: int = 0
    help_requests_total: int = 0
    errors_total: int = 0
    uptime_start: Optional[datetime] = None
    last_reset: Optional[datetime] = None


class UserStats:
    """Sistema completo de estadísticas de usuario con persistencia opcional"""
    
    def __init__(self, persist_to_file: bool = True, stats_file: Optional[str] = None):
        self.logger = get_service_logger("stats")
        
        # Configuración de persistencia
        self.persist_to_file = persist_to_file
        self.stats_file = Path(stats_file) if stats_file else Path("bot_stats.json")
        
        # Datos en memoria
        self.user_activities: Dict[int, UserActivity] = {}
        self.global_stats = GlobalStats(uptime_start=datetime.now())
        
        # Configuración de auto-save
        self.auto_save_interval = 300  # 5 minutos
        self.last_save = datetime.now()
        self.unsaved_changes = False
        
        # Límites y limpieza
        self.max_inactive_days = 90  # Limpiar usuarios inactivos después de 90 días
        self.max_users_in_memory = 10000  # Límite de usuarios en memoria
        
        # Cargar datos existentes
        if self.persist_to_file and self.stats_file.exists():
            self._load_from_file()
        
        self.logger.info("📊 Sistema de estadísticas inicializado")
        if self.persist_to_file:
            self.logger.info(f"💾 Persistencia activada: {self.stats_file}")
    
    def record_action(self, user_id: int, action: str, username: Optional[str] = None, 
                     first_name: Optional[str] = None) -> None:
        """
        Registra una acción de usuario
        
        Args:
            user_id: ID del usuario
            action: Tipo de acción ('translations', 'summaries', 'downloads', etc.)
            username: Username del usuario (opcional)
            first_name: Primer nombre del usuario (opcional)
        """
        try:
            now = datetime.now()
            
            # Obtener o crear actividad del usuario
            if user_id not in self.user_activities:
                self.user_activities[user_id] = UserActivity(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    first_seen=now
                )
                self.global_stats.total_users += 1
                self.logger.debug(f"👤 Nuevo usuario registrado: {user_id}")
            
            user_activity = self.user_activities[user_id]
            
            # Actualizar información de usuario si cambió
            if username and user_activity.username != username:
                user_activity.username = username
            if first_name and user_activity.first_name != first_name:
                user_activity.first_name = first_name
            
            # Registrar la acción
            if hasattr(user_activity, action):
                setattr(user_activity, action, getattr(user_activity, action) + 1)
                
                # Actualizar estadísticas globales
                global_field = f"{action}_total"
                if hasattr(self.global_stats, global_field):
                    setattr(self.global_stats, global_field, 
                           getattr(self.global_stats, global_field) + 1)
                
                self.logger.debug(f"📈 Acción registrada: {action} para usuario {user_id}")
            else:
                self.logger.warning(f"❌ Acción desconocida: {action}")
                return
            
            # Actualizar timestamps y totales
            user_activity.last_seen = now
            user_activity.total_actions = (
                user_activity.translations + user_activity.summaries + 
                user_activity.downloads + user_activity.conversations + 
                user_activity.help_requests
            )
            
            self.global_stats.total_actions += 1
            self.unsaved_changes = True
            
            # Auto-save si es necesario
            self._auto_save_if_needed()
            
        except Exception as e:
            self.logger.error(f"❌ Error registrando acción: {e}")
    
    def record_error(self, user_id: int, error_type: str, error_message: str) -> None:
        """Registra un error para análisis"""
        self.record_action(user_id, 'errors')
        self.logger.warning(f"🚨 Error registrado para {user_id}: {error_type} - {error_message}")
    
    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """
        Obtiene estadísticas de un usuario específico
        
        Returns:
            Diccionario con estadísticas del usuario
        """
        if user_id not in self.user_activities:
            return {
                'translations': 0, 'summaries': 0, 'downloads': 0,
                'conversations': 0, 'help_requests': 0, 'errors': 0,
                'total_actions': 0, 'first_seen': None, 'last_seen': None,
                'is_new_user': True
            }
        
        activity = self.user_activities[user_id]
        
        # Calcular métricas adicionales
        days_using = 0
        if activity.first_seen:
            days_using = (datetime.now() - activity.first_seen).days
        
        actions_per_day = activity.total_actions / max(days_using, 1)
        
        return {
            'translations': activity.translations,
            'summaries': activity.summaries,
            'downloads': activity.downloads,
            'conversations': activity.conversations,
            'help_requests': activity.help_requests,
            'errors': activity.errors,
            'total_actions': activity.total_actions,
            'first_seen': activity.first_seen,
            'last_seen': activity.last_seen,
            'days_using_bot': days_using,
            'actions_per_day': round(actions_per_day, 1),
            'is_new_user': False,
            'most_used_feature': self._get_most_used_feature(activity)
        }
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas globales del bot"""
        uptime_hours = 0
        if self.global_stats.uptime_start:
            uptime_hours = (datetime.now() - self.global_stats.uptime_start).total_seconds() / 3600
        
        return {
            'total_users': self.global_stats.total_users,
            'total_actions': self.global_stats.total_actions,
            'translations_total': self.global_stats.translations_total,
            'summaries_total': self.global_stats.summaries_total,
            'downloads_total': self.global_stats.downloads_total,
            'conversations_total': self.global_stats.conversations_total,
            'help_requests_total': self.global_stats.help_requests_total,
            'errors_total': self.global_stats.errors_total,
            'uptime_hours': round(uptime_hours, 1),
            'actions_per_hour': round(self.global_stats.total_actions / max(uptime_hours, 1), 1),
            'active_users_today': self._count_active_users_today(),
            'new_users_today': self._count_new_users_today(),
            'most_popular_feature': self._get_most_popular_feature()
        }
    
    def get_top_users(self, limit: int = 10, by: str = 'total_actions') -> List[Dict[str, Any]]:
        """
        Obtiene los usuarios más activos
        
        Args:
            limit: Número de usuarios a retornar
            by: Campo por el cual ordenar ('total_actions', 'translations', etc.)
            
        Returns:
            Lista de usuarios ordenados por actividad
        """
        sorted_users = sorted(
            self.user_activities.values(),
            key=lambda x: getattr(x, by, 0),
            reverse=True
        )
        
        return [
            {
                'user_id': user.user_id,
                'username': user.username,
                'first_name': user.first_name,
                'total_actions': user.total_actions,
                'translations': user.translations,
                'summaries': user.summaries,
                'downloads': user.downloads,
                'last_seen': user.last_seen
            }
            for user in sorted_users[:limit]
        ]
    
    def get_usage_analytics(self) -> Dict[str, Any]:
        """Análisis avanzado de uso del bot"""
        now = datetime.now()
        
        # Usuarios por período
        users_last_hour = sum(1 for u in self.user_activities.values() 
                             if u.last_seen and (now - u.last_seen).total_seconds() < 3600)
        users_last_day = sum(1 for u in self.user_activities.values() 
                            if u.last_seen and (now - u.last_seen).days < 1)
        users_last_week = sum(1 for u in self.user_activities.values() 
                             if u.last_seen and (now - u.last_seen).days < 7)
        
        # Distribución de acciones
        action_distribution = {
            'translations': self.global_stats.translations_total,
            'summaries': self.global_stats.summaries_total,
            'downloads': self.global_stats.downloads_total,
            'conversations': self.global_stats.conversations_total,
            'help_requests': self.global_stats.help_requests_total
        }
        
        # Calcular porcentajes
        total_functional_actions = sum(action_distribution.values())
        action_percentages = {
            action: round((count / max(total_functional_actions, 1)) * 100, 1)
            for action, count in action_distribution.items()
        }
        
        return {
            'users_active_last_hour': users_last_hour,
            'users_active_last_day': users_last_day,
            'users_active_last_week': users_last_week,
            'retention_rate_week': round((users_last_week / max(self.global_stats.total_users, 1)) * 100, 1),
            'action_distribution': action_distribution,
            'action_percentages': action_percentages,
            'error_rate': round((self.global_stats.errors_total / max(self.global_stats.total_actions, 1)) * 100, 2)
        }
    
    # === MÉTODOS PRIVADOS ===
    
    def _get_most_used_feature(self, activity: UserActivity) -> str:
        """Determina la función más usada por un usuario"""
        features = {
            'traducción': activity.translations,
            'resúmenes': activity.summaries,
            'descargas': activity.downloads,
            'conversación': activity.conversations,
            'ayuda': activity.help_requests
        }
        return max(features, key=features.get) if any(features.values()) else 'ninguna'
    
    def _get_most_popular_feature(self) -> str:
        """Determina la función más popular globalmente"""
        features = {
            'traducción': self.global_stats.translations_total,
            'resúmenes': self.global_stats.summaries_total,
            'descargas': self.global_stats.downloads_total,
            'conversación': self.global_stats.conversations_total,
            'ayuda': self.global_stats.help_requests_total
        }
        return max(features, key=features.get) if any(features.values()) else 'ninguna'
    
    def _count_active_users_today(self) -> int:
        """Cuenta usuarios activos hoy"""
        today = datetime.now().date()
        return sum(1 for u in self.user_activities.values() 
                  if u.last_seen and u.last_seen.date() == today)
    
    def _count_new_users_today(self) -> int:
        """Cuenta usuarios nuevos hoy"""
        today = datetime.now().date()
        return sum(1 for u in self.user_activities.values() 
                  if u.first_seen and u.first_seen.date() == today)
    
    def _auto_save_if_needed(self) -> None:
        """Auto-guarda si han pasado suficientes minutos"""
        if not self.persist_to_file or not self.unsaved_changes:
            return
        
        if (datetime.now() - self.last_save).total_seconds() >= self.auto_save_interval:
            self.save_to_file()
    
    # === PERSISTENCIA ===
    
    def save_to_file(self) -> bool:
        """Guarda estadísticas a archivo"""
        if not self.persist_to_file:
            return False
        
        try:
            # Preparar datos para serialización
            data = {
                'global_stats': {
                    **asdict(self.global_stats),
                    'uptime_start': self.global_stats.uptime_start.isoformat() if self.global_stats.uptime_start else None,
                    'last_reset': self.global_stats.last_reset.isoformat() if self.global_stats.last_reset else None
                },
                'user_activities': {}
            }
            
            # Serializar actividades de usuarios
            for user_id, activity in self.user_activities.items():
                data['user_activities'][str(user_id)] = {
                    **asdict(activity),
                    'first_seen': activity.first_seen.isoformat() if activity.first_seen else None,
                    'last_seen': activity.last_seen.isoformat() if activity.last_seen else None
                }
            
            # Guardar archivo
            self.stats_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.last_save = datetime.now()
            self.unsaved_changes = False
            
            self.logger.debug(f"💾 Estadísticas guardadas: {len(self.user_activities)} usuarios")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error guardando estadísticas: {e}")
            return False
    
    def _load_from_file(self) -> bool:
        """Carga estadísticas desde archivo"""
        try:
            with open(self.stats_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Cargar estadísticas globales
            global_data = data.get('global_stats', {})
            self.global_stats = GlobalStats(
                total_users=global_data.get('total_users', 0),
                total_actions=global_data.get('total_actions', 0),
                translations_total=global_data.get('translations_total', 0),
                summaries_total=global_data.get('summaries_total', 0),
                downloads_total=global_data.get('downloads_total', 0),
                conversations_total=global_data.get('conversations_total', 0),
                help_requests_total=global_data.get('help_requests_total', 0),
                errors_total=global_data.get('errors_total', 0),
                uptime_start=datetime.fromisoformat(global_data['uptime_start']) if global_data.get('uptime_start') else datetime.now(),
                last_reset=datetime.fromisoformat(global_data['last_reset']) if global_data.get('last_reset') else None
            )
            
            # Cargar actividades de usuarios
            user_data = data.get('user_activities', {})
            for user_id_str, activity_data in user_data.items():
                user_id = int(user_id_str)
                self.user_activities[user_id] = UserActivity(
                    user_id=user_id,
                    username=activity_data.get('username'),
                    first_name=activity_data.get('first_name'),
                    translations=activity_data.get('translations', 0),
                    summaries=activity_data.get('summaries', 0),
                    downloads=activity_data.get('downloads', 0),
                    conversations=activity_data.get('conversations', 0),
                    help_requests=activity_data.get('help_requests', 0),
                    errors=activity_data.get('errors', 0),
                    first_seen=datetime.fromisoformat(activity_data['first_seen']) if activity_data.get('first_seen') else None,
                    last_seen=datetime.fromisoformat(activity_data['last_seen']) if activity_data.get('last_seen') else None
                )
            
            self.logger.info(f"📂 Estadísticas cargadas: {len(self.user_activities)} usuarios")
            return True
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error cargando estadísticas: {e}")
            return False
    
    def cleanup_inactive_users(self) -> Dict[str, int]:
        """Limpia usuarios inactivos para optimizar memoria"""
        cutoff_date = datetime.now() - timedelta(days=self.max_inactive_days)
        
        inactive_users = [
            user_id for user_id, activity in self.user_activities.items()
            if activity.last_seen and activity.last_seen < cutoff_date
        ]
        
        for user_id in inactive_users:
            del self.user_activities[user_id]
        
        if inactive_users:
            self.unsaved_changes = True
            self.logger.info(f"🧹 Limpiados {len(inactive_users)} usuarios inactivos")
        
        return {
            'cleaned_users': len(inactive_users),
            'remaining_users': len(self.user_activities)
        }
    
    def reset_stats(self) -> bool:
        """Reinicia todas las estadísticas (usar con cuidado)"""
        try:
            self.user_activities.clear()
            self.global_stats = GlobalStats(
                uptime_start=datetime.now(),
                last_reset=datetime.now()
            )
            
            if self.persist_to_file:
                self.save_to_file()
            
            self.logger.info("🔄 Estadísticas reiniciadas completamente")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error reiniciando estadísticas: {e}")
            return False


# Instancia global de estadísticas
user_stats = UserStats()