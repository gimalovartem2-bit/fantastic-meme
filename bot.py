import logging
import re
import json
import aiohttp
import ssl
from collections import Counter
import sys
from typing import Dict, List, Optional, Tuple
import asyncio
import base64
import uuid
import requests

# Проверка версии Python
print(f"Python version: {sys.version}")

try:
    from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        ConversationHandler,
        ContextTypes,
        filters
    )

    print("Библиотеки telegram успешно импортированы")
except ImportError as e:
    print(f"Ошибка импорта: {e}")
    print("\nПожалуйста, установите библиотеку:")
    print("1. Откройте терминал PyCharm (вкладка Terminal внизу)")
    print("2. Введите: pip install python-telegram-bot")
    print("3. Или: python -m pip install python-telegram-bot")
    sys.exit(1)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== НАСТРОЙКИ GIGACHAT API ====================
GIGACHAT_CLIENT_ID = "019c1ed5-8a08-703f-a5d8-71572a5105d2"
GIGACHAT_CLIENT_SECRET = "MDE5YzFlZDUtOGEwOC03MDNmLWE1ZDgtNzE1NzJhNTEwNWQyOjkwYzJjNDk1LTNhYzYtNDlmMC1hMmRlLTdjNjQ5OWQ3ZjI4Yg=="
GIGACHAT_SCOPE = "GIGACHAT_API_PERS"

# URL для авторизации и запросов
GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"


# ==================== БАЗОВЫЙ КЛАСС ДЛЯ GIGACHAT API ====================

class GigaChatBase:
    """Базовый класс для работы с GigaChat API"""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expiry = 0
        self.session: Optional[aiohttp.ClientSession] = None
        self.timeout = aiohttp.ClientTimeout(total=45)

        # SSL контекст
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    async def get_session(self) -> aiohttp.ClientSession:
        """Создает или возвращает существующую сессию"""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(ssl=self.ssl_context)
            self.session = aiohttp.ClientSession(timeout=self.timeout, connector=connector)
        return self.session

    async def get_access_token(self) -> Optional[str]:
        """Получает access token для GigaChat API"""
        import time
        if self.access_token and time.time() < self.token_expiry:
            return self.access_token

        try:
            session = await self.get_session()

            # Используем client_secret напрямую как base64
            auth_base64 = self.client_secret

            headers = {
                'Authorization': f'Basic {auth_base64}',
                'RqUID': str(uuid.uuid4()),
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            }

            data = {'scope': GIGACHAT_SCOPE}

            async with session.post(GIGACHAT_AUTH_URL, headers=headers, data=data, ssl=self.ssl_context) as response:
                response_text = await response.text()

                if response.status == 200:
                    result = json.loads(response_text)
                    self.access_token = result.get('access_token')
                    expires_in = result.get('expires_in', 1800)
                    self.token_expiry = time.time() + expires_in - 300
                    logger.info(f"✅ Токен GigaChat получен")
                    return self.access_token
                else:
                    logger.error(f"❌ Ошибка получения токена: {response.status}")
                    return None

        except Exception as e:
            logger.error(f"❌ Ошибка при получении токена: {e}")
            return None

    async def make_gigachat_request(self, system_prompt: str, user_prompt: str) -> Optional[Dict]:
        """Делает запрос к GigaChat API"""
        access_token = await self.get_access_token()
        if not access_token:
            return None

        try:
            session = await self.get_session()

            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }

            data = {
                "model": "GigaChat",
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 2000,
                "stream": False
            }

            async with session.post(GIGACHAT_API_URL, headers=headers, json=data, ssl=self.ssl_context) as response:
                if response.status == 200:
                    result = await response.json()
                    if 'choices' in result and len(result['choices']) > 0:
                        message = result['choices'][0].get('message', {})
                        return {'success': True, 'response': message.get('content', '')}

                return {'success': False, 'error': f'Status: {response.status}'}

        except Exception as e:
            logger.error(f"❌ Ошибка запроса к GigaChat: {e}")
            return {'success': False, 'error': str(e)}

    async def close(self):
        """Закрывает сессию"""
        if self.session and not self.session.closed:
            await self.session.close()


# ==================== УНИВЕРСАЛЬНЫЙ ИИ-АНАЛИЗАТОР ====================

class GigaChatUniversalAnalyzer(GigaChatBase):
    """Универсальный класс для анализа текста через GigaChat"""

    async def analyze_text(self, text: str, analysis_type: str) -> Dict:
        """Универсальный анализ текста"""
        if not text.strip():
            return {
                'success': True,
                'analysis': 'Текст пустой',
                'analysis_type': analysis_type,
                'source': 'gigachat'
            }

        # Определяем system_prompt в зависимости от типа анализа
        system_prompts = {
            'text_analysis': """Ты эксперт по лингвистическому анализу текста. Проанализируй текст и предоставь подробный анализ в JSON формате:
            {
                "statistics": {
                    "characters": число,
                    "words": число, 
                    "sentences": число,
                    "average_word_length": число,
                    "average_sentence_length": число
                },
                "language_style": "описание стиля (разговорный/официальный/художественный и т.д.)",
                "complexity": "оценка сложности (простой/средний/сложный)",
                "readability_score": число от 0 до 100,
                "key_themes": ["тема1", "тема2", "тема3"],
                "emotional_tone": "эмоциональная окраска",
                "recommendations": ["рекомендация1", "рекомендация2"]
            }
            Отвечай ТОЛЬКО в JSON формате, без дополнительного текста.""",

            'morphology': """Ты эксперт по морфологии русского языка. Сделай полный морфологический разбор слова. Отвечай в JSON формате:
            {
                "word": "исходное слово",
                "part_of_speech": "часть речи",
                "grammatical_features": {
                    "case": "падеж",
                    "number": "число",
                    "gender": "род", 
                    "person": "лицо",
                    "tense": "время",
                    "mood": "наклонение",
                    "voice": "залог",
                    "aspect": "вид"
                },
                "initial_form": "начальная форма",
                "morphological_analysis": "подробный разбор по составу",
                "syntactic_role": "синтаксическая роль в предложении",
                "examples": ["пример1", "пример2"]
            }
            Если слово не существует или некорректно, верни ошибку в поле "error".
            Отвечай ТОЛЬКО в JSON формате.""",

            'phonetics': """Ты эксперт по фонетике русского языка. Сделай фонетический анализ слова. Отвечай в JSON формате:
            {
                "word": "исходное слово",
                "transcription": "транскрипция в квадратных скобках",
                "syllables": ["слог1", "слог2"],
                "syllable_count": число,
                "stress_syllable": номер ударного слога (начиная с 1),
                "sound_analysis": {
                    "vowels": число,
                    "consonants": число,
                    "voiced_consonants": число,
                    "voiceless_consonants": число,
                    "hard_consonants": число,
                    "soft_consonants": число
                },
                "sound_letter_analysis": "подробный разбор звук-буква",
                "phonetic_features": ["особенность1", "особенность2"]
            }
            Отвечай ТОЛЬКО в JSON формате.""",

            'synonyms': """Ты эксперт по лексикологии русского языка. Найди синонимы, антонимы и родственные слова. Отвечай в JSON формате:
            {
                "word": "исходное слово",
                "synonyms": ["синоним1", "синоним2", "синоним3"],
                "antonyms": ["антоним1", "антоним2"],
                "related_words": ["родственное1", "родственное2"],
                "word_family": "словообразовательное гнездо",
                "etymology": "краткая этимология",
                "usage_examples": ["пример1", "пример2"],
                "stylistic_notes": "стилистические пометы"
            }
            Отвечай ТОЛЬКО в JSON формате.""",

            'language_detection': """Ты эксперт по определению языков. Определи язык(и) текста и предоставь анализ. Отвечай в JSON формате:
            {
                "detected_languages": [
                    {
                        "language": "название языка",
                        "confidence": число от 0 до 100,
                        "code": "код языка"
                    }
                ],
                "primary_language": "основной язык",
                "is_mixed": true/false,
                "language_features": ["особенность1", "особенность2"],
                "translation_hint": "подсказка для перевода"
            }
            Отвечай ТОЛЬКО в JSON формате.""",

            'stylistics': """Ты эксперт по стилистике русского языка. Проанализируй стилистические особенности текста. Отвечай в JSON формате:
            {
                "style_type": "тип стиля",
                "stylistic_features": ["особенность1", "особенность2"],
                "tone": "тон текста",
                "formality_level": "уровень формальности",
                "vocabulary_richness": "богатство словаря",
                "sentence_variety": "разнообразие предложений",
                "stylistic_errors": ["ошибка1", "ошибка2"],
                "improvement_suggestions": ["совет1", "совет2"],
                "overall_impression": "общее впечатление"
            }
            Отвечай ТОЛЬКО в JSON формате.""",

            'etymology': """Ты эксперт по этимологии русского языка. Исследуй происхождение слова. Отвечай в JSON формате:
            {
                "word": "исходное слово",
                "origin": "происхождение",
                "historical_forms": ["форма1", "форма2"],
                "root": "корень",
                "cognates": ["родственное1", "родственное2"],
                "borrowing_source": "источник заимствования (если есть)",
                "meaning_evolution": "эволюция значения",
                "interesting_facts": ["факт1", "факт2"]
            }
            Отвечай ТОЛЬКО в JSON формате."""
        }

        system_prompt = system_prompts.get(analysis_type, system_prompts['text_analysis'])

        # Определяем user_prompt в зависимости от типа анализа
        user_prompts = {
            'text_analysis': f"""Проанализируй следующий текст:

            "{text}"

            Предоставь полный лингвистический анализ.""",

            'morphology': f"""Сделай полный морфологический разбор слова: "{text}"

            Укажи все грамматические признаки и синтаксическую роль.""",

            'phonetics': f"""Сделай фонетический анализ слова: "{text}"

            Укажи транскрипцию, слоги, ударение и звуковой состав.""",

            'synonyms': f"""Найди синонимы, антонимы и родственные слова для: "{text}"

            Также укажи этимологию и примеры использования.""",

            'language_detection': f"""Определи язык(и) следующего текста:

            "{text}"

            Укажи с уверенностью в процентах.""",

            'stylistics': f"""Проанализируй стилистические особенности текста:

            "{text}"

            Укажи стилистические ошибки и предложи улучшения.""",

            'etymology': f"""Исследуй происхождение слова: "{text}"

            Укажи исторические формы и родственные слова."""
        }

        user_prompt = user_prompts.get(analysis_type, user_prompts['text_analysis'])

        result = await self.make_gigachat_request(system_prompt, user_prompt)

        if result.get('success', False):
            response_text = result.get('response', '')
            return self._parse_analysis_response(response_text, analysis_type, text)
        else:
            return self._create_fallback_response(text, analysis_type, result.get('error', 'Ошибка API'))

    def _parse_analysis_response(self, response_text: str, analysis_type: str, original_text: str) -> Dict:
        """Парсит ответ от GigaChat для универсального анализа"""
        try:
            # Очищаем ответ
            clean_response = self._clean_json_response(response_text)

            # Пробуем распарсить JSON
            try:
                parsed = json.loads(clean_response)
            except json.JSONDecodeError:
                # Если не JSON, возвращаем как текст
                return {
                    'success': True,
                    'analysis_type': analysis_type,
                    'analysis': clean_response,
                    'original_text': original_text,
                    'source': 'gigachat_text'
                }

            # Форматируем ответ в зависимости от типа анализа
            formatted_response = self._format_analysis(parsed, analysis_type, original_text)

            return {
                'success': True,
                'analysis_type': analysis_type,
                'analysis': formatted_response,
                'parsed_data': parsed,
                'original_text': original_text,
                'source': 'gigachat'
            }

        except Exception as e:
            logger.error(f"Ошибка парсинга анализа {analysis_type}: {e}")
            return self._create_fallback_response(original_text, analysis_type, "Ошибка парсинга ответа")

    def _format_analysis(self, parsed_data: Dict, analysis_type: str, original_text: str) -> str:
        """Форматирует анализ для красивого вывода"""

        if analysis_type == 'text_analysis':
            stats = parsed_data.get('statistics', {})
            return (
                    f"📊 <b>Полный анализ текста:</b>\n\n"
                    f"<b>Статистика:</b>\n"
                    f"• Символов: {stats.get('characters', 'N/A')}\n"
                    f"• Слов: {stats.get('words', 'N/A')}\n"
                    f"• Предложений: {stats.get('sentences', 'N/A')}\n"
                    f"• Ср. длина слова: {stats.get('average_word_length', 'N/A')}\n"
                    f"• Ср. длина предложения: {stats.get('average_sentence_length', 'N/A')}\n\n"
                    f"<b>Стиль языка:</b> {parsed_data.get('language_style', 'N/A')}\n"
                    f"<b>Сложность:</b> {parsed_data.get('complexity', 'N/A')}\n"
                    f"<b>Читаемость:</b> {parsed_data.get('readability_score', 'N/A')}/100\n"
                    f"<b>Эмоциональный тон:</b> {parsed_data.get('emotional_tone', 'N/A')}\n\n"
                    f"<b>Ключевые темы:</b>\n" + "\n".join(
                [f"• {theme}" for theme in parsed_data.get('key_themes', [])]) + "\n\n"
                                                                                 f"<b>Рекомендации:</b>\n" + "\n".join(
                [f"• {rec}" for rec in parsed_data.get('recommendations', [])])
            )

        elif analysis_type == 'morphology':
            features = parsed_data.get('grammatical_features', {})
            return (
                    f"🔤 <b>Морфологический разбор слова '{original_text}':</b>\n\n"
                    f"<b>Часть речи:</b> {parsed_data.get('part_of_speech', 'N/A')}\n"
                    f"<b>Начальная форма:</b> {parsed_data.get('initial_form', 'N/A')}\n\n"
                    f"<b>Грамматические признаки:</b>\n"
                    f"• Падеж: {features.get('case', 'N/A')}\n"
                    f"• Число: {features.get('number', 'N/A')}\n"
                    f"• Род: {features.get('gender', 'N/A')}\n"
                    f"• Лицо: {features.get('person', 'N/A')}\n"
                    f"• Время: {features.get('tense', 'N/A')}\n"
                    f"• Наклонение: {features.get('mood', 'N/A')}\n"
                    f"• Залог: {features.get('voice', 'N/A')}\n"
                    f"• Вид: {features.get('aspect', 'N/A')}\n\n"
                    f"<b>Морфемный разбор:</b>\n{parsed_data.get('morphological_analysis', 'N/A')}\n\n"
                    f"<b>Синтаксическая роль:</b> {parsed_data.get('syntactic_role', 'N/A')}\n\n"
                    f"<b>Примеры использования:</b>\n" + "\n".join(
                [f"• {ex}" for ex in parsed_data.get('examples', [])])
            )

        elif analysis_type == 'phonetics':
            sound_analysis = parsed_data.get('sound_analysis', {})
            return (
                    f"🎵 <b>Фонетический анализ слова '{original_text}':</b>\n\n"
                    f"<b>Транскрипция:</b> {parsed_data.get('transcription', 'N/A')}\n"
                    f"<b>Слоги:</b> {'-'.join(parsed_data.get('syllables', []))}\n"
                    f"<b>Количество слогов:</b> {parsed_data.get('syllable_count', 'N/A')}\n"
                    f"<b>Ударный слог:</b> {parsed_data.get('stress_syllable', 'N/A')}\n\n"
                    f"<b>Звуковой состав:</b>\n"
                    f"• Гласных: {sound_analysis.get('vowels', 'N/A')}\n"
                    f"• Согласных: {sound_analysis.get('consonants', 'N/A')}\n"
                    f"• Звонких согласных: {sound_analysis.get('voiced_consonants', 'N/A')}\n"
                    f"• Глухих согласных: {sound_analysis.get('voiceless_consonants', 'N/A')}\n"
                    f"• Твёрдых согласных: {sound_analysis.get('hard_consonants', 'N/A')}\n"
                    f"• Мягких согласных: {sound_analysis.get('soft_consonants', 'N/A')}\n\n"
                    f"<b>Звуко-буквенный анализ:</b>\n{parsed_data.get('sound_letter_analysis', 'N/A')}\n\n"
                    f"<b>Фонетические особенности:</b>\n" + "\n".join(
                [f"• {feature}" for feature in parsed_data.get('phonetic_features', [])])
            )

        elif analysis_type == 'synonyms':
            return (
                    f"📚 <b>Лексический анализ слова '{original_text}':</b>\n\n"
                    f"<b>Синонимы:</b>\n" + "\n".join([f"• {syn}" for syn in parsed_data.get('synonyms', [])]) + "\n\n"
                                                                                                                 f"<b>Антонимы:</b>\n" + "\n".join(
                [f"• {ant}" for ant in parsed_data.get('antonyms', [])]) + "\n\n"
                                                                           f"<b>Родственные слова:</b>\n" + "\n".join(
                [f"• {rel}" for rel in parsed_data.get('related_words', [])]) + "\n\n"
                                                                                f"<b>Словообразовательное гнездо:</b>\n{parsed_data.get('word_family', 'N/A')}\n\n"
                                                                                f"<b>Этимология:</b>\n{parsed_data.get('etymology', 'N/A')}\n\n"
                                                                                f"<b>Примеры использования:</b>\n" + "\n".join(
                [f"• {ex}" for ex in parsed_data.get('usage_examples', [])]) + "\n\n"
                                                                               f"<b>Стилистические пометы:</b>\n{parsed_data.get('stylistic_notes', 'N/A')}"
            )

        elif analysis_type == 'language_detection':
            languages = parsed_data.get('detected_languages', [])
            lang_list = "\n".join([f"• {lang.get('language')}: {lang.get('confidence')}%" for lang in languages])
            return (
                    f"🌍 <b>Определение языка текста:</b>\n\n"
                    f"<b>Обнаруженные языки:</b>\n{lang_list}\n\n"
                    f"<b>Основной язык:</b> {parsed_data.get('primary_language', 'N/A')}\n"
                    f"<b>Смешанный текст:</b> {'Да' if parsed_data.get('is_mixed', False) else 'Нет'}\n\n"
                    f"<b>Языковые особенности:</b>\n" + "\n".join(
                [f"• {feature}" for feature in parsed_data.get('language_features', [])]) + "\n\n"
                                                                                            f"<b>Подсказка для перевода:</b>\n{parsed_data.get('translation_hint', 'N/A')}"
            )

        elif analysis_type == 'stylistics':
            return (
                    f"🎨 <b>Стилистический анализ текста:</b>\n\n"
                    f"<b>Тип стиля:</b> {parsed_data.get('style_type', 'N/A')}\n"
                    f"<b>Тон текста:</b> {parsed_data.get('tone', 'N/A')}\n"
                    f"<b>Уровень формальности:</b> {parsed_data.get('formality_level', 'N/A')}\n"
                    f"<b>Богатство словаря:</b> {parsed_data.get('vocabulary_richness', 'N/A')}\n"
                    f"<b>Разнообразие предложений:</b> {parsed_data.get('sentence_variety', 'N/A')}\n\n"
                    f"<b>Стилистические особенности:</b>\n" + "\n".join(
                [f"• {feature}" for feature in parsed_data.get('stylistic_features', [])]) + "\n\n"
                                                                                             f"<b>Стилистические ошибки:</b>\n" + (
                        "\n".join(
                            [f"• {error}" for error in parsed_data.get('stylistic_errors', [])]) if parsed_data.get(
                            'stylistic_errors') else "• Не обнаружено") + "\n\n"
                                                                          f"<b>Предложения по улучшению:</b>\n" + "\n".join(
                [f"• {suggestion}" for suggestion in parsed_data.get('improvement_suggestions', [])]) + "\n\n"
                                                                                                        f"<b>Общее впечатление:</b>\n{parsed_data.get('overall_impression', 'N/A')}"
            )

        elif analysis_type == 'etymology':
            return (
                    f"📜 <b>Этимологический анализ слова '{original_text}':</b>\n\n"
                    f"<b>Происхождение:</b>\n{parsed_data.get('origin', 'N/A')}\n\n"
                    f"<b>Исторические формы:</b>\n" + "\n".join(
                [f"• {form}" for form in parsed_data.get('historical_forms', [])]) + "\n\n"
                                                                                     f"<b>Корень:</b> {parsed_data.get('root', 'N/A')}\n\n"
                                                                                     f"<b>Родственные слова:</b>\n" + "\n".join(
                [f"• {cognate}" for cognate in parsed_data.get('cognates', [])]) + "\n\n"
                                                                                   f"<b>Источник заимствования:</b> {parsed_data.get('borrowing_source', 'Не заимствовано')}\n\n"
                                                                                   f"<b>Эволюция значения:</b>\n{parsed_data.get('meaning_evolution', 'N/A')}\n\n"
                                                                                   f"<b>Интересные факты:</b>\n" + "\n".join(
                [f"• {fact}" for fact in parsed_data.get('interesting_facts', [])])
            )

        else:
            # Для неизвестных типов возвращаем JSON как текст
            return f"<b>Анализ ({analysis_type}):</b>\n{json.dumps(parsed_data, ensure_ascii=False, indent=2)}"

    def _clean_json_response(self, text: str) -> str:
        """Очищает текст для парсинга JSON"""
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)

        start = text.find('{')
        end = text.rfind('}')

        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]

        return text.strip()

    def _create_fallback_response(self, text: str, analysis_type: str, error_msg: str) -> Dict:
        """Создает ответ при ошибке"""
        return {
            'success': False,
            'analysis_type': analysis_type,
            'analysis': f'ИИ анализ недоступен: {error_msg}',
            'original_text': text,
            'source': 'error'
        }


# ==================== КЛАСС ДЛЯ ПРОВЕРКИ ГРАММАТИКИ ====================

class GigaChatGrammarChecker(GigaChatBase):
    """Класс для проверки грамматики и пунктуации через GigaChat"""

    async def check_grammar(self, text: str) -> Dict:
        """Проверяет грамматику и пунктуацию"""
        if not text.strip():
            return {
                'success': True,
                'ai_comment': 'Текст пустой',
                'has_errors': False,
                'source': 'gigachat'
            }

        system_prompt = """Ты эксперт по русской грамматике и пунктуации. Проанализируй текст на:

1. ОБЯЗАТЕЛЬНО проверь запятые:
   - Перед союзами "а", "но", "да" (в значении "но"), "однако", "зато" в сложносочиненных предложениях
   - Перед союзами "что", "чтобы", "когда", "потому что", "так как", "если" в сложноподчиненных предложениях
   - В сложных предложениях между частями
   - При однородных членах с союзами "а", "но", "и", "или"

2. Проверь пунктуацию:
   - Запятые в причастных и деепричастных оборотах
   - Тире между подлежащим и сказуемым
   - Двоеточия при перечислениях и пояснениях
   - Кавычки в прямой речи

3. Грамматические ошибки:
   - Согласование подлежащего и сказуемого
   - Управление (падежи после предлогов и глаголов)
   - Видо-временные формы глаголов

4. Стилистические ошибки

Отвечай только в JSON формате: {
    "issues": [{
        "type": "тип ошибки (пунктуация/грамматика/стилистика)",
        "original": "фрагмент с ошибкой", 
        "corrected": "исправленный фрагмент", 
        "explanation": "подробное объяснение правила",
        "severity": "уровень серьезности (низкий/средний/высокий)"
    }], 
    "corrected_text": "полностью исправленный текст с правильной пунктуацией", 
    "ai_comment": "общий анализ текста", 
    "issue_count": число,
    "score": число от 0 до 100
}"""

        user_prompt = f"""Проанализируй грамматику и пунктуацию следующего текста:

        "{text}"

        **ВНИМАНИЕ: Обрати особое внимание на запятые:**
        1. Перед союзами "а", "но", "однако", "зато" - всегда ставится запятая в сложносочиненных предложениях
        2. Перед "что", "чтобы", "потому что", "так как", "если", "когда" - в сложноподчиненных предложениях
        3. Между частями сложного предложения
        4. При однородных членах предложения

        **Примеры правильной расстановки:**
        - "Я хотел поехать в отпуск, а на работе сказали..."
        - "Мама сказала, что придут гости"
        - "Он устал, поэтому лег спать"
        - "Я купил хлеб, молоко и сыр"

        Найди ВСЕ ошибки в тексте и исправь их."""

        result = await self.make_gigachat_request(system_prompt, user_prompt)

        if result.get('success', False):
            response_text = result.get('response', '')
            return self._parse_grammar_response(response_text, text)
        else:
            return self._create_fallback_response(text, result.get('error', 'Ошибка API'))

    def _parse_grammar_response(self, response_text: str, original_text: str) -> Dict:
        """Парсит ответ от GigaChat для проверки грамматики"""
        try:
            # Очищаем ответ
            clean_response = self._clean_json_response(response_text)
            parsed = json.loads(clean_response)

            issues = parsed.get('issues', [])
            corrected_text = parsed.get('corrected_text', original_text)
            ai_comment = parsed.get('ai_comment', '')
            issue_count = parsed.get('issue_count', len(issues))
            score = parsed.get('score', max(0, 100 - (issue_count * 5)))

            # Извлекаем информацию об ошибках
            issue_list = []
            correction_list = []
            explanation_list = []
            type_list = []
            severity_list = []

            for issue in issues:
                if isinstance(issue, dict):
                    issue_type = issue.get('type', 'грамматика')
                    original = issue.get('original', '')
                    corrected = issue.get('corrected', '')
                    explanation = issue.get('explanation', '')
                    severity = issue.get('severity', 'средний')

                    if original:
                        issue_list.append(original)
                        correction_list.append(corrected)
                        explanation_list.append(explanation)
                        type_list.append(issue_type)
                        severity_list.append(severity)

            return {
                'issues': issue_list,
                'corrections': correction_list,
                'explanations': explanation_list,
                'types': type_list,
                'severities': severity_list,
                'corrected_text': corrected_text,
                'ai_comment': ai_comment,
                'total_sentences': len(re.split(r'[.!?]+', original_text)),
                'total_chars': len(original_text),
                'issue_count': issue_count,
                'score': score,
                'has_issues': issue_count > 0,
                'success': True,
                'source': 'gigachat_grammar'
            }

        except json.JSONDecodeError:
            return self._create_text_response(response_text, original_text)
        except Exception as e:
            logger.error(f"Ошибка парсинга грамматики: {e}")
            return self._create_fallback_response(original_text, "Ошибка парсинга ответа")

    def _clean_json_response(self, text: str) -> str:
        """Очищает текст для парсинга JSON"""
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)

        start = text.find('{')
        end = text.rfind('}')

        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]

        return text.strip()

    def _create_text_response(self, response_text: str, original_text: str) -> Dict:
        """Создает ответ из текста"""
        return {
            'issues': [],
            'corrections': [],
            'explanations': [],
            'types': [],
            'severities': [],
            'corrected_text': original_text,
            'ai_comment': response_text[:300] if response_text else "ИИ дал рекомендации по грамматике",
            'total_sentences': len(re.split(r'[.!?]+', original_text)),
            'total_chars': len(original_text),
            'issue_count': 0,
            'score': 100,
            'has_issues': False,
            'success': True,
            'source': 'gigachat_text'
        }

    def _create_fallback_response(self, text: str, error_msg: str) -> Dict:
        """Создает ответ при ошибке"""
        return {
            'issues': [],
            'corrections': [],
            'explanations': [],
            'types': [],
            'severities': [],
            'corrected_text': text,
            'ai_comment': f'ИИ проверка грамматики недоступна: {error_msg}',
            'total_sentences': len(re.split(r'[.!?]+', text)),
            'total_chars': len(text),
            'issue_count': 0,
            'score': 0,
            'has_issues': False,
            'success': False,
            'source': 'error'
        }


# ==================== КЛАСС ДЛЯ ПРОВЕРКИ ОРФОГРАФИИ ====================

class GigaChatSpellChecker(GigaChatBase):
    """Класс для проверки орфографии через GigaChat"""

    async def check_spelling(self, text: str) -> Dict:
        """Проверяет орфографию и грамматику"""
        if not text.strip():
            return {
                'success': True,
                'ai_comment': 'Текст пустой',
                'has_errors': False,
                'source': 'gigachat'
            }

        system_prompt = """Ты эксперт по русскому языку. Найди и исправь орфографические и грамматические ошибки в тексте. 
        Отвечай только в JSON формате: {
            "errors": [{"original": "слово", "corrected": "исправление", "explanation": "объяснение"}], 
            "corrected_text": "исправленный текст", 
            "ai_comment": "комментарий", 
            "error_count": число,
            "accuracy_score": число от 0 до 100
        }"""

        user_prompt = f"""Проверь орфографию и грамматику текста: "{text}"
        Если ошибок нет, верни пустой массив errors."""

        result = await self.make_gigachat_request(system_prompt, user_prompt)

        if result.get('success', False):
            response_text = result.get('response', '')
            return self._parse_spelling_response(response_text, text)
        else:
            return self._create_fallback_response(text, result.get('error', 'Ошибка API'))

    def _parse_spelling_response(self, response_text: str, original_text: str) -> Dict:
        """Парсит ответ от GigaChat для проверки орфографии"""
        try:
            # Очищаем ответ
            clean_response = self._clean_json_response(response_text)
            parsed = json.loads(clean_response)

            errors = parsed.get('errors', [])
            corrected_text = parsed.get('corrected_text', original_text)
            ai_comment = parsed.get('ai_comment', '')
            error_count = parsed.get('error_count', len(errors))
            accuracy_score = parsed.get('accuracy_score', max(0, 100 - (error_count * 10)))

            # Извлекаем ошибки
            error_list = []
            suggestion_list = []
            explanation_list = []

            for error in errors:
                if isinstance(error, dict):
                    original = error.get('original', '')
                    corrected = error.get('corrected', '')
                    explanation = error.get('explanation', '')

                    if original and corrected:
                        error_list.append(original)
                        suggestion_list.append(corrected)
                        explanation_list.append(explanation)

            return {
                'errors': error_list,
                'suggestions': suggestion_list,
                'explanations': explanation_list,
                'corrected_text': corrected_text,
                'ai_comment': ai_comment,
                'total_words': len(re.findall(r'\b\w+\b', original_text)),
                'error_words': error_count,
                'has_errors': error_count > 0,
                'accuracy_score': accuracy_score,
                'success': True,
                'source': 'gigachat_spelling'
            }

        except json.JSONDecodeError:
            return self._create_text_response(response_text, original_text)
        except Exception as e:
            logger.error(f"Ошибка парсинга: {e}")
            return self._create_fallback_response(original_text, "Ошибка парсинга ответа")

    def _clean_json_response(self, text: str) -> str:
        """Очищает текст для парсинга JSON"""
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)

        start = text.find('{')
        end = text.rfind('}')

        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]

        return text.strip()

    def _create_text_response(self, response_text: str, original_text: str) -> Dict:
        """Создает ответ из текста"""
        return {
            'errors': [],
            'suggestions': [],
            'explanations': [],
            'corrected_text': original_text,
            'ai_comment': response_text[:300] if response_text else "ИИ дал рекомендации",
            'total_words': len(re.findall(r'\b\w+\b', original_text)),
            'error_words': 0,
            'has_errors': False,
            'accuracy_score': 100,
            'success': True,
            'source': 'gigachat_text'
        }

    def _create_fallback_response(self, text: str, error_msg: str) -> Dict:
        """Создает ответ при ошибке"""
        return {
            'errors': [],
            'suggestions': [],
            'explanations': [],
            'corrected_text': text,
            'ai_comment': f'ИИ проверка недоступна: {error_msg}',
            'has_errors': False,
            'accuracy_score': 0,
            'success': False,
            'source': 'error'
        }


# ==================== КОМБИНИРОВАННЫЙ ПРОВЕРЯЛЬЩИК ====================

class CombinedAnalyzer:
    """Комбинированный анализатор с GigaChat AI"""

    def __init__(self, gigachat_client_id: str = None, gigachat_client_secret: str = None):
        self.universal_analyzer = None
        self.grammar_checker = None
        self.spell_checker = None

        # Инициализируем анализаторы GigaChat
        if gigachat_client_id and gigachat_client_secret:
            try:
                self.universal_analyzer = GigaChatUniversalAnalyzer(gigachat_client_id, gigachat_client_secret)
                self.grammar_checker = GigaChatGrammarChecker(gigachat_client_id, gigachat_client_secret)
                self.spell_checker = GigaChatSpellChecker(gigachat_client_id, gigachat_client_secret)
                logger.info("✅ Все ИИ анализаторы инициализированы")
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации GigaChat анализаторов: {e}")

        # Локальный словарь ошибок
        self.common_errors = {
            'здраствуйте': ('здравствуйте', 'Неправильное написание приветствия'),
            'зделать': ('сделать', 'Неправильная приставка'),
            'придти': ('прийти', 'Устаревшая форма глагола'),
            'ихний': ('их', 'Просторечное выражение'),
            'ложить': ('класть', 'Глагол "ложить" используется только с приставками'),
            'одел': ('надел', 'Путаница с глаголами одевать/надевать'),
            'симпотичный': ('симпатичный', 'Опечатка в слове'),
            'экстримальный': ('экстремальный', 'Опечатка "и" вместо "е"'),
            'агенство': ('агентство', 'Орфографическая ошибка'),
            'сдесь': ('здесь', 'Правильно через "зде"'),
            'через-чюр': ('чересчур', 'Слитное написание'),
            'вообщем': ('в общем', 'Раздельное написание'),
        }

    async def analyze(self, text: str, analysis_type: str) -> Dict:
        """Универсальный анализ текста"""
        if not self.universal_analyzer:
            return self._create_local_fallback(text, analysis_type, "GigaChat API не настроен")

        try:
            return await self.universal_analyzer.analyze_text(text, analysis_type)
        except Exception as e:
            logger.error(f"Ошибка ИИ анализа {analysis_type}: {e}")
            return self._create_local_fallback(text, analysis_type, str(e))

    async def check_grammar(self, text: str) -> Dict:
        """Проверка грамматики"""
        if not self.grammar_checker:
            return self._create_grammar_fallback(text)

        try:
            return await self.grammar_checker.check_grammar(text)
        except Exception as e:
            logger.error(f"Ошибка ИИ проверки грамматики: {e}")
            return self._create_grammar_fallback(text)

    async def check_spelling(self, text: str) -> Dict:
        """Проверка орфографии"""
        if not self.spell_checker:
            return self._create_spelling_fallback(text)

        try:
            return await self.spell_checker.check_spelling(text)
        except Exception as e:
            logger.error(f"Ошибка ИИ проверки орфографии: {e}")
            return self._create_spelling_fallback(text)

    def _create_local_fallback(self, text: str, analysis_type: str, error_msg: str) -> Dict:
        """Создает ответ при ошибке"""
        return {
            'success': False,
            'analysis_type': analysis_type,
            'analysis': f'ИИ анализ ({analysis_type}) недоступен: {error_msg}\n\nИспользую локальный анализ...',
            'original_text': text,
            'source': 'local_fallback'
        }

    def _create_grammar_fallback(self, text: str) -> Dict:
        """Локальная проверка грамматики"""
        issues = []
        corrections = []
        explanations = []
        types = []
        severities = []

        # Простая локальная проверка
        if '  ' in text:
            issues.append('двойной пробел')
            corrections.append('один пробел')
            explanations.append('Уберите лишние пробелы')
            types.append('пунктуация')
            severities.append('низкий')

        if re.search(r'[а-яё]\s+а\s+[а-яё]', text, re.IGNORECASE):
            issues.append('пропущена запятая перед союзом "а"')
            corrections.append('добавить запятую перед "а"')
            explanations.append('В сложносочиненных предложениях перед союзом "а" всегда ставится запятая')
            types.append('пунктуация')
            severities.append('высокий')

        if re.search(r'[а-яё]\s+что\s+[а-яё]', text, re.IGNORECASE):
            issues.append('пропущена запятая перед союзом "что"')
            corrections.append('добавить запятую перед "что"')
            explanations.append('В сложноподчиненных предложениях перед союзом "что" ставится запятая')
            types.append('пунктуация')
            severities.append('высокий')

        return {
            'issues': issues,
            'corrections': corrections,
            'explanations': explanations,
            'types': types,
            'severities': severities,
            'corrected_text': text,
            'ai_comment': 'Используется локальная проверка грамматики',
            'total_sentences': len(re.split(r'[.!?]+', text)),
            'total_chars': len(text),
            'issue_count': len(issues),
            'score': 100 if not issues else 80,
            'has_issues': len(issues) > 0,
            'success': True,
            'source': 'local'
        }

    def _create_spelling_fallback(self, text: str) -> Dict:
        """Локальная проверка орфографии"""
        errors = []
        suggestions = []
        explanations = []

        words = re.findall(r'\b[а-яёА-ЯЁ]+\b', text)

        for word in words:
            word_lower = word.lower()
            if word_lower in self.common_errors:
                correction, explanation = self.common_errors[word_lower]
                errors.append(word)
                suggestions.append(correction)
                explanations.append(explanation)

        return {
            'errors': errors,
            'suggestions': suggestions,
            'explanations': explanations,
            'corrected_text': text,
            'ai_comment': 'Используется локальная проверка орфографии',
            'total_words': len(words),
            'error_words': len(errors),
            'has_errors': len(errors) > 0,
            'accuracy_score': 100 if not errors else 80,
            'success': True,
            'source': 'local'
        }

    async def close(self):
        """Закрывает соединения"""
        if self.universal_analyzer:
            await self.universal_analyzer.close()
        if self.grammar_checker:
            await self.grammar_checker.close()
        if self.spell_checker:
            await self.spell_checker.close()


# ==================== ИНИЦИАЛИЗАЦИЯ АНАЛИЗАТОРА ====================

analyzer = CombinedAnalyzer(
    gigachat_client_id=GIGACHAT_CLIENT_ID,
    gigachat_client_secret=GIGACHAT_CLIENT_SECRET
)


# ==================== ОСНОВНОЙ КОД БОТА ====================

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📊 Анализ текста (ИИ)")],
        [KeyboardButton("🤖 Проверка грамматики (ИИ)")],
        [KeyboardButton("🎵 Фонетический анализ (ИИ)")],
        [KeyboardButton("🔤 Морфология (ИИ)")],
        [KeyboardButton("📚 Синонимы (ИИ)")],
        [KeyboardButton("🔍 Проверка орфографии (ИИ)")],
        [KeyboardButton("🌍 Определить язык (ИИ)")],
        [KeyboardButton("🎨 Стилистика (ИИ)")],
        [KeyboardButton("📜 Этимология (ИИ)")],
        [KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    gigachat_status = "✅ GigaChat API доступен" if GIGACHAT_CLIENT_ID and GIGACHAT_CLIENT_SECRET else "⚠️ GigaChat API не настроен"

    await update.message.reply_text(
        f"🤖 <b>Привет, {user.first_name}! Я бот-лингвист с ИИ</b>\n\n"
        "✨ <b>Все функции работают через GigaChat AI:</b>\n"
        "• 📊 <b>Анализ текста</b> - полный лингвистический анализ\n"
        "• 🤖 <b>Проверка грамматики</b> - пунктуация и синтаксис\n"
        "• 🎵 <b>Фонетический анализ</b> - звуки и транскрипция\n"
        "• 🔤 <b>Морфология</b> - полный разбор слова\n"
        "• 📚 <b>Синонимы</b> - синонимы, антонимы, этимология\n"
        "• 🔍 <b>Проверка орфографии</b> - исправление ошибок\n"
        "• 🌍 <b>Определение языка</b> - мультиязычный анализ\n"
        "• 🎨 <b>Стилистика</b> - анализ стиля и тона\n"
        "• 📜 <b>Этимология</b> - происхождение слов\n\n"
        f"{gigachat_status}\n\n"
        "<b>Команды:</b>\n"
        "/test - Протестировать все функции\n"
        "/help - Справка\n\n"
        "Выберите опцию из меню ниже:",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )
    return 0


async def text_analysis_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для анализа текста"""
    await update.message.reply_text(
        "📊 <b>Полный ИИ анализ текста</b>\n\n"
        "Отправьте текст для глубокого анализа:\n\n"
        "<i>GigaChat AI проанализирует:</i>\n"
        "• Статистику текста (слова, предложения)\n"
        "• Стиль и сложность языка\n"
        "• Эмоциональный тон\n"
        "• Ключевые темы\n"
        "• Читаемость и рекомендации\n\n"
        "<b>Пример:</b>\n"
        "<code>В лесу родилась ёлочка, в лесу она росла.</code>",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )
    return 1


async def process_text_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка анализа текста"""
    text = update.message.text

    if not text.strip():
        await update.message.reply_text("Пожалуйста, отправьте текст для анализа",
                                        reply_markup=get_main_keyboard())
        return 1

    status_msg = await update.message.reply_text(
        "🤖 <i>ИИ анализирует текст...</i>\n<i>Это может занять несколько секунд</i>",
        parse_mode='HTML'
    )

    try:
        result = await analyzer.analyze(text, 'text_analysis')

        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id
        )

        if result.get('success', False):
            response = result['analysis']
        else:
            response = result.get('analysis', 'Не удалось выполнить анализ')

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"Ошибка при анализе текста: {e}")

        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass

        response = (
            "❌ <b>Произошла ошибка при анализе текста</b>\n\n"
            "<i>Попробуйте еще раз или используйте другую функцию.</i>"
        )

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    return 0


async def morphology_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для морфологического анализа"""
    await update.message.reply_text(
        "🔤 <b>ИИ морфологический разбор слова</b>\n\n"
        "Отправьте слово для полного морфологического анализа:\n\n"
        "<i>GigaChat AI проанализирует:</i>\n"
        "• Часть речи\n"
        "• Все грамматические признаки\n"
        "• Начальную форму\n"
        "• Морфемный состав\n"
        "• Синтаксическую роль\n"
        "• Примеры использования\n\n"
        "<b>Примеры:</b>\n"
        "<code>бегущий</code>\n"
        "<code>прекрасный</code>\n"
        "<code>читали</code>",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )
    return 4


async def process_morphology(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка морфологического анализа"""
    text = update.message.text.strip()

    if not text:
        await update.message.reply_text("Пожалуйста, отправьте слово",
                                        reply_markup=get_main_keyboard())
        return 4

    status_msg = await update.message.reply_text(
        "🤖 <i>ИИ делает морфологический разбор...</i>\n<i>Это может занять несколько секунд</i>",
        parse_mode='HTML'
    )

    try:
        result = await analyzer.analyze(text, 'morphology')

        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id
        )

        if result.get('success', False):
            response = result['analysis']
        else:
            response = result.get('analysis', 'Не удалось выполнить анализ')

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"Ошибка при морфологическом анализе: {e}")

        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass

        response = (
            "❌ <b>Произошла ошибка при морфологическом анализе</b>\n\n"
            "<i>Попробуйте еще раз или используйте другую функцию.</i>"
        )

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    return 0


async def phonetics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для фонетического анализа"""
    await update.message.reply_text(
        "🎵 <b>ИИ фонетический анализ слова</b>\n\n"
        "Отправьте слово для фонетического анализа:\n\n"
        "<i>GigaChat AI проанализирует:</i>\n"
        "• Транскрипцию\n"
        "• Слоги и ударение\n"
        "• Звуковой состав\n"
        "• Звонкие/глухие согласные\n"
        "• Твёрдые/мягкие согласные\n"
        "• Звуко-буквенный разбор\n\n"
        "<b>Примеры:</b>\n"
        "<code>яблоко</code>\n"
        "<code>солнце</code>\n"
        "<code>счастье</code>",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )
    return 3


async def process_phonetics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фонетического анализа"""
    text = update.message.text.strip()

    if not text:
        await update.message.reply_text("Пожалуйста, отправьте слово",
                                        reply_markup=get_main_keyboard())
        return 3

    status_msg = await update.message.reply_text(
        "🤖 <i>ИИ делает фонетический анализ...</i>\n<i>Это может занять несколько секунд</i>",
        parse_mode='HTML'
    )

    try:
        result = await analyzer.analyze(text, 'phonetics')

        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id
        )

        if result.get('success', False):
            response = result['analysis']
        else:
            response = result.get('analysis', 'Не удалось выполнить анализ')

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"Ошибка при фонетическом анализе: {e}")

        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass

        response = (
            "❌ <b>Произошла ошибка при фонетическом анализе</b>\n\n"
            "<i>Попробуйте еще раз или используйте другую функцию.</i>"
        )

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    return 0


async def synonyms_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для поиска синонимов"""
    await update.message.reply_text(
        "📚 <b>ИИ лексический анализ слова</b>\n\n"
        "Отправьте слово для поиска синонимов и антонимов:\n\n"
        "<i>GigaChat AI найдёт:</i>\n"
        "• Синонимы\n"
        "• Антонимы\n"
        "• Родственные слова\n"
        "• Этимологию\n"
        "• Примеры использования\n"
        "• Стилистические пометы\n\n"
        "<b>Примеры:</b>\n"
        "<code>красивый</code>\n"
        "<code>быстро</code>\n"
        "<code>добрый</code>",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )
    return 7


async def process_synonyms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поиска синонимов"""
    text = update.message.text.strip()

    if not text:
        await update.message.reply_text("Пожалуйста, отправьте слово",
                                        reply_markup=get_main_keyboard())
        return 7

    status_msg = await update.message.reply_text(
        "🤖 <i>ИИ ищет синонимы и антонимы...</i>\n<i>Это может занять несколько секунд</i>",
        parse_mode='HTML'
    )

    try:
        result = await analyzer.analyze(text, 'synonyms')

        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id
        )

        if result.get('success', False):
            response = result['analysis']
        else:
            response = result.get('analysis', 'Не удалось выполнить анализ')

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"Ошибка при поиске синонимов: {e}")

        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass

        response = (
            "❌ <b>Произошла ошибка при поиске синонимов</b>\n\n"
            "<i>Попробуйте еще раз или используйте другую функцию.</i>"
        )

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    return 0


async def language_detection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для определения языка"""
    await update.message.reply_text(
        "🌍 <b>ИИ определение языка текста</b>\n\n"
        "Отправьте текст для определения языка:\n\n"
        "<i>GigaChat AI определит:</i>\n"
        "• Все языки в тексте\n"
        "• Уверенность в процентах\n"
        "• Основной язык\n"
        "• Языковые особенности\n"
        "• Подсказки для перевода\n\n"
        "<b>Примеры:</b>\n"
        "<code>Hello world</code>\n"
        "<code>Bonjour tout le monde</code>\n"
        "<code>Hola mundo</code>",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )
    return 9


async def process_language_detection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка определения языка"""
    text = update.message.text.strip()

    if not text:
        await update.message.reply_text("Пожалуйста, отправьте текст",
                                        reply_markup=get_main_keyboard())
        return 9

    status_msg = await update.message.reply_text(
        "🤖 <i>ИИ определяет язык...</i>\n<i>Это может занять несколько секунд</i>",
        parse_mode='HTML'
    )

    try:
        result = await analyzer.analyze(text, 'language_detection')

        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id
        )

        if result.get('success', False):
            response = result['analysis']
        else:
            response = result.get('analysis', 'Не удалось выполнить анализ')

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"Ошибка при определении языка: {e}")

        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass

        response = (
            "❌ <b>Произошла ошибка при определении языка</b>\n\n"
            "<i>Попробуйте еще раз или используйте другую функцию.</i>"
        )

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    return 0


async def stylistics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для стилистического анализа"""
    await update.message.reply_text(
        "🎨 <b>ИИ стилистический анализ текста</b>\n\n"
        "Отправьте текст для стилистического анализа:\n\n"
        "<i>GigaChat AI проанализирует:</i>\n"
        "• Тип стиля\n"
        "• Тон текста\n"
        "• Уровень формальности\n"
        "• Богатство словаря\n"
        "• Стилистические ошибки\n"
        "• Предложения по улучшению\n\n"
        "<b>Пример:</b>\n"
        "<code>Ну это типа в общем короче я пошел</code>",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )
    return 10


async def process_stylistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка стилистического анализа"""
    text = update.message.text.strip()

    if not text:
        await update.message.reply_text("Пожалуйста, отправьте текст",
                                        reply_markup=get_main_keyboard())
        return 10

    status_msg = await update.message.reply_text(
        "🤖 <i>ИИ анализирует стилистику...</i>\n<i>Это может занять несколько секунд</i>",
        parse_mode='HTML'
    )

    try:
        result = await analyzer.analyze(text, 'stylistics')

        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id
        )

        if result.get('success', False):
            response = result['analysis']
        else:
            response = result.get('analysis', 'Не удалось выполнить анализ')

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"Ошибка при стилистическом анализе: {e}")

        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass

        response = (
            "❌ <b>Произошла ошибка при стилистическом анализе</b>\n\n"
            "<i>Попробуйте еще раз или используйте другую функцию.</i>"
        )

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    return 0


async def etymology_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для этимологического анализа"""
    await update.message.reply_text(
        "📜 <b>ИИ этимологический анализ слова</b>\n\n"
        "Отправьте слово для исследования происхождения:\n\n"
        "<i>GigaChat AI исследовает:</i>\n"
        "• Происхождение слова\n"
        "• Исторические формы\n"
        "• Корень слова\n"
        "• Родственные слова\n"
        "• Эволюцию значения\n"
        "• Интересные факты\n\n"
        "<b>Примеры:</b>\n"
        "<code>компьютер</code>\n"
        "<code>спутник</code>\n"
        "<code>медведь</code>",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )
    return 11


async def process_etymology(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка этимологического анализа"""
    text = update.message.text.strip()

    if not text:
        await update.message.reply_text("Пожалуйста, отправьте слово",
                                        reply_markup=get_main_keyboard())
        return 11

    status_msg = await update.message.reply_text(
        "🤖 <i>ИИ исследует этимологию...</i>\n<i>Это может занять несколько секунд</i>",
        parse_mode='HTML'
    )

    try:
        result = await analyzer.analyze(text, 'etymology')

        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id
        )

        if result.get('success', False):
            response = result['analysis']
        else:
            response = result.get('analysis', 'Не удалось выполнить анализ')

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"Ошибка при этимологическом анализе: {e}")

        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass

        response = (
            "❌ <b>Произошла ошибка при этимологическом анализе</b>\n\n"
            "<i>Попробуйте еще раз или используйте другую функцию.</i>"
        )

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    return 0


# ==================== СУЩЕСТВУЮЩИЕ ФУНКЦИИ (грамматика и орфография) ====================

async def grammar_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для проверки грамматики"""
    gigachat_status = " (с GigaChat AI)" if GIGACHAT_CLIENT_ID and GIGACHAT_CLIENT_SECRET else " (локальная проверка)"

    await update.message.reply_text(
        f"🤖 <b>ИИ проверка грамматики и пунктуации{gigachat_status}</b>\n\n"
        "Отправьте текст для проверки:\n\n"
        "<i>Использую GigaChat AI для анализа:</i>\n"
        "• Правильность расстановки знаков препинания\n"
        "• Грамматические ошибки в предложениях\n"
        "• Стилистические рекомендации\n"
        "• Логика построения предложений\n\n"
        "<b>Примеры для теста:</b>\n"
        "<code>Я пошел в магазин купил хлеб молоко и сыр</code>\n"
        "<code>Несмотря на то что было поздно он продолжал работать.</code>\n"
        "<code>Мама сказала чтобы я убрал комнату потому что придут гости.</code>",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )
    return 2


async def process_grammar_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка проверки грамматики"""
    text = update.message.text

    if not text.strip():
        await update.message.reply_text("Пожалуйста, отправьте текст для проверки",
                                        reply_markup=get_main_keyboard())
        return 2

    status_msg = await update.message.reply_text(
        "🤖 <i>ИИ анализирует грамматику...</i>\n<i>Это может занять несколько секунд</i>",
        parse_mode='HTML'
    )

    try:
        result = await analyzer.check_grammar(text)

        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id
        )

        if result.get('success', False):
            if not result.get('has_issues', False):
                response = (
                    f"✅ <b>Грамматическая проверка завершена успешно!</b>\n\n"
                    f"📊 <b>Статистика:</b>\n"
                    f"• Предложений: {result['total_sentences']}\n"
                    f"• Символов: {result['total_chars']}\n"
                    f"• Ошибок не обнаружено\n"
                    f"• Оценка грамматики: {result.get('score', 100)}/100\n"
                    f"• Источник: {result.get('source', 'unknown')}\n\n"
                )

                ai_comment = result.get('ai_comment', '')
                if ai_comment and 'недоступна' not in ai_comment.lower():
                    response += f"💡 <b>Комментарий ИИ:</b>\n{ai_comment}\n\n"

                response += "<i>Отличная грамматика! 👏</i>"

            else:
                response = f"⚠️ <b>Найдено грамматических проблем: {result['issue_count']}</b>\n\n"

                if result['issues']:
                    response += "<b>Исправления:</b>\n"
                    for i, (issue, correction, explanation, issue_type, severity) in enumerate(
                            zip(result['issues'], result['corrections'], result['explanations'],
                                result['types'], result['severities']), 1):
                        severity_icon = "🔴" if severity == 'высокий' else "🟡" if severity == 'средний' else "🟢"
                        type_icon = "📝" if 'пунктуация' in issue_type else "🔤" if 'грамматика' in issue_type else "💡"

                        response += f"{i}. {severity_icon}{type_icon} <b>{issue_type.upper()}</b>\n"
                        response += f"   <code>{issue}</code> → <b>{correction}</b>\n"
                        response += f"   <i>{explanation}</i>\n\n"

                response += f"📝 <b>Исправленный текст:</b>\n"
                response += f"<pre>{result['corrected_text']}</pre>\n\n"

                response += f"📊 <b>Детали:</b>\n"
                response += f"• Предложений: {result['total_sentences']}\n"
                response += f"• Символов: {result['total_chars']}\n"
                response += f"• Найдено проблем: {result['issue_count']}\n"
                response += f"• Оценка грамматики: {result.get('score', 0)}/100\n"
                response += f"• Источник: {result.get('source', 'unknown')}\n\n"

                ai_comment = result.get('ai_comment', '')
                if ai_comment and 'недоступна' not in ai_comment.lower():
                    response += f"💡 <b>Комментарий ИИ:</b>\n{ai_comment}\n\n"

                response += "<i>🤖 Анализ выполнен с помощью GigaChat AI</i>"
        else:
            ai_comment = result.get('ai_comment', 'Ошибка проверки')
            response = (
                f"⚠️ <b>Проверка грамматики не удалась</b>\n\n"
                f"{ai_comment}"
            )

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"Ошибка при проверке грамматики: {e}")

        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass

        response = (
            "❌ <b>Произошла ошибка при проверке грамматики</b>\n\n"
            "<i>Попробуйте еще раз или используйте другую функцию.</i>"
        )

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    return 0


async def spell_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для проверки орфографии"""
    await update.message.reply_text(
        "🔍 <b>ИИ проверка орфографии</b>\n\n"
        "Отправьте текст для проверки:\n\n"
        "<i>Использую GigaChat AI для анализа:</i>\n"
        "• Орфографические ошибки\n"
        "• Грамматические ошибки\n"
        "• Стилистические рекомендации\n\n"
        "<b>Примеры для теста:</b>\n"
        "<code>Здраствуйте, как ваши дела?</code>\n"
        "<code>Я ходил в кина вчера.</code>\n"
        "<code>Мне нравиться читать книжки.</code>",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )
    return 8


async def process_spell_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка проверки орфографии"""
    text = update.message.text

    if not text.strip():
        await update.message.reply_text("Пожалуйста, отправьте текст для проверки",
                                        reply_markup=get_main_keyboard())
        return 8

    status_msg = await update.message.reply_text(
        "🤖 <i>ИИ проверяет орфографию...</i>\n<i>Это может занять несколько секунд</i>",
        parse_mode='HTML'
    )

    try:
        result = await analyzer.check_spelling(text)

        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id
        )

        if result.get('success', False):
            if not result.get('has_errors', False):
                response = (
                    f"✅ <b>Проверка завершена успешно!</b>\n\n"
                    f"📊 <b>Статистика:</b>\n"
                    f"• Проверено слов: {result.get('total_words', 0)}\n"
                    f"• Ошибок не обнаружено\n"
                    f"• Точность текста: {result.get('accuracy_score', 100)}%\n"
                    f"• Источник: {result.get('source', 'unknown')}\n\n"
                )

                ai_comment = result.get('ai_comment', '')
                if ai_comment and 'недоступна' not in ai_comment.lower():
                    response += f"💡 <b>Комментарий ИИ:</b>\n{ai_comment}\n\n"

                response += "<i>Отличная грамотность! 👏</i>"

            else:
                response = f"⚠️ <b>Найдено ошибок: {result.get('error_words', 0)}</b>\n\n"

                if result.get('errors'):
                    response += "<b>Исправления:</b>\n"
                    for i, (error, suggestion) in enumerate(zip(result['errors'], result['suggestions']), 1):
                        explanation = ""
                        if 'explanations' in result and i - 1 < len(result['explanations']):
                            explanation = f" <i>({result['explanations'][i - 1]})</i>"
                        response += f"{i}. <code>{error}</code> → <b>{suggestion}</b>{explanation}\n"

                response += f"\n📝 <b>Исправленный текст:</b>\n"
                response += f"<pre>{result.get('corrected_text', text)}</pre>\n\n"

                response += f"📊 <b>Детали:</b>\n"
                response += f"• Всего слов: {result.get('total_words', 0)}\n"
                response += f"• Найдено ошибок: {result.get('error_words', 0)}\n"
                response += f"• Точность текста: {result.get('accuracy_score', 0)}%\n"

                ai_comment = result.get('ai_comment', '')
                if ai_comment and 'недоступна' not in ai_comment.lower():
                    response += f"💡 <b>Комментарий ИИ:</b>\n{ai_comment}\n\n"

                response += "<i>🤖 Проверка выполнена с помощью GigaChat AI</i>"
        else:
            ai_comment = result.get('ai_comment', 'Ошибка проверки')
            response = f"⚠️ <b>Проверка не удалась</b>\n\n{ai_comment}"

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"Ошибка при проверке орфографии: {e}")

        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass

        response = (
            "⚠️ <b>Произошла ошибка при проверке</b>\n\n"
            "<i>Попробуйте еще раз или используйте другую функцию.</i>"
        )

        await update.message.reply_html(response, reply_markup=get_main_keyboard())

    return 0


# ==================== ТЕСТОВАЯ КОМАНДА ====================

async def test_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая команда для проверки всех функций"""
    test_text = "быстрый"

    await update.message.reply_text(
        f"🧪 <b>Тестирую все ИИ-функции на слове: '{test_text}'</b>\n\n"
        f"<i>Это может занять несколько секунд...</i>",
        parse_mode='HTML'
    )

    results = []

    # Тестируем все функции
    test_cases = [
        ('📊 Анализ текста', 'text_analysis', "Быстрый рыжий лис перепрыгнул через ленивую собаку."),
        ('🔤 Морфология', 'morphology', test_text),
        ('🎵 Фонетика', 'phonetics', test_text),
        ('📚 Синонимы', 'synonyms', test_text),
        ('🌍 Язык', 'language_detection', "Hello world и привет мир"),
        ('🎨 Стилистика', 'stylistics', "Ну короче типа в общем я пошел"),
        ('📜 Этимология', 'etymology', test_text),
    ]

    for name, analysis_type, text in test_cases:
        try:
            result = await analyzer.analyze(text, analysis_type)
            if result.get('success', False):
                results.append(f"✅ {name}: Успешно")
            else:
                results.append(f"⚠️ {name}: Ошибка")
        except Exception as e:
            results.append(f"❌ {name}: Ошибка ({str(e)[:50]})")

    # Проверяем грамматику и орфографию
    grammar_text = "Я хотел поехать в отпуск а на работе сказали что надо работать"
    try:
        grammar_result = await analyzer.check_grammar(grammar_text)
        if grammar_result.get('success', False):
            results.append(f"✅ Проверка грамматики: Найдено {grammar_result.get('issue_count', 0)} ошибок")
        else:
            results.append("⚠️ Проверка грамматики: Ошибка")
    except Exception:
        results.append("❌ Проверка грамматики: Ошибка")

    spelling_text = "Здраствуйте, как ваши дела?"
    try:
        spelling_result = await analyzer.check_spelling(spelling_text)
        if spelling_result.get('success', False):
            results.append(f"✅ Проверка орфографии: Найдено {spelling_result.get('error_words', 0)} ошибок")
        else:
            results.append("⚠️ Проверка орфографии: Ошибка")
    except Exception:
        results.append("❌ Проверка орфографии: Ошибка")

    response = "📋 <b>Результаты тестирования ИИ-функций:</b>\n\n"
    response += "\n".join(results)
    response += "\n\n✨ <b>Все функции работают через GigaChat AI!</b>"

    await update.message.reply_html(response, reply_markup=get_main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gigachat_status = "✅ GigaChat API подключен" if GIGACHAT_CLIENT_ID and GIGACHAT_CLIENT_SECRET else "⚠️ GigaChat API не настроен"

    help_text = f"""
🤖 <b>ПОМОЩЬ - БОТ-ЛИНГВИСТ С ПОЛНЫМ ИИ-АНАЛИЗОМ</b>

<b>Статус ИИ: {gigachat_status}</b>

✨ <b>Все функции используют GigaChat AI:</b>

<b>Основные функции:</b>
• 📊 <b>Анализ текста (ИИ)</b> - полный лингвистический анализ
• 🤖 <b>Проверка грамматики (ИИ)</b> - пунктуация и синтаксис
• 🔍 <b>Проверка орфографии (ИИ)</b> - исправление ошибок

<b>Углубленный анализ:</b>
• 🎵 <b>Фонетический анализ (ИИ)</b> - звуки, транскрипция, слоги
• 🔤 <b>Морфология (ИИ)</b> - полный разбор слова
• 📚 <b>Синонимы (ИИ)</b> - синонимы, антонимы, этимология
• 🌍 <b>Определение языка (ИИ)</b> - мультиязычный анализ
• 🎨 <b>Стилистика (ИИ)</b> - анализ стиля и тона
• 📜 <b>Этимология (ИИ)</b> - происхождение слов

<b>Для работы ИИ нужны ключи GigaChat</b>
Получите ключи: https://developers.sber.ru/studio
- Бесплатно: 1000 токенов в день
- Требуется учетная запись Госуслуг

<b>Команды:</b>
/start - Перезапустить бота
/test - Протестировать все ИИ-функции
/help - Показать это сообщение
    """
    await update.message.reply_html(help_text, reply_markup=get_main_keyboard())
    return 0


async def handle_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📊 Анализ текста (ИИ)":
        return await text_analysis_handler(update, context)
    elif text == "🤖 Проверка грамматики (ИИ)":
        return await grammar_check_handler(update, context)
    elif text == "🎵 Фонетический анализ (ИИ)":
        return await phonetics_handler(update, context)
    elif text == "🔤 Морфология (ИИ)":
        return await morphology_handler(update, context)
    elif text == "📚 Синонимы (ИИ)":
        return await synonyms_handler(update, context)
    elif text == "🔍 Проверка орфографии (ИИ)":
        return await spell_check_handler(update, context)
    elif text == "🌍 Определить язык (ИИ)":
        return await language_detection_handler(update, context)
    elif text == "🎨 Стилистика (ИИ)":
        return await stylistics_handler(update, context)
    elif text == "📜 Этимология (ИИ)":
        return await etymology_handler(update, context)
    elif text == "❓ Помощь":
        return await help_command(update, context)
    else:
        await update.message.reply_text(
            "Пожалуйста, выберите опцию из меню ниже:",
            reply_markup=get_main_keyboard()
        )
        return 0


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Главное меню. Выберите опцию:",
        reply_markup=get_main_keyboard()
    )
    return 0


# ==================== ОСНОВНАЯ ФУНКЦИЯ ====================

def main():
    TOKEN = "8373843533:AAH9uigqO99bT2SFP9KssZbMfYqc7Ggfyfo"

    try:
        application = Application.builder().token(TOKEN).build()

        # Регистрируем тестовую команду
        application.add_handler(CommandHandler('test', test_all))

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                0: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_selection)],
                1: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_text_analysis)],
                2: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_grammar_check)],
                3: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_phonetics)],
                4: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_morphology)],
                7: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_synonyms)],
                8: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_spell_check)],
                9: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_language_detection)],
                10: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_stylistics)],
                11: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_etymology)],
            },
            fallbacks=[
                CommandHandler('start', start),
                CommandHandler('help', help_command),
                CommandHandler('menu', menu_command),
            ],
            allow_reentry=True
        )

        application.add_handler(conv_handler)
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('menu', menu_command))

        print("=" * 50)
        print("🤖 БОТ-ЛИНГВИСТ С ПОЛНЫМ ИИ-АНАЛИЗОМ")
        print("=" * 50)
        print("✨ Все функции используют GigaChat AI:")
        print("   📊 Анализ текста")
        print("   🤖 Проверка грамматики")
        print("   🔍 Проверка орфографии")
        print("   🎵 Фонетический анализ")
        print("   🔤 Морфология")
        print("   📚 Синонимы")
        print("   🌍 Определение языка")
        print("   🎨 Стилистика")
        print("   📜 Этимология")

        if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
            print("   ⚠️  GigaChat API не настроен")
        else:
            print("   ✅ GigaChat API настроен")

        print("\n📱 Для остановки нажмите Ctrl+C")
        print("✅ Бот готов к работе!")
        print("=" * 50)

        application.run_polling()

    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")
        import traceback
        traceback.print_exc()


async def shutdown():
    """Корректное завершение работы"""
    await analyzer.close()


if __name__ == '__main__':
    try:
        import aiohttp

        print("✅ aiohttp установлен")
    except ImportError:
        print("❌ aiohttp не установлен")
        print("Установите: pip install aiohttp")
        sys.exit(1)

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🛑 Бот остановлен пользователем")
        asyncio.run(shutdown())
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        asyncio.run(shutdown())