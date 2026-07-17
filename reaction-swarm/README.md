# Reaction Swarm — 10 ботов-админов

10 Telegram-ботов-админов ставят реакции и комментарии на новые посты в каналах:
- `@sochiautoparts`
- `@bmw_mpower_club`
- `@chasnastya`
- `@abakan_mebel`

## Архитектура

- **`swarm.py`** — async long-polling daemon на aiohttp
- **Режим `--daemon`**: 10 ботов параллельно слушают `getUpdates` (timeout=30с),
  реактят и комментят в real-time (1-2 сек задержка)
- **Режим single-shot** (без флага): один цикл `getUpdates → process → exit`,
  для sandbox/cron

## Workflow

`.github/workflows/reaction-swarm.yml` запускает swarm 24/7 на GitHub Actions:
- `python3 swarm.py --daemon` в auto-restart loop (переживает любой crash)
- schedule каждые 4 часа (fallback) + re-dispatch (primary)
- `cancel-in-progress: true` — нет параллельных инстансов → нет 409 Conflict
- параллельно с `run-bot.yml` (AI Mega Bot "Василий") — не конфликтует

## State files (gitignored)

- `.offsets.json` — per-bot offsets (at-least-once delivery)
- `.commented.json` — persistent guard от дублей комментариев
- `.heartbeat` — monitoring timestamp
- `.run.lock` — flock, нет дублей инстансов

## Environment

Все переменные передаются через GitHub Secrets:
- `BOT_TOKEN_ALLSTARSPAY` ... `BOT_TOKEN_LUKOILOIL` (10 токенов)
- `SWARM_CHANNELS` — список каналов
- `SWARM_LONG_POLL_TIMEOUT=30` — long-poll timeout
- `SWARM_DISABLED_BOTS=allstarspay` — отключён (внешний инстанс, 409)
- `SWARM_STALE_WINDOW=7200` — skip posts старше 2 часов

## Локальный запуск (для теста)

```bash
cd reaction-swarm
cp .env.example .env  # заполнить токены
pip install -r requirements.txt
python3 swarm.py --daemon
```
