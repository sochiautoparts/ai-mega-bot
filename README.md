# AI Mega Bot 🤖 (OpenClaw architecture)

Мультифункциональный AI-бот **Василий** (@aimega_bot) в Telegram, работающий
**в среде OpenClaw** и развёрнутый **в GitHub Actions 24/7 бесплатно**.

## 🏗 Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│  GitHub Actions runner (ubuntu-latest)                      │
│                                                             │
│   ┌──────────────────────┐    OpenAI-compatible API         │
│   │  OpenClaw Gateway    │  POST /v1/chat/completions       │
│   │  (Node.js, port 18789│◀────────────────────────┐        │
│   │  OpenAI endpoint on) │                         │        │
│   └──────────┬───────────┘                         │        │
│              │ model failover + key rotation        │        │
│   ┌──────────▼─────────────┐  Pollinations(free)   ┌────────┴───────┐
│   │  AI providers          │  Groq/Gemini/OR/HF/   │ Python aiogram │
│   │  (11 providers)        │  Cerebras/OpenAI/...  │ bot (handlers) │
│   └────────────────────────┘                       └────────────────┘
│                                                             │
│   unlimited auto-restart loop → 24/7                        │
└─────────────────────────────────────────────────────────────┘
```

**OpenClaw** разворачивается в Actions как Gateway (Node.js), который отдаёт
OpenAI-совместимый `POST /v1/chat/completions` на localhost. Python-бот
(aiogram) обрабатывает Telegram-логику и **все AI-запросы** направляет через
OpenClaw — то есть бот работает именно в среде OpenClaw.

## 🎯 Поведение бота

| Где добавлен бот | Что делает |
|---|---|
| 📰 **Канал** | **Только реакции** (👍❤️🔥😄😮🙏) на посты. Без комментариев — канал остаётся чистым. |
| 👥 **Группа / супергруппа** | **Активно общается** со всеми (включая ботов), ставит реакции, комментирует новости и события. **Дополняет** новости и события информацией из интернета (веб-поиск). |
| 💬 **Личный чат** | Общение с памятью диалога, понимает фото/голосовые/стикеры. |
| 🏷 **Inline mode** | `@aimega_bot <вопрос>` работает в **любом чате** (даже где бота нет). |

## ✨ Возможности (9 функций)

| Функция | Описание | Требует ключей |
|---|---|---|
| 💬 **Текст** | Общение в личке и группах, память диалога и фактов о людях | Нет (Pollinations free) |
| 📷 **Фото (Vision)** | Понимает содержимое фото, описывает и реагирует | Gemini/OpenAI (опц.) |
| 🎤 **Голосовые** | Транскрипция через Whisper + ответ на текст | Groq (опц.) |
| 😀 **Стикеры** | Реагирует на эмодзи стикера, комментирует | Нет |
| 🎬 **GIF/Видео/Кружочки** | Реагирует и комментирует (при обращении) | Нет |
| 🔍 **Новости** | Развёрнуто дополняет новости инфой из интернета (DDG+SearXNG+Yandex) | Нет |
| 🗣 **Proactive topics** | Сам начинает беседу в тихих/активных группах | Нет |
| 📝 **Память бесед** | 30-мин суммаризация обсуждений для долгой памяти | Нет |
| 🏷 **Inline** | `@aimega_bot <вопрос>` в любом чате | Нет |

**Покрытие 100% типов сообщений** — ни одно сообщение не игнорируется: текст, фото, голос, стикеры, GIF, видео, кружочки, документы, dice, контакты, локации, опросы.

## 🤖 AI-провайдеры (через OpenClaw)

Бот **всегда работает** на Pollinations (бесплатно, без ключа). Остальные
провайдеры **автовключаются** при наличии ключа в GitHub Secrets:

| Провайдер | Тип | Ключ |
|-----------|-----|------|
| **Pollinations** | Текст (GPT-OSS 20B) | Не нужен (free) |
| Groq | Llama 3.3 70B (быстрый) | `GROQ_API_KEY` |
| Google Gemini | 2.0 Flash | `GEMINI_API_KEY` |
| OpenRouter | free-модели (Llama, Gemma) | `OPENROUTER_API_KEY` |
| HuggingFace | Qwen2.5 7B | `HF_TOKEN` |
| Cerebras | Llama 3.3 70B | `CEREBRAS_API_KEY` |
| SambaNova | Llama 3.1 8B | `SAMBANOVA_API_KEY` |
| Mistral | Mistral Small | `MISTRAL_API_KEY` |
| OpenAI | GPT-4o / mini | `OPENAI_API_KEY` |
| Anthropic | Claude 3.5 Sonnet | `ANTHROPIC_API_KEY` |
| xAI | Grok | `XAI_API_KEY` |

Конфиг OpenClaw генерируется **динамически** при старте (`scripts/gen_openclaw_config.py`)
— в него попадают только провайдеры с реальными ключами + Pollinations.
Порядок failover: Groq → Gemini → Cerebras → OpenRouter → HF → … → Pollinations.

## 🔄 Надёжность 24/7 (как у luba)

`.github/workflows/run-bot.yml` реализует тот же паттерн, что и
[sochiautoparts/luba](https://github.com/sochiautoparts/luba):

1. **Cancel conflicting runs** — отменяет другие запуски и ждёт 60с для чистой передачи.
2. **Unlimited auto-restart loop** — бот перезапускается при любом падении
   (экспоненциальный бэкофф 5→10→15→30с).
3. **DB cache** — SQLite кэшируется между запусками (actions/cache).
4. **DB git commit** — база коммитится в репо для персистентности памяти.
5. **Re-dispatch** — в конце ворклоу триггерит следующий запуск (3 попытки) → 24/7.
6. **concurrency: cancel-in-progress** — только один экземпляр бота одновременно.

## 🚀 Запуск

### GitHub Actions (24/7 бесплатно)

1. Форкните/клонируйте репозиторий.
2. `Settings → Secrets and variables → Actions` добавьте секреты (см. ниже).
3. Запустите workflow `Run AI Mega Bot 24/7 (OpenClaw)` (`workflow_dispatch`).

### Локально

```bash
pip install -r requirements.txt
npm install -g openclaw@latest      # Node 22+
cp .env.example .env                # заполнить BOT_TOKEN
python -m bot.main
```

## 🔑 Секреты GitHub

| Секрет | Обязательный | Описание |
|--------|:---:|---|
| `BOT_TOKEN` | ✅ | Токен от @BotFather |
| `BOT_ID` | ✅ | Числовой ID бота |
| `OWNER_ID` | ✅ | Ваш Telegram ID |
| `GH_PAT_TOKEN` | ✅ | GitHub PAT для self-dispatch |
| `GROQ_API_KEY` | опц. | https://console.groq.com/keys |
| `GEMINI_API_KEY` | опц. | https://aistudio.google.com/apikey |
| `OPENROUTER_API_KEY` | опц. | https://openrouter.ai/keys |
| `HF_TOKEN` | опц. | https://huggingface.co/settings/tokens |
| `CEREBRAS_API_KEY` | опц. | https://cloud.cerebras.ai/ |
| `SAMBANOVA_API_KEY` | опц. | https://cloud.sambanova.ai/ |
| `MISTRAL_API_KEY` | опц. | https://console.mistral.ai/ |
| `OPENAI_API_KEY` | опц. | платный |
| `ANTHROPIC_API_KEY` | опц. | платный |
| `XAI_API_KEY` | опц. | платный |

> **Бот работает сразу на Pollinations (без ключей).** Ключи увеличивают
> скорость, надёжность и лимиты.

## ⚙️ Настройки бота (@BotFather)

### 1. Group Privacy → OFF (чтобы бот видел ВСЕ сообщения в группах)
`@BotFather` → `/mybots` → ваш бот → **Bot Settings** → **Group Privacy** → **Turn off**

### 2. Реакции в каналах (чтобы бот ставил 👍❤️🔥)
Добавьте бота **админом канала**:
- Канал → **Manage Channel** → **Administrators** → **Add Administrator**
- Найдите бота, дайте право **Post Messages** (реакции работают автоматически)

В группах реакции работают без админки — бот просто должен быть участником.

### 3. Inline Mode (чтобы бот отвечал в ЛЮБОМ чате через @упоминание)
`@BotFather` → `/mybots` → ваш бот → **Bot Settings** → **Inline Mode** → **Turn on**
После этого в любом чате можно написать `@aimega_bot как дела` — Василий ответит мгновенно.

## 📁 Структура

```
ai-mega-bot/
├── .github/workflows/run-bot.yml   # 24/7 надёжный перезапуск (luba-style)
├── openclaw/openclaw.json          # пример конфига OpenClaw (полный)
├── scripts/gen_openclaw_config.py  # динамическая генерация конфига по ключам
├── bot/
│   ├── main.py                     # запуск OpenClaw gateway + бот (5 фоновых задач)
│   ├── config.py                   # конфиг из env
│   ├── database.py                 # SQLite (users, facts, history, summaries, ...)
│   ├── reactions.py                # emoji-реакции
│   ├── web_search.py               # DuckDuckGo + SearXNG + Yandex + article fetch
│   ├── context.py                  # сбор контекста: профиль + summaries + recent
│   ├── mood.py                     # динамическое настроение (мужской род)
│   ├── safe_send.py                # rate-limit-safe отправка + safe_send
│   ├── persona.py                  # системные промпты с few-shot примерами
│   ├── media_handler.py            # фото + голосовые → base64
│   ├── proactive.py                # proactive topics + conversation summaries loop
│   └── handlers/
│       ├── channels.py             # ТОЛЬКО реакции на посты каналов
│       ├── groups.py               # активное общение + 100% типов сообщений
│       ├── chat.py                 # личные чаты + фото/голос/стикеры/catch-all
│       ├── inline.py               # @aimega_bot inline mode (любой чат)
│       └── admin.py                # /stats /models /diag /broadcast ...
├── ai/client.py                    # OpenClaw + Pollinations + vision + Whisper
├── requirements.txt
└── .env.example
```

## 🧠 Команды

- `/start`, `/help` — приветствие + список возможностей
- `/clear` — забыть историю личного чата
- `/mood` — показать настроение
- `/whoami` — что бот помнит о тебе (профиль + факты)
- `/stats` (владелец) — статистика AI-запросов по слоям
- `/models` (владелец) — модели Pollinations + статистика AI
- `/providers` (владелец) — активные провайдеры OpenClaw
- `/diag` (владелец) — диагностика: видит ли бот сообщения в чате
- `/channel_on <id>` / `/channel_off <id>` (владелец) — вкл/выкл реакции канала
- `/broadcast <chat_id> <text>` (владелец) — отправить сообщение

## 📄 Лицензия

MIT
