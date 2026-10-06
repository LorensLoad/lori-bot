"""
bot.py — точка входа Telegram-бота Lori.

Запуск: python bot.py

Настройки (токен, ключ Gemini, модель, часовой пояс) — в файле .env.
Характер и тексты — в prompts.py.
Списки стоп-слов — в bad_words.py.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, Filter
from aiogram.types import Message
from google import genai

from config import (
    BOT_TOKEN, GEMINI_API_KEY, GEMINI_MODEL,
    TIMEZONE_OFFSET, TIMEZONE_NAME, check_settings,
)
from prompts import SYSTEM_PROMPT, TEXTS
from bad_words import BAD_WORDS, FORBIDDEN_TOPICS

# ─── Логирование ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("lori")
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ─── Проверка ключей (если пусто — остановит бота) ───
check_settings()

# ─── Клиент Gemini и Telegram ───
client = genai.Client(api_key=GEMINI_API_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

chats = {}  # {user_id: chat-объект Gemini}
TG_MAX_LENGTH = 4096


# ═══════════════════════════════════════════════════════
#  ФИЛЬТР ЗАПРЕЩЁННОГО КОНТЕНТА
# ═══════════════════════════════════════════════════════
class BadContentFilter(Filter):
    """Пропускает сообщение, если в нём нет запрещённых слов и тем."""
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return True  # не текст — пропускаем, обработается отдельно

        text = message.text.lower()

        if any(bad in text for bad in BAD_WORDS):
            return False
        if any(topic in text for topic in FORBIDDEN_TOPICS):
            return False
        return True


# ═══════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════
def get_chat(user_id: int):
    """Возвращает чат пользователя, создаёт при первом обращении."""
    if user_id not in chats:
        chats[user_id] = client.chats.create(
            model=GEMINI_MODEL,
            config={"system_instruction": SYSTEM_PROMPT},
        )
    return chats[user_id]


def _now_local() -> datetime:
    """Текущее время с учётом часового пояса из .env."""
    return datetime.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)


def time_greeting() -> str:
    """Приветствие по времени суток."""
    hour = _now_local().hour
    if 5 <= hour < 12:
        return TEXTS["greeting_morning"]
    if 12 <= hour < 18:
        return TEXTS["greeting_day"]
    if 18 <= hour < 23:
        return TEXTS["greeting_evening"]
    return TEXTS["greeting_night"]


def current_time_string() -> str:
    """Строка с текущим временем, которая подмешивается к сообщению пользователя."""
    now = _now_local()
    return now.strftime(f"%d.%m.%Y, %H:%M ({TIMEZONE_NAME}, UTC+{TIMEZONE_OFFSET})")


async def send_long_message(message: types.Message, text: str):
    """Отправляет длинный текст с разбивкой. При битом HTML — отправляет как обычный."""
    async def safe_send(txt: str):
        try:
            await message.answer(txt, parse_mode="HTML")
        except Exception:
            await message.answer(txt)

    if len(text) <= TG_MAX_LENGTH:
        await safe_send(text)
        return

    chunks = []
    while text:
        if len(text) <= TG_MAX_LENGTH:
            chunks.append(text)
            break

        split_pos = text.rfind("\n", 0, TG_MAX_LENGTH)
        if split_pos == -1:
            split_pos = text.rfind(". ", 0, TG_MAX_LENGTH)
        if split_pos == -1:
            split_pos = TG_MAX_LENGTH

        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip()

    for chunk in chunks:
        await safe_send(chunk)
        await asyncio.sleep(0.3)


# ═══════════════════════════════════════════════════════
#  КОМАНДЫ
# ═══════════════════════════════════════════════════════
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chats.pop(message.from_user.id, None)  # сброс истории
    await message.answer(
        TEXTS["start"].format(
            greeting=time_greeting(),
            name=message.from_user.first_name,
        ),
        parse_mode="HTML",
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(TEXTS["help"], parse_mode="HTML")


@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    chats.pop(message.from_user.id, None)
    await message.answer(TEXTS["cleared"])


# ═══════════════════════════════════════════════════════
#  ОТВЕТ НА ЗАПРЕЩЁННЫЙ КОНТЕНТ
# ═══════════════════════════════════════════════════════
@dp.message(~BadContentFilter())
async def handle_bad_content(message: types.Message):
    await message.answer(
        "Прошу прощения, но я не могу обработать это сообщение. "
        "Пожалуйста, воздержитесь от нецензурной лексики и запрещённых тем."
    )


# ═══════════════════════════════════════════════════════
#  ОСНОВНОЙ ОБРАБОТЧИК
# ═══════════════════════════════════════════════════════
@dp.message(BadContentFilter())
async def chat_with_ai(message: types.Message):
    log.info("msg from %s: %s", message.from_user.id, message.text)

    if message.text is None:
        await message.answer(TEXTS["only_text"])
        return

    user_id = message.from_user.id
    user_text = message.text

    # Фоновая задача «печатает...», пока думает Gemini
    async def keep_typing():
        try:
            while True:
                await bot.send_chat_action(message.chat.id, "typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    typing_task = asyncio.create_task(keep_typing())

    try:
        chat = get_chat(user_id)
        message_for_ai = f"[Сейчас {current_time_string()}]\n\n{user_text}"
        response = chat.send_message(message_for_ai)
        answer = response.text or TEXTS["empty"]
        await send_long_message(message, answer)

    except Exception as e:
        error_text = str(e)

        if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
            await message.answer(TEXTS["rate_limit"])
        elif "SAFETY" in error_text or "blocked" in error_text.lower():
            await message.answer(TEXTS["safety"])
        elif "Connection" in error_text or "timeout" in error_text.lower():
            await message.answer(TEXTS["connection"])
        else:
            log.exception("Неизвестная ошибка")
            await message.answer(TEXTS["unknown_error"])

    finally:
        typing_task.cancel()


# ═══════════════════════════════════════════════════════
#  ЗАПУСК
# ═══════════════════════════════════════════════════════
async def main():
    log.info("Бот Lori запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())