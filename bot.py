"""
bot.py — точка входа Telegram-бота Lori.
Запуск: python bot.py
"""
import re
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, Filter
from aiogram.types import Message
from openai import OpenAI
from dotenv import load_dotenv
from aiogram import F
import html

from database import (
    init_db, save_message, get_history,
    clear_history, get_facts,
)
from config import (
    BOT_TOKEN, GROQ_API_KEY, GROQ_MODEL,
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
logging.getLogger("httpx").setLevel(logging.WARNING)

# ─── Проверка ключей ───
check_settings()

# ─── Клиент Groq (OpenAI-совместимый) ───
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY,
)

# ─── Telegram ───
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

TG_MAX_LENGTH = 4096

def markdown_to_html(text: str) -> str:
    """Преобразует markdown от Lori в безопасный HTML для Telegram."""

    # 1. Сначала вытаскиваем блоки кода ```lang ... ```
    code_blocks = []
    def save_code_block(match):
        lang = match.group(1) or ""
        code = match.group(2)
        # Экранируем < > & внутри кода
        code_safe = html.escape(code)
        placeholder = f"___CODE_BLOCK_{len(code_blocks)}___"
        code_blocks.append(
            f'<pre><code class="language-{lang}">{code_safe}</code></pre>'
        )
        return placeholder

    text = re.sub(
        r"```(\w+)?\n(.*?)```",
        save_code_block,
        text,
        flags=re.DOTALL,
    )

    # 2. Инлайн-код `code`
    def save_inline_code(match):
        code = match.group(1)
        return f"<code>{html.escape(code)}</code>"

    text = re.sub(r"`([^`]+)`", save_inline_code, text)

    # 3. Жирный и курсив
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

    # 4. Возвращаем блоки кода обратно
    for i, block in enumerate(code_blocks):
        text = text.replace(f"___CODE_BLOCK_{i}___", block)

    return text

# ═══════════════════════════════════════════════════════
#  ФИЛЬТР ЗАПРЕЩЁННОГО КОНТЕНТА
# ═══════════════════════════════════════════════════════
class BadContentFilter(Filter):
    """Пропускает сообщение, если в нём нет запрещённых слов и тем."""
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return True

        text = message.text.lower()

        if any(bad in text for bad in BAD_WORDS):
            return False
        if any(topic in text for topic in FORBIDDEN_TOPICS):
            return False
        return True


# ═══════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════
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
    """Строка с текущим временем."""
    now = _now_local()
    return now.strftime(f"%d.%m.%Y, %H:%M ({TIMEZONE_NAME}, UTC+{TIMEZONE_OFFSET})")


async def send_long_message(message: types.Message, text: str):
    """Отправляет длинный текст с разбивкой. При битом HTML — как обычный."""
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
    await message.answer(
        TEXTS["start"].format(
            greeting=time_greeting(),
            name=message.from_user.first_name,
        ),
        parse_mode="HTML",
        reply_markup=main_keyboard(),   # ← добавляем кнопки
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(TEXTS["help"], parse_mode="HTML")


@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    user_id = message.from_user.id
    await clear_history(user_id)
    await message.answer("🧹 История диалога очищена. Начнём с чистого листа.")

def markdown_to_html(text: str) -> str:
    """Меняет **жирный** и *курсив* на HTML-теги."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    return text

# ═══════════════════════════════════════════════════════
#  ОТВЕТ НА ЗАПРЕЩЁННЫЙ КОНТЕНТ
# ═══════════════════════════════════════════════════════
@dp.message(~BadContentFilter())
async def handle_bad_content(message: types.Message):
    await message.answer(
        "Прошу прощения, но я не могу обработать это сообщение. "
        "Пожалуйста, воздержитесь от нецензурной лексики и запрещённых тем."
    )

@dp.message(F.text == "🧹 Очистить историю")
async def btn_clear(message: types.Message):
    user_id = message.from_user.id
    await clear_history(user_id)
    await message.answer("🧹 История диалога очищена. Начнём с чистого листа.")


@dp.message(F.text == "❓ Помощь")
async def btn_help(message: types.Message):
    await message.answer(TEXTS["help"], parse_mode="HTML")
# ═══════════════════════════════════════════════════════
#  ОСНОВНОЙ ОБРАБОТЧИК
# ═══════════════════════════════════════════════════════
@dp.message(BadContentFilter())
async def chat_with_ai(message: types.Message):
    if message.text is None:
        await message.answer("Я понимаю только текст 🙂")
        return

    user_id = message.from_user.id
    user_text = message.text

    print(f"[{user_id}] {message.from_user.first_name}: {user_text}")

    await save_message(user_id, "user", user_text)

    # Фоновая задача «печатает...»
    async def keep_typing():
        while True:
            await bot.send_chat_action(message.chat.id, "typing")
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(keep_typing())

    try:
        # История и факты из базы
        history = await get_history(user_id, limit=20)
        facts = await get_facts(user_id)
        now_str = current_time_string()

        history_text = "\n".join(
            f"{'Пользователь' if role == 'user' else 'Lori'}: {content}"
            for role, content in history[:-1]
        )

        system_prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"[Сейчас {now_str}]\n"
            f"[Что ты знаешь о пользователе: {facts or 'пока ничего'}]\n"
            f"[История диалога:]\n{history_text}"
        )

        # Запрос к Groq
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        )
        answer = response.choices[0].message.content
        answer = markdown_to_html(answer)

        await save_message(user_id, "assistant", answer)
        await send_long_message(message, answer)

    except Exception as e:
        error_text = str(e)

        if "429" in error_text or "rate_limit" in error_text.lower():
            await message.answer(
                "Прошу прощения, сэр. Я исчерпала дневной лимит запросов. "
                "Вернусь в строй, как только Groq обновит квоту."
            )
        elif "401" in error_text or "unauthorized" in error_text.lower():
            await message.answer(
                "Прошу прощения, сэр. Похоже, проблема с моим ключом доступа. "
                "Пожалуйста, проверьте настройки."
            )
        else:
            await message.answer(f"Прошу прощения, произошла ошибка: {e}")

    finally:
        typing_task.cancel()


# ═══════════════════════════════════════════════════════
#  ЗАПУСК
# ═══════════════════════════════════════════════════════
async def main():
    await init_db()
    print("База данных готова.")
    print("Бот Lori запущен...")
    print("─" * 50)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())