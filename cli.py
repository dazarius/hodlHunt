#!/usr/bin/env python3
"""HodlHunt CLI — полноценная утилита для охоты из терминала (аналог UI)."""
import sys
import os
import asyncio
import argparse
import httpx
import time
from datetime import datetime
from solders.pubkey import Pubkey

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from OrbisPaySDK.interface.sol import SOL
from OrbisPaySDK.const import LAMPORTS_PER_SOL
from config import load_wallets_config, save_wallets_config
from main import HodlHunt, derive_fish, derive_name_registry


def _load_env() -> dict:
    env = dict(os.environ)
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def _get_sol_and_hunt(args=None, wallet_index: int | None = None) -> tuple[SOL, HodlHunt]:
    env = _load_env()
    rpc = (getattr(args, "rpc", None) if args else None) or env.get("HODL_RPC", "https://api.mainnet-beta.solana.com")
    keypair = (getattr(args, "keypair", None) if args else None) or env.get("HODL_KEYPAIR")
    if not keypair:
        wallets, active = load_wallets_config()
        idx = wallet_index if wallet_index is not None else active
        keypair = wallets[idx] if wallets and 0 <= idx < len(wallets) else (wallets[0] if wallets else None)
    if not keypair:
        print("[!] Нет keypair. Укажи --keypair или HODL_KEYPAIR в .env")
        sys.exit(1)
    cu_limit = int(env.get("HODL_CU_LIMIT", "200000"))
    cu_price = int(env.get("HODL_CU_PRICE", "375000"))
    sol = SOL(rpc_url=rpc, KEYPAIR=keypair)
    hunt = HodlHunt(sol, compute_unit_limit=cu_limit, compute_unit_price=cu_price)
    return sol, hunt


def _fmt_sol(lamports: int) -> str:
    return f"{lamports / LAMPORTS_PER_SOL:.4f}"


def _fmt_ts(ts: int) -> str:
    if not ts or ts <= 0:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_delta(secs: float) -> str:
    if secs <= 0:
        return "NOW"
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d > 0:
        parts.append(f"{d}d")
    if h > 0:
        parts.append(f"{h}h")
    parts.append(f"{m:02d}m {s:02d}s")
    return " ".join(parts)


def _print_fish_full(f: dict, share_price: float = 0, label: str = "") -> None:
    """Вывести полную информацию о рыбе включая PDA."""
    owner = f["owner"]
    fish_id = f["fish_id"]
    owner_pk = Pubkey.from_string(owner) if isinstance(owner, str) else owner
    pda, bump = derive_fish(owner_pk, fish_id)
    name_reg, _ = derive_name_registry(f["name"])
    sol_val = f["share"] * share_price / 1e9 if share_price else 0

    print()
    print("  ╭" + "─" * 70 + "╮")
    print("  │  🐟 Fish: " + f["name"] + " " * (70 - 12 - len(f["name"])) + "│")
    print("  ├" + "─" * 70 + "┤")
    print("  │  fish_id:              " + str(fish_id) + " " * (46 - len(str(fish_id))) + "│")
    print("  │  owner:                " + owner + " " * (46 - len(owner)) + "│")
    print("  │  PDA (fish account):   " + str(pda) + " " * (46 - len(str(pda))) + "│")
    print("  │  PDA (name_registry):  " + str(name_reg) + " " * (46 - len(str(name_reg))) + "│")
    print("  │  PDA bump:             " + str(bump) + " " * (46 - len(str(bump))) + "│")
    print("  ├" + "─" * 70 + "┤")
    print("  │  share:                " + f"{f['share']:,}" + " " * (46 - len(f"{f['share']:,}")) + "│")
    print("  │  ~SOL value:           " + f"{sol_val:.4f}" + " " * (46 - len(f"{sol_val:.4f}")) + "│")
    print("  ├" + "─" * 70 + "┤")
    print("  │  created_at:           " + _fmt_ts(f.get("created_at", 0)) + " " * (46 - len(_fmt_ts(f.get("created_at", 0)))) + "│")
    print("  │  last_fed_at:          " + _fmt_ts(f.get("last_fed_at", 0)) + " " * (46 - len(_fmt_ts(f.get("last_fed_at", 0)))) + "│")
    print("  │  last_hunt_at:         " + _fmt_ts(f.get("last_hunt_at", 0)) + " " * (46 - len(_fmt_ts(f.get("last_hunt_at", 0)))) + "│")
    print("  │  can_hunt_after:       " + _fmt_ts(f.get("can_hunt_after", 0)) + " " * (46 - len(_fmt_ts(f.get("can_hunt_after", 0)))) + "│")
    print("  ├" + "─" * 70 + "┤")
    print("  │  is_protected:         " + str(f.get("is_protected", False)) + " " * (46 - len(str(f.get("is_protected", False)))) + "│")
    print("  │  protection_ends_at:   " + _fmt_ts(f.get("protection_ends_at", 0)) + " " * (46 - len(_fmt_ts(f.get("protection_ends_at", 0)))) + "│")
    print("  ├" + "─" * 70 + "┤")
    print("  │  total_hunts:          " + str(f.get("total_hunts", 0)) + " " * (46 - len(str(f.get("total_hunts", 0)))) + "│")
    print("  │  total_hunt_income:    " + f"{f.get('total_hunt_income', 0):,}" + " " * (46 - len(f"{f.get('total_hunt_income', 0):,}")) + "│")
    print("  │  hunting_marks_placed: " + str(f.get("hunting_marks_placed", 0)) + " " * (46 - len(str(f.get("hunting_marks_placed", 0)))) + "│")
    print("  │  marked_by_hunter_id:  " + str(f.get("marked_by_hunter_id", 0)) + " " * (46 - len(str(f.get("marked_by_hunter_id", 0)))) + "│")
    print("  │  mark_placed_at:       " + _fmt_ts(f.get("mark_placed_at", 0)) + " " * (46 - len(_fmt_ts(f.get("mark_placed_at", 0)))) + "│")
    print("  │  mark_expires_at:      " + _fmt_ts(f.get("mark_expires_at", 0)) + " " * (46 - len(_fmt_ts(f.get("mark_expires_at", 0)))) + "│")
    print("  │  mark_cost:            " + f"{f.get('mark_cost', 0):,}" + " " * (46 - len(f"{f.get('mark_cost', 0):,}")) + "│")
    print("  ╰" + "─" * 70 + "╯")
    print()


# ── Commands ────────────────────────────────────────────────────────────────

async def cmd_dashboard(args):
    """Дашборд при запуске без параметров."""
    sol, hunt = _get_sol_and_hunt(args)
    env = _load_env()
    rpc_short = (env.get("HODL_RPC", "") or "mainnet")[:30]
    if "mainnet" in rpc_short.lower():
        rpc_short = "mainnet"
    elif len(rpc_short) > 25:
        rpc_short = rpc_short[:12] + "..." + rpc_short[-8:]

    body = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [str(sol.get_pubkey())]}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(sol.rpc_url, json=body)
        result = resp.json()
    bal = result.get("result", {}).get("value", 0)
    pub = str(sol.get_pubkey())
    wallet_short = pub[:8] + "..." + pub[-4:] if len(pub) > 14 else pub

    ocean = await hunt.get_ocean()
    share_price = (ocean["balance_fishes"] / ocean["total_shares"]) if ocean and ocean.get("total_shares") else 0

    fishes = await hunt.get_my_fish_list()
    my_sol, my_name = 0.0, "—"
    if fishes:
        my_name = fishes[0]["name"]
        my_sol = fishes[0]["share"] * share_price / 1e9 if share_price else 0

    prey_count, prey_top = 0, []
    if fishes and ocean:
        my_share = fishes[0]["share"]
        my_wallet = str(sol.get_pubkey())
        all_fish = await hunt.get_all_fish()
        for f in all_fish:
            if f["owner"] == my_wallet or f["share"] >= my_share or f["share"] == 0 or f["marked_by_hunter_id"] != 0:
                continue
            sol_val = f["share"] * share_price / 1e9 if share_price else 0
            if sol_val < 0.1:
                continue
            prey_top.append((f["name"], f["fish_id"], sol_val))
            prey_count += 1
        prey_top.sort(key=lambda x: -x[2])
        prey_top = prey_top[:5]

    W = 52
    def ln(t: str) -> str:
        return "  │  " + (t + " " * W)[:W] + "  │"

    print()
    print("  ╭" + "─" * (W + 4) + "╮")
    print(ln("🐟 HodlHunt CLI"))
    print("  ├" + "─" * (W + 4) + "┤")
    print(ln(f"Wallet:  {wallet_short}"))
    print(ln(f"Balance: {_fmt_sol(bal)} SOL"))
    print(ln(f"RPC:     {rpc_short}"))
    print("  ├" + "─" * (W + 4) + "┤")
    print(ln(f"My Fish: {my_name}  ~{my_sol:.4f} SOL"))
    print("  ├" + "─" * (W + 4) + "┤")
    print(ln(f"Prey: {prey_count} targets"))
    for i, (name, fid, sol_val) in enumerate(prey_top, 1):
        print(ln(f"  {i}. {name[:14]:<14} id={fid}  ~{sol_val:.4f} SOL"))
    if not prey_top:
        print(ln("  (no prey — run 'find' or create fish first)"))
    print("  ├" + "─" * (W + 4) + "┤")
    print(ln("hodlhunt -i  for interactive mode"))
    print(ln("hodlhunt --help"))
    print("  ╰" + "─" * (W + 4) + "╯")
    print()


async def cmd_my(args):
    """Моя рыба (кратко)."""
    _, hunt = _get_sol_and_hunt(args)
    fishes = await hunt.get_my_fish_list()
    if not fishes:
        print("[!] Нет рыбы на этом кошельке")
        return
    ocean = await hunt.get_ocean()
    share_price = (ocean["balance_fishes"] / ocean["total_shares"]) if ocean and ocean.get("total_shares") else 0
    print(f"\n{'─'*70}")
    print(f"  My Fish ({len(fishes)} шт.)")
    print(f"{'─'*70}")
    for f in fishes:
        sol_val = f["share"] * share_price / 1e9 if share_price else 0
        pda, _ = derive_fish(Pubkey.from_string(f["owner"]), f["fish_id"])
        print(f"  {f['name']}  id={f['fish_id']}  share={f['share']:,}  ~{sol_val:.4f} SOL")
        print(f"    PDA: {pda}")
    print(f"{'─'*70}\n")


async def cmd_fish(args):
    """Полная информация о рыбе (PDA и все поля). По имени или owner+fish_id."""
    _, hunt = _get_sol_and_hunt(args)
    ocean = await hunt.get_ocean()
    share_price = (ocean["balance_fishes"] / ocean["total_shares"]) if ocean and ocean.get("total_shares") else 0

    owner = getattr(args, "owner", None)
    fish_id = getattr(args, "fish_id", None)
    name = getattr(args, "name", None)

    if name:
        all_fish = await hunt.get_all_fish()
        f = next((x for x in all_fish if x["name"] == name), None)
        if not f:
            print(f"[!] Рыба '{name}' не найдена")
            return
    elif owner and fish_id is not None:
        f = await hunt.get_fish(owner, int(fish_id))
        if not f:
            print(f"[!] Рыба owner={owner} fish_id={fish_id} не найдена")
            return
    else:
        my_fish = await hunt.get_my_fish()
        if not my_fish:
            print("[!] Нет своей рыбы. Укажи -o OWNER -f FISH_ID или -n NAME")
            return
        f = my_fish

    _print_fish_full(f, share_price)


async def cmd_ocean(args):
    """Ocean и vault."""
    _, hunt = _get_sol_and_hunt(args)
    ocean = await hunt.get_ocean()
    if not ocean:
        print("[!] Не удалось загрузить Ocean")
        return
    vault = ocean.get("vault_balance", ocean.get("balance_fishes", 0))
    print(f"\n  Ocean: {ocean['total_fish_count']} fish, {ocean['total_shares']:,} shares")
    print(f"  Vault: {_fmt_sol(vault)} SOL")
    if ocean.get("total_shares"):
        sp = ocean["balance_fishes"] / ocean["total_shares"]
        print(f"  Share price: {sp:.2f} lamports/share")
    print()


async def cmd_balance(args):
    """Баланс кошелька."""
    sol, _ = _get_sol_and_hunt(args)
    body = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [str(sol.get_pubkey())]}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(sol.rpc_url, json=body)
        result = resp.json()
    bal = result.get("result", {}).get("value", 0)
    print(f"  Balance: {_fmt_sol(bal)} SOL\n")


async def cmd_list(args):
    """Список рыб с PDA."""
    _, hunt = _get_sol_and_hunt(args)
    ocean = await hunt.get_ocean()
    share_price = (ocean["balance_fishes"] / ocean["total_shares"]) if ocean and ocean.get("total_shares") else 0
    fishes = await hunt.get_all_fish()
    min_sol = getattr(args, "min_sol", 0) or 0
    limit = getattr(args, "limit", 20) or 20
    show_pda = getattr(args, "pda", False)
    rows = []
    for f in fishes:
        sol_val = f["share"] * share_price / 1e9 if share_price else 0
        if sol_val < min_sol:
            continue
        pda, _ = derive_fish(Pubkey.from_string(f["owner"]), f["fish_id"])
        rows.append((f, sol_val, str(pda)))
    rows.sort(key=lambda r: -r[1])
    rows = rows[:limit]
    print(f"\n{'─'*100}")
    print(f"  Fish List (top {len(rows)}, min {min_sol} SOL)")
    print(f"{'─'*100}")
    print(f"  {'Name':<18} {'ID':>6} {'Owner':<14} {'Share':>12} {'SOL':>8}  Marked  PDA")
    print(f"{'─'*100}")
    for f, sol_val, pda in rows:
        m = "✓" if f["marked_by_hunter_id"] else "—"
        owner_short = f["owner"][:8] + ".." + f["owner"][-4:] if len(f["owner"]) > 14 else f["owner"]
        pda_short = (pda[:12] + ".." + pda[-8:]) if show_pda and len(pda) > 24 else (pda if show_pda else "—")
        print(f"  {f['name']:<18} {f['fish_id']:>6} {owner_short:<16} {f['share']:>12,} {sol_val:>8.4f}  {m:^6}  {pda_short}")
    print(f"{'─'*100}\n")


async def cmd_marks(args):
    """Рыбы с моими метками (My Marks)."""
    _, hunt = _get_sol_and_hunt(args)
    my_fish = await hunt.get_my_fish()
    if not my_fish:
        print("[!] Нет своей рыбы")
        return
    ocean = await hunt.get_ocean()
    share_price = (ocean["balance_fishes"] / ocean["total_shares"]) if ocean and ocean.get("total_shares") else 0
    all_fish = await hunt.get_all_fish()
    marked = [f for f in all_fish if f["marked_by_hunter_id"] == my_fish["fish_id"]]
    now = int(time.time())
    feed_days = getattr(args, "feed_days", 7) or 7
    print(f"\n{'─'*95}")
    print(f"  My Marks ({len(marked)} fish marked by '{my_fish['name']}')")
    print(f"{'─'*95}")
    print(f"  {'Name':<16} {'ID':>6} {'SOL':>8} {'Prey Time':<12} {'Hunt In':<12} {'Mark Expires':<14}  PDA")
    print(f"{'─'*95}")
    for f in marked:
        prey_time = f["last_fed_at"] + feed_days * 86400
        hunt_rem = prey_time - now
        mark_exp = f.get("mark_expires_at", 0) or 0
        mark_rem = mark_exp - now if mark_exp > 0 else 0
        sol_val = f["share"] * share_price / 1e9 if share_price else 0
        pda, _ = derive_fish(Pubkey.from_string(f["owner"]), f["fish_id"])
        hunt_str = _fmt_delta(hunt_rem) if hunt_rem > 0 else "READY"
        exp_str = _fmt_delta(mark_rem) if mark_rem > 0 else "EXPIRED"
        print(f"  {f['name']:<16} {f['fish_id']:>6} {sol_val:>8.4f} {datetime.fromtimestamp(prey_time).strftime('%m-%d %H:%M'):<12} {hunt_str:<12} {exp_str:<14}  {str(pda)[:20]}..")
    print(f"{'─'*95}\n")


async def cmd_find(args):
    """Найти добычу (prey)."""
    _, hunt = _get_sol_and_hunt(args)
    count = getattr(args, "count", 10) or 10
    min_sol = getattr(args, "min_sol", 0.1) or 0.1
    ocean = await hunt.get_ocean()
    share_price = (ocean["balance_fishes"] / ocean["total_shares"]) if ocean and ocean.get("total_shares") else 0
    my_fish = await hunt.get_my_fish()
    if not my_fish:
        print("[!] Нет рыбы — создай в UI или укажи кошелёк с рыбой")
        return
    my_wallet = str(hunt.sol.get_pubkey())
    all_fish = await hunt.get_all_fish()
    candidates = []
    for f in all_fish:
        if f["owner"] == my_wallet or f["share"] == 0 or f["share"] >= my_fish["share"] or f["marked_by_hunter_id"] != 0:
            continue
        sol_val = f["share"] * share_price / 1e9 if share_price else 0
        if sol_val < min_sol:
            continue
        f["_sol"] = sol_val
        pda, _ = derive_fish(Pubkey.from_string(f["owner"]), f["fish_id"])
        f["_pda"] = str(pda)
        candidates.append(f)
    candidates.sort(key=lambda f: -f["share"])
    candidates = candidates[:count]
    print(f"\n[*] My fish: '{my_fish['name']}' ~{my_fish['share'] * share_price / 1e9:.4f} SOL")
    print(f"[*] Found {len(candidates)} valid prey (min {min_sol} SOL)\n")
    for i, c in enumerate(candidates):
        print(f"  {i+1}. '{c['name']}' id={c['fish_id']} owner={c['owner'][:8]}.. ~{c['_sol']:.4f} SOL")
        print(f"      PDA: {c['_pda']}")
    print()


async def cmd_mark(args):
    """Поставить метку."""
    _, hunt = _get_sol_and_hunt(args)
    owner = getattr(args, "owner", None)
    fish_id = getattr(args, "fish_id", None)
    if not owner or fish_id is None:
        print("[!] Нужны --owner и --fish-id")
        return
    sig = await hunt.place_hunting_mark(owner, int(fish_id))
    if sig:
        print(f"[+] Mark sent: https://solscan.io/tx/{sig}\n")
    else:
        print("[!] Mark failed\n")


async def cmd_hunt(args):
    """Охотиться (кусать)."""
    _, hunt = _get_sol_and_hunt(args)
    owner = getattr(args, "owner", None)
    fish_id = getattr(args, "fish_id", None)
    name = getattr(args, "name", None)
    share = getattr(args, "share", None)
    if not all([owner, fish_id is not None, name, share is not None]):
        print("[!] Нужны --owner --fish-id --name --share")
        return
    sig = await hunt.hunt_fish(owner, int(fish_id), name, int(share))
    if sig:
        print(f"[+] Hunt sent: https://solscan.io/tx/{sig}\n")
    else:
        print("[!] Hunt failed\n")


async def cmd_feed(args):
    """Покормить рыбу."""
    _, hunt = _get_sol_and_hunt(args)
    amount = getattr(args, "amount", 0) or 0
    if amount <= 0:
        print("[!] Укажи --amount (в SOL)")
        return
    lamports = int(amount * LAMPORTS_PER_SOL)
    sig = await hunt.feed_fish(lamports)
    if sig:
        print(f"[+] Feed sent: https://solscan.io/tx/{sig}\n")
    else:
        print("[!] Feed failed\n")


async def cmd_create(args):
    """Создать рыбу."""
    _, hunt = _get_sol_and_hunt(args)
    name = getattr(args, "name", None) or ""
    deposit = getattr(args, "deposit", 0) or 0
    if not name:
        print("[!] Укажи --name")
        return
    if deposit <= 0:
        print("[!] Укажи --deposit (в SOL)")
        return
    lamports = int(deposit * LAMPORTS_PER_SOL)
    sig = await hunt.create_fish(name, lamports)
    if sig:
        print(f"[+] CreateFish sent: https://solscan.io/tx/{sig}\n")
    else:
        print("[!] CreateFish failed\n")


async def cmd_exit(args):
    """Exit Game (выйти из игры)."""
    _, hunt = _get_sol_and_hunt(args)
    sig = await hunt.exit_game()
    if sig:
        print(f"[+] ExitGame sent: https://solscan.io/tx/{sig}\n")
    else:
        print("[!] ExitGame failed\n")


async def cmd_transfer(args):
    """Передать рыбу другому кошельку."""
    _, hunt = _get_sol_and_hunt(args)
    to_addr = getattr(args, "to", None)
    if not to_addr:
        print("[!] Укажи --to (адрес получателя)")
        return
    sig = await hunt.transfer_fish(to_addr)
    if sig:
        print(f"[+] Transfer sent: https://solscan.io/tx/{sig}\n")
    else:
        print("[!] Transfer failed\n")


async def cmd_resurrect(args):
    """Resurrect (воскресить рыбу после exit)."""
    _, hunt = _get_sol_and_hunt(args)
    name = getattr(args, "name", None) or ""
    deposit = getattr(args, "deposit", 0) or 0
    if not name:
        print("[!] Укажи --name")
        return
    if deposit <= 0:
        print("[!] Укажи --deposit (в SOL)")
        return
    lamports = int(deposit * LAMPORTS_PER_SOL)
    sig = await hunt.resurrect_fish(name, lamports)
    if sig:
        print(f"[+] Resurrect sent: https://solscan.io/tx/{sig}\n")
    else:
        print("[!] Resurrect failed\n")


async def cmd_schedule(args):
    """Планировщик меток."""
    _, hunt = _get_sol_and_hunt(args)
    count = getattr(args, "count", 4) or 4
    min_sol = getattr(args, "min_sol", 0.1) or 0.1
    feed_days = getattr(args, "feed_days", 7) or 7
    mark_hours = getattr(args, "mark_hours", 24) or 24
    results = await hunt.schedule_marks(
        count=count, min_sol=min_sol,
        feeding_period=feed_days * 86400,
        mark_window=mark_hours * 3600,
    )
    ok = sum(1 for r in results if r)
    print(f"\n[*] Done: {ok}/{len(results)} marks placed\n")


async def cmd_batch(args):
    """Метки на несколько целей."""
    _, hunt = _get_sol_and_hunt(args)
    count = getattr(args, "count", 4) or 4
    min_sol = getattr(args, "min_sol", 0.1) or 0.1
    ocean = await hunt.get_ocean()
    share_price = (ocean["balance_fishes"] / ocean["total_shares"]) if ocean and ocean.get("total_shares") else 0
    my_fish = await hunt.get_my_fish()
    if not my_fish:
        print("[!] Нет рыбы")
        return
    my_wallet = str(hunt.sol.get_pubkey())
    all_fish = await hunt.get_all_fish()
    targets = [f for f in all_fish if f["owner"] != my_wallet and f["share"] < my_fish["share"] and f["share"] > 0
               and f["marked_by_hunter_id"] == 0]
    for f in targets:
        f["_sol"] = f["share"] * share_price / 1e9 if share_price else 0
    targets = [f for f in targets if f["_sol"] >= min_sol]
    targets.sort(key=lambda f: -f["share"])
    targets = targets[:count]
    if not targets:
        print("[!] No valid prey found")
        return
    print(f"\n[*] Placing {len(targets)} marks in parallel...")
    sigs = await hunt.batch_place_marks(targets)
    ok = sum(1 for s in sigs if s)
    print(f"[*] Result: {ok}/{len(targets)} marks sent\n")


def cmd_wallets(args, switch_index: int | None = None):
    """Список кошельков. wallets N — переключить на кошелёк #N."""
    if switch_index is None and hasattr(args, "index") and args.index is not None:
        switch_index = args.index
    wallets, active = load_wallets_config()
    from logic.utils import pubkey_from_keypair

    if switch_index is not None:
        idx = int(switch_index) - 1 if switch_index >= 1 else switch_index
        if 0 <= idx < len(wallets):
            save_wallets_config(wallets, idx)
            if hasattr(args, "keypair"):
                args.keypair = None
            print(f"\n  Switched to wallet #{idx + 1}")
        else:
            print(f"  [!] Invalid index. Use 1..{len(wallets)}")

    wallets, active = load_wallets_config()
    print(f"\n  Wallets ({len(wallets)}), active: #{active + 1}")
    print("  " + "─" * 60)
    for i, kp in enumerate(wallets):
        pub = pubkey_from_keypair(kp) if kp else "?"
        short = f"{pub[:8]}...{pub[-4:]}" if len(pub) > 14 else pub
        mark = " ←" if i == active else ""
        print(f"  #{i+1}  {short}{mark}")
    print("  wallets N  — переключить на кошелёк #N")
    print()


async def _run_cmd(cmd: str, args) -> bool:
    """Выполнить команду по строке. Возвращает False для выхода."""
    cmd = cmd.strip().lower()
    if not cmd or cmd in ("q", "quit", "exit"):
        return False
    parts = cmd.split()
    if not parts:
        return True
    aliases = {
        "d": "dashboard", "m": "my", "f": "fish", "o": "ocean", "b": "balance",
        "l": "list", "k": "marks", "n": "find", "r": "mark", "h": "hunt",
        "e": "feed", "c": "create", "x": "exit", "t": "transfer", "z": "resurrect",
        "s": "schedule", "a": "batch", "w": "wallets", "help": "help",
    }
    c = aliases.get(parts[0], parts[0])
    if c == "help":
        print("  my fish ocean balance list marks find mark hunt feed create exit transfer resurrect schedule batch wallets")
        return True
    try:
        if c == "my":
            await cmd_my(args)
        elif c == "fish":
            a = argparse.Namespace(rpc=args.rpc, keypair=args.keypair, owner=None, fish_id=None, name=None)
            if len(parts) >= 2:
                a.name = parts[1]
            await cmd_fish(a)
        elif c == "ocean":
            await cmd_ocean(args)
        elif c == "balance":
            await cmd_balance(args)
        elif c == "list":
            a = argparse.Namespace(rpc=args.rpc, keypair=args.keypair, min_sol=0, limit=20, pda=True)
            if len(parts) >= 2:
                a.limit = int(parts[1])
            await cmd_list(a)
        elif c == "marks":
            await cmd_marks(args)
        elif c == "find":
            a = argparse.Namespace(rpc=args.rpc, keypair=args.keypair, count=10, min_sol=0.1)
            if len(parts) >= 2:
                a.count = int(parts[1])
            await cmd_find(a)
        elif c == "mark":
            if len(parts) < 3:
                print("  mark OWNER FISH_ID")
                return True
            a = argparse.Namespace(rpc=args.rpc, keypair=args.keypair, owner=parts[1], fish_id=int(parts[2]))
            await cmd_mark(a)
        elif c == "hunt":
            if len(parts) < 5:
                print("  hunt OWNER FISH_ID NAME SHARE")
                return True
            a = argparse.Namespace(rpc=args.rpc, keypair=args.keypair, owner=parts[1], fish_id=int(parts[2]), name=parts[3], share=int(parts[4]))
            await cmd_hunt(a)
        elif c == "feed":
            if len(parts) < 2:
                print("  feed AMOUNT_SOL")
                return True
            a = argparse.Namespace(rpc=args.rpc, keypair=args.keypair, amount=float(parts[1]))
            await cmd_feed(a)
        elif c == "create":
            if len(parts) < 3:
                print("  create NAME DEPOSIT_SOL")
                return True
            a = argparse.Namespace(rpc=args.rpc, keypair=args.keypair, name=parts[1], deposit=float(parts[2]))
            await cmd_create(a)
        elif c == "exit":
            await cmd_exit(args)
        elif c == "transfer":
            if len(parts) < 2:
                print("  transfer TO_ADDRESS")
                return True
            a = argparse.Namespace(rpc=args.rpc, keypair=args.keypair, to=parts[1])
            await cmd_transfer(a)
        elif c == "resurrect":
            if len(parts) < 3:
                print("  resurrect NAME DEPOSIT_SOL")
                return True
            a = argparse.Namespace(rpc=args.rpc, keypair=args.keypair, name=parts[1], deposit=float(parts[2]))
            await cmd_resurrect(a)
        elif c == "schedule":
            a = argparse.Namespace(rpc=args.rpc, keypair=args.keypair, count=4, min_sol=0.1, feed_days=7, mark_hours=24)
            if len(parts) >= 2:
                a.count = int(parts[1])
            await cmd_schedule(a)
        elif c == "batch":
            a = argparse.Namespace(rpc=args.rpc, keypair=args.keypair, count=4, min_sol=0.1)
            if len(parts) >= 2:
                a.count = int(parts[1])
            await cmd_batch(a)
        elif c == "wallets":
            switch_idx = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
            cmd_wallets(args, switch_idx)
        elif c == "dashboard":
            await cmd_dashboard(args)
        else:
            print(f"  Unknown: {parts[0]}. Type 'help' or 'h'")
    except Exception as e:
        print(f"  [!] {e}")
    return True


async def cmd_interactive(args):
    """Интерактивный режим (меню)."""
    await cmd_dashboard(args)
    print("  Commands: my fish ocean balance list marks find mark hunt feed")
    print("  create exit transfer resurrect schedule batch wallets")
    print("  Short: m f o b l k n r h e c x t z s a w")
    print("  q/quit to exit")
    print()
    while True:
        try:
            cmd = input("hodlhunt> ")
        except (EOFError, KeyboardInterrupt):
            break
        if not await _run_cmd(cmd, args):
            break


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="hodlhunt",
        description="HodlHunt CLI — полноценная утилита для охоты (аналог UI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  hodlhunt                    # дашборд
  hodlhunt -i                 # интерактивный режим
  hodlhunt fish -n dazay      # полная инфа о рыбе + PDA
  hodlhunt fish -o ADDR -f 1  # по owner и fish_id
  hodlhunt list --pda         # список с PDA
  hodlhunt marks              # мои метки
  hodlhunt create NAME 0.1    # создать рыбу
  hodlhunt mark -o ADDR -f 1  # метка
  hodlhunt hunt -o ADDR -f 1 -n Name -s 1000000
        """,
    )
    parser.add_argument("--rpc", help="RPC URL")
    parser.add_argument("--keypair", help="Base58 keypair")
    parser.add_argument("-i", "--interactive", action="store_true", help="Интерактивный режим")

    sub = parser.add_subparsers(dest="cmd", help="Команда")

    def add(name, *subs, **kw):
        p = sub.add_parser(name, **kw)
        for s in subs:
            if isinstance(s, tuple):
                p.add_argument(*s[0], **s[1])
            else:
                p.set_defaults(func=s)
        return p

    p_dash = sub.add_parser("dashboard", help="Дашборд")
    p_dash.set_defaults(func=cmd_dashboard)

    p_my = sub.add_parser("my", help="Моя рыба")
    p_my.set_defaults(func=cmd_my)

    p_fish = sub.add_parser("fish", help="Полная инфа о рыбе (PDA и все поля)")
    p_fish.add_argument("-o", "--owner", help="Owner")
    p_fish.add_argument("-f", "--fish-id", type=int, help="Fish ID")
    p_fish.add_argument("-n", "--name", help="Имя рыбы")
    p_fish.set_defaults(func=cmd_fish)

    p_ocean = sub.add_parser("ocean", help="Ocean")
    p_ocean.set_defaults(func=cmd_ocean)

    p_bal = sub.add_parser("balance", help="Баланс")
    p_bal.set_defaults(func=cmd_balance)

    p_list = sub.add_parser("list", help="Список рыб")
    p_list.add_argument("-m", "--min-sol", type=float, default=0)
    p_list.add_argument("-n", "--limit", type=int, default=20)
    p_list.add_argument("--pda", action="store_true", help="Показать PDA")
    p_list.set_defaults(func=cmd_list)

    p_marks = sub.add_parser("marks", help="Мои метки")
    p_marks.add_argument("--feed-days", type=int, default=7)
    p_marks.set_defaults(func=cmd_marks)

    p_find = sub.add_parser("find", help="Найти добычу")
    p_find.add_argument("-n", "--count", type=int, default=10)
    p_find.add_argument("-m", "--min-sol", type=float, default=0.1)
    p_find.set_defaults(func=cmd_find)

    p_mark = sub.add_parser("mark", help="Поставить метку")
    p_mark.add_argument("-o", "--owner", required=True)
    p_mark.add_argument("-f", "--fish-id", type=int, required=True)
    p_mark.set_defaults(func=cmd_mark)

    p_hunt = sub.add_parser("hunt", help="Охотиться")
    p_hunt.add_argument("-o", "--owner", required=True)
    p_hunt.add_argument("-f", "--fish-id", type=int, required=True)
    p_hunt.add_argument("-n", "--name", required=True)
    p_hunt.add_argument("-s", "--share", type=int, required=True)
    p_hunt.set_defaults(func=cmd_hunt)

    p_feed = sub.add_parser("feed", help="Покормить")
    p_feed.add_argument("-a", "--amount", type=float, required=True)
    p_feed.set_defaults(func=cmd_feed)

    p_create = sub.add_parser("create", help="Создать рыбу")
    p_create.add_argument("-n", "--name", required=True)
    p_create.add_argument("-d", "--deposit", type=float, required=True)
    p_create.set_defaults(func=cmd_create)

    p_exit = sub.add_parser("exit", help="Exit Game")
    p_exit.set_defaults(func=cmd_exit)

    p_transfer = sub.add_parser("transfer", help="Передать рыбу")
    p_transfer.add_argument("-t", "--to", required=True)
    p_transfer.set_defaults(func=cmd_transfer)

    p_resurrect = sub.add_parser("resurrect", help="Воскресить")
    p_resurrect.add_argument("-n", "--name", required=True)
    p_resurrect.add_argument("-d", "--deposit", type=float, required=True)
    p_resurrect.set_defaults(func=cmd_resurrect)

    p_sched = sub.add_parser("schedule", help="Планировщик")
    p_sched.add_argument("-n", "--count", type=int, default=4)
    p_sched.add_argument("-m", "--min-sol", type=float, default=0.1)
    p_sched.add_argument("--feed-days", type=int, default=7)
    p_sched.add_argument("--mark-hours", type=int, default=24)
    p_sched.set_defaults(func=cmd_schedule)

    p_batch = sub.add_parser("batch", help="Метки batch")
    p_batch.add_argument("-n", "--count", type=int, default=4)
    p_batch.add_argument("-m", "--min-sol", type=float, default=0.1)
    p_batch.set_defaults(func=cmd_batch)

    p_wallets = sub.add_parser("wallets", help="Кошельки. wallets N — переключить")
    p_wallets.add_argument("index", type=int, nargs="?", help="Номер кошелька для переключения (1..N)")
    p_wallets.set_defaults(func=cmd_wallets)

    args = parser.parse_args()

    if args.interactive:
        asyncio.run(cmd_interactive(args))
        return

    if args.cmd is None:
        args.func = cmd_dashboard
    if asyncio.iscoroutinefunction(args.func):
        asyncio.run(args.func(args))
    else:
        args.func(args)


if __name__ == "__main__":
    main()
