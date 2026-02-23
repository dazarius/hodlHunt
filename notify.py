"""
Отправка уведомлений в Telegram и Discord.
Читает настройки из .env: HODL_TG_*, HODL_DISCORD_WEBHOOK
"""
import os
import re
import threading

try:
    import httpx
except ImportError:
    httpx = None


def _load_env() -> dict:
    env = dict(os.environ)
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def _strip_html(text: str) -> str:
    """Убрать HTML-теги для Discord."""
    return re.sub(r"<[^>]+>", "", text)


def send_tg(text: str, token: str | None = None, chat_id: str | None = None) -> bool:
    """Отправить в Telegram. token/chat_id из .env если не указаны."""
    if not httpx:
        return False
    env = _load_env()
    token = token or env.get("HODL_TG_TOKEN", "").strip()
    chat_id = chat_id or env.get("HODL_TG_CHAT", "").strip()
    if not token or not chat_id:
        return False

    def _post():
        try:
            r = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            if r.status_code != 200:
                import logging
                logging.getLogger("hodlhunt").warning(f"TG send failed: {r.text[:100]}")
        except Exception as e:
            import logging
            logging.getLogger("hodlhunt").warning(f"TG send: {e}")

    threading.Thread(target=_post, daemon=True).start()
    return True


def send_discord(text: str, webhook_url: str | None = None) -> bool:
    """Отправить в Discord через webhook. webhook_url из .env (HODL_DISCORD_WEBHOOK) если не указан."""
    if not httpx:
        return False
    env = _load_env()
    webhook_url = webhook_url or env.get("HODL_DISCORD_WEBHOOK", "").strip()
    if not webhook_url or "discord.com/api/webhooks" not in webhook_url:
        return False

    plain = _strip_html(text)

    def _post():
        try:
            r = httpx.post(
                webhook_url,
                json={"content": plain[:2000], "username": "HodlHunt"},
                timeout=10,
            )
            if r.status_code not in (200, 204):
                import logging
                logging.getLogger("hodlhunt").warning(f"Discord send failed: {r.status_code} {r.text[:100]}")
        except Exception as e:
            import logging
            logging.getLogger("hodlhunt").warning(f"Discord send: {e}")

    threading.Thread(target=_post, daemon=True).start()
    return True


def send_all(text: str, tg_token: str | None = None, tg_chat: str | None = None, discord_webhook: str | None = None):
    """Отправить в Telegram и Discord (если настроены)."""
    send_tg(text, token=tg_token, chat_id=tg_chat)
    send_discord(text, webhook_url=discord_webhook)
