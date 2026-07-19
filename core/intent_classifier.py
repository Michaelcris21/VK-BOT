"""
Clasificador de intenciones inteligente usando Gemini AI para VK
Analiza texto natural del usuario y determina qué acción realizar
"""

import re
import asyncio
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import google.generativeai as genai
from config import settings, get_service_logger


@dataclass
class IntentResult:
    """Resultado del análisis de intención"""
    intent: str
    confidence: float
    parameters: Dict[str, Any]
    raw_response: str
    reasoning: Optional[str] = None


class IntentClassifier:
    """Clasificador inteligente de intenciones usando Gemini AI"""
    
    def __init__(self):
        self.logger = get_service_logger("intent_classifier")
        self.model = genai.GenerativeModel(settings.AI.MODEL_TEXT)
        self.generation_config = genai.types.GenerationConfig(
            temperature=settings.AI.TEMPERATURE_INTENT,
            max_output_tokens=800  # Respuestas cortas para clasificación
        )
        
        # Cache para intenciones recientes
        self.intent_cache = {}
        self.cache_max_size = 50
        
        self.logger.info("🧠 Clasificador de intenciones inicializado")
    
    async def classify_intent(self, text: str, user_id: Optional[int] = None) -> IntentResult:
        """Clasifica la intención del texto del usuario"""
        try:
            self.logger.info(f"Analizando intención: '{text[:50]}...'", user_id=user_id)
            
            cache_key = hash(text.lower().strip())
            if cache_key in self.intent_cache:
                self.logger.info("✅ Usando intención desde cache", user_id=user_id)
                return self.intent_cache[cache_key]
            
            if not text or not text.strip():
                return self._create_fallback_result("Texto vacío")
            
            classification_prompt = self._build_classification_prompt(text)
            
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.model.generate_content,
                    classification_prompt,
                    generation_config=self.generation_config
                ),
                timeout=settings.AI.API_TIMEOUT
            )
            
            # Verificación robusta antes de acceder a .text
            if not response.parts:
                finish_reason = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
                self.logger.warning(
                    f"Clasificación bloqueada o vacía. Finish Reason: {finish_reason}",
                    user_id=user_id
                )
                return self._create_fallback_result(f"Respuesta bloqueada por IA (Reason: {finish_reason})")

            content = "".join(part.text for part in response.parts if part.text)
            if not content.strip():
                return self._create_fallback_result("Sin respuesta de IA")
            
            result = self._parse_ai_response(content, text)
            
            if result.confidence >= settings.AI.INTENT_CONFIDENCE_THRESHOLD:
                self._update_cache(cache_key, result)
            
            self.logger.info(
                f"🎯 Intención clasificada: {result.intent} (confianza: {result.confidence:.2f})",
                user_id=user_id
            )
            
            return result
            
        except asyncio.TimeoutError:
            self.logger.error("⏱️ Timeout en clasificación de intención", user_id=user_id)
            return self._create_fallback_result("Timeout en análisis")
        
        except Exception as e:
            self.logger.error("❌ Error en clasificación", error=e, user_id=user_id)
            return self._create_fallback_result(f"Error: {str(e)}")
    
    def _build_classification_prompt(self, text: str) -> str:
        """Construye el prompt para clasificación de intenciones"""
        return f"""Eres un asistente experto en análisis de intenciones para un bot de VK.

INTENCIONES DISPONIBLES:
• TRADUCIR - Usuario quiere traducir un texto específico.
• AYUDA - Usuario pide información sobre el bot o cómo usarlo.
• ESTADISTICAS - Usuario pregunta por sus estadísticas de uso.
• IDIOMAS - Usuario pregunta por idiomas soportados.
• CONFIGURAR_TRADUCCION - Usuario quiere activar o desactivar el modo de traducción automática para todo el chat.
• CONVERSACION - Charla general, saludos, preguntas casuales que no encajan en otra categoría.

CONTEXTO IMPORTANTE:
- Si menciona "activa el modo traductor", "empieza a traducir todo", "traduce a partir de ahora", "deja de traducir" -> CONFIGURAR_TRADUCCION
- Si hay texto específico para traducir (ej: "traduce esto:") -> TRADUCIR
- Si pregunta sobre funciones del bot o comandos -> AYUDA
- Si es saludo, charla casual, pregunta general -> CONVERSACION

ANÁLISIS REQUERIDO:
Analiza este mensaje: "{text}"

FORMATO DE RESPUESTA (OBLIGATORIO):
INTENCION: [una de las intenciones disponibles]
CONFIANZA: [0.0 a 1.0]
PARAMETROS: [JSON con parámetros extraídos]
RAZON: [breve explicación de por qué elegiste esta intención]

PARAMETROS SEGÚN INTENCIÓN:
- TRADUCIR: {{"texto": "texto a traducir"}}
- AYUDA: {{"tipo_ayuda": "general/comandos"}}
- CONFIGURAR_TRADUCCION: {{"accion": "activar/desactivar", "idiomas": ["es", "en"]}}
- CONVERSACION: {{"tipo": "saludo/pregunta"}}

Responde SOLO en el formato requerido y de forma idéntica."""

    def _parse_ai_response(self, ai_response: str, original_text: str) -> IntentResult:
        """Parsea la respuesta de la IA y extrae la clasificación"""
        try:
            lines = ai_response.strip().split('\n')
            
            intent = None
            confidence = 0.5  # Valor por defecto
            parameters = {}
            reasoning = None
            
            for line in lines:
                line = line.strip()
                if line.startswith('INTENCION:'):
                    intent = line.replace('INTENCION:', '').strip()
                elif line.startswith('CONFIANZA:'):
                    try:
                        confidence = float(line.replace('CONFIANZA:', '').strip())
                        confidence = max(0.0, min(1.0, confidence))  # Clamp entre 0-1
                    except ValueError:
                        confidence = 0.5
                elif line.startswith('PARAMETROS:'):
                    params_str = line.replace('PARAMETROS:', '').strip()
                    try:
                        import json
                        parameters = json.loads(params_str)
                    except json.JSONDecodeError:
                        parameters = {}
                elif line.startswith('RAZON:'):
                    reasoning = line.replace('RAZON:', '').strip()
            
            # Validar intención
            if intent not in settings.Intents.ALL_INTENTS:
                self.logger.warning(f"🤔 Intención desconocida '{intent}', usando CONVERSACION")
                intent = settings.Intents.CONVERSATION
                confidence = max(0.3, confidence - 0.2)  # Reducir confianza
            
            # Enriquecimiento automático de parámetros
            parameters = self._enrich_parameters(intent, original_text, parameters)
            
            return IntentResult(
                intent=intent,
                confidence=confidence,
                parameters=parameters,
                raw_response=ai_response,
                reasoning=reasoning
            )
            
        except Exception as e:
            self.logger.error(f"❌ Error parseando respuesta IA: {e}")
            return self._create_fallback_result(f"Error de parsing: {str(e)}")
    
    def _enrich_parameters(self, intent: str, text: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Enriquece parámetros con análisis adicional automático"""
        # Para TRADUCIR: detectar texto si no está especificado
        if intent == settings.Intents.TRANSLATE and 'texto' not in params:
            params['texto'] = text.strip()
        
        # Para AYUDA: detectar tipo específico
        if intent == settings.Intents.HELP and 'tipo_ayuda' not in params:
            text_lower = text.lower()
            if any(word in text_lower for word in ['comando', 'cómo usar', 'instrucción']):
                params['tipo_ayuda'] = 'comandos'
            elif any(word in text_lower for word in ['función', 'qué hace', 'para qué']):
                params['tipo_ayuda'] = 'funciones'
            else:
                params['tipo_ayuda'] = 'general'
        
        return params
    
    def _create_fallback_result(self, reason: str) -> IntentResult:
        """Crea resultado de fallback para casos de error"""
        return IntentResult(
            intent=settings.Intents.CONVERSATION,
            confidence=0.3,
            parameters={'tipo': 'error', 'razon': reason},
            raw_response="",
            reasoning=f"Fallback debido a: {reason}"
        )
    
    def _update_cache(self, cache_key: int, result: IntentResult) -> None:
        """Actualiza el cache de intenciones"""
        if len(self.intent_cache) >= self.cache_max_size:
            oldest_key = next(iter(self.intent_cache))
            del self.intent_cache[oldest_key]
        self.intent_cache[cache_key] = result
    
    def get_intent_confidence_level(self, confidence: float) -> str:
        """Convierte confianza numérica a nivel descriptivo"""
        if confidence >= 0.9:
            return "muy alta"
        elif confidence >= 0.7:
            return "alta"
        elif confidence >= 0.5:
            return "media"
        elif confidence >= 0.3:
            return "baja"
        else:
            return "muy baja"
    
    def clear_cache(self) -> None:
        """Limpia el cache de intenciones"""
        self.intent_cache.clear()
        self.logger.info("🧹 Cache de intenciones limpiado")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Retorna estadísticas del cache"""
        return {
            'size': len(self.intent_cache),
            'max_size': self.cache_max_size,
            'usage_percent': (len(self.intent_cache) / self.cache_max_size) * 100
        }


# Función de conveniencia
async def classify_user_intent(text: str, user_id: Optional[int] = None) -> IntentResult:
    classifier = IntentClassifier()
    return await classifier.classify_intent(text, user_id)
