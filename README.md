# AI Mega Bot 🤖

Мультифункциональный AI-хаб в Telegram — чат, генерация картинок, перевод, транскрипция аудио, помощь с кодом.

## 🎯 Возможности

| Функция | Описание | Бесплатно |
|---------|----------|-----------|
| 💬 **Чат с AI** | Общение с нейросетями (Llama 3.3 70B, DeepSeek, GPT-4o mini) | ✅ 10/день |
| 🎨 **Генерация картинок** | Создание изображений по описанию (Flux, Stable Diffusion) | ✅ 3/день |
| 🎤 **Транскрипция** | Голосовые сообщения → текст (Whisper) | ✅ 1/день |
| 🌍 **Перевод** | Мгновенный перевод на 30+ языков (NLLB-200) | ✅ 5/день |
| 💻 **Помощь с кодом** | Отладка, оптимизация, генерация кода | ✅ 5/день |
| 🔊 **TTS** | Текст в речь (Pro+) | ⭐ Pro |

## 💎 Тарифы

| | 🆓 Free | ⭐ Pro | 💎 Ultra |
|---|---------|--------|----------|
| Цена | 0 ★ | 149 ★/мес | 499 ★/мес |
| Чат | 10/день | 200/день | ∞ |
| Картинки | 3/день | 30/день | 100/день |
| Перевод | 5/день | 100/день | ∞ |
| Быстрые модели | ❌ | ✅ | ✅ |
| История чата | ❌ | 7 дней | 30 дней |

## 🏗 Архитектура

```
ai-mega-bot/
├── bot/                    # Telegram Bot (aiogram 3.x)
│   ├── main.py             # Точка входа (bot + Flask API)
│   ├── config.py           # Конфигурация (env vars)
│   ├── database.py         # SQLite WAL mode
│   ├── handlers/           # Обработчики команд
│   ├── keyboards.py        # Inline клавиатуры
│   └── middleware.py       # Tier enforcement, rate limits
├── ai/                     # AI интеграции
│   ├── router.py           # AI Router с fallback цепочками
│   ├── rate_limiter.py     # Лимиты провайдеров
│   ├── cache.py            # LRU + SQLite кэш
│   └── providers/          # Адаптеры AI API
├── api/                    # REST API (Flask)
├── miniapp/                # Mini App (GitHub Pages)
├── data/                   # Публичные данные
└── .github/workflows/      # 24/7 GitHub Actions
```

## 🤖 AI Провайдеры

| Провайдер | Тип | Лимит | Ключ |
|-----------|-----|-------|------|
| **Pollinations** | Текст + Изображения | ∞ | Не нужен! |
| Groq | Текст + Whisper | 14 400/день | Нужен |
| OpenRouter | Текст | 10 000/день | Нужен |
| GitHub Models | Текст | 200/день | Нужен |
| Gemini | Текст + Перевод | 1 500/день | Нужен |
| Cerebras | Текст | 1 000 000/день | Нужен |
| HuggingFace | Мультимедиа | 5 000/день | Нужен |

**Pollinations работает без ключа — бот запускается сразу!**
Другие провайдеры подключаются при наличии ключей для увеличения лимитов.

## 🚀 Запуск

### Локально
```bash
pip install -r requirements.txt
export BOT_TOKEN=your_token
python -m bot.main
```

### GitHub Actions (24/7 бесплатно)
1. Создайте публичный репозиторий
2. Добавьте секреты (Settings → Secrets)
3. Запустите workflow `run-bot.yml`

## 🔑 Секреты GitHub

| Секрет | Описание | Обязательный |
|--------|----------|-------------|
| `BOT_TOKEN` | Токен от @BotFather | ✅ Да |
| `OWNER_ID` | Telegram ID владельца | ✅ Да |
| `ADMIN_IDS` | Telegram ID админов | ✅ Да |
| `GH_PAT_TOKEN` | GitHub PAT для keep-alive | ✅ Да |
| `API_SECRET` | Секрет для REST API | ✅ Да |
| `GROQ_API_KEY` | API ключ Groq | ❌ Опционально |
| `OPENROUTER_API_KEY` | API ключ OpenRouter | ❌ Опционально |
| `GITHUB_TOKEN` | GitHub PAT для Models | ❌ Опционально |
| `GEMINI_API_KEY` | Google AI API ключ | ❌ Опционально |
| `HF_TOKEN` | HuggingFace Access Token | ❌ Опционально |
| `CEREBRAS_API_KEY` | Cerebras API ключ | ❌ Опционально |

> **Бот работает сразу с Pollinations (без ключей).** Дополнительные ключи увеличивают скорость и лимиты.

## 💰 Монетизация

Telegram Stars (XTR) — встроенная платёжная система:
- Оплата прямо в Telegram
- Без комиссий для пользователей
- Вывод: Stars → Fragment → TON → рубли

## 📄 Лицензия

MIT
