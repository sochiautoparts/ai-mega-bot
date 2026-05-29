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

| Провайдер | Тип | Лимит | Модели |
|-----------|-----|-------|--------|
| Groq | Текст | 14 400/день | Llama 3.3 70B, Mixtral 8x7B |
| OpenRouter | Текст | 10 000/день | DeepSeek V4, Llama 3.1 8B |
| GitHub Models | Текст | 200/день | GPT-4o mini, Mistral Large |
| Gemini | Текст | 1 500/день | Gemini 2.0 Flash |
| Pollinations | Изображения | ∞ | Flux |
| HuggingFace | Мультимедиа | 5 000/день | Whisper, Bark, NLLB-200 |

**Суммарно: 16 000+ текстовых запросов/день бесплатно!**

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

## 🔑 Обязательные секреты GitHub

| Секрет | Описание |
|--------|----------|
| `BOT_TOKEN` | Токен от @BotFather |
| `ADMIN_IDS` | Telegram ID админов (через запятую) |
| `GROQ_API_KEY` | API ключ Groq (бесплатно на groq.com) |
| `OPENROUTER_API_KEY` | API ключ OpenRouter (бесплатно) |
| `GH_GITHUB_TOKEN` | GitHub PAT для GitHub Models |
| `GEMINI_API_KEY` | Google AI API ключ |
| `HF_TOKEN` | HuggingFace Access Token |
| `GH_PAT_TOKEN` | GitHub PAT для keep-alive (actions:write) |
| `API_SECRET` | Секрет для REST API |

## 💰 Монетизация

Telegram Stars (XTR) — встроенная платёжная система:
- Оплата прямо в Telegram
- Без комиссий для пользователей
- Вывод: Stars → Fragment → TON → рубли

## 📄 Лицензия

MIT
