#services/translation_service.py
"""
Servicio de Traducción Inteligente
Maneja toda la lógica de traducción con cache, detección de idiomas y optimizaciones
"""

import re
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

import google.generativeai as genai
from langdetect import detect as lang_detect_func, LangDetectException

from config import settings, get_service_logger
from services.ai_service import ai_service, AIRequest


class TranslationService:
    """Servicio especializado en traducción de texto"""
    
    def __init__(self):
        self.logger = get_service_logger("translation")
        
        # Configurar modelo de IA
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel(settings.AI.MODEL_TEXT)
        self.generation_config = genai.types.GenerationConfig(
            temperature=settings.AI.TEMPERATURE_TRANSLATION,
            max_output_tokens=settings.AI.MAX_OUTPUT_TOKENS
        )
        
        # Cache de traducciones
        self.translation_cache: Dict[int, Tuple[str, datetime]] = {}

        self.slavic_languages = settings.Translation.SLAVIC_LANGUAGES
        
        self.logger.info("🌐 Servicio de traducción inicializado")

    async def translate_text(self, text: str, source_lang: Optional[str] = None, user_id: Optional[int] = None) -> str:
        """
        Traduce texto con lógica inteligente de idiomas, ahora usando el robusto 'chat mode' de la IA.
        """
        try:
            self.logger.info(f"🔄 Iniciando traducción: '{text[:30]}...'", user_id=user_id)
            
            self._clean_cache()
            
            cache_key = hash(text.lower().strip())
            if cache_key in self.translation_cache:
                cached_result, _ = self.translation_cache[cache_key]
                self.logger.info("💾 Usando traducción desde cache", user_id=user_id)
                return cached_result
            
            if not self._is_valid_text(text):
                return "❌ No hay texto válido para traducir."
            
            if not source_lang:
                source_lang = self._detect_language_safe(text)
            
            self.logger.info(f"🌍 Idioma detectado: {source_lang}", user_id=user_id)
            
            clean_text, urls = self._extract_urls_with_placeholders(text)
            
            # Determinar el idioma de destino
            target_language = await self.get_target_language(source_lang)
            
            # --- INICIO DE LA CORRECCIÓN CLAVE: Nueva forma de llamar a la IA ---
            
            # Usamos la nueva función especializada del ai_service que es más robusta
            translated_text = await ai_service.generate_translation(clean_text, target_language)
            
            if not translated_text:
                # Si la función robusta falla, devolvemos un error claro.
                return "❌ No se pudo generar la traducción (bloqueada por la IA)."

            # --- FIN DE LA CORRECCIÓN CLAVE ---
            
            if self._is_same_language(translated_text, text):
                return "🤔 El texto parece estar ya en el idioma de destino."
            
            final_text = self._restore_urls(translated_text, urls)
            
            self.translation_cache[cache_key] = (final_text, datetime.now())
            
            self.logger.info("✅ Traducción completada exitosamente", user_id=user_id)
            return final_text
            
        except asyncio.TimeoutError:
            self.logger.warning("⏱️ Timeout en traducción", user_id=user_id)
            return "⏱️ La traducción está tardando demasiado. Intenta con un texto más corto."
        
        except Exception as e:
            self.logger.error("❌ Error en traducción", error=e, user_id=user_id)
            return f"❌ Error técnico al traducir: {str(e)[:100]}..."

    # Asegúrate de que tu `translate_to_target` también use la nueva lógica
    async def translate_to_target(self, text: str, target_language: str) -> Optional[str]:
        """Traduce texto a un idioma de destino específico."""
        try:
            # Reutilizamos la lógica robusta del ai_service
            return await ai_service.generate_translation(text, target_language)
        except Exception as e:
            self.logger.error(f"❌ Error en traducción a objetivo '{target_language}'", error=e)
            return None
    def _build_translation_prompt(self, text: str, source_lang: str) -> str:
        """Construye el prompt de traducción según el idioma detectado"""
        
        if source_lang in settings.Translation.SLAVIC_LANGUAGES:
            # Idioma eslavo → Español
            target_lang = "español"
            source_name = settings.Translation.SLAVIC_LANGUAGES[source_lang]
            
            prompt = f"""Traduce el siguiente texto del {source_name.upper()} al ESPAÑOL de manera fluida y natural.

INSTRUCCIONES IMPORTANTES:
- Haz una traducción completa y precisa
- NO repitas el texto original
- NO incluyas explicaciones adicionales
- Responde SOLO con la traducción en español
- Mantén el formato original (emojis, paréntesis, puntuación)
- Mantén el tono y estilo del original
- Si hay jerga o expresiones coloquiales, adapta al español natural
- Preserva los placeholders {settings.Translation.LINK_PLACEHOLDER} exactamente como están

Texto en {source_name}:
{text}"""
        
        else:
            # Otro idioma → Ruso
            target_lang = "ruso"
            
            prompt = f"""Traduce el siguiente texto al RUSO de manera fluida y natural.

INSTRUCCIONES IMPORTANTES:
- Haz una traducción completa y precisa
- NO repitas el texto original
- NO incluyas explicaciones adicionales
- Responde SOLO con la traducción en ruso
- Mantén el formato original (emojis, paréntesis, puntuación)
- Mantén el tono y estilo del original
- Si hay jerga o expresiones coloquiales, adapta al ruso natural
- Preserva los placeholders {settings.Translation.LINK_PLACEHOLDER} exactamente como están

Texto a traducir:
{text}"""
        
        return prompt
    
    def _detect_language_safe(self, text: str) -> str:
        """Detecta idioma de forma segura con fallbacks"""
        try:
            # Limpiar texto para mejor detección
            clean_text = re.sub(r'[^\w\s]', ' ', text)
            clean_text = ' '.join(clean_text.split())
            
            if len(clean_text) < 3:
                self.logger.warning("Texto muy corto para detección de idioma")
                return 'en'
            
            detected = lang_detect_func(clean_text)
            self.logger.debug(f"Idioma detectado por langdetect: {detected}")
            return detected
            
        except (LangDetectException, Exception) as e:
            self.logger.warning(f"Error detectando idioma: {e}")
            return 'en'  # Default a inglés
    
    def _extract_urls_with_placeholders(self, text: str) -> Tuple[str, List[str]]:
        """Extrae URLs y las reemplaza con placeholders"""
        urls = []
        url_pattern = re.compile(settings.Patterns.URL_PATTERN)
        
        def replace_url(match):
            urls.append(match.group(0))
            return settings.Translation.LINK_PLACEHOLDER
        
        text_with_placeholders = url_pattern.sub(replace_url, text)
        
        if urls:
            self.logger.debug(f"Extraídas {len(urls)} URLs del texto")
        
        return text_with_placeholders, urls
    
    def _restore_urls(self, text: str, urls: List[str]) -> str:
        """Restaura las URLs en el texto traducido"""
        for url in urls:
            if settings.Translation.LINK_PLACEHOLDER in text:
                text = text.replace(settings.Translation.LINK_PLACEHOLDER, url, 1)
        
        if urls:
            self.logger.debug(f"Restauradas {len(urls)} URLs en el texto traducido")
        
        return text
    
    def _is_valid_text(self, text: str) -> bool:
        """Verifica si el texto es válido para traducción"""
        if not text or not text.strip():
            return False
        
        # Debe tener al menos algún carácter alfabético
        if not any(c.isalpha() for c in text):
            return False
        
        # Texto muy corto es problemático
        if len(text.strip()) < 2:
            return False
        
        return True
    
    def _is_same_language(self, translated: str, original: str) -> bool:
        """Verifica si la traducción es igual al original (mismo idioma)"""
        # Normalizar textos para comparación
        norm_translated = re.sub(r'\s+', ' ', translated.lower().strip())
        norm_original = re.sub(r'\s+', ' ', original.lower().strip())
        
        # Si son muy similares, probablemente mismo idioma
        return norm_translated == norm_original
    
    def _clean_cache(self) -> None:
        """Limpia el cache de traducciones antiguas"""
        current_time = datetime.now()
        expired_keys = [
            key for key, (_, timestamp) in self.translation_cache.items() 
            if current_time - timestamp > timedelta(hours=settings.Translation.CACHE_EXPIRE_HOURS)
        ]
        
        for key in expired_keys:
            del self.translation_cache[key]
        
        # Limitar tamaño del cache
        if len(self.translation_cache) > settings.Translation.CACHE_MAX_SIZE:
            oldest_keys = sorted(
                self.translation_cache.keys(), 
                key=lambda k: self.translation_cache[k][1]
            )[:len(self.translation_cache) - settings.Translation.CACHE_MAX_SIZE]
            
            for key in oldest_keys:
                del self.translation_cache[key]
        
        if expired_keys:
            self.logger.debug(f"🧹 Cache limpiado: {len(expired_keys)} entradas expiradas")
    
    # === MÉTODOS DE UTILIDAD ===
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Retorna estadísticas del cache"""
        return {
            'size': len(self.translation_cache),
            'max_size': settings.Translation.CACHE_MAX_SIZE,
            'usage_percent': (len(self.translation_cache) / settings.Translation.CACHE_MAX_SIZE) * 100
        }
    
    def clear_cache(self) -> None:
        """Limpia completamente el cache"""
        cache_size = len(self.translation_cache)
        self.translation_cache.clear()
        self.logger.info(f"🧹 Cache completamente limpiado ({cache_size} entradas)")
    
    def get_supported_languages(self) -> Dict[str, str]:
        """Retorna los idiomas eslavos soportados"""
        return settings.Translation.SLAVIC_LANGUAGES.copy()
    
    def is_slavic_language(self, lang_code: str) -> bool:
        """Verifica si un código de idioma es eslavo"""
        return lang_code in settings.Translation.SLAVIC_LANGUAGES
    
    def get_translation_direction(self, source_lang: str) -> Tuple[str, str]:
        """
        Determina la dirección de traducción
        
        Returns:
            Tupla (idioma_destino, nombre_idioma_origen)
        """
        if source_lang in settings.Translation.SLAVIC_LANGUAGES:
            return "español", settings.Translation.SLAVIC_LANGUAGES[source_lang]
        else:
            return "ruso", f"idioma {source_lang}"
    
    # === MÉTODOS PARA TESTING ===
    
    async def test_translation(self, text: str) -> Dict[str, Any]:
        """
        Método para testing que retorna información detallada
        
        Returns:
            Diccionario con información del proceso de traducción
        """
        start_time = datetime.now()
        
        # Detectar idioma
        detected_lang = self._detect_language_safe(text)
        target_lang, source_name = self.get_translation_direction(detected_lang)
        
        # Extraer URLs
        clean_text, urls = self._extract_urls_with_placeholders(text)
        
        # Traducir
        result = await self.translate_text(text)
        
        end_time = datetime.now()
        
        return {
            'original_text': text,
            'detected_language': detected_lang,
            'source_language_name': source_name,
            'target_language': target_lang,
            'clean_text': clean_text,
            'extracted_urls': urls,
            'translated_text': result,
            'processing_time_ms': (end_time - start_time).total_seconds() * 1000,
            'cache_stats': self.get_cache_stats(),
            'was_cached': hash(text.lower().strip()) in self.translation_cache
        }
    
# En la clase TranslationService, dentro de services/translation_service.py

    async def translate_to_target(self, text: str, target_language: str) -> str:
        """Traduce texto a un idioma de destino específico."""
        try:
            # Aquí va tu lógica para llamar a la API de traducción
            # (ej: Google Translate, Gemini, etc.) especificando el 'target_language'
            
            # Ejemplo simplificado con Gemini:
            prompt = f"Translate the following text to {target_language}. Respond ONLY with the translation.\n\nText: \"{text}\""
            
            # Suponiendo que tienes un cliente de IA genérico
            response = await ai_service.generate_text(AIRequest(prompt=prompt, temperature=0.1))

            if response.success:
                return response.content
            else:
                return f"Error al traducir a {target_language}"

        except Exception as e:
            self.logger.error(f"❌ Error en traducción a objetivo '{target_language}'", error=e)
            return f"No se pudo traducir a {target_language}."

    async def translate_to_target(self, text: str, target_language: str) -> Optional[str]:
        """
        Traduce texto a un idioma de destino específico de forma robusta,
        con reintentos y prompts alternativos.
        """
        self.logger.info(f"Traduciendo a '{target_language}': '{text[:30]}...'")
        
        # --- INICIO DE LA CORRECCIÓN A PRUEBA DE FALLOS ---

        # Intento 1: Prompt directo y simple
        prompt1 = f"Translate the following text to {target_language}. Respond ONLY with the full, complete translation, without any extra text or explanations.\n\nText: \"{text}\""
        
        request = AIRequest(prompt=prompt1, temperature=0.1)
        response = await ai_service.generate_text(request)

        # Si el primer intento funciona, genial.
        if response.success and response.content:
            return response.content
        
        self.logger.warning(f"Intento 1 de traducción falló (Reason: {response.error}). Reintentando con prompt alternativo...")

        # Intento 2: Prompt más contextual y menos restrictivo
        # A veces, darle más contexto ayuda a pasar los filtros de seguridad.
        prompt2 = f"""
        You are a translation expert. Your task is to translate a user's message.
        The user's message is: "{text}"
        Translate this message accurately into the language: {target_language}.
        Your response must ONLY be the translated text itself.
        """
        
        request = AIRequest(prompt=prompt2, temperature=0.2)
        response = await ai_service.generate_text(request)

        if response.success and response.content:
            self.logger.info("✅ Traducción exitosa en el segundo intento.")
            return response.content
        
        # Si ambos intentos fallan, nos rendimos.
        self.logger.error(f"❌ Traducción fallida después de 2 intentos. Último error: {response.error}")
        return None # Devolvemos None para indicar un fallo total.

    async def get_target_language(self, source_language: str) -> str:
        """
        Determina el idioma de destino basado en la lógica inteligente.
        Usa la lista de idiomas eslavos desde la configuración.
        """
        if source_language in self.slavic_languages:
            return 'es' # Español
        else:
            return 'ru' # Ruso


# Instancia global del servicio (opcional, para compatibilidad)
translation_service = TranslationService()