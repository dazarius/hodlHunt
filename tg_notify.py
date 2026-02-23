"""
Отправка в Telegram. Алиас для notify.send_tg (обратная совместимость).
"""
from notify import send_tg


def send(text: str, token: str | None = None, chat_id: str | None = None) -> bool:
    """Отправить сообщение в Telegram. token/chat_id из .env если не указаны."""
    return send_tg(text, token=token, chat_id=chat_id)
