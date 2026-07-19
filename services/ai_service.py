#services/ai_service.py
"""
Servicio de IA - Integración con Gemini AI
Maneja todas las interacciones con modelos de IA de Google
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass
from enum import Enum

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from config import settings, get_service_logger
from langdetect import detect, LangDetectException


class AIModelType(Enum):
    """Tipos de modelos de IA disponibles"""
    TEXT = "text"
    VIDEO = "video"
    IMAGE = "image"
    MULTIMODAL = "multimodal"


@dataclass
class AIRequest:
    """Estructura para solicitudes de IA"""
    prompt: str
    model_type: AIModelType = AIModelType.TEXT
    max_tokens: int = 1000
    temperature: float = 0.7
    context: Optional[str] = None
    language: Optional[str] = None


@dataclass
class AIResponse:
    """Estructura para respuestas de IA"""
    content: str
    model_used: str
    tokens_used: int
    processing_time: float
    success: bool
    error: Optional[str] = None


class AIService:
    """Servicio principal de IA con Gemini"""
    
    def __init__(self):
        self.logger = get_service_logger("ai_service")
        
        # Configurar API
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        
        # Models disponibles con rotación automática
        self.models = {
            AIModelType.TEXT: settings.AI.MODEL_TEXT_ROTATION,
            AIModelType.VIDEO: settings.AI.MODEL_VIDEO_ROTATION,
            AIModelType.IMAGE: settings.AI.MODEL_TEXT_ROTATION,  # Usar la misma rotación
            AIModelType.MULTIMODAL: settings.AI.MODEL_TEXT_ROTATION
        }
        
        # Índice actual de modelo para cada tipo (para rotación)
        self.current_model_index = {
            AIModelType.TEXT: 0,
            AIModelType.VIDEO: 0,
            AIModelType.IMAGE: 0,
            AIModelType.MULTIMODAL: 0
        }
        
        # Configuración de seguridad
        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        # Cache de respuestas
        self.response_cache: Dict[str, AIResponse] = {}
        
        self.logger.info("🤖 Servicio de IA inicializado")
        self.logger.info(f"📋 Modelos disponibles: {', '.join(self.models[AIModelType.TEXT])}")
    
    async def generate_text(self, request: AIRequest) -> AIResponse:
        """Genera texto usando modelos de IA"""
        try:
            start_time = datetime.now()
            
            # Verificar cache
            cache_key = f"{request.prompt}_{request.model_type.value}_{request.temperature}"
            if cache_key in self.response_cache:
                cached_response = self.response_cache[cache_key]
                self.logger.info("📋 Respuesta obtenida del cache")
                return cached_response
            
            # Obtener modelo
            model_name = self._get_model(request.model_type)
            model = genai.GenerativeModel(model_name)
            
            # Construir prompt
            full_prompt = self._build_prompt(request)
            
            # Generar respuesta con timeout
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate_content,
                    full_prompt,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=request.max_tokens,
                        temperature=request.temperature,
                    ),
                    safety_settings=self.safety_settings,
                    request_options={'retry': None}
                ),
                timeout=60.0
            )
            
            # Procesar respuesta
            content = response.text if response.text else "No se pudo generar contenido"
            processing_time = (datetime.now() - start_time).total_seconds()
            
            # Crear respuesta
            ai_response = AIResponse(
                content=content,
                model_used=model_name,
                tokens_used=len(content.split()),  # Aproximación
                processing_time=processing_time,
                success=True
            )
            
            # Guardar en cache
            self.response_cache[cache_key] = ai_response
            
            self.logger.info(f"✅ Texto generado con {model_name} en {processing_time:.2f}s")
            return ai_response
            
        except Exception as e:
            self.logger.error(f"❌ Error generando texto: {e}")
            return AIResponse(
                content="",
                model_used="",
                tokens_used=0,
                processing_time=0,
                success=False,
                error=str(e)
            )
    
    async def generate_multimodal(self, request: AIRequest, images: List[bytes] = None) -> AIResponse:
        """Genera contenido multimodal (texto + imágenes)"""
        try:
            start_time = datetime.now()
            
            # Obtener modelo multimodal
            model_name = self._get_model(AIModelType.MULTIMODAL)
            model = genai.GenerativeModel(model_name)
            
            # Construir contenido
            content_parts = [request.prompt]
            if images:
                for img_data in images:
                    content_parts.append({
                        'mime_type': 'image/jpeg',
                        'data': img_data
                    })
            
            # Generar respuesta con timeout
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate_content,
                    content_parts,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=request.max_tokens,
                        temperature=request.temperature,
                    ),
                    safety_settings=self.safety_settings,
                    request_options={'retry': None}
                ),
                timeout=60.0
            )
            
            # Procesar respuesta
            content = response.text if response.text else "No se pudo generar contenido"
            processing_time = (datetime.now() - start_time).total_seconds()
            
            # Crear respuesta
            ai_response = AIResponse(
                content=content,
                model_used=model_name,
                tokens_used=len(content.split()),
                processing_time=processing_time,
                success=True
            )
            
            self.logger.info(f"✅ Contenido multimodal generado con {model_name} en {processing_time:.2f}s")
            return ai_response
            
        except Exception as e:
            self.logger.error(f"❌ Error generando contenido multimodal: {e}")
            return AIResponse(
                content="",
                model_used="",
                tokens_used=0,
                processing_time=0,
                success=False,
                error=str(e)
            )
    
    def _get_model(self, model_type: AIModelType) -> str:
        """Obtiene el modelo apropiado para el tipo usando el índice de rotación"""
        models = self.models.get(model_type, self.models[AIModelType.TEXT])
        current_index = self.current_model_index.get(model_type, 0)
        return models[current_index]
    
    def _rotate_model(self, model_type: AIModelType) -> bool:
        """
        Rota al siguiente modelo disponible.
        Returns: True si la rotación fue exitosa, False si no hay más modelos
        """
        models_list = self.models.get(model_type, self.models[AIModelType.TEXT])
        current_index = self.current_model_index[model_type]
        
        if current_index + 1 < len(models_list):
            self.current_model_index[model_type] += 1
            new_model = models_list[self.current_model_index[model_type]]
            self.logger.warning(f"🔄 Rotando modelo {model_type.value}: {new_model}")
            return True
        else:
            self.logger.error(f"❌ No hay más modelos disponibles para {model_type.value}")
            return False
    
    def _is_quota_error(self, error: Exception) -> bool:
        """Detecta si el error es debido a cuota agotada"""
        error_str = str(error).lower()
        quota_indicators = [
            "quota",
            "rate limit",
            "resource exhausted",
            "resource_exhausted",
            "429",
            "too many requests",
            "quota exceeded"
        ]
        return any(indicator in error_str for indicator in quota_indicators)
    
    async def _call_with_rotation(self, model_type: AIModelType, call_func):
        """
        Ejecuta una llamada a la API con rotación automática en caso de cuota agotada.
        
        Args:
            model_type: Tipo de modelo a usar
            call_func: Función async que realiza la llamada a la API
            
        Returns:
            Resultado de la llamada exitosa
            
        Raises:
            Exception: Si todos los modelos fallan
        """
        max_attempts = len(self.models.get(model_type, self.models[AIModelType.TEXT]))
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                return await call_func()
            except Exception as e:
                last_error = e
                if self._is_quota_error(e) and attempt < max_attempts - 1:
                    self.logger.warning(f"⚠️ Cuota agotada para modelo actual, rotando...")
                    if not self._rotate_model(model_type):
                        raise
                    # Continuar al siguiente intento con el nuevo modelo
                else:
                    # No es error de cuota o ya no hay más modelos
                    raise
        
        # Si llegamos aquí, todos los intentos fallaron
        raise last_error if last_error else Exception("Todos los modelos fallaron")
    
    def _build_prompt(self, request: AIRequest) -> str:
        """Construye el prompt completo"""
        prompt_parts = []
        
        if request.context:
            prompt_parts.append(f"Contexto: {request.context}")
        
        if request.language:
            prompt_parts.append(f"Idioma de respuesta: {request.language}")
        
        prompt_parts.append(f"Prompt: {request.prompt}")
        
        return "\n\n".join(prompt_parts)
    
    def clear_cache(self):
        """Limpia el cache de respuestas"""
        self.response_cache.clear()
        self.logger.info("🗑️ Cache de IA limpiado")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del cache"""
        return {
            "cached_responses": len(self.response_cache),
            "cache_size_mb": sum(len(str(response)) for response in self.response_cache.values()) / 1024 / 1024
        }
    
    # En la clase AIService, dentro de services/ai_service.py

# En la clase AIService, dentro de services/ai_service.py

    async def generate_chat_response(self, system_prompt: str, history: List[Dict[str, Any]], user_prompt: str, images: List[bytes] = None) -> AIResponse:
        """
        Genera una respuesta dentro de una conversación continua (chat) usando la interfaz de chat optimizada.
        Soporta imágenes para análisis multimodal.
        """
        try:
            start_time = datetime.now()
            
            # Usar modelo multimodal por defecto si hay imágenes, o el de texto si no
            # Nota: Gemini 1.5 Flash/Pro son multimodales por naturaleza, así que MODEL_TEXT suele servir si es 1.5
            model_name = self._get_model(AIModelType.MULTIMODAL if images else AIModelType.TEXT)
            
            # Usamos 'system_instruction' que es la forma oficial y más estable de dar personalidad.
            model = genai.GenerativeModel(model_name, system_instruction=system_prompt)
            
            # Iniciar un chat con el historial existente
            chat = model.start_chat(history=history)
            
            # Preparar el contenido del mensaje (texto + imágenes opcionales)
            content_parts = [user_prompt]
            if images:
                for img_bytes in images:
                    content_parts.append({
                        'mime_type': 'image/jpeg',
                        'data': img_bytes
                    })
            
            # Enviar el nuevo mensaje del usuario con timeout
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    chat.send_message,
                    content_parts,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=2000,
                        temperature=0.8,
                    ),
                    safety_settings=self.safety_settings,
                    request_options={'retry': None}
                ),
                timeout=60.0
            )
            
            if not response.parts:
                finish_reason = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
                error_msg = f"Respuesta de chat bloqueada o vacía (Reason: {finish_reason})"
                self.logger.warning(error_msg)
                return AIResponse(content="", model_used=model_name, tokens_used=0, processing_time=0, success=False, error=error_msg)

            content = "".join(part.text for part in response.parts if part.text)
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return AIResponse(
                content=content,
                model_used=model_name,
                tokens_used=0, 
                processing_time=processing_time,
                success=True
            )

        except Exception as e:
            self.logger.error(f"❌ Error generando respuesta de chat", error=e)
            return AIResponse(content="", model_used="", tokens_used=0, processing_time=0, success=False, error=str(e))

    async def detect_language(self, text: str) -> str:
        """Detecta el idioma del texto usando la librería langdetect."""
        try:
            # langdetect es síncrono, así que no necesita asyncio.to_thread
            lang_code = detect(text)
            return lang_code
        except LangDetectException:
            # Esto pasa si el texto es muy corto o ambiguo (ej: "ok")
            self.logger.warning(f"No se pudo detectar el idioma para: '{text[:20]}'. Usando 'en'.")
            return 'en'
        except Exception as e:
            self.logger.error(f"❌ Error inesperado en langdetect: {e}")
            return 'en'

    async def generate_text(self, request: AIRequest) -> AIResponse:
        """Genera texto usando modelos de IA de forma robusta."""
        try:
            start_time = datetime.now()
            
            cache_key = f"{request.prompt}_{request.model_type.value}_{request.temperature}"
            if cache_key in self.response_cache:
                self.logger.info("📋 Respuesta obtenida del cache")
                return self.response_cache[cache_key]
            
            model_name = self._get_model(request.model_type)
            model = genai.GenerativeModel(model_name)
            
            full_prompt = self._build_prompt(request)
            
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate_content,
                    full_prompt,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=request.max_tokens,
                        temperature=request.temperature,
                    ),
                    safety_settings=self.safety_settings,
                    request_options={'retry': None}
                ),
                timeout=60.0
            )
            
            # --- INICIO DE LA CORRECCIÓN CRÍTICA ---
            # Verificación robusta ANTES de acceder a response.text
            # Esta es la misma lógica que aplicamos al clasificador.
            if not response.parts:
                finish_reason = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
                error_msg = f"Respuesta de IA bloqueada o vacía (Reason: {finish_reason})"
                self.logger.warning(error_msg)
                return AIResponse(
                    content="", model_used=model_name, tokens_used=0,
                    processing_time=(datetime.now() - start_time).total_seconds(),
                    success=False, error=error_msg
                )

            content = "".join(part.text for part in response.parts if part.text)
            # --- FIN DE LA CORRECCIÓN CRÍTICA ---
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            ai_response = AIResponse(
                content=content,
                model_used=model_name,
                tokens_used=len(content.split()),
                processing_time=processing_time,
                success=True
            )
            
            self.response_cache[cache_key] = ai_response
            
            self.logger.info(f"✅ Texto generado con {model_name} en {processing_time:.2f}s")
            return ai_response
            
        except Exception as e:
            self.logger.error(f"❌ Error generando texto", error=e)
            return AIResponse(
                content="", model_used="", tokens_used=0,
                processing_time=0, success=False, error=str(e)
            )
        
# En la clase AIService, dentro de services/ai_service.py

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> Optional[str]:
        """
        Transcribe un archivo de audio a texto usando un modelo multimodal de Gemini.
        """
        try:
            start_time = datetime.now()
            self.logger.info(f"🎤 Iniciando transcripción de audio ({len(audio_bytes) / 1024:.1f} KB)...")
            
            # Usamos un modelo potente para la transcripción
            model_name = self._get_model(AIModelType.VIDEO) # Los modelos de video son excelentes para audio también
            model = genai.GenerativeModel(model_name)
            
            # Creamos el 'Part' de audio como en la documentación
            audio_part = {
                'mime_type': mime_type,
                'data': audio_bytes
            }
            
            # El prompt es directo: le pedimos la transcripción.
            prompt = "Provide a transcript of the speech in this audio file. Respond only with the transcribed text."

            # Hacemos la llamada multimodal con timeout
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate_content,
                    [prompt, audio_part],
                    safety_settings=self.safety_settings,
                    request_options={'retry': None}
                ),
                timeout=60.0
            )
            
            if not response.parts:
                finish_reason = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
                self.logger.warning(f"Transcripción bloqueada o vacía. Finish Reason: {finish_reason}")
                return None

            transcribed_text = "".join(part.text for part in response.parts if part.text)
            processing_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"✅ Transcripción completada en {processing_time:.2f}s: '{transcribed_text[:50]}...'")
            return transcribed_text

        except Exception as e:
            self.logger.error(f"❌ Error durante la transcripción de audio", error=e)
            return None

# En la clase AIService, dentro de services/ai_service.py

    async def generate_translation(self, text: str, target_language: str) -> Optional[str]:
        """
        Genera una traducción de forma robusta usando la interfaz de chat,
        que es menos propensa a ser bloqueada por los filtros de seguridad.
        Incluye rotación automática de modelos si se agota la cuota.
        """
        async def _do_translation():
            start_time = datetime.now()
            
            # Usamos un 'system_instruction' que le da a la IA un rol claro y profesional.
            system_prompt = f"You are a professional, highly accurate translation engine. Your sole purpose is to translate the user's text into {target_language}. You must respond ONLY with the translated text itself, without any introductory phrases, explanations, or apologies."

            model_name = self._get_model(AIModelType.TEXT)
            model = genai.GenerativeModel(model_name, system_instruction=system_prompt)

            # Iniciamos una "mini-conversación" de un solo turno para la traducción.
            chat = model.start_chat(history=[])
            
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    chat.send_message,
                    text,
                    safety_settings=self.safety_settings,
                    request_options={'retry': None}
                ),
                timeout=60.0
            )

            if not response.parts:
                finish_reason = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
                self.logger.warning(f"Traducción bloqueada o vacía. Finish Reason: {finish_reason}")
                return None

            translated_text = "".join(part.text for part in response.parts if part.text)
            processing_time = (datetime.now() - start_time).total_seconds()
            self.logger.info(f"✅ Traducción generada con '{model_name}' en {processing_time:.2f}s")
            
            return translated_text
        
        try:
            return await self._call_with_rotation(AIModelType.TEXT, _do_translation)
        except Exception as e:
            self.logger.error(f"❌ Error generando traducción", error=e)
            return None

# Instancia global del servicio
ai_service = AIService()
