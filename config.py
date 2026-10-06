"""
config.py — все настройки бота в одном месте.
Значения читаются из файла .env (см. .env.example).
Здесь ничего менять не нужно — меняйте файл .env.
"""
import os

from dotenv import load_dotenv

# Читаем файл .env и кладём его значения в переменные окружения
load_dotenv()


def _get_int(name: str, default: int) -> int:
    """Читает целое число из .env. Если нет или испорчено — берёт default."""
    try:
        return int(os.getenv(name, "").strip())
    except ValueError:
        return default


# ── Ключи ──
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# ── Модель Gemini ──
# По умолчанию — gemini-3.5-flash-lite (быстрая и бесплатная).
# Если появятся ошибки "model not found" — смените значение в .env.
# Список актуальных моделей: https://ai.google.dev/gemini-api/docs/models
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()

# ── Часовой пояс ──
# Москва = 3, Киев = 2, Алматы = 5, Берлин = 1 и т.д.
TIMEZONE_OFFSET = _get_int("TIMEZONE_OFFSET", 3)
TIMEZONE_NAME = os.getenv("TIMEZONE_NAME", "Москва").strip() or "Москва"


def check_settings() -> None:
    """Проверяет, что ключи вписаны. Если нет — останавливает бота с понятным текстом."""
    problems = []
    if not BOT_TOKEN or BOT_TOKEN.startswith("сюда_"):
        problems.append("• Не указан BOT_TOKEN (токен от @BotFather)")
    if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("сюда_"):
        problems.append("• Не указан GEMINI_API_KEY (ключ с aistudio.google.com/apikey)")

    if problems:
        raise SystemExit(
            "\nБот не может запуститься:\n"
            + "\n".join(problems)
            + "\n\nОткройте файл .env, впишите значения и запустите снова.\n"
            "Если .env нет — скопируйте .env.example и переименуйте копию в .env\n"
        )