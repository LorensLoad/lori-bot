import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "openai/gpt-oss-120b"

TIMEZONE_OFFSET = 3
TIMEZONE_NAME = "Москва"


def check_settings():
    """Проверяет, что ключи заданы. Если нет — останавливает бота."""
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN не задан в .env")
    if not GROQ_API_KEY:
        raise SystemExit("❌ GROQ_API_KEY не задан в .env")