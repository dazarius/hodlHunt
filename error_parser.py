import json
import re
import os
from typing import Tuple

_ERROR_MAP = {}
_IDL_PATH = os.path.join(os.path.dirname(__file__), "idl.json")

def _load_errors():
    global _ERROR_MAP
    if _ERROR_MAP:
        return
    
    if not os.path.exists(_IDL_PATH):
        return
        
    try:
        with open(_IDL_PATH, "r", encoding="utf-8") as f:
            idl = json.load(f)
            for err in idl.get("errors", []):
                _ERROR_MAP[err["code"]] = {
                    "name": err["name"],
                    "msg": err["msg"]
                }
    except Exception:
        pass

def parse_tx_error(err_str: str) -> str:
    """
    Парсит сообщение об ошибке (например от SendTransactionPreflightFailureMessage)
    и возвращает человекочитаемый Markdown.
    """
    _load_errors()
    
    # Ищем код ошибки вида Custom(6009) или 0x1779
    code = None
    
    # 1. Поиск Error Code / Number:
    m = re.search(r"Error Number:\s*(\d+)", err_str)
    if m:
        code = int(m.group(1))
        
    # 2. Поиск Custom(6009)
    if not code:
        m = re.search(r"Custom\((\d+)\)", err_str)
        if m:
            code = int(m.group(1))
            
    # 3. Поиск Hex 0x1779
    if not code:
        m = re.search(r"custom program error:\s*(0x[0-9a-fA-F]+)", err_str)
        if m:
            try:
                code = int(m.group(1), 16)
            except ValueError:
                pass

    if code and code in _ERROR_MAP:
        err_info = _ERROR_MAP[code]
        return f"🚨 Ошибка контракта: <b>{err_info['name']}</b>\n💡 <i>{err_info['msg']}</i>"
    
    # fallback если не нашли специфичную ошибку, но видим кастом
    if code:
        return f"🚨 Неизвестная ошибка контракта: <b>{code}</b>"
        
    return f"❌ Ошибка отправки:\n<code>{err_str[:200]}...</code>"

def format_queue_error_html(action: str, label: str, err_str: str) -> str:
    parsed_err = parse_tx_error(err_str)
    return (
        f"🔴 <b>Ошибка в очереди</b>\n"
        f"🎣 Действие: <code>{action}</code>\n"
        f"🎯 Цель: <code>{label}</code>\n\n"
        f"{parsed_err}"
    )
