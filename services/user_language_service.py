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
    primary_language: Optional[str] = None    # Idioma principal detectado (ej: "ru")
    custom_flag: Optional[str] = None         # Bandera personalizada elegida por el usuario
    language_counts: Dict[str, int] = field(default_factory=dict)  # Historial: {"ru": 45, "es": 2}
    total_messages: int = 0                   # Total de mensajes analizados
    confidence: float = 0.0                   # Confianza en el idioma principal (0.0 - 1.0)
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None

    def register_message(self, detected_lang: str):
        """Registra un mensaje y actualiza el perfil"""
        self.total_messages += 1
        self.language_counts[detected_lang] = self.language_counts.get(detected_lang, 0) + 1
        self.last_seen = datetime.now().isoformat()
        if not self.first_seen:
            self.first_seen = self.last_seen

        # Recalcular idioma principal
        if self.language_counts:
            most_common = max(self.language_counts, key=self.language_counts.get)
            count = self.language_counts[most_common]
            self.primary_language = most_common
            self.confidence = count / self.total_messages

    def get_target_language(self) -> Optional[str]:
        """
        Determina a qué idioma traducir para ESTE usuario.
        El usuario necesita recibir las traducciones en su propio idioma principal.
        """
        if not self.primary_language or self.confidence < 0.5:
            return None
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


def get_native_language_from_profile(user_info: dict) -> Optional[str]:
    """
    Intenta extraer el idioma nativo del usuario a partir de su perfil de VK
    utilizando los campos de país y configuración personal de idiomas.
    """
    # 1. Analizar 'personal' -> 'langs'
    personal = user_info.get("personal", {}) or {}
    langs = personal.get("langs", [])
    if langs:
        for lang in langs:
            lang_lower = str(lang).lower()
            if "бълг" in lang_lower or "bulg" in lang_lower:
                return "bg"
            if "укр" in lang_lower or "ukra" in lang_lower:
                return "uk"
            if "рус" in lang_lower or "russ" in lang_lower:
                return "ru"
            if "исп" in lang_lower or "span" in lang_lower or "espan" in lang_lower:
                return "es"
            if "пол" in lang_lower or "pola" in lang_lower or "poly" in lang_lower:
                return "pl"
            if "чеш" in lang_lower or "czec" in lang_lower:
                return "cs"
            if "слов" in lang_lower or "slov" in lang_lower:
                if "слова" in lang_lower or "slova" in lang_lower:
                    return "sk"
                if "слове" in lang_lower or "slove" in lang_lower:
                    return "sl"
            if "серб" in lang_lower or "serb" in lang_lower:
                return "sr"
            if "хорв" in lang_lower or "croa" in lang_lower:
                return "hr"

    # 2. Analizar 'country'
    country = user_info.get("country", {}) or {}
    country_title = str(country.get("title", "")).lower()
    if country_title:
        if "болг" in country_title or "bulg" in country_title:
            return "bg"
        if "укр" in country_title or "ukra" in country_title:
            return "uk"
        if "росс" in country_title or "russi" in country_title or "белар" in country_title or "belar" in country_title or "казах" in country_title or "kazak" in country_title:
            return "ru"
        if "испа" in country_title or "spain" in country_title or "mexi" in country_title or "mexc" in country_title or "arge" in country_title or "colo" in country_title or "peru" in country_title or "venez" in country_title or "chile" in country_title:
            return "es"
        if "поль" in country_title or "polan" in country_title:
            return "pl"
        if "чех" in country_title or "czec" in country_title:
            return "cs"
        if "слов" in country_title or "slov" in country_title:
            if "слова" in country_title:
                return "sk"
            if "слове" in country_title:
                return "sl"
        if "серб" in country_title or "serbi" in country_title:
            return "sr"
        if "хорв" in country_title or "croat" in country_title:
            return "hr"
            
    return None


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
                          display_name: str, detected_lang: str,
                          profile_native_lang: Optional[str] = None) -> UserLanguageProfile:
        """Registra un mensaje y actualiza/crea el perfil del usuario"""
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
        profile.display_name = display_name  # Actualizar nombre si cambió
        
        # Pre-configurar el idioma nativo si viene del perfil de VK
        if profile_native_lang and (not profile.primary_language or profile.total_messages < 3):
            if profile.primary_language != profile_native_lang:
                profile.primary_language = profile_native_lang
                profile.confidence = 1.0
                profile.language_counts[profile_native_lang] = profile.language_counts.get(profile_native_lang, 0) + 1
                self.logger.info(f"🧠 Inicializado idioma nativo de {display_name} como '{profile_native_lang}' desde perfil de VK")

        profile.register_message(detected_lang)

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

        Ejemplo: Si el usuario habla 'ru' y el mensaje está en 'ru',
                 NO necesita traducción para él.
        """
        profile = self.get_profile(peer_id, user_id)
        if not profile or profile.confidence < 0.5:
            return True  # Sin datos, traducir por defecto

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
