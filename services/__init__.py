"""
Servicios del bot multilingüe inteligente para VK
"""

from .translation_service import TranslationService, translation_service
from .ai_service import AIService, ai_service
from .user_language_service import language_tracker

__all__ = [
    'TranslationService',
    'translation_service',
    'AIService',
    'ai_service',
    'language_tracker'
]
