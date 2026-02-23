"""Конфигурация путей, логирования и кэша."""
import os
import json
import logging
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"hodlhunt_{datetime.now().strftime('%Y%m%d')}.log")
WALLETS_CONFIG_PATH = os.path.join(BASE_DIR, "wallets_config.json")

file_logger = logging.getLogger("hodlhunt")
file_logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
file_logger.addHandler(_fh)


def sched_cache_path(wallet_index: int) -> str:
    return os.path.join(BASE_DIR, f"scheduler_cache_{wallet_index}.json")


def all_sched_cache_paths(wallets_count: int) -> list[tuple[int, str]]:
    """Return [(wallet_index, path), ...] for all wallet caches."""
    return [(i, os.path.join(BASE_DIR, f"scheduler_cache_{i}.json")) for i in range(max(wallets_count, 1))]


SCHEDULE_TRANSACTIONS_PATH = os.path.join(BASE_DIR, "schedule.transactions")


def load_wallets_config() -> tuple[list[str], int]:
    """Return (wallets, active_index)."""
    default_key = os.environ.get("HODL_KEYPAIR", "")
    if not os.path.exists(WALLETS_CONFIG_PATH):
        save_wallets_config([default_key], 0)
        return [default_key], 0
    try:
        with open(WALLETS_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        wallets = data.get("wallets", [default_key])
        if not wallets:
            wallets = [default_key]
        active = max(0, min(data.get("active_index", 0), len(wallets) - 1))
        return wallets, active
    except Exception:
        return [default_key], 0


def save_wallets_config(wallets: list[str], active_index: int):
    with open(WALLETS_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"wallets": wallets, "active_index": active_index}, f, indent=2)
