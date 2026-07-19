"""
Handler Principal de Mensajes para VK usando vkbottle BotLabeler
Maneja mensajes de texto, traducción automática, modo asistente y notas de voz
"""
from vkbottle import GroupEventType
from vkbottle.bot import BotLabeler, Message

from config import settings, get_service_logger
from services import ai_service, translation_service
from services.user_language_service import language_tracker, get_native_language_from_profile
from utils import user_stats, text_formatter
from core import IntelligentRouter, ActionStatus

labeler = BotLabeler()
logger = get_service_logger("message_handler")
router = IntelligentRouter()

# Mapeo de mensaje original a su traducción (en memoria, para actualización de ediciones)
# Clave: (peer_id, original_conversation_message_id) -> lista de translation_message_ids
translation_mapping = {}


@labeler.message()
async def handle_message(message: Message):
    """Punto de entrada principal para todos los mensajes (catch-all)"""
    try:
        text = message.text
        
        # Loggear entrada de mensaje
        logger.info(f"📩 Mensaje recibido de {message.from_id} en chat {message.peer_id}: '{text[:60] if text else '[Adjuntos]'}'")
        
        # Verificar si hay payload de configuración de idioma
        if message.payload:
            import json
            try:
                payload_data = json.loads(message.payload)
                if "set_lang" in payload_data:
                    lang = payload_data["set_lang"]
                    user_info = await message.ctx_api.users.get(user_ids=[message.from_id])
                    display_name = user_info[0].first_name if user_info else f"User {message.from_id}"
                    
                    language_tracker.set_user_language(message.peer_id, message.from_id, display_name, lang)
                    
                    lang_names = {
                        'ru': 'Ruso 🇷🇺', 'uk': 'Ucraniano 🇺🇦', 'es': 'Español 🇪🇸',
                        'bg': 'Búlgaro 🇧🇬', 'pl': 'Polaco 🇵🇱', 'cs': 'Checo 🇨🇿',
                        'sr': 'Serbio 🇷🇸', 'sk': 'Eslovaco 🇸🇰', 'hr': 'Croata 🇭🇷',
                        'sl': 'Esloveno 🇸🇮'
                    }
                    lang_name = lang_names.get(lang, lang.upper())
                    await message.answer(f"✅ ¡Idioma configurado! Ahora tu idioma principal es {lang_name}.", random_id=0)
                    return
            except Exception as e:
                logger.error(f"❌ Error al procesar payload de idioma: {e}")
        
        # 1. Verificar si hay un mensaje de voz adjunto
        if message.attachments:
            for att in message.attachments:
                if att.audio_message:
                    logger.info(f"🎙️ Detectado mensaje de voz adjunto de {message.from_id}")
                    await _handle_voice(message, att)
                    return
        
        if not text:
            return

        # 2. Determinar tipo de chat (privado vs grupo)
        is_private = (message.peer_id == message.from_id)
        is_group = (message.peer_id > 2000000000)

        # 3. Lógica de doble personalidad (Asistente vs Traductor)
        if is_private:
            # Chat privado → Modo asistente
            await _handle_assistant_mode(message)
        elif is_group:
            # Grupo → verificar si es mención del bot
            bot_mention = f"[club{settings.VK_GROUP_ID}|"
            # VK a veces envía menciones en el texto
            if bot_mention in text:
                logger.info(f"🤖 Mención detectada en grupo {message.peer_id} -> Modo Asistente")
                # Quitar mención para procesar el texto limpio
                clean_text = text.replace(f"[club{settings.VK_GROUP_ID}|", "").replace("]", "").strip()
                # Si había un @bot_name después de la barra vertical, lo removemos también
                if "|" in text:
                    parts = text.split("|", 1)
                    if len(parts) > 1 and "]" in parts[1]:
                        clean_text = parts[1].split("]", 1)[1].strip()
                
                # Modificar el texto del mensaje temporalmente para el router
                message.text = clean_text
                await _handle_assistant_mode(message)
            else:
                # No es mención → Modo traductor automático de grupo
                await _handle_translator_mode(message)
        else:
            await _handle_translator_mode(message)

    except Exception as e:
        logger.error(f"❌ Error en handle_message: {e}")


async def _handle_assistant_mode(message: Message):
    """Modo asistente inteligente con enrutamiento de intenciones"""
    try:
        logger.info(f"🧠 Procesando mensaje en Modo Asistente para usuario {message.from_id}")
        # Enviar indicador de escritura
        try:
            await message.ctx_api.messages.set_activity(peer_id=message.peer_id, type="typing")
        except Exception:
            pass

        # Procesar con el router
        result = await router.process_message(message)
        
        if result.status == ActionStatus.SUCCESS:
            user_stats.record_action(message.from_id, 'conversations')
        elif result.status == ActionStatus.ERROR:
            user_stats.record_error(message.from_id, 'router_error', result.message)

        # Enviar respuesta
        logger.info(f"📤 Enviando respuesta de asistente a {message.from_id}")
        await message.answer(result.message, keyboard=result.keyboard, random_id=0)

    except Exception as e:
        logger.error(f"❌ Error en modo asistente: {e}")
        await message.answer("❌ Ocurrió un error al procesar tu solicitud con el asistente.", random_id=0)


async def _handle_translator_mode(message: Message):
    """Traduce automáticamente mensajes en grupo, personalizado por participante"""
    text = message.text
    if not text or len(text.strip()) < 2:
        return

    # Validar que contenga caracteres válidos para traducción
    is_valid, _ = text_formatter.is_valid_text_for_translation(text)
    if not is_valid:
        return

    user_id = message.from_id
    peer_id = message.peer_id

    try:
        # 1. Obtener nombre y datos del usuario (país, idiomas) para perfilarlo de inmediato
        user_info = await message.ctx_api.users.get(user_ids=[user_id], fields=["country", "personal"])
        display_name = user_info[0].first_name if user_info else f"User {user_id}"
        
        profile_native_lang = None
        if user_info:
            profile_native_lang = get_native_language_from_profile(user_info[0].__dict__)

        # 2. Detectar idioma del mensaje
        detected_lang = await ai_service.detect_language(text)
        logger.info(f"🌐 Idioma detectado para '{display_name}': {detected_lang}")

        # 3. Registrar en el tracker (el bot aprende)
        language_tracker.register_message(peer_id, user_id, display_name, detected_lang, profile_native_lang)

        # 4. Obtener todos los participantes del chat
        participants = language_tracker.get_chat_participants(peer_id)

        # 5. Determinar idiomas de destino necesarios
        target_languages = set()
        for participant in participants:
            if participant.user_id == user_id:
                continue  # No traducir para el propio autor
            
            if language_tracker.should_translate_for_user(peer_id, participant.user_id, detected_lang):
                target = participant.get_target_language()
                if target and target != detected_lang:
                    target_languages.add(target)

        # 6. Si no hay suficientes perfiles, usar lógica por defecto (fallback)
        if not target_languages:
            default_target = await translation_service.get_target_language(detected_lang)
            if detected_lang != default_target:
                logger.info(f"🔄 Usando traducción por defecto: {detected_lang} -> {default_target}")
                target_languages.add(default_target)

        # 7. Traducir y responder para cada idioma de destino
        for target_lang in target_languages:
            translated = await translation_service.translate_to_target(text, target_lang)
            if translated:
                if translated.strip().lower() == text.strip().lower():
                    continue

                sender_profile = language_tracker.get_profile(peer_id, user_id)
                sender_flag = sender_profile.get_flag() if sender_profile else {"es": "🌐", "ru": "🇷🇺", "uk": "🇺🇦", "bg": "🇧🇬"}.get(detected_lang, "🌐")
                
                logger.info(f"📤 Enviando traducción al {target_lang} para el chat grupal {peer_id}")
                user_stats.record_action(user_id, 'translations')
                sent_msg = await message.answer(f"{sender_flag} {display_name}: {translated}", random_id=0)
                
                # Guardar mapeo de forma segura
                msg_id = None
                if sent_msg:
                    if hasattr(sent_msg, "message_id"):
                        msg_id = sent_msg.message_id
                    elif hasattr(sent_msg, "id"):
                        msg_id = sent_msg.id
                    elif isinstance(sent_msg, dict):
                        msg_id = sent_msg.get("message_id") or sent_msg.get("id")
                    elif isinstance(sent_msg, int):
                        msg_id = sent_msg
                
                if msg_id:
                    key = (peer_id, message.conversation_message_id)
                    if key not in translation_mapping:
                        translation_mapping[key] = []
                    translation_mapping[key].append(msg_id)

    except Exception as e:
        logger.error(f"❌ Error en modo traductor de grupo: {e}")


async def _handle_voice(message: Message, attachment):
    """Maneja mensajes de voz: descarga -> transcribe -> traduce -> responde"""
    try:
        await message.answer(settings.Voice.PROCESSING_MESSAGE, random_id=0)

        # 1. Obtener URL del audio
        audio_msg = attachment.audio_message
        audio_url = audio_msg.link_ogg  # URL del audio en formato OGG (Opus)

        if not audio_url:
            await message.answer("❌ No se pudo obtener el enlace de descarga del audio de VK.", random_id=0)
            return

        # 2. Descargar el audio de VK
        logger.info(f"📥 Descargando audio desde: {audio_url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(audio_url)
            if response.status_code != 200:
                await message.answer("❌ Error al descargar el archivo de voz de los servidores de VK.", random_id=0)
                return
            audio_bytes = response.content

        # 3. Transcribir con Gemini AI
        transcribed_text = await ai_service.transcribe_audio(audio_bytes, "audio/ogg")
        if not transcribed_text:
            await message.answer("❌ No se pudo transcribir el mensaje de voz. El audio puede ser inaudible.", random_id=0)
            return

        # 4. Detectar idioma de la transcripción
        detected_lang = await ai_service.detect_language(transcribed_text)
        
        is_private = (message.peer_id == message.from_id)
        
        if is_private:
            # En chat privado: responde directamente al usuario
            target_lang = await translation_service.get_target_language(detected_lang)
            
            if detected_lang == target_lang:
                await message.answer(f"🎙️ Transcripción:\n{transcribed_text}", random_id=0)
            else:
                translated = await translation_service.translate_to_target(transcribed_text, target_lang)
                if translated:
                    await message.answer(
                        f"🎙️ Original: {transcribed_text}\n\n"
                        f"📝 Traducción: {translated}",
                        random_id=0
                    )
                else:
                    await message.answer(
                        f"🎙️ Transcripción: {transcribed_text}\n\n"
                        f"❌ No se pudo traducir.",
                        random_id=0
                    )
        else:
            # En grupo: publicar transcripción y traducirla de acuerdo al tracker
            user_id = message.from_id
            peer_id = message.peer_id
            
            # Obtener nombre y datos del usuario (país, idiomas) para notas de voz
            user_info = await message.ctx_api.users.get(user_ids=[user_id], fields=["country", "personal"])
            display_name = user_info[0].first_name if user_info else f"User {user_id}"
            
            profile_native_lang = None
            if user_info:
                profile_native_lang = get_native_language_from_profile(user_info[0].__dict__)
            
            # Registrar transcripción en el tracker
            language_tracker.register_message(peer_id, user_id, display_name, detected_lang, profile_native_lang)
            
            # Mostrar transcripción original en el grupo
            await message.answer(f"🎙️ {display_name} (voz): {transcribed_text}", random_id=0)
            
            # Buscar destinatarios que necesiten traducción
            participants = language_tracker.get_chat_participants(peer_id)
            target_languages = set()
            for participant in participants:
                if participant.user_id == user_id:
                    continue
                if language_tracker.should_translate_for_user(peer_id, participant.user_id, detected_lang):
                    target = participant.get_target_language()
                    if target and target != detected_lang:
                        target_languages.add(target)
            
            if not target_languages:
                default_target = await translation_service.get_target_language(detected_lang)
                if detected_lang != default_target:
                    target_languages.add(default_target)
            
            # Enviar las traducciones
            for target_lang in target_languages:
                translated = await translation_service.translate_to_target(transcribed_text, target_lang)
                if translated:
                    sender_profile = language_tracker.get_profile(peer_id, user_id)
                    sender_flag = sender_profile.get_flag() if sender_profile else {"es": "🌐", "ru": "🇷🇺", "uk": "🇺🇦", "bg": "🇧🇬"}.get(detected_lang, "🌐")
                    sent_msg = await message.answer(f"{sender_flag} {display_name} (voz): {translated}", random_id=0)
                    
                    # Guardar mapeo de forma segura
                    msg_id = None
                    if sent_msg:
                        if hasattr(sent_msg, "message_id"):
                            msg_id = sent_msg.message_id
                        elif hasattr(sent_msg, "id"):
                            msg_id = sent_msg.id
                        elif isinstance(sent_msg, dict):
                            msg_id = sent_msg.get("message_id") or sent_msg.get("id")
                        elif isinstance(sent_msg, int):
                            msg_id = sent_msg
                    
                    if msg_id:
                        key = (peer_id, message.conversation_message_id)
                        if key not in translation_mapping:
                            translation_mapping[key] = []
                        translation_mapping[key].append(msg_id)

        # Registrar estadísticas de traducción de voz
        user_stats.record_action(message.from_id, 'translations')

    except Exception as e:
        logger.error(f"❌ Error al procesar mensaje de voz: {e}")
        await message.answer(settings.Voice.ERROR_MESSAGE, random_id=0)


@labeler.raw_event(GroupEventType.MESSAGE_EDIT, dataclass=Message)
async def handle_message_edit(message: Message):
    """Maneja mensajes editados: re-traduce y actualiza el mensaje anterior del bot"""
    logger.info(f"📝 Evento raw MESSAGE_EDIT recibido: Chat {message.peer_id}, Mensaje {message.conversation_message_id}")
    try:
        text = message.text
        if not text:
            return
            
        peer_id = message.peer_id
        user_id = message.from_id
        original_cmid = message.conversation_message_id
        
        # Buscar si tenemos traducciones previas para este mensaje
        key = (peer_id, original_cmid)
        if key not in translation_mapping:
            return
            
        # Re-detectar idioma e invocar traducción
        detected_lang = await ai_service.detect_language(text)
        
        # Obtener nombre del usuario
        user_info = await message.ctx_api.users.get(user_ids=[user_id])
        display_name = user_info[0].first_name if user_info else f"User {user_id}"
        
        sender_profile = language_tracker.get_profile(peer_id, user_id)
        sender_flag = sender_profile.get_flag() if sender_profile else {"es": "🌐", "ru": "🇷🇺", "uk": "🇺🇦", "bg": "🇧🇬"}.get(detected_lang, "🌐")

        # Buscar destinatarios que necesiten traducción
        participants = language_tracker.get_chat_participants(peer_id)
        target_languages = set()
        for participant in participants:
            if participant.user_id == user_id:
                continue
            if language_tracker.should_translate_for_user(peer_id, participant.user_id, detected_lang):
                target = participant.get_target_language()
                if target and target != detected_lang:
                    target_languages.add(target)
                    
        if not target_languages:
            default_target = await translation_service.get_target_language(detected_lang)
            if detected_lang != default_target:
                target_languages.add(default_target)
                
        # Editar cada una de las traducciones enviadas anteriormente
        translation_msg_ids = translation_mapping[key]
        
        for i, target_lang in enumerate(target_languages):
            if i >= len(translation_msg_ids):
                break
                
            translated = await translation_service.translate_to_target(text, target_lang)
            if translated:
                if translated.strip().lower() == text.strip().lower():
                    continue
                    
                msg_to_edit_id = translation_msg_ids[i]
                new_text = f"{sender_flag} {display_name}: {translated}"
                
                logger.info(f"📝 Actualizando traducción editada (ID: {msg_to_edit_id}) en chat {peer_id}")
                await message.ctx_api.messages.edit(
                    peer_id=peer_id,
                    message_id=msg_to_edit_id,
                    message=new_text,
                    keep_forward_messages=True
                )
    except Exception as e:
        logger.error(f"❌ Error al procesar mensaje editado: {e}")
