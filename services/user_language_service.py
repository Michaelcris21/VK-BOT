"""
services/user_language_service.py
Servicio de identificación y perfilado de idioma por participante
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional
from datetime import datetime
import json
from pathlib import Path

from config import get_service_logger


@dataclass
class UserLanguageProfile:
    """Perfil lingüístico de un participante"""
    user_id: int
    peer_id: int                              # ID del chat (grupo/privado)
    display_name: str = ""                    # Nombre visible del usuario
    primary_language: Optional[str] = None    # Idioma principal configurado manualmente
    gender: Optional[str] = None              # Género del usuario: "male" o "female"
    custom_flag: Optional[str] = None         # Bandera personalizada elegida por el usuario
    language_counts: Dict[str, int] = field(default_factory=dict)  # Historial estadístico
    total_messages: int = 0                   # Total de mensajes registrados
    confidence: float = 0.0                   # Confianza (legacy, se mantiene por compatibilidad)
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None

    def is_fully_configured(self) -> bool:
        """Verifica si el usuario ha configurado idioma Y género"""
        return self.primary_language is not None and self.gender is not None

    def register_message(self):
        """Registra un mensaje (solo estadísticas, NO modifica el idioma)"""
        self.total_messages += 1
        self.last_seen = datetime.now().isoformat()
        if not self.first_seen:
            self.first_seen = self.last_seen

    def get_target_language(self) -> Optional[str]:
        """
        Determina a qué idioma traducir para ESTE usuario.
        El usuario necesita recibir las traducciones en su propio idioma principal.
        """
        return self.primary_language

    def get_flag(self) -> str:
        """Obtiene la bandera del usuario (la elegida o la por defecto de su idioma)"""
        if self.custom_flag:
            return self.custom_flag
        defaults = {
            "es": "🌐",
            "ru": "🇷🇺",
            "uk": "🇺🇦",
            "bg": "🇧🇬",
            "pl": "🇵🇱",
            "cs": "🇨🇿",
            "sr": "🇷🇸",
            "sk": "🇸🇰",
            "hr": "🇭🇷",
            "sl": "🇸🇮"
        }
        return defaults.get(self.primary_language, "🌐")


class UserLanguageTracker:
    """Gestiona los perfiles lingüísticos de todos los participantes"""

    def __init__(self, profiles_file: str = "user_language_profiles.json"):
        self.logger = get_service_logger("lang_tracker")
        self.profiles_file = Path(profiles_file)
        # Clave: (peer_id, user_id) → perfil por chat+usuario
        self.profiles: Dict[str, UserLanguageProfile] = {}
        self._load_profiles()
        self.logger.info("🧠 Tracker de idiomas por participante inicializado")

    def _profile_key(self, peer_id: int, user_id: int) -> str:
        return f"{peer_id}:{user_id}"

    def get_profile(self, peer_id: int, user_id: int) -> Optional[UserLanguageProfile]:
        """Obtiene el perfil de un usuario en un chat específico"""
        return self.profiles.get(self._profile_key(peer_id, user_id))

    def register_message(self, peer_id: int, user_id: int,
                          display_name: str) -> UserLanguageProfile:
        """Registra un mensaje y actualiza/crea el perfil del usuario (solo estadísticas)"""
        key = self._profile_key(peer_id, user_id)

        if key not in self.profiles:
            self.profiles[key] = UserLanguageProfile(
                user_id=user_id,
                peer_id=peer_id,
                display_name=display_name
            )
            self.logger.info(
                f"👤 Nuevo participante registrado: {display_name} "
                f"(user={user_id}, chat={peer_id})"
            )

        profile = self.profiles[key]
        profile.display_name = display_name
        profile.register_message()

        # Auto-guardar cada 10 mensajes
        if profile.total_messages % 10 == 0:
            self._save_profiles()

        return profile

    def set_user_language(self, peer_id: int, user_id: int,
                          display_name: str, lang_code: str) -> UserLanguageProfile:
        """Establece manualmente el idioma de un usuario y lo persiste"""
        key = self._profile_key(peer_id, user_id)
        if key not in self.profiles:
            self.profiles[key] = UserLanguageProfile(
                user_id=user_id,
                peer_id=peer_id,
                display_name=display_name
            )
        profile = self.profiles[key]
        profile.display_name = display_name
        profile.primary_language = lang_code
        profile.confidence = 1.0
        # Darle peso de mensajes simulados para fijarlo
        profile.total_messages = max(profile.total_messages, 1)
        profile.language_counts[lang_code] = profile.language_counts.get(lang_code, 0) + 10
        
        self.logger.info(f"🧠 Idioma establecido manualmente para {display_name}: {lang_code}")
        self._save_profiles()
        return profile

    def set_user_flag(self, peer_id: int, user_id: int,
                      display_name: str, flag: str) -> UserLanguageProfile:
        """Establece una bandera o emoji personalizado para el usuario y lo persiste"""
        key = self._profile_key(peer_id, user_id)
        if key not in self.profiles:
            self.profiles[key] = UserLanguageProfile(
                user_id=user_id,
                peer_id=peer_id,
                display_name=display_name
            )
        profile = self.profiles[key]
        profile.display_name = display_name
        profile.custom_flag = flag
        self.logger.info(f"🧠 Bandera personalizada para {display_name} establecida como: {flag}")
        self._save_profiles()
        return profile

    def set_user_gender(self, peer_id: int, user_id: int,
                        display_name: str, gender: str) -> UserLanguageProfile:
        """Establece el género del usuario y lo persiste"""
        key = self._profile_key(peer_id, user_id)
        if key not in self.profiles:
            self.profiles[key] = UserLanguageProfile(
                user_id=user_id,
                peer_id=peer_id,
                display_name=display_name
            )
        profile = self.profiles[key]
        profile.display_name = display_name
        profile.gender = gender
        self.logger.info(f"🧠 Género establecido para {display_name}: {gender}")
        self._save_profiles()
        return profile

    def get_translation_target_for_user(self, peer_id: int, user_id: int) -> Optional[str]:
        """
        Devuelve el idioma al que se debe traducir un mensaje
        para que ESTE usuario lo entienda.

        Returns:
            "es", "ru", o None si no hay suficiente info
        """
        profile = self.get_profile(peer_id, user_id)
        if not profile:
            return None
        return profile.get_target_language()

    def should_translate_for_user(self, peer_id: int, user_id: int,
                                  message_lang: str) -> bool:
        """
        Determina si un mensaje en cierto idioma necesita traducción
        para un usuario específico.
        Solo traduce si el usuario está completamente configurado y
        el mensaje está en un idioma diferente al suyo.
        """
        profile = self.get_profile(peer_id, user_id)
        if not profile or not profile.is_fully_configured():
            return False  # Sin configurar, NO traducir

        return message_lang != profile.primary_language

    def get_chat_participants(self, peer_id: int) -> list:
        """Lista todos los participantes registrados de un chat"""
        return [
            profile for key, profile in self.profiles.items()
            if profile.peer_id == peer_id
        ]

    def get_chat_language_summary(self, peer_id: int) -> Dict[str, list]:
        """
        Resumen de idiomas en un chat agrupado por idioma.
        Útil para el comando /idiomas_grupo.

        Returns:
            {"ru": ["Иван", "Олег"], "es": ["Carlos", "María"]}
        """
        participants = self.get_chat_participants(peer_id)
        summary: Dict[str, list] = {}

        for p in participants:
            if p.primary_language and p.confidence >= 0.5:
                lang = p.primary_language
                if lang not in summary:
                    summary[lang] = []
                summary[lang].append(p.display_name)

        return summary

    # === PERSISTENCIA ===

    def _save_profiles(self):
        """Guarda perfiles a archivo JSON"""
        try:
            data = {
                key: asdict(profile)
                for key, profile in self.profiles.items()
            }
            with open(self.profiles_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"❌ Error guardando perfiles: {e}")

    def _load_profiles(self):
        """Carga perfiles desde archivo JSON"""
        if not self.profiles_file.exists():
            return
        try:
            with open(self.profiles_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for key, profile_data in data.items():
                self.profiles[key] = UserLanguageProfile(**profile_data)
            self.logger.info(f"📂 Cargados {len(self.profiles)} perfiles lingüísticos")
        except Exception as e:
            self.logger.warning(f"⚠️ Error cargando perfiles: {e}")


# Instancia global
language_tracker = UserLanguageTracker()
