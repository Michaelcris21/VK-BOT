"""
Router Inteligente - Orquesta todas las acciones del bot basado en intenciones para VK
Conecta el clasificador de intenciones con los servicios correspondientes
"""

import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
import httpx
from vkbottle.bot import Message

from config import settings, get_service_logger
from .intent_classifier import IntentClassifier, IntentResult
from services import ai_service
from services.ai_service import AIRequest


class ActionStatus(Enum):
    """Estados de ejecución de acciones"""
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    USER_ERROR = "user_error"


@dataclass
class ActionResult:
    """Resultado de la ejecución de una acción"""
    status: ActionStatus
    message: str
    keyboard: Optional[str] = None  # JSON string de teclado de VK
    metadata: Optional[Dict[str, Any]] = None


# Historial global de conversación (en memoria)
conversation_histories: Dict[int, List[Dict[str, Any]]] = {}


class IntelligentRouter:
    """Router que ejecuta acciones basado en intenciones clasificadas"""
    
    def __init__(self):
        self.logger = get_service_logger("router")
        self.intent_classifier = IntentClassifier()
        
        # Registro de servicios (se inicializan lazy)
        self._services = {}
        
        # Mapa de intenciones a métodos
        self.intent_handlers = {
            settings.Intents.TRANSLATE: self._handle_translation,
            settings.Intents.HELP: self._handle_help,
            settings.Intents.STATS: self._handle_stats,
            settings.Intents.LANGUAGES: self._handle_languages,
            settings.Intents.CONVERSATION: self._handle_conversation,
            settings.Intents.CONFIGURE_TRANSLATION: self._handle_configure_translation,
        }
        
        self.logger.info("🎯 Router inteligente de VK inicializado")
    
    async def process_message(self, message: Message) -> ActionResult:
        """
        Procesa un mensaje completo: clasifica intención y ejecuta acción
        
        Args:
            message: Message de vkbottle
            
        Returns:
            ActionResult con el resultado de la acción
        """
        user_id = message.from_id
        message_text = message.text
        
        try:
            self.logger.info(f"📨 Procesando mensaje: '{message_text[:50]}...'", user_id=user_id)
            
            # Preparar texto para análisis (incluyendo contexto de respuesta si existe)
            analysis_text = message_text
            replied_msg = message.reply_message
            
            if replied_msg:
                replied_content = replied_msg.text or ""
                if replied_content:
                    analysis_text = f"{message_text}\n\n[CONTEXTO DEL MENSAJE RESPONDIDO]: {replied_content}"
                    self.logger.info(f"🔗 Contexto de respuesta detectado ({len(replied_content)} chars)")

            # Paso 1: Clasificar intención
            intent_result = await self.intent_classifier.classify_intent(analysis_text, user_id)
            
            # Paso 2: Verificar confianza. Si la confianza es baja, sugerimos opciones.
            if intent_result.confidence < settings.AI.INTENT_CONFIDENCE_THRESHOLD:
                return await self._suggest_options(message)
            
            # Paso 3: Ejecutar acción correspondiente
            handler = self.intent_handlers.get(intent_result.intent)
            if not handler:
                self.logger.warning(f"🤔 No hay handler para intención: {intent_result.intent}")
                return await self._handle_conversation(intent_result, message)
            
            self.logger.info(f"🎯 Ejecutando: {intent_result.intent} (confianza: {intent_result.confidence:.2f})", user_id=user_id)
            return await handler(intent_result, message)
            
        except Exception as e:
            self.logger.error("❌ Error en router", error=e, user_id=user_id)
            return ActionResult(
                status=ActionStatus.ERROR,
                message="❌ Ocurrió un error inesperado. Por favor intenta de nuevo.",
            )
    
    async def _suggest_options(self, message: Message) -> ActionResult:
        """Sugiere opciones cuando no se entiende la intención"""
        suggestions_text = (
            "🤔 No estoy seguro de qué quieres hacer. ¿Podrías ser más específico?\n\n"
            "Puedes:\n"
            "📝 Enviar texto para traducir\n"
            "❓ Escribir /help para ayuda\n"
            "📊 Escribir /stats para ver tus estadísticas"
        )
        
        # Opcionalmente crear teclado de ayuda de VK
        from vkbottle import Keyboard, KeyboardButtonColor, Text
        keyboard = Keyboard(one_time=True, inline=True)
        keyboard.add(Text("📖 Ayuda"), color=KeyboardButtonColor.PRIMARY)
        keyboard.add(Text("🌍 Idiomas"), color=KeyboardButtonColor.SECONDARY)
        
        return ActionResult(
            status=ActionStatus.USER_ERROR,
            message=suggestions_text,
            keyboard=keyboard.get_json()
        )
    
    # === HANDLERS PARA CADA INTENCIÓN ===
    
    async def _handle_translation(self, 
                                intent_result: IntentResult,
                                message: Message) -> ActionResult:
        """Maneja solicitudes de traducción"""
        try:
            translation_service = await self._get_service('translation')
            
            # Extraer texto a traducir
            text_to_translate = intent_result.parameters.get('texto', message.text)
            
            # Ejecutar traducción
            result = await translation_service.translate_text(text_to_translate, user_id=message.from_id)
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                message=result
            )
            
        except Exception as e:
            self.logger.error("❌ Error en traducción", error=e, user_id=message.from_id)
            return ActionResult(
                status=ActionStatus.ERROR,
                message=settings.Messages.ERROR_TRANSLATION
            )
    
    async def _handle_help(self, 
                          intent_result: IntentResult,
                          message: Message) -> ActionResult:
        """Maneja solicitudes de ayuda"""
        help_type = intent_result.parameters.get('tipo_ayuda', 'general')
        
        if help_type == 'comandos':
            text = self._get_commands_help()
        elif help_type == 'funciones':
            text = self._get_functions_help()
        else:
            text = self._get_general_help()
        
        return ActionResult(
            status=ActionStatus.SUCCESS,
            message=text
        )
    
    async def _handle_stats(self, 
                           intent_result: IntentResult,
                           message: Message) -> ActionResult:
        """Maneja solicitudes de estadísticas"""
        try:
            stats_service = await self._get_service('stats')
            user_id = message.from_id
            
            stats = stats_service.get_user_stats(user_id)
            
            stats_text = (
                f"📊 TUS ESTADÍSTICAS\n\n"
                f"📝 Traducciones: {stats['translations']}\n"
                f"💬 Conversaciones: {stats['conversations']}\n"
                f"❓ Consultas de ayuda: {stats['help_requests']}\n"
                f"📈 Total de acciones: {stats['total_actions']}\n"
            )
            
            if stats['days_using_bot'] > 0:
                stats_text += (
                    f"\n📅 Usando el bot: {stats['days_using_bot']} días\n"
                    f"📈 Promedio: {stats['actions_per_day']} acciones/día\n"
                    f"🎯 Función favorita: {stats['most_used_feature']}"
                )

            return ActionResult(
                status=ActionStatus.SUCCESS,
                message=stats_text
            )
            
        except Exception as e:
            self.logger.error("❌ Error obteniendo stats", error=e, user_id=message.from_id)
            return ActionResult(
                status=ActionStatus.ERROR,
                message="❌ Error obteniendo tus estadísticas."
            )
    
    async def _handle_languages(self, 
                               intent_result: IntentResult,
                               message: Message) -> ActionResult:
        """Maneja solicitudes de idiomas soportados"""
        lang_text = "🌍 IDIOMAS SOPORTADOS\n\nIDIOMAS ESLAVOS → Español 🇪🇸\n\n"
        
        flags = {'ru': '🇷🇺', 'uk': '🇺🇦', 'bg': '🇧🇬', 'sr': '🇷🇸', 'hr': '🇭🇷', 
                 'cs': '🇨🇿', 'sk': '🇸🇰', 'pl': '🇵🇱', 'sl': '🇸🇮', 'mk': '🇲🇰', 'bs': '🇧🇦'}
        
        for code, name in settings.Translation.SLAVIC_LANGUAGES.items():
            flag = flags.get(code, '🏳️')
            lang_text += f"{flag} {name}\n"
        
        lang_text += "\nOTROS IDIOMAS → Ruso 🇷🇺"
        lang_text += "\n🌐 Inglés, Español, Francés, Alemán, Italiano, etc."
        
        return ActionResult(
            status=ActionStatus.SUCCESS,
            message=lang_text
        )
    
    async def _handle_conversation(self, 
                                  intent_result: IntentResult,
                                  message: Message) -> ActionResult:
        """Maneja conversación general con personalidad (texto plano)"""
        user_id = message.from_id
        peer_id = message.peer_id
        user_text = message.text

        self.logger.info(f"🧠 Manejando conversación con personalidad para: '{user_text[:50]}...'", user_id=user_id)
        
        try:
            # Obtener nombre de usuario
            user_info = await message.ctx_api.users.get(user_ids=[user_id])
            user_name = user_info[0].first_name if user_info else f"User {user_id}"

            # Obtener historial de conversación
            if peer_id not in conversation_histories:
                conversation_histories[peer_id] = []
            
            history = conversation_histories[peer_id]
            
            # Contexto de respuesta
            context_header = ""
            if message.reply_message:
                r_user_id = message.reply_message.from_id
                r_info = await message.ctx_api.users.get(user_ids=[r_user_id])
                r_name = r_info[0].first_name if r_info else "Alguien"
                r_content = message.reply_message.text or "[Multimedia]"
                if len(r_content) > 100:
                    r_content = r_content[:100] + "..."
                context_header = f"[RESPONDIENDO A {r_name}]: \"{r_content}\"\n"

            formatted_user_text = f"{context_header}[{user_name}]: {user_text}"
            
            # Detección de imágenes (descargar directamente desde URLs de VK)
            image_bytes_list = []
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.photo:
                        sizes = attachment.photo.sizes
                        if sizes:
                            # Seleccionar el de mayor resolución
                            max_size = sorted(sizes, key=lambda x: (x.width or 0) * (x.height or 0))[-1]
                            url = max_size.url
                            if url:
                                self.logger.info(f"📥 Descargando imagen desde VK para Gemini: {url}")
                                async with httpx.AsyncClient() as client:
                                    response = await client.get(url)
                                    if response.status_code == 200:
                                        image_bytes_list.append(response.content)
                                        self.logger.info("✅ Imagen descargada correctamente")
            
            # System prompt con instrucciones de personalidad y formato para VK
            system_prompt = f"""
            Eres CrisTranslate, un asistente de IA útil y directo para VK.

            **REGLA CRÍTICA DE IDIOMA:**
            1. Debes identificar el idioma del último mensaje del usuario ({user_name}) y responder ÚNICAMENTE en ese mismo idioma.
            2. Si el usuario escribe en Ruso, responde en Ruso. Si escribe en Español, responde en Español.
            3. NUNCA cambies de idioma a menos que el usuario lo haga primero.

            **REGLAS DE PERSONALIDAD:**
            1. CERO SALUDOS: Ve AL GRANO.
            2. BREVEDAD: Responde en 2-3 frases.
            3. FORMATO: Usa TEXTO PLANO. No uses Markdown (** o __) ni HTML.
            """
            
            # Generar respuesta
            ai_response_obj = await ai_service.generate_chat_response(
                system_prompt, 
                history, 
                formatted_user_text, 
                images=image_bytes_list
            )
            
            if not ai_response_obj.success or not ai_response_obj.content:
                final_message = "Lo siento, me he perdido. ¿Podemos intentarlo de nuevo?"
            else:
                final_message = ai_response_obj.content
                
                # Guardar en historial
                history_content = formatted_user_text
                if image_bytes_list:
                    history_content += " [IMAGEN ADJUNTA]"
                
                history.append({'role': 'user', 'parts': [history_content]})
                history.append({'role': 'model', 'parts': [final_message]})
            
            # Limitar tamaño de historial
            while len(history) > 16:
                history.pop(0)

            return ActionResult(
                status=ActionStatus.SUCCESS,
                message=final_message
            )

        except Exception as e:
            self.logger.error("❌ Error en conversación con IA", error=e, user_id=user_id)
            return ActionResult(
                status=ActionStatus.ERROR, 
                message="Uff, un pequeño cortocircuito. Inténtalo de nuevo."
            )
    
    async def _handle_configure_translation(self, intent_result: IntentResult, message: Message) -> ActionResult:
        """Activa o desactiva la traducción automática (Modo grupo)"""
        # Como vkbottle no tiene un context.chat_data global nativo de la misma forma,
        # la configuración se puede retornar como metadatos para que el handler la persista.
        action = intent_result.parameters.get('accion', 'activar')
        languages = intent_result.parameters.get('idiomas')
        
        if action == 'desactivar':
            msg = "✅ Modo de traducción automática desactivado."
            targets = []
            active = False
        else:
            active = True
            if languages:
                targets = languages
                msg = f"✅ ¡Modo de traducción multi-idioma activado! Traduciré a: {', '.join(languages).upper()}"
            else:
                targets = ['smart_default']
                msg = "✅ ¡Modo de traducción inteligente activado! (Eslavo → Español, Otros → Ruso)"
                
        return ActionResult(
            status=ActionStatus.SUCCESS,
            message=msg,
            metadata={'active': active, 'targets': targets}
        )

    # === SERVICIOS LAZY LOADING ===
    
    async def _get_service(self, service_name: str):
        """Obtiene un servicio con lazy loading"""
        if service_name not in self._services:
            if service_name == 'translation':
                from services.translation_service import TranslationService
                self._services[service_name] = TranslationService()
            elif service_name == 'stats':
                from utils.stats import UserStats
                if not hasattr(self, '_stats_instance'):
                    self._stats_instance = UserStats()
                self._services[service_name] = self._stats_instance
            else:
                raise ValueError(f"Servicio desconocido: {service_name}")
        
        return self._services[service_name]
    
    # === MÉTODOS DE AYUDA ===
    
    def _get_general_help(self) -> str:
        """Obtiene texto de ayuda general"""
        return (
            "📖 GUÍA COMPLETA DEL BOT\n\n"
            "🌍 TRADUCTOR AUTOMÁTICO\n"
            "• Simplemente envía cualquier texto\n"
            "• Idiomas eslavos → Traducción al español\n"
            "• Otros idiomas → Traducción al ruso\n\n"
            "🎙️ TRADUCCIÓN DE VOZ\n"
            "• Envía un mensaje de voz\n"
            "• Transcripción automática con Gemini\n"
            "• Traducción automática del texto\n\n"
            "💬 CONVERSACIÓN NATURAL\n"
            "• Solo habla naturalmente conmigo\n"
            "• Entiendo tu intención automáticamente\n"
            "• No necesitas comandos específicos\n\n"
            "⚡ EJEMPLOS:\n"
            "• \"Traduce: Привет мир!\"\n"
            "• \"¿Qué idiomas soportas?\"\n\n"
            "¡Simplemente habla conmigo! 🤖"
        )
    
    def _get_commands_help(self) -> str:
        """Obtiene ayuda de comandos específicos"""
        return (
            "🔧 COMANDOS DISPONIBLES\n\n"
            "/start - Iniciar el bot\n"
            "/help - Esta ayuda\n"
            "/stats - Tus estadísticas\n"
            "/idiomas - Idiomas soportados\n"
            "/mi_idioma - Consulta tu perfil lingüístico\n\n"
            "💡 Nota: ¡Pero no necesitas comandos! Solo habla naturalmente."
        )
    
    def _get_functions_help(self) -> str:
        """Obtiene ayuda de funciones"""
        return (
            "⚙️ FUNCIONES DEL BOT\n\n"
            "🧠 Análisis Inteligente\n"
            "• Entiendo tu intención automáticamente\n"
            "• No necesitas comandos específicos\n\n"
            "🌐 Traducción Automática\n"
            "• Detección automática de idioma\n"
            "• Preserva enlaces y formato\n\n"
            "🎙️ Traducción de Voz\n"
            "• Transcripción automática\n"
            "• Traducción al idioma de destino"
        )
