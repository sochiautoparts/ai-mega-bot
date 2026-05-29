"""
База данных SQLite для бота
- Пользователи с подписками
- Реферальная система
- История платежей
- Аналитика использования
"""

import aiosqlite
import time
from config import Config

DB = Config.DB_PATH


async def init_db():
    """Инициализация всех таблиц"""
    async with aiosqlite.connect(DB) as db:
        # Пользователи
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                language_code TEXT DEFAULT 'ru',
                plan TEXT DEFAULT 'free',           -- free / pro / premium
                plan_expires_at REAL DEFAULT 0,     -- timestamp окончания подписки
                referrer_id INTEGER DEFAULT 0,       -- кто пригласил
                referral_count INTEGER DEFAULT 0,    -- сколько пригласил
                chat_used_today INTEGER DEFAULT 0,   -- использовано чатов сегодня
                image_used_today INTEGER DEFAULT 0,  -- использовано картинок сегодня
                copy_used_today INTEGER DEFAULT 0,   -- использовано копирайтинга сегодня
                last_reset_date TEXT DEFAULT '',      -- дата последнего сброса лимитов
                total_messages INTEGER DEFAULT 0,     -- всего сообщений
                total_images INTEGER DEFAULT 0,       -- всего картинок
                total_copywrites INTEGER DEFAULT 0,   -- всего копирайтов
                registered_at REAL DEFAULT 0,         -- дата регистрации
                is_banned INTEGER DEFAULT 0,          -- забанен?
                channel_subscribed INTEGER DEFAULT 0   -- подписан на канал?
            )
        """)

        # Платежи
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount_stars INTEGER,
                plan TEXT,
                months INTEGER,
                telegram_payment_id TEXT,
                status TEXT DEFAULT 'pending',  -- pending / completed / refunded
                created_at REAL DEFAULT 0
            )
        """)

        # Реферальные события
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                bonus_given INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0
            )
        """)

        # Ежедневная аналитика
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                new_users INTEGER DEFAULT 0,
                active_users INTEGER DEFAULT 0,
                messages_sent INTEGER DEFAULT 0,
                images_generated INTEGER DEFAULT 0,
                copywrites_generated INTEGER DEFAULT 0,
                revenue_stars INTEGER DEFAULT 0,
                new_subscribers INTEGER DEFAULT 0
            )
        """)

        await db.commit()


async def get_user(user_id: int) -> dict | None:
    """Получить данные пользователя"""
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def create_user(user_id: int, username: str = "", first_name: str = "",
                      referrer_id: int = 0) -> dict:
    """Создать нового пользователя с пробным Pro-периодом"""
    now = time.time()
    trial_end = now + (Config.TRIAL_PRO_DAYS * 86400)
    today = time.strftime("%Y-%m-%d")

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users 
            (user_id, username, first_name, plan, plan_expires_at, 
             referrer_id, last_reset_date, registered_at)
            VALUES (?, ?, ?, 'pro', ?, ?, ?, ?)
        """, (user_id, username, first_name, trial_end, referrer_id, today, now))
        await db.commit()

        # Обработка реферала
        if referrer_id and referrer_id != user_id:
            referrer = await get_user(referrer_id)
            if referrer:
                # Начисляем бонус рефереру
                new_expire = max(referrer['plan_expires_at'], now) + (Config.REFERRAL_BONUS_DAYS * 86400)
                new_plan = 'pro' if new_expire > now else referrer['plan']
                await db.execute("""
                    UPDATE users SET referral_count = referral_count + 1,
                                     plan = ?, plan_expires_at = ?
                    WHERE user_id = ?
                """, (new_plan, new_expire, referrer_id))

                # Записываем реферальное событие
                await db.execute("""
                    INSERT INTO referrals (referrer_id, referred_id, bonus_given, created_at)
                    VALUES (?, ?, 1, ?)
                """, (referrer_id, user_id, now))
                await db.commit()

    return await get_user(user_id)


async def check_and_update_plan(user_id: int) -> dict:
    """Проверить подписку и обновить статус если истёк"""
    user = await get_user(user_id)
    if not user:
        return None

    now = time.time()
    if user['plan'] in ('pro', 'premium') and user['plan_expires_at'] < now:
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE users SET plan = 'free' WHERE user_id = ?", (user_id,))
            await db.commit()
        user['plan'] = 'free'

    return user


async def reset_daily_limits_if_needed(user_id: int) -> dict:
    """Сбросить дневные лимиты если наступил новый день"""
    today = time.strftime("%Y-%m-%d")
    user = await get_user(user_id)
    if not user:
        return None

    if user['last_reset_date'] != today:
        async with aiosqlite.connect(DB) as db:
            await db.execute("""
                UPDATE users SET chat_used_today = 0, image_used_today = 0,
                                 copy_used_today = 0, last_reset_date = ?
                WHERE user_id = ?
            """, (today, user_id))
            await db.commit()
        user['chat_used_today'] = 0
        user['image_used_today'] = 0
        user['copy_used_today'] = 0
        user['last_reset_date'] = today

    return user


async def can_use_chat(user_id: int) -> tuple[bool, int]:
    """Можно ли использовать чат? Возвращает (можно, остаток)"""
    user = await reset_daily_limits_if_needed(user_id)
    await check_and_update_plan(user_id)
    user = await get_user(user_id)
    if not user:
        return False, 0

    if user['plan'] in ('pro', 'premium'):
        return True, 999

    remaining = Config.FREE_CHAT_LIMIT - user['chat_used_today']
    return remaining > 0, remaining


async def can_use_image(user_id: int) -> tuple[bool, int]:
    """Можно ли генерировать картинку?"""
    user = await reset_daily_limits_if_needed(user_id)
    await check_and_update_plan(user_id)
    user = await get_user(user_id)
    if not user:
        return False, 0

    if user['plan'] in ('pro', 'premium'):
        return True, 999

    remaining = Config.FREE_IMAGE_LIMIT - user['image_used_today']
    return remaining > 0, remaining


async def can_use_copywrite(user_id: int) -> tuple[bool, int]:
    """Можно ли использовать копирайтинг?"""
    user = await reset_daily_limits_if_needed(user_id)
    await check_and_update_plan(user_id)
    user = await get_user(user_id)
    if not user:
        return False, 0

    if user['plan'] in ('pro', 'premium'):
        return True, 999

    remaining = Config.FREE_COPYWRITE_LIMIT - user['copy_used_today']
    return remaining > 0, remaining


async def increment_chat_usage(user_id: int):
    """Увеличить счётчик использования чата"""
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            UPDATE users SET chat_used_today = chat_used_today + 1,
                             total_messages = total_messages + 1
            WHERE user_id = ?
        """, (user_id,))
        await db.commit()


async def increment_image_usage(user_id: int):
    """Увеличить счётчик генерации картинок"""
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            UPDATE users SET image_used_today = image_used_today + 1,
                             total_images = total_images + 1
            WHERE user_id = ?
        """, (user_id,))
        await db.commit()


async def increment_copywrite_usage(user_id: int):
    """Увеличить счётчик копирайтинга"""
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            UPDATE users SET copy_used_today = copy_used_today + 1,
                             total_copywrites = total_copywrites + 1
            WHERE user_id = ?
        """, (user_id,))
        await db.commit()


async def activate_subscription(user_id: int, months: int, payment_id: str = ""):
    """Активировать подписку на N месяцев"""
    now = time.time()
    user = await get_user(user_id)
    if not user:
        return

    # Если уже есть подписка — продлеваем от текущей даты окончания
    current_end = max(user['plan_expires_at'], now)
    new_end = current_end + (months * 30 * 86400)

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            UPDATE users SET plan = 'pro', plan_expires_at = ? WHERE user_id = ?
        """, (new_end, user_id))

        await db.execute("""
            INSERT INTO payments (user_id, amount_stars, plan, months, 
                                  telegram_payment_id, status, created_at)
            VALUES (?, ?, 'pro', ?, ?, 'completed', ?)
        """, (user_id, months * Config.PRICE_STARS_MONTH // months, months, payment_id, now))

        await db.commit()


async def get_stats() -> dict:
    """Получить общую статистику для админки"""
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("SELECT COUNT(*) as cnt FROM users") as c:
            total_users = (await c.fetchone())['cnt']

        async with db.execute("SELECT COUNT(*) as cnt FROM users WHERE plan != 'free'") as c:
            paid_users = (await c.fetchone())['cnt']

        async with db.execute("SELECT SUM(total_messages) as s FROM users") as c:
            total_messages = (await c.fetchone())['s'] or 0

        async with db.execute("SELECT SUM(total_images) as s FROM users") as c:
            total_images = (await c.fetchone())['s'] or 0

        async with db.execute("SELECT SUM(referral_count) as s FROM users") as c:
            total_referrals = (await c.fetchone())['s'] or 0

        async with db.execute("SELECT SUM(amount_stars) as s FROM payments WHERE status='completed'") as c:
            total_revenue = (await c.fetchone())['s'] or 0

        return {
            "total_users": total_users,
            "paid_users": paid_users,
            "total_messages": total_messages,
            "total_images": total_images,
            "total_referrals": total_referrals,
            "total_revenue_stars": total_revenue,
        }


async def get_recent_users(limit: int = 10) -> list[dict]:
    """Последние зарегистрированные пользователи"""
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY registered_at DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def ban_user(user_id: int, ban: bool = True):
    """Забанить/разбанить пользователя"""
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?",
                         (1 if ban else 0, user_id))
        await db.commit()


async def update_channel_subscription(user_id: int, subscribed: bool):
    """Обновить статус подписки на канал"""
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET channel_subscribed = ? WHERE user_id = ?",
                         (1 if subscribed else 0, user_id))
        await db.commit()
