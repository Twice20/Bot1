import asyncio
import re
import sqlite3
import time
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "ВСТАВЬ_ТОКЕН_ОТ_BOTFATHER"

ADMIN_IDS = [8171375787, 7164817125, 618731193]

REPLY_TEXT = "Привет я MillyBot, я сделан для авто ответа,\nКлюч: t.me/MillyMods"
DB_FILE = "stats.db"
MAX_LEN = 120  # длиннее - не считаем запросом ключа
# ===============================================

router = Router()

# ---------- Определение запроса ключа ----------
# Само слово "ключ" (целое слово, разные формы), либо key
WORD = r"(?:ключ(?:а|у|е|ом|и|ей|ик|ика|ику|ики)?|кюч|key|кей)"
# Граница слова для кириллицы и латиницы
B_L = r"(?<![а-яёa-z0-9])"
B_R = r"(?![а-яёa-z0-9])"
KEY = B_L + WORD + B_R

# Слова-глаголы/вопросы, которые вместе с "ключ" означают запрос
ASK = (
    r"(?:дай|дайте|давай|давайте|скинь|скиньте|пришли|пришлите|отправь|отправьте|"
    r"кинь|киньте|подскажи|подскажите|скажи|скажите|где|как|откуда|куда|"
    r"есть|нужен|нужна|нужно|надо|хочу|хочется|можно|можете|может|"
    r"получить|получу|получаю|найти|найду|взять|возьму|достать|достану|"
    r"купить|куплю|дают|выдают|выдайте|выдай|подарите|подари|"
    r"ссылк[ауи]|ссылку|плиз|пожалуйста|пж|пжл|плз|срочно)"
)

# 1) Сообщение целиком - только слово "ключ" (+ знаки/смайлы)
ONLY_KEY = re.compile(rf"^\W*{KEY}\W*$", re.IGNORECASE)
# 2) Просящее слово рядом со словом "ключ" в любом порядке
ASK_NEAR_KEY = re.compile(
    rf"(?:{B_L}{ASK}{B_R}.{{0,40}}{KEY})|(?:{KEY}.{{0,40}}{B_L}{ASK}{B_R})",
    re.IGNORECASE,
)
# Исключения: устойчивые выражения, которые не про наш ключ
NOT_REQUEST = re.compile(
    r"(гаечн\w+|разводн\w+|торцев\w+|ключ\s+от\s+(?:машин|квартир|дом|двер|гараж|сейф)\w*|"
    r"ключи\s+от\s+\w+|ключ\s+к\s+успех\w*|скрипичн\w+\s+ключ|"
    r"ключ\s+на\s+\d+|api\s*key|апи\s*ключ)",
    re.IGNORECASE,
)


def is_key_request(text: str) -> bool:
    text = text.strip()
    if not text or len(text) > MAX_LEN:
        return False
    if NOT_REQUEST.search(text):
        return False
    if ONLY_KEY.match(text):
        return True
    return bool(ASK_NEAR_KEY.search(text))


# ---------- База данных ----------
def db_init():
    with sqlite3.connect(DB_FILE) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS key_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                ts INTEGER
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_ts ON key_requests(ts)")


def db_add(chat_id: int, user_id: int, username: str | None, full_name: str):
    with sqlite3.connect(DB_FILE) as db:
        db.execute(
            "INSERT INTO key_requests (chat_id, user_id, username, full_name, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, user_id, username, full_name, int(time.time())),
        )


def db_stats(chat_id: int, days: int):
    since = int(time.time()) - days * 86400
    with sqlite3.connect(DB_FILE) as db:
        rows = db.execute(
            """
            SELECT user_id, MAX(username), MAX(full_name), COUNT(*) AS cnt
            FROM key_requests
            WHERE chat_id = ? AND ts >= ?
            GROUP BY user_id
            ORDER BY cnt DESC
            """,
            (chat_id, since),
        ).fetchall()
    return rows


# ---------- Вспомогательное ----------
def stats_keyboard(active: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("✅ " if active == 1 else "") + "1 день",
                    callback_data="stat:1",
                ),
                InlineKeyboardButton(
                    text=("✅ " if active == 7 else "") + "7 дней",
                    callback_data="stat:7",
                ),
            ]
        ]
    )


def build_stats_text(chat_id: int, days: int) -> str:
    rows = db_stats(chat_id, days)
    title = "1 день" if days == 1 else "7 дней"

    if not rows:
        return f"📊 <b>Статистика запросов ключа за {title}</b>\n\nНикто не просил ключ."

    total = sum(r[3] for r in rows)
    lines = [f"📊 <b>Статистика запросов ключа за {title}</b>\n"]

    for i, (user_id, username, full_name, cnt) in enumerate(rows, start=1):
        if username:
            name = f"@{escape(username)}"
        else:
            name = f'<a href="tg://user?id={user_id}">{escape(full_name or str(user_id))}</a>'
        lines.append(f"{i}. {name} - {cnt} раз(а)")

    lines.append(f"\n👥 Людей: {len(rows)}")
    lines.append(f"🔑 Всего запросов: {total}")
    return "\n".join(lines)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ---------- Хендлеры ----------
@router.message(Command("StatKey"))
async def cmd_statkey(message: Message):
    if not is_admin(message.from_user.id):
        return  # не-админам бот не отвечает
    await message.answer(
        build_stats_text(message.chat.id, 1),
        reply_markup=stats_keyboard(1),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("stat:"))
async def cb_stat(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    days = int(callback.data.split(":")[1])
    text = build_stats_text(callback.message.chat.id, days)

    try:
        await callback.message.edit_text(
            text,
            reply_markup=stats_keyboard(days),
            parse_mode="HTML",
        )
    except Exception:
        pass  # текст не изменился - Telegram кидает ошибку, игнорируем
    await callback.answer()


@router.message(F.text)
async def on_text(message: Message):
    if message.from_user.is_bot or message.text.startswith("/"):
        return

    if is_key_request(message.text):
        u = message.from_user
        db_add(message.chat.id, u.id, u.username, u.full_name)
        await message.reply(REPLY_TEXT)
    # Всё остальное игнорируется


# ---------- Запуск ----------
async def main():
    db_init()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
