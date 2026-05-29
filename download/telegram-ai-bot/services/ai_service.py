"""
Сервис интеграции с OpenAI API
- Чат с контекстом
- Генерация изображений (DALL-E)
- Копирайтинг (специализированные промпты)
"""

import openai
import logging
from config import Config

logger = logging.getLogger(__name__)

# Инициализация клиента
client = openai.AsyncOpenAI(api_key=Config.OPENAI_API_KEY)

# === Хранилище контекста диалогов (в памяти) ===
# В продакшене лучше использовать Redis
chat_contexts: dict[int, list[dict]] = {}
MAX_CONTEXT_MESSAGES = 20  # максимум сообщений в контексте


async def chat_completion(user_id: int, message: str, system_prompt: str = None) -> str:
    """
    Чат с AI с сохранением контекста диалога
    
    Args:
        user_id: ID пользователя Telegram
        message: Текст сообщения
        system_prompt: Кастомный системный промпт (опционально)
    
    Returns:
        Ответ AI
    """
    if system_prompt is None:
        system_prompt = (
            "Ты — умный AI-ассистент в Telegram. Отвечай полезно, кратко и по делу. "
            "Используй форматирование Markdown где уместно. "
            "Если пишешь код — оборачивай в блоки кода. "
            "Отвечай на языке пользователя."
        )

    # Получаем или создаём контекст
    if user_id not in chat_contexts:
        chat_contexts[user_id] = []

    # Добавляем сообщение пользователя
    chat_contexts[user_id].append({"role": "user", "content": message})

    # Ограничиваем контекст
    if len(chat_contexts[user_id]) > MAX_CONTEXT_MESSAGES:
        chat_contexts[user_id] = chat_contexts[user_id][-MAX_CONTEXT_MESSAGES:]

    # Формируем сообщения для API
    messages = [{"role": "system", "content": system_prompt}] + chat_contexts[user_id]

    try:
        response = await client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=messages,
            max_tokens=2000,
            temperature=0.7,
        )
        answer = response.choices[0].message.content

        # Сохраняем ответ в контекст
        chat_contexts[user_id].append({"role": "assistant", "content": answer})

        return answer

    except openai.RateLimitError:
        return "⚠️ Сервер перегружен. Попробуй через 30 секунд."
    except openai.APIError as e:
        logger.error(f"OpenAI API error: {e}")
        return "❌ Ошибка AI-сервиса. Попробуй позже."
    except Exception as e:
        logger.error(f"Unexpected error in chat_completion: {e}")
        return "❌ Произошла ошибка. Попробуй позже."


async def generate_image(prompt: str, size: str = "1024x1024") -> str | None:
    """
    Генерация изображения через DALL-E
    
    Args:
        prompt: Описание изображения
        size: Размер (1024x1024, 1792x1024, 1024x1792)
    
    Returns:
        URL изображения или None при ошибке
    """
    try:
        # Улучшаем промпт для лучшего результата
        enhanced_prompt = (
            f"{prompt}. "
            "High quality, detailed, professional."
        )

        response = await client.images.generate(
            model=Config.OPENAI_IMAGE_MODEL,
            prompt=enhanced_prompt,
            size=size,
            quality="standard",
            n=1,
        )
        return response.data[0].url

    except openai.RateLimitError:
        return None
    except openai.APIError as e:
        logger.error(f"DALL-E API error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in generate_image: {e}")
        return None


async def copywrite_text(task: str, topic: str, tone: str = "профессиональный",
                         length: str = "средний") -> str:
    """
    AI-копирайтинг с специализированными промптами
    
    Args:
        task: Тип задачи (post, email, ad, seo, product)
        topic: Тема/описание
        tone: Тон (профессиональный, дружелюбный, продающий)
        length: Длина (краткий, средний, подробный)
    
    Returns:
        Сгенерированный текст
    """
    task_prompts = {
        "post": "Напиши пост для социальных сетей (Instagram/VK/Telegram)",
        "email": "Напиши email-рассылку с заголовком и призывом к действию",
        "ad": "Напиши рекламный текст (заголовок + описание + CTA)",
        "seo": "Напиши SEO-оптимизированную статью с ключевыми словами",
        "product": "Напиши продающее описание товара для маркетплейса",
    }

    length_map = {
        "краткий": "100-150 слов",
        "средний": "200-400 слов",
        "подробный": "500-800 слов",
    }

    system_prompt = f"""Ты — профессиональный копирайтер с 10-летним опытом.
{task_prompts.get(task, task_prompts['post'])}

Тема: {topic}
Тон: {tone}
Объём: {length_map.get(length, '200-400 слов')}

Правила:
- Пиши на русском языке
- Используй эмодзи где уместно (для постов)
- Добавляй призыв к действию (CTA)
- Делай текст структурированным с абзацами
- Для рекламы: используй формулу AIDA (Attention, Interest, Desire, Action)
"""

    try:
        response = await client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Напиши текст на тему: {topic}"}
            ],
            max_tokens=2000,
            temperature=0.8,
        )
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"Error in copywrite_text: {e}")
        return "❌ Ошибка генерации текста. Попробуй позже."


def clear_context(user_id: int):
    """Очистить контекст диалога пользователя"""
    if user_id in chat_contexts:
        del chat_contexts[user_id]
