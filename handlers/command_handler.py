"""
Handler de Comandos para VK usando vkbottle BotLabeler
"""
from vkbottle.bot import BotLabeler, Message
from vkbottle import Keyboard, KeyboardButtonColor, Text

from config import settings, get_service_logger
from utils import user_stats

labeler = BotLabeler()
logger = get_service_logger("command_handler")


@labeler.message(text=["/start", "Начать"])
async def handle_start(message: Message):
    """Comando /start o botón Empezar de VK"""
    user_id = message.from_id
    user_stats.record_action(user_id, 'conversations')

    # Crear teclado de VK
    keyboard = Keyboard(one_time=False, inline=False)
    keyboard.add(Text("📖 Ayuda"), color=KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("🌍 Idiomas"), color=KeyboardButtonColor.SECONDARY)
    keyboard.row()
    keyboard.add(Text("📊 Estadísticas"), color=KeyboardButtonColor.SECONDARY)
    keyboard.add(Text("🧠 Mi Idioma"), color=KeyboardButtonColor.SECONDARY)

    welcome = (
        "¡Hola! 👋\n\n"
        "🤖 Bot Traductor Multilingüe con IA\n"
        "Powered by Gemini AI\n\n"
        "🌐 Traduzco entre idiomas eslavos y español/ruso\n"
        "🎙️ También puedo traducir mensajes de voz\n\n"
        "💡 Solo envía cualquier texto y lo traduciré automáticamente"
    )

    await message.answer(welcome, keyboard=keyboard.get_json(), random_id=0)


@labeler.message(text=["/help", "📖 Ayuda"])
async def handle_help(message: Message):
    """Comando /help"""
    user_id = message.from_id
    user_stats.record_action(user_id, 'help_requests')
    
    help_text = (
        "📖 GUÍA DEL BOT\n\n"
        "🌍 TRADUCTOR AUTOMÁTICO\n"
        "• Envía cualquier texto para traducir\n"
        "• Idiomas eslavos → Español\n"
        "• Otros idiomas → Ruso\n"
        "• Detección automática de idioma\n\n"
        "🎙️ TRADUCCIÓN DE VOZ\n"
        "• Envía un mensaje de voz\n"
        "• Transcripción automática con Gemini AI\n"
        "• Traducción automática del texto\n\n"
        "⚡ COMANDOS:\n"
        "• /start - Iniciar el bot\n"
        "• /help - Esta ayuda\n"
        "• /stats - Tus estadísticas\n"
        "• /idiomas - Idiomas soportados\n"
        "• /mi_idioma - Tu perfil lingüístico\n\n"
        "💡 Solo habla naturalmente conmigo"
    )
    await message.answer(help_text, random_id=0)


@labeler.message(text=["/stats", "📊 Estadísticas"])
async def handle_stats(message: Message):
    """Comando /stats"""
    user_id = message.from_id
    stats = user_stats.get_user_stats(user_id)

    if stats['is_new_user']:
        await message.answer("📊 Aún no tienes estadísticas. ¡Empieza a usar el bot!", random_id=0)
        return

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

    await message.answer(stats_text, random_id=0)


@labeler.message(text=["/languages", "/idiomas", "🌍 Idiomas"])
async def handle_languages(message: Message):
    """Comando /idiomas"""
    flags = {
        'ru': '🇷🇺', 'uk': '🇺🇦', 'bg': '🇧🇬', 'sr': '🇷🇸',
        'hr': '🇭🇷', 'cs': '🇨🇿', 'sk': '🇸🇰', 'pl': '🇵🇱',
        'sl': '🇸🇮', 'mk': '🇲🇰', 'bs': '🇧🇦'
    }

    lang_text = "🌍 IDIOMAS SOPORTADOS\n\nIDIOMAS ESLAVOS → Español 🌐\n\n"
    for code, name in settings.Translation.SLAVIC_LANGUAGES.items():
        flag = flags.get(code, '🏳️')
        lang_text += f"{flag} {name}\n"

    lang_text += (
        "\nOTROS IDIOMAS → Ruso 🇷🇺\n"
        "🌐 Inglés, Español, Francés, Alemán, Italiano, etc.\n\n"
        "👇 Selecciona tu idioma principal a continuación para configurarlo de inmediato:"
    )

    # Crear teclado inline para elegir idioma
    keyboard = Keyboard(one_time=False, inline=True)
    keyboard.add(Text("Español 🌐", {"set_lang": "es"}), color=KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("Ruso 🇷🇺", {"set_lang": "ru"}), color=KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("Búlgaro 🇧🇬", {"set_lang": "bg"}), color=KeyboardButtonColor.SECONDARY)
    keyboard.add(Text("Ucraniano 🇺🇦", {"set_lang": "uk"}), color=KeyboardButtonColor.SECONDARY)
    keyboard.row()
    keyboard.add(Text("Polaco 🇵🇱", {"set_lang": "pl"}), color=KeyboardButtonColor.SECONDARY)
    keyboard.add(Text("Checo 🇨🇿", {"set_lang": "cs"}), color=KeyboardButtonColor.SECONDARY)

    await message.answer(lang_text, keyboard=keyboard.get_json(), random_id=0)


@labeler.message(text=["/mi_idioma", "🧠 Mi Idioma"])
async def handle_my_language(message: Message):
    """Comando /mi_idioma — muestra el perfil lingüístico del usuario"""
    from services.user_language_service import language_tracker

    profile = language_tracker.get_profile(message.peer_id, message.from_id)

    if not profile or profile.total_messages < 3:
        await message.answer(
            "🤷 Aún no tengo suficientes datos sobre tu idioma.\n"
            "Envía al menos 3 mensajes para que pueda identificarte.",
            random_id=0
        )
        return

    lang_names = {
        'ru': 'Ruso 🇷🇺', 'uk': 'Ucraniano 🇺🇦', 'es': 'Español 🌐',
        'en': 'Inglés 🇬🇧', 'bg': 'Búlgaro 🇧🇬', 'sr': 'Serbio 🇷🇸',
        'hr': 'Croata 🇭🇷', 'cs': 'Checo 🇨🇿', 'pl': 'Polaco 🇵🇱',
        'de': 'Alemán 🇩🇪', 'fr': 'Francés 🇫🇷', 'it': 'Italiano 🇮🇹',
    }

    primary = lang_names.get(profile.primary_language, profile.primary_language)
    confidence_pct = round(profile.confidence * 100)

    text = (
        f"🧠 TU PERFIL LINGÜÍSTICO\n\n"
        f"👤 {profile.display_name}\n"
        f"🗣️ Idioma principal: {primary}\n"
        f"📊 Confianza: {confidence_pct}%\n"
        f"💬 Mensajes analizados: {profile.total_messages}\n\n"
    )

    # Mostrar distribución
    if len(profile.language_counts) > 1:
        text += "📈 Distribución:\n"
        sorted_langs = sorted(
            profile.language_counts.items(),
            key=lambda x: x[1], reverse=True
        )
        for lang_code, count in sorted_langs:
            name = lang_names.get(lang_code, lang_code)
            pct = round((count / profile.total_messages) * 100)
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            text += f"  {name}: {bar} {pct}%\n"

    text += (
        f"\n💡 Las traducciones se personalizan para ti.\n"
        f"Los mensajes se traducirán a tu idioma automáticamente."
    )

    await message.answer(text, random_id=0)


@labeler.message(text="/mi_bandera <flag>")
async def handle_set_flag(message: Message, flag: str):
    """Establece una bandera personalizada para el usuario"""
    from services.user_language_service import language_tracker
    
    flag = flag.strip()
    
    user_info = await message.ctx_api.users.get(user_ids=[message.from_id])
    display_name = user_info[0].first_name if user_info else f"User {message.from_id}"
    
    language_tracker.set_user_flag(message.peer_id, message.from_id, display_name, flag)
    
    await message.answer(
        f"✅ ¡Tu bandera ha sido actualizada! Ahora tus traducciones se mostrarán con: {flag}",
        random_id=0
    )


@labeler.message(text="/mi_bandera")
async def handle_set_flag_help(message: Message):
    """Muestra la ayuda para configurar la bandera"""
    help_text = (
        "🏳️ CONFIGURAR TU BANDERA/EMOJI\n\n"
        "Puedes elegir el emoji de bandera que prefieras para representarte en el grupo.\n\n"
        "💡 Modo de uso:\n"
        "Escribe /mi_bandera seguido del emoji de tu bandera.\n\n"
        "Ejemplos:\n"
        "• `/mi_bandera 🇲🇽` (México)\n"
        "• `/mi_bandera 🇨🇴` (Colombia)\n"
        "• `/mi_bandera 🇦🇷` (Argentina)\n"
        "• `/mi_bandera 🇪🇸` (España)\n"
        "• `/mi_bandera 🇻🇪` (Venezuela)\n\n"
        "🔄 Puedes usar cualquier emoji que te identifique."
    )
    await message.answer(help_text, random_id=0)
