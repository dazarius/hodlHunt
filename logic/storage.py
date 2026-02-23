"""Хранилище рыб по кошелькам. {wallet_index: {fishes: [], fishes_data: {fish_id: fish}}}"""
from typing import Any

# wallet_index -> {fishes: list, fishes_data: {fish_id: fish_dict}}
_wallet_fish: dict[int, dict[str, Any]] = {}


def set_wallet_fish(wallet_index: int, fishes: list[dict]) -> None:
    """Сохранить список рыб для кошелька."""
    fishes = fishes or []
    fishes_data = {f["fish_id"]: f for f in fishes if f.get("fish_id") is not None}
    actual_fish_ids = [f["fish_id"] for f in fishes if f.get("fish_id") is not None]
    _wallet_fish[wallet_index] = {"fishes": fishes, "fishes_data": fishes_data, "actual_fish_ids": actual_fish_ids}


def get_wallet_fish(wallet_index: int) -> dict[str, Any]:
    """Получить данные рыб для кошелька. Возвращает {fishes: [], fishes_data: {}, actual_fish_ids: []}."""
    return _wallet_fish.get(wallet_index, {"fishes": [], "fishes_data": {}, "actual_fish_ids": []})


def get_actual_fish_ids(wallet_index: int) -> list[int]:
    """Список fish_id из данных по рыбе для кошелька."""
    return get_wallet_fish(wallet_index).get("actual_fish_ids", [])


def get_fishes(wallet_index: int) -> list[dict]:
    """Список рыб для кошелька."""
    return get_wallet_fish(wallet_index)["fishes"]


def get_fish_by_id(wallet_index: int, fish_id: int) -> dict | None:
    """Рыба по fish_id для кошелька."""
    return get_wallet_fish(wallet_index)["fishes_data"].get(fish_id)


def set_all_wallets_fish(data: dict[int, list[dict]], merge_empty: bool = True) -> None:
    """Записать рыб для всех кошельков. data: {wallet_index: [fish, ...]}.
    merge_empty=True: пустые списки не перезаписывают кэш (защита от rate limit 429)."""
    for idx, fishes in data.items():
        if merge_empty and not fishes and idx in _wallet_fish:
            continue
        set_wallet_fish(idx, fishes or [])


def get_all() -> dict[int, dict[str, Any]]:
    """Весь кэш."""
    return dict(_wallet_fish)


def clear() -> None:
    """Очистить кэш."""
    _wallet_fish.clear()
