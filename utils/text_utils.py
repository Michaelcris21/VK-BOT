"""
Utilidades de Texto para VK
Funciones para formateo, escape, validación y manipulación de texto plano
"""

import re
from typing import List, Tuple, Optional
from config import settings, get_service_logger


class TextFormatter:
    """Formateador de texto adaptado para VK (texto plano)"""
    
    def __init__(self):
        self.logger = get_service_logger("text_utils")
    
    # === ESCAPE Y FORMATEO ===
    
    def escape_markdown_v2(self, text: str) -> str:
        """VK no usa MarkdownV2, retorna el texto sin modificar"""
        return text
    
    def escape_html(self, text: str) -> str:
        """VK no usa HTML en mensajes de bot, retorna el texto sin modificar"""
        return text
    
    def format_user_mention(self, user_id: int, name: str, parse_mode: str = None) -> str:
        """
        Formatea mención de usuario para VK.
        Formato de VK: [id{user_id}|{name}]
        
        Args:
            user_id: ID del usuario de VK
            name: Nombre del usuario
            parse_mode: Ignorado en VK
            
        Returns:
            Mención formateada
        """
        clean_name = name.replace('|', '').replace('[', '').replace(']', '')
        return f"[id{user_id}|{clean_name}]"
    
    # === DIVISIÓN DE TEXTO LARGO ===
    
    def split_long_message(self, text: str, max_length: int = None) -> List[str]:
        """
        Divide texto largo en mensajes más pequeños respetando estructura
        
        Args:
            text: Texto a dividir
            max_length: Longitud máxima por mensaje
            
        Returns:
            Lista de mensajes divididos
        """
        if not max_length:
            max_length = settings.VK.MAX_MESSAGE_LENGTH
        
        if len(text) <= max_length:
            return [text]
        
        return self._smart_split_text(text, max_length)
    
    def _smart_split_text(self, text: str, max_length: int) -> List[str]:
        """División inteligente que respeta estructura del texto"""
        parts = []
        current_part = ""
        
        # Dividir por párrafos primero
        paragraphs = text.split('\n\n')
        
        for paragraph in paragraphs:
            # Si el párrafo + parte actual cabe, agregarlo
            potential_length = len(current_part) + len(paragraph) + (2 if current_part else 0)
            
            if potential_length <= max_length:
                if current_part:
                    current_part += '\n\n' + paragraph
                else:
                    current_part = paragraph
            else:
                # Guardar parte actual si existe
                if current_part:
                    parts.append(current_part.strip())
                    current_part = ""
                
                # Si el párrafo es muy largo, dividirlo por líneas
                if len(paragraph) > max_length:
                    parts.extend(self._split_paragraph(paragraph, max_length))
                else:
                    current_part = paragraph
        
        # Agregar última parte
        if current_part:
            parts.append(current_part.strip())
        
        return [part for part in parts if part.strip()]
    
    def _split_paragraph(self, paragraph: str, max_length: int) -> List[str]:
        """Divide un párrafo largo por líneas o oraciones"""
        parts = []
        
        # Intentar dividir por líneas
        lines = paragraph.split('\n')
        current_part = ""
        
        for line in lines:
            potential_length = len(current_part) + len(line) + (1 if current_part else 0)
            
            if potential_length <= max_length:
                if current_part:
                    current_part += '\n' + line
                else:
                    current_part = line
            else:
                if current_part:
                    parts.append(current_part.strip())
                    current_part = ""
                
                # Si la línea es muy larga, dividirla por oraciones
                if len(line) > max_length:
                    parts.extend(self._split_by_sentences(line, max_length))
                else:
                    current_part = line
        
        if current_part:
            parts.append(current_part.strip())
        
        return parts
    
    def _split_by_sentences(self, text: str, max_length: int) -> List[str]:
        """Divide texto por oraciones"""
        # Patrones para fin de oración
        sentence_endings = r'[.!?]+\s+'
        sentences = re.split(f'({sentence_endings})', text)
        
        parts = []
        current_part = ""
        
        i = 0
        while i < len(sentences):
            sentence = sentences[i]
            
            # Si es un separador, combinarlo con la oración anterior
            if i + 1 < len(sentences) and re.match(sentence_endings, sentences[i + 1]):
                sentence += sentences[i + 1]
                i += 2
            else:
                i += 1
            
            potential_length = len(current_part) + len(sentence)
            
            if potential_length <= max_length:
                current_part += sentence
            else:
                if current_part:
                    parts.append(current_part.strip())
                
                # Si la oración es muy larga, dividirla por chunks
                if len(sentence) > max_length:
                    parts.extend(self._split_by_chunks(sentence, max_length))
                    current_part = ""
                else:
                    current_part = sentence
        
        if current_part:
            parts.append(current_part.strip())
        
        return parts
    
    def _split_by_chunks(self, text: str, max_length: int) -> List[str]:
        """División final por chunks de tamaño fijo"""
        parts = []
        
        for i in range(0, len(text), max_length):
            chunk = text[i:i + max_length]
            parts.append(chunk)
        
        return parts
    
    # === VALIDACIÓN DE TEXTO ===
    
    def is_valid_text_for_translation(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        Valida si un texto es válido para traducción
        
        Returns:
            Tupla (es_válido, mensaje_error)
        """
        if not text or not text.strip():
            return False, "Texto vacío"
        
        if len(text.strip()) < 2:
            return False, "Texto muy corto"
        
        # Debe contener al menos algunas letras
        if not re.search(r'[a-zA-Zа-яё]', text):
            return False, "No contiene texto alfabético"
        
        # Verificar si es solo URLs o símbolos
        text_without_urls = re.sub(settings.Patterns.URL_PATTERN, '', text)
        clean_text = re.sub(r'[^\w\s]', '', text_without_urls)
        
        if len(clean_text.strip()) < 2:
            return False, "Solo contiene URLs o símbolos"
        
        return True, None
    
    def clean_text_for_processing(self, text: str) -> str:
        """Limpia texto para mejor procesamiento"""
        # Normalizar espacios
        text = re.sub(r'\s+', ' ', text)
        
        # Remover caracteres de control
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        
        # Limpiar y retornar
        return text.strip()
    
    # === EXTRACCIÓN DE URLs ===
    
    def extract_urls_with_placeholders(self, text: str, placeholder: str = None) -> Tuple[str, List[str]]:
        """
        Extrae URLs del texto y las reemplaza con placeholders
        
        Args:
            text: Texto original
            placeholder: Placeholder a usar (por defecto usa el de settings)
            
        Returns:
            Tupla (texto_con_placeholders, lista_urls)
        """
        if not placeholder:
            placeholder = settings.Translation.LINK_PLACEHOLDER
        
        urls = []
        url_pattern = re.compile(settings.Patterns.URL_PATTERN)
        
        def replace_url(match):
            urls.append(match.group(0))
            return placeholder
        
        text_with_placeholders = url_pattern.sub(replace_url, text)
        
        return text_with_placeholders, urls


# Instancia global
text_formatter = TextFormatter()
