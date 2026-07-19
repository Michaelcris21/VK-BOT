"""
Sistema de Cache Centralizado
Manejo de múltiples tipos de cache con limpieza automática y estadísticas
"""

import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple, Union
from dataclasses import dataclass, asdict
from abc import ABC, abstractmethod

from config import settings, get_service_logger


@dataclass
class CacheEntry:
    """Entrada individual de cache"""
    key: str
    value: Any
    created_at: datetime
    expires_at: Optional[datetime]
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    size_bytes: int = 0
    
    def is_expired(self) -> bool:
        """Verifica si la entrada ha expirado"""
        if not self.expires_at:
            return False
        return datetime.now() > self.expires_at
    
    def access(self) -> None:
        """Registra acceso a la entrada"""
        self.access_count += 1
        self.last_accessed = datetime.now()


@dataclass
class CacheStats:
    """Estadísticas de cache"""
    name: str
    total_entries: int
    active_entries: int
    expired_entries: int
    hit_count: int
    miss_count: int
    hit_rate_percent: float
    total_size_bytes: int
    average_entry_size: float
    oldest_entry: Optional[datetime]
    newest_entry: Optional[datetime]
    last_cleanup: Optional[datetime]


class CacheBackend(ABC):
    """Interface para backends de cache"""
    
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        pass
    
    @abstractmethod
    def set(self, key: str, value: Any, expires_in: Optional[int] = None) -> bool:
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        pass
    
    @abstractmethod
    def clear(self) -> int:
        pass
    
    @abstractmethod
    def keys(self) -> List[str]:
        pass


class MemoryCache(CacheBackend):
    """Cache en memoria con gestión avanzada"""
    
    def __init__(self, name: str, max_size: int = 1000, default_ttl: int = 3600):
        self.name = name
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.entries: Dict[str, CacheEntry] = {}
        self.hit_count = 0
        self.miss_count = 0
        self.last_cleanup = datetime.now()
        
        self.logger = get_service_logger(f"cache.{name}")
        self.logger.debug(f"🗄️ Cache '{name}' inicializado (max: {max_size}, ttl: {default_ttl}s)")
    
    def get(self, key: str) -> Optional[Any]:
        """Obtiene valor del cache"""
        if key not in self.entries:
            self.miss_count += 1
            return None
        
        entry = self.entries[key]
        
        if entry.is_expired():
            del self.entries[key]
            self.miss_count += 1
            return None
        
        entry.access()
        self.hit_count += 1
        return entry.value
    
    def set(self, key: str, value: Any, expires_in: Optional[int] = None) -> bool:
        """Guarda valor en cache"""
        try:
            # Limpiar si estamos en el límite
            if len(self.entries) >= self.max_size:
                self._evict_entries(self.max_size // 4)  # Limpiar 25%
            
            # Calcular expiración
            expires_at = None
            if expires_in:
                expires_at = datetime.now() + timedelta(seconds=expires_in)
            elif self.default_ttl > 0:
                expires_at = datetime.now() + timedelta(seconds=self.default_ttl)
            
            # Calcular tamaño aproximado
            size_bytes = self._estimate_size(value)
            
            # Crear entrada
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=datetime.now(),
                expires_at=expires_at,
                size_bytes=size_bytes
            )
            
            self.entries[key] = entry
            self.logger.debug(f"💾 Guardado en cache: {key} ({size_bytes} bytes)")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error guardando en cache: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Elimina entrada del cache"""
        if key in self.entries:
            del self.entries[key]
            self.logger.debug(f"🗑️ Eliminado del cache: {key}")
            return True
        return False
    
    def clear(self) -> int:
        """Limpia todo el cache"""
        count = len(self.entries)
        self.entries.clear()
        self.hit_count = 0
        self.miss_count = 0
        self.logger.info(f"🧹 Cache '{self.name}' limpiado ({count} entradas)")
        return count
    
    def keys(self) -> List[str]:
        """Retorna todas las keys del cache"""
        return list(self.entries.keys())
    
    def cleanup_expired(self) -> int:
        """Limpia entradas expiradas"""
        now = datetime.now()
        expired_keys = [
            key for key, entry in self.entries.items()
            if entry.is_expired()
        ]
        
        for key in expired_keys:
            del self.entries[key]
        
        self.last_cleanup = now
        
        if expired_keys:
            self.logger.debug(f"🧹 Limpiadas {len(expired_keys)} entradas expiradas")
        
        return len(expired_keys)
    
    def _evict_entries(self, count: int) -> int:
        """Elimina entradas usando estrategia LRU"""
        if not self.entries:
            return 0
        
        # Ordenar por último acceso (LRU)
        sorted_entries = sorted(
            self.entries.items(),
            key=lambda x: x[1].last_accessed or x[1].created_at
        )
        
        evicted = 0
        for key, _ in sorted_entries[:count]:
            if key in self.entries:
                del self.entries[key]
                evicted += 1
        
        self.logger.debug(f"♻️ Evitadas {evicted} entradas por límite de tamaño")
        return evicted
    
    def _estimate_size(self, value: Any) -> int:
        """Estima el tamaño en bytes de un valor"""
        try:
            if isinstance(value, str):
                return len(value.encode('utf-8'))
            elif isinstance(value, (int, float, bool)):
                return 8
            elif isinstance(value, (list, tuple, dict)):
                return len(str(value).encode('utf-8'))
            else:
                return len(str(value).encode('utf-8'))
        except:
            return 100  # Estimación por defecto
    
    def get_stats(self) -> CacheStats:
        """Obtiene estadísticas del cache"""
        active_entries = [e for e in self.entries.values() if not e.is_expired()]
        expired_entries = len(self.entries) - len(active_entries)
        
        total_accesses = self.hit_count + self.miss_count
        hit_rate = (self.hit_count / max(total_accesses, 1)) * 100
        
        total_size = sum(entry.size_bytes for entry in self.entries.values())
        avg_size = total_size / max(len(self.entries), 1)
        
        entry_dates = [e.created_at for e in self.entries.values() if e.created_at]
        oldest = min(entry_dates) if entry_dates else None
        newest = max(entry_dates) if entry_dates else None
        
        return CacheStats(
            name=self.name,
            total_entries=len(self.entries),
            active_entries=len(active_entries),
            expired_entries=expired_entries,
            hit_count=self.hit_count,
            miss_count=self.miss_count,
            hit_rate_percent=round(hit_rate, 2),
            total_size_bytes=total_size,
            average_entry_size=round(avg_size, 2),
            oldest_entry=oldest,
            newest_entry=newest,
            last_cleanup=self.last_cleanup
        )


class FileCache(CacheBackend):
    """Cache persistente en archivo"""
    
    def __init__(self, name: str, cache_dir: str = "cache", max_files: int = 1000):
        self.name = name
        self.cache_dir = Path(cache_dir) / name
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_files = max_files
        
        self.logger = get_service_logger(f"file_cache.{name}")
        self.logger.debug(f"📁 Cache de archivos '{name}' inicializado en {self.cache_dir}")
    
    def get(self, key: str) -> Optional[Any]:
        """Obtiene valor del cache de archivos"""
        file_path = self._get_file_path(key)
        
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Verificar expiración
            if data.get('expires_at'):
                expires_at = datetime.fromisoformat(data['expires_at'])
                if datetime.now() > expires_at:
                    file_path.unlink()  # Eliminar archivo expirado
                    return None
            
            return data.get('value')
            
        except Exception as e:
            self.logger.warning(f"❌ Error leyendo cache de archivo: {e}")
            return None
    
    def set(self, key: str, value: Any, expires_in: Optional[int] = None) -> bool:
        """Guarda valor en cache de archivos"""
        try:
            # Limpiar si hay muchos archivos
            self._cleanup_if_needed()
            
            file_path = self._get_file_path(key)
            
            # Preparar datos
            data = {
                'key': key,
                'value': value,
                'created_at': datetime.now().isoformat(),
                'expires_at': (datetime.now() + timedelta(seconds=expires_in)).isoformat() if expires_in else None
            }
            
            # Guardar archivo
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error guardando en cache de archivo: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Elimina archivo del cache"""
        file_path = self._get_file_path(key)
        if file_path.exists():
            file_path.unlink()
            return True
        return False
    
    def clear(self) -> int:
        """Limpia todos los archivos del cache"""
        count = 0
        for file_path in self.cache_dir.glob("*.json"):
            file_path.unlink()
            count += 1
        
        self.logger.info(f"🧹 Cache de archivos '{self.name}' limpiado ({count} archivos)")
        return count
    
    def keys(self) -> List[str]:
        """Retorna todas las keys del cache"""
        keys = []
        for file_path in self.cache_dir.glob("*.json"):
            # El nombre del archivo es el hash de la key
            keys.append(file_path.stem)
        return keys
    
    def _get_file_path(self, key: str) -> Path:
        """Genera path del archivo para una key"""
        # Usar hash para evitar problemas con caracteres especiales
        key_hash = hashlib.md5(key.encode('utf-8')).hexdigest()
        return self.cache_dir / f"{key_hash}.json"
    
    def _cleanup_if_needed(self) -> None:
        """Limpia archivos antiguos si hay demasiados"""
        files = list(self.cache_dir.glob("*.json"))
        
        if len(files) >= self.max_files:
            # Ordenar por fecha de modificación y eliminar los más antiguos
            files.sort(key=lambda f: f.stat().st_mtime)
            files_to_remove = files[:len(files) - self.max_files + 100]  # Dejar espacio
            
            for file_path in files_to_remove:
                file_path.unlink()
            
            self.logger.debug(f"🧹 Limpiados {len(files_to_remove)} archivos antiguos")


class CacheManager:
    """Gestor central de múltiples caches"""
    
    def __init__(self):
        self.caches: Dict[str, CacheBackend] = {}
        self.logger = get_service_logger("cache_manager")
        
        self.logger.info("🗄️ Gestor de cache inicializado")
    
    def create_memory_cache(self, name: str, max_size: int = 1000, default_ttl: int = 3600) -> MemoryCache:
        """Crea un cache en memoria"""
        cache = MemoryCache(name, max_size, default_ttl)
        self.caches[name] = cache
        self.logger.info(f"✅ Cache en memoria '{name}' creado")
        return cache
    
    def create_file_cache(self, name: str, cache_dir: str = "cache", max_files: int = 1000) -> FileCache:
        """Crea un cache en archivos"""
        cache = FileCache(name, cache_dir, max_files)
        self.caches[name] = cache
        self.logger.info(f"✅ Cache de archivos '{name}' creado")
        return cache
    
    def get_cache(self, name: str) -> Optional[CacheBackend]:
        """Obtiene un cache por nombre"""
        return self.caches.get(name)
    
    def get_or_create_memory_cache(self, name: str, max_size: int = 1000, default_ttl: int = 3600) -> MemoryCache:
        """Obtiene un cache existente o crea uno nuevo en memoria"""
        cache = self.get_cache(name)
        if cache and isinstance(cache, MemoryCache):
            return cache
        return self.create_memory_cache(name, max_size, default_ttl)
    
    def get_or_create_file_cache(self, name: str, cache_dir: str = "cache", max_files: int = 1000) -> FileCache:
        """Obtiene un cache existente o crea uno nuevo en archivos"""
        cache = self.get_cache(name)
        if cache and isinstance(cache, FileCache):
            return cache
        return self.create_file_cache(name, cache_dir, max_files)
    
    def remove_cache(self, name: str) -> bool:
        """Elimina un cache"""
        if name in self.caches:
            cache = self.caches[name]
            if hasattr(cache, 'clear'):
                cache.clear()
            del self.caches[name]
            self.logger.info(f"🗑️ Cache '{name}' eliminado")
            return True
        return False
    
    def clear_all_caches(self) -> int:
        """Limpia todos los caches"""
        total_cleared = 0
        for name, cache in self.caches.items():
            if hasattr(cache, 'clear'):
                cleared = cache.clear()
                total_cleared += cleared
        
        self.logger.info(f"🧹 Todos los caches limpiados ({total_cleared} entradas)")
        return total_cleared
    
    def cleanup_all_caches(self) -> int:
        """Limpia entradas expiradas de todos los caches"""
        total_cleaned = 0
        for name, cache in self.caches.items():
            if hasattr(cache, 'cleanup_expired'):
                cleaned = cache.cleanup_expired()
                total_cleaned += cleaned
        
        if total_cleaned > 0:
            self.logger.info(f"🧹 Limpieza automática completada ({total_cleaned} entradas)")
        
        return total_cleaned
    
    def get_all_stats(self) -> Dict[str, CacheStats]:
        """Obtiene estadísticas de todos los caches"""
        stats = {}
        for name, cache in self.caches.items():
            if hasattr(cache, 'get_stats'):
                stats[name] = cache.get_stats()
        return stats
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas globales de todos los caches"""
        all_stats = self.get_all_stats()
        
        if not all_stats:
            return {
                "total_caches": 0,
                "total_entries": 0,
                "total_hits": 0,
                "total_misses": 0,
                "average_hit_rate": 0.0,
                "total_size_bytes": 0
            }
        
        total_entries = sum(stats.total_entries for stats in all_stats.values())
        total_hits = sum(stats.hit_count for stats in all_stats.values())
        total_misses = sum(stats.miss_count for stats in all_stats.values())
        total_size = sum(stats.total_size_bytes for stats in all_stats.values())
        
        total_accesses = total_hits + total_misses
        avg_hit_rate = (total_hits / max(total_accesses, 1)) * 100
        
        return {
            "total_caches": len(all_stats),
            "total_entries": total_entries,
            "total_hits": total_hits,
            "total_misses": total_misses,
            "average_hit_rate": round(avg_hit_rate, 2),
            "total_size_bytes": total_size,
            "caches": {name: asdict(stats) for name, stats in all_stats.items()}
        }
    
    def list_caches(self) -> List[str]:
        """Lista todos los caches disponibles"""
        return list(self.caches.keys())
    
    def health_check(self) -> Dict[str, Any]:
        """Verifica la salud de todos los caches"""
        health = {
            "status": "healthy",
            "caches": {},
            "issues": []
        }
        
        for name, cache in self.caches.items():
            cache_health = {"status": "healthy", "issues": []}
            
            try:
                # Verificar si el cache responde
                if hasattr(cache, 'keys'):
                    keys = cache.keys()
                    cache_health["key_count"] = len(keys)
                
                # Verificar estadísticas si están disponibles
                if hasattr(cache, 'get_stats'):
                    stats = cache.get_stats()
                    cache_health["stats"] = asdict(stats)
                    
                    # Verificar hit rate muy bajo
                    if stats.hit_rate_percent < 10 and stats.hit_count + stats.miss_count > 10:
                        cache_health["issues"].append("Low hit rate")
                        cache_health["status"] = "warning"
                    
                    # Verificar muchas entradas expiradas
                    if stats.expired_entries > stats.active_entries:
                        cache_health["issues"].append("Many expired entries")
                        cache_health["status"] = "warning"
                
            except Exception as e:
                cache_health["status"] = "error"
                cache_health["issues"].append(f"Error: {str(e)}")
                health["status"] = "degraded"
            
            health["caches"][name] = cache_health
            health["issues"].extend([f"{name}: {issue}" for issue in cache_health["issues"]])
        
        return health


# Instancia global del gestor de cache
cache_manager = CacheManager()

# Funciones de conveniencia para uso directo
def get_cache(name: str) -> Optional[CacheBackend]:
    """Obtiene un cache por nombre"""
    return cache_manager.get_cache(name)

def create_memory_cache(name: str, max_size: int = 1000, default_ttl: int = 3600) -> MemoryCache:
    """Crea un cache en memoria"""
    return cache_manager.create_memory_cache(name, max_size, default_ttl)

def create_file_cache(name: str, cache_dir: str = "cache", max_files: int = 1000) -> FileCache:
    """Crea un cache en archivos"""
    return cache_manager.create_file_cache(name, cache_dir, max_files)

def get_or_create_memory_cache(name: str, max_size: int = 1000, default_ttl: int = 3600) -> MemoryCache:
    """Obtiene un cache existente o crea uno nuevo en memoria"""
    return cache_manager.get_or_create_memory_cache(name, max_size, default_ttl)

def get_or_create_file_cache(name: str, cache_dir: str = "cache", max_files: int = 1000) -> FileCache:
    """Obtiene un cache existente o crea uno nuevo en archivos"""
    return cache_manager.get_or_create_file_cache(name, cache_dir, max_files)

def clear_all_caches() -> int:
    """Limpia todos los caches"""
    return cache_manager.clear_all_caches()

def cleanup_all_caches() -> int:
    """Limpia entradas expiradas de todos los caches"""
    return cache_manager.cleanup_all_caches()

def get_cache_stats() -> Dict[str, Any]:
    """Obtiene estadísticas globales de todos los caches"""
    return cache_manager.get_global_stats()

def health_check() -> Dict[str, Any]:
    """Verifica la salud de todos los caches"""
    return cache_manager.health_check()


# Caches predefinidos para el bot
def initialize_bot_caches():
    """Inicializa los caches predefinidos del bot"""
    logger = get_service_logger("cache_init")
    
    try:
        # Cache de traducciones
        create_memory_cache(
            name="translations",
            max_size=settings.Translation.CACHE_MAX_SIZE,
            default_ttl=settings.Translation.CACHE_EXPIRE_HOURS * 3600
        )
        
        # Cache de respuestas de IA
        create_memory_cache(
            name="ai_responses",
            max_size=100,
            default_ttl=6 * 3600  # 6 horas
        )
        
        # Cache de metadatos de videos
        create_memory_cache(
            name="video_metadata",
            max_size=50,
            default_ttl=2 * 3600  # 2 horas
        )
        
        # Cache de intenciones
        create_memory_cache(
            name="intents",
            max_size=200,
            default_ttl=24 * 3600  # 24 horas
        )
        
        # Cache persistente de estadísticas
        create_file_cache(
            name="stats",
            cache_dir="cache",
            max_files=100
        )
        
        logger.info("✅ Caches del bot inicializados correctamente")
        
    except Exception as e:
        logger.error(f"❌ Error inicializando caches del bot: {e}")


# Inicializar caches al importar el módulo
initialize_bot_caches()
bot_caches = cache_manager