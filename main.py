import asyncio
import struct
import time
import os
import httpx
import base64

from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.transaction import Transaction
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price

from OrbisPaySDK.interface.sol import SOL
from OrbisPaySDK.const import LAMPORTS_PER_SOL
from solana.rpc.types import TxOpts
from solana.rpc.commitment import Confirmed


def send_tg(text: str, token: str | None = None, chat_id: str | None = None) -> bool:
    """Отправить сообщение в Telegram. Использует tg_notify."""
    try:
        from tg_notify import send
        return send(text, token=token, chat_id=chat_id)
    except ImportError:
        return False


DONATE_AMOUNT_SOL = 0.001  # выше rent-exempt (~0.00089 SOL) для нового аккаунта


def _load_donate_settings() -> tuple[bool, str | None]:
    """(enabled, address) from .env. Address None if invalid."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return False, None
    env = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    enabled = env.get("HODL_DONATE_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
    addr = env.get("HODL_DONATE_ADDRESS", "").strip()
    if not addr or addr == "YOUR_SOLANA_ADDRESS_HERE" or len(addr) < 32:
        return enabled, None
    return enabled, addr


def _make_donate_instruction(signer: Pubkey, to_addr: str) -> Instruction:
    """System Program transfer: 0.0005 SOL to donate address."""
    lamports = int(DONATE_AMOUNT_SOL * LAMPORTS_PER_SOL)
    to_pubkey = Pubkey.from_string(to_addr)
    data = struct.pack("<IQ", 2, lamports)  # Transfer = 2
    return Instruction(
        program_id=SYSTEM_PROGRAM,
        accounts=[
            AccountMeta(signer, is_signer=True, is_writable=True),
            AccountMeta(to_pubkey, is_signer=False, is_writable=True),
        ],
        data=data,
    )


HODL_PROGRAM = Pubkey.from_string("B1osUCap5eJ2iJnbRqfCQB87orhJM5EqZqPcGMbjJvXz")
HODL_ADMIN = Pubkey.from_string("Fa4WXXCL7Cj6LcgMMkFWqqDpJQ25Lpyb6k2Mk6rPBe9")
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")

DISC = {
    "create_fish":        bytes([207, 216, 149, 42, 19, 153, 243, 33]),
    "exit_game":          bytes([139, 185, 61, 13, 2, 53, 173, 37]),
    "feed_fish":          bytes([81, 91, 100, 196, 61, 12, 50, 133]),
    "hunt_fish":          bytes([161, 213, 229, 35, 6, 119, 179, 189]),
    "place_hunting_mark": bytes([151, 195, 107, 64, 113, 207, 51, 15]),
    "resurrect_fish":     bytes([104, 92, 198, 81, 23, 248, 99, 87]),
    "transfer_fish":      bytes([152, 33, 97, 135, 196, 37, 237, 190]),
}

FISH_DISC = bytes([123, 52, 122, 216, 206, 125, 64, 149])
OCEAN_DISC = bytes([2, 110, 213, 240, 58, 81, 82, 204])

FISH_ACCOUNT_SIZE = 198


# ── PDA derivation ──────────────────────────────────────────────────────────

def derive_ocean() -> tuple[Pubkey, int]:
    """seeds = [b"ocean"]"""
    return Pubkey.find_program_address([b"ocean"], HODL_PROGRAM)


def derive_vault(ocean: Pubkey) -> tuple[Pubkey, int]:
    """seeds = [b"vault", ocean]"""
    return Pubkey.find_program_address([b"vault", bytes(ocean)], HODL_PROGRAM)


def derive_fish(owner: Pubkey, fish_id: int) -> tuple[Pubkey, int]:
    """seeds = [b"fish", owner, u64_le(fish_id)]"""
    return Pubkey.find_program_address(
        [b"fish", bytes(owner), struct.pack("<Q", fish_id)],
        HODL_PROGRAM,
    )


def derive_name_registry(name: str) -> tuple[Pubkey, int]:
    """seeds = [b"fish_name", name_utf8]"""
    return Pubkey.find_program_address(
        [b"fish_name", name.encode("utf-8")],
        HODL_PROGRAM,
    )


# ── Account parsing ─────────────────────────────────────────────────────────

def parse_ocean(data: bytes) -> dict | None:
    if len(data) < 8 or data[:8] != OCEAN_DISC:
        return None
    o = 8
    admin = Pubkey.from_bytes(data[o:o+32]); o += 32
    total_fish_count, = struct.unpack_from("<Q", data, o); o += 8
    total_shares, = struct.unpack_from("<Q", data, o); o += 8
    balance_fishes, = struct.unpack_from("<Q", data, o); o += 8
    vault_bump = data[o]; o += 1
    last_feeding_update, = struct.unpack_from("<q", data, o); o += 8
    next_fish_id, = struct.unpack_from("<Q", data, o); o += 8
    vault = Pubkey.from_bytes(data[o:o+32]); o += 32
    is_storm = bool(data[o]); o += 1
    feeding_percentage, = struct.unpack_from("<H", data, o); o += 2
    storm_probability_bps, = struct.unpack_from("<H", data, o); o += 2
    last_cycle_mode = data[o]; o += 1
    cycle_start_time, = struct.unpack_from("<q", data, o); o += 8
    next_mode_change_time, = struct.unpack_from("<q", data, o); o += 8
    return {
        "admin": str(admin),
        "total_fish_count": total_fish_count,
        "total_shares": total_shares,
        "balance_fishes": balance_fishes,
        "vault_bump": vault_bump,
        "last_feeding_update": last_feeding_update,
        "next_fish_id": next_fish_id,
        "vault": str(vault),
        "is_storm": is_storm,
        "feeding_percentage": feeding_percentage,
        "storm_probability_bps": storm_probability_bps,
        "last_cycle_mode": last_cycle_mode,
        "cycle_start_time": cycle_start_time,
        "next_mode_change_time": next_mode_change_time,
    }


def parse_fish(data: bytes) -> dict | None:
    if len(data) < 65 or data[:8] != FISH_DISC:
        return None
    o = 8
    fish_id, = struct.unpack_from("<Q", data, o); o += 8
    owner = Pubkey.from_bytes(data[o:o+32]); o += 32
    share, = struct.unpack_from("<Q", data, o); o += 8
    name_len, = struct.unpack_from("<I", data, o); o += 4
    name = data[o:o+name_len].decode("utf-8", errors="replace"); o += name_len
    created_at, = struct.unpack_from("<q", data, o); o += 8
    last_fed_at, = struct.unpack_from("<q", data, o); o += 8
    last_hunt_at, = struct.unpack_from("<q", data, o); o += 8
    can_hunt_after, = struct.unpack_from("<q", data, o); o += 8
    is_protected = bool(data[o]); o += 1
    protection_ends_at, = struct.unpack_from("<q", data, o); o += 8
    total_hunts, = struct.unpack_from("<Q", data, o); o += 8
    total_hunt_income, = struct.unpack_from("<Q", data, o); o += 8
    received_from_hunt_value, = struct.unpack_from("<Q", data, o); o += 8
    hunting_marks_placed = data[o]; o += 1
    last_mark_reset, = struct.unpack_from("<q", data, o); o += 8
    marked_by_hunter_id, = struct.unpack_from("<Q", data, o); o += 8
    mark_placed_at, = struct.unpack_from("<q", data, o); o += 8
    mark_expires_at, = struct.unpack_from("<q", data, o); o += 8
    mark_cost, = struct.unpack_from("<Q", data, o); o += 8
    return {
        "fish_id": fish_id,
        "owner": str(owner),
        "share": share,
        "name": name,
        "created_at": created_at,
        "last_fed_at": last_fed_at,
        "last_hunt_at": last_hunt_at,
        "can_hunt_after": can_hunt_after,
        "is_protected": is_protected,
        "protection_ends_at": protection_ends_at,
        "total_hunts": total_hunts,
        "total_hunt_income": total_hunt_income,
        "received_from_hunt_value": received_from_hunt_value,
        "hunting_marks_placed": hunting_marks_placed,
        "last_mark_reset": last_mark_reset,
        "marked_by_hunter_id": marked_by_hunter_id,
        "mark_placed_at": mark_placed_at,
        "mark_expires_at": mark_expires_at,
        "mark_cost": mark_cost,
    }


# ── HodlHunt client ─────────────────────────────────────────────────────────

class HodlHunt:
    def __init__(
        self,
        sol: SOL,
        compute_unit_limit: int = 200_000,
        compute_unit_price: int = 375_000,
    ):
        self.sol = sol
        self.ocean, _ = derive_ocean()
        self.vault, _ = derive_vault(self.ocean)
        self.cu_limit = compute_unit_limit
        self.cu_price = compute_unit_price
        self._my_fish_cache: dict | None = None
        self._my_fish_list_cache: list[dict] | None = None

    # ── helpers ──────────────────────────────────────────────────────────

    async def _send_tx(self, ixns: list[Instruction], label: str) -> str | None:
        signer = self.sol.get_pubkey()
        donate_enabled, donate_addr = _load_donate_settings()
        if donate_enabled and donate_addr:
            ixns = [*ixns]
            #_make_donate_instruction(signer, donate_addr)
        all_ixns = [
            set_compute_unit_limit(self.cu_limit),
            set_compute_unit_price(self.cu_price),
            *ixns,
        ]
        msg = Message(all_ixns, signer)
        bh = (await self.sol.client.get_latest_blockhash()).value.blockhash
        tx = Transaction([self.sol.KEYPAIR], msg, bh)
        opts = TxOpts(skip_preflight=True, preflight_commitment=Confirmed)
        resp = await self.sol.client.send_transaction(tx, opts=opts)
        sig = str(resp.value)
        print(f"[+] {label} sent: {sig}")

        try:
            confirm = await self.sol.client.confirm_transaction(resp.value)
        except Exception as e:
            err_msg = (str(e) + str(getattr(e, "__cause__", ""))).lower()
            if "429" in err_msg or "too many requests" in err_msg or "rate" in err_msg:
                print("[!] RPC rate limit (429) — tx sent, check solscan.io/tx/" + sig[:16] + "...")
            else:
                print(f"[!] Confirm error (tx sent): {type(e).__name__} — check solscan.io/tx/{sig[:20]}...")
            return sig

        if confirm.value:
            err = (
                getattr(confirm.value[0], "err", None)
                if isinstance(confirm.value, list)
                else None
            )
            if err:
                print(f"[!] Transaction error: {err}")
                raise Exception(f"Transaction confirmation error: {err}")
            print("[+] Confirmed!")
            return sig

        print("[!] Confirmation failed (timeout) — tx may still succeed, check solscan")
        return sig

    async def _fetch_account(self, pubkey: Pubkey) -> bytes | None:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [str(pubkey), {"encoding": "base64"}],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.sol.rpc_url, json=body)
            result = resp.json()
        value = result.get("result", {}).get("value")
        if not value:
            return None
        return base64.b64decode(value["data"][0])

    # ── reads ────────────────────────────────────────────────────────────

    async def _get_balance(self, pubkey: Pubkey) -> int:
        body = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [str(pubkey)]}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.sol.rpc_url, json=body)
            result = resp.json()
        return result.get("result", {}).get("value", 0)

    async def get_ocean(self) -> dict | None:
        data = await self._fetch_account(self.ocean)
        ocean = parse_ocean(data) if data else None
        if ocean:
            ocean["vault_balance"] = await self._get_balance(self.vault)
        return ocean

    async def get_all_fish(self) -> list[dict]:
        filters = [
            {"memcmp": {"offset": 0, "bytes": base64.b64encode(FISH_DISC).decode(), "encoding": "base64"}},
        ]
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getProgramAccounts",
            "params": [
                str(HODL_PROGRAM),
                {"encoding": "base64", "filters": filters},
            ],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.sol.rpc_url, json=body)
            result = resp.json()

        fishes = []
        for acc in result.get("result", []):
            raw = base64.b64decode(acc["account"]["data"][0])
            parsed = parse_fish(raw)
            if parsed:
                parsed["address"] = acc["pubkey"]
                fishes.append(parsed)
        return sorted(fishes, key=lambda f: f["fish_id"])

    async def get_fish_by_wallet(self, wallet: str | Pubkey) -> dict | None:
        if isinstance(wallet, str): 
            wallet = Pubkey.from_string(wallet)

        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getProgramAccounts",
            "params": [
                str(HODL_PROGRAM),
                {
                    "encoding": "base64",
                    "filters": [
                        {"memcmp": {"offset": 0, "bytes": base64.b64encode(FISH_DISC).decode(), "encoding": "base64"}},
                        {"memcmp": {"offset": 16, "bytes": str(wallet)}},
                    ],
                },
            ],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.sol.rpc_url, json=body)
            result = resp.json()

        accounts = result.get("result", [])
        if not accounts:
            return None
        raw = base64.b64decode(accounts[0]["account"]["data"][0])
        parsed = parse_fish(raw)
        if parsed:
            parsed["address"] = accounts[0]["pubkey"]
        return parsed

    async def get_all_fish_by_wallet(self, wallet: str | Pubkey) -> list[dict]:
        if isinstance(wallet, str):
            wallet = Pubkey.from_string(wallet)
        body = {
            "jsonrpc": "2.0", "id": 1, "method": "getProgramAccounts",
            "params": [
                str(HODL_PROGRAM),
                {
                    "encoding": "base64",
                    "filters": [
                        {"memcmp": {"offset": 0, "bytes": base64.b64encode(FISH_DISC).decode(), "encoding": "base64"}},
                        {"memcmp": {"offset": 16, "bytes": str(wallet)}},
                    ],
                },
            ],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.sol.rpc_url, json=body)
            result = resp.json()
        fishes = []
        for acc in result.get("result", []):
            raw = base64.b64decode(acc["account"]["data"][0])
            parsed = parse_fish(raw)
            if parsed:
                parsed["address"] = acc["pubkey"]
                fishes.append(parsed)
        return sorted(fishes, key=lambda f: f["fish_id"])

    async def get_my_fish_list(self, force: bool = False) -> list[dict]:
        

        fishes = await self.get_all_fish_by_wallet(self.sol.get_pubkey())
        self._my_fish_list_cache = fishes
        return fishes

    async def get_fish(self, owner: str | Pubkey, fish_id: int) -> dict | None:
        if isinstance(owner, str):
            owner = Pubkey.from_string(owner)
        fish_pda, _ = derive_fish(owner, fish_id)
        data = await self._fetch_account(fish_pda)
        if not data:
            return None
        parsed = parse_fish(data)
        if parsed:
            parsed["address"] = str(fish_pda)
        return parsed

    async def get_my_fish(self, force: bool = False, fish_id: int | None = None) -> dict | None:
        fishes = await self.get_my_fish_list(force=force)
        if fish_id is not None:
            if fishes:
                for f in fishes:
                    if f["fish_id"] == fish_id:
                        return f
            return await self.get_fish(self.sol.get_pubkey(), fish_id)
        if not fishes:
            return None
        return fishes[0]

    # ── create_fish(name, deposit) ───────────────────────────────────────

    async def create_fish(self, name: str, deposit: int) -> str | None:
        signer = self.sol.get_pubkey()
        ocean_data = await self.get_ocean()
        if not ocean_data:
            print("[!] Couldn't fetch Ocean")
            return None

        fish_pda, _ = derive_fish(signer, ocean_data["next_fish_id"])
        name_reg, _ = derive_name_registry(name)

        name_bytes = name.encode("utf-8")
        data = (
            DISC["create_fish"]
            + struct.pack("<I", len(name_bytes))
            + name_bytes
            + struct.pack("<Q", deposit)
        )
        ix = Instruction(
            program_id=HODL_PROGRAM,
            accounts=[
                AccountMeta(self.ocean, is_signer=False, is_writable=True),
                AccountMeta(fish_pda, is_signer=False, is_writable=True),
                AccountMeta(name_reg, is_signer=False, is_writable=True),
                AccountMeta(self.vault, is_signer=False, is_writable=True),
                AccountMeta(signer, is_signer=True, is_writable=True),
                AccountMeta(HODL_ADMIN, is_signer=False, is_writable=True),
                AccountMeta(SYSTEM_PROGRAM, is_signer=False, is_writable=False),
            ],
            data=data,
        )
        return await self._send_tx([ix], "CreateFish")

    # ── feed_fish(feeding_amount) ────────────────────────────────────────

    async def build_feed_fish_ix(self, feeding_amount: int, fish_id: int | None = None) -> Instruction | None:
        signer = self.sol.get_pubkey()
        my_fish = await self.get_my_fish(fish_id=fish_id)
        if not my_fish:
            print("[!] Couldn't find your Fish account")
            return None

        fish_pda, _ = derive_fish(signer, my_fish["fish_id"])
        data = DISC["feed_fish"] + struct.pack("<Q", feeding_amount)

        ix = Instruction(
            program_id=HODL_PROGRAM,
            accounts=[
                AccountMeta(self.ocean, is_signer=False, is_writable=True),
                AccountMeta(fish_pda, is_signer=False, is_writable=True),
                AccountMeta(self.vault, is_signer=False, is_writable=True),
                AccountMeta(signer, is_signer=True, is_writable=True),
                AccountMeta(HODL_ADMIN, is_signer=False, is_writable=True),
                AccountMeta(SYSTEM_PROGRAM, is_signer=False, is_writable=False),
            ],
            data=data,
        )
        return ix

    async def feed_fish(self, feeding_amount: int, fish_id: int | None = None) -> str | None:
        ix = await self.build_feed_fish_ix(feeding_amount, fish_id)
        if not ix: return None
        return await self._send_tx([ix], "FeedFish")

    # ── place_hunting_mark(prey_wallet, prey_fish_id) ────────────────────

    async def build_place_hunting_mark_ix(
        self,
        prey_wallet: str | Pubkey,
        prey_fish_id: int,
        hunter_fish_id: int | None = None,
    ) -> Instruction | None:
        if isinstance(prey_wallet, str):
            prey_wallet = Pubkey.from_string(prey_wallet)

        signer = self.sol.get_pubkey()
        my_fish = await self.get_my_fish(fish_id=hunter_fish_id)
        if not my_fish:
            print("[!] Couldn't find your Fish account")
            return None

        hunter_pda, _ = derive_fish(signer, my_fish["fish_id"])
        prey_pda, _ = derive_fish(prey_wallet, prey_fish_id)

        ix = Instruction(
            program_id=HODL_PROGRAM,
            accounts=[
                AccountMeta(self.ocean, is_signer=False, is_writable=True),
                AccountMeta(hunter_pda, is_signer=False, is_writable=True),
                AccountMeta(prey_pda, is_signer=False, is_writable=True),
                AccountMeta(self.vault, is_signer=False, is_writable=True),
                AccountMeta(signer, is_signer=True, is_writable=True),
                AccountMeta(HODL_ADMIN, is_signer=False, is_writable=True),
                AccountMeta(SYSTEM_PROGRAM, is_signer=False, is_writable=False),
            ],
            data=DISC["place_hunting_mark"],
        )
        return ix

    async def place_hunting_mark(
        self,
        prey_wallet: str | Pubkey,
        prey_fish_id: int,
        hunter_fish_id: int | None = None,
    ) -> str | None:
        ix = await self.build_place_hunting_mark_ix(prey_wallet, prey_fish_id, hunter_fish_id)
        if not ix: return None
        return await self._send_tx([ix], "PlaceHuntingMark")

    # ── hunt_fish(prey_wallet, prey_fish_id, prey_name, expected_prey_share)

    async def build_hunt_fish_ix(
        self,
        prey_wallet: str | Pubkey,
        prey_fish_id: int,
        prey_name: str,
        expected_prey_share: int,
        hunter_fish_id: int | None = None,
    ) -> Instruction | None:
        if isinstance(prey_wallet, str):
            prey_wallet = Pubkey.from_string(prey_wallet)

        signer = self.sol.get_pubkey()
        my_fish = await self.get_my_fish(fish_id=hunter_fish_id)
        if not my_fish:
            print("[!] Couldn't find your Fish account")
            return None

        hunter_pda, _ = derive_fish(signer, my_fish["fish_id"])
        prey_pda, _ = derive_fish(prey_wallet, prey_fish_id)
        prey_name_reg, _ = derive_name_registry(prey_name)

        data = DISC["hunt_fish"] + struct.pack("<Q", expected_prey_share)

        ix = Instruction(
            program_id=HODL_PROGRAM,
            accounts=[
                AccountMeta(self.ocean, is_signer=False, is_writable=True),
                AccountMeta(hunter_pda, is_signer=False, is_writable=True),
                AccountMeta(prey_pda, is_signer=False, is_writable=True),
                AccountMeta(self.vault, is_signer=False, is_writable=True),
                AccountMeta(signer, is_signer=True, is_writable=True),
                AccountMeta(HODL_ADMIN, is_signer=False, is_writable=True),
                AccountMeta(SYSTEM_PROGRAM, is_signer=False, is_writable=False),
                AccountMeta(prey_name_reg, is_signer=False, is_writable=True),
            ],
            data=data,
        )
        return ix

    async def hunt_fish(
        self,
        prey_wallet: str | Pubkey,
        prey_fish_id: int,
        prey_name: str,
        expected_prey_share: int,
        hunter_fish_id: int | None = None,
    ) -> str | None:
        ix = await self.build_hunt_fish_ix(prey_wallet, prey_fish_id, prey_name, expected_prey_share, hunter_fish_id)
        if not ix: return None
        return await self._send_tx([ix], "HuntFish")

    # ── exit_game() ──────────────────────────────────────────────────────

    async def exit_game(self, fish_id: int | None = None) -> str | None:
        signer = self.sol.get_pubkey()
        my_fish = await self.get_my_fish(fish_id=fish_id)
        if not my_fish:
            print("[!] Couldn't find your Fish account")
            return None

        fish_pda, _ = derive_fish(signer, my_fish["fish_id"])
        name_reg, _ = derive_name_registry(my_fish["name"])

        ix = Instruction(
            program_id=HODL_PROGRAM,
            accounts=[
                AccountMeta(self.ocean, is_signer=False, is_writable=True),
                AccountMeta(fish_pda, is_signer=False, is_writable=True),
                AccountMeta(self.vault, is_signer=False, is_writable=True),
                AccountMeta(signer, is_signer=True, is_writable=True),
                AccountMeta(HODL_ADMIN, is_signer=False, is_writable=True),
                AccountMeta(name_reg, is_signer=False, is_writable=True),
                AccountMeta(SYSTEM_PROGRAM, is_signer=False, is_writable=False),
            ],
            data=DISC["exit_game"],
        )
        return await self._send_tx([ix], "ExitGame")

    # ── resurrect_fish(name, deposit) ────────────────────────────────────

    async def resurrect_fish(self, name: str, deposit: int) -> str | None:
        signer = self.sol.get_pubkey()
        my_fish = await self.get_my_fish()
        if not my_fish:
            print("[!] Couldn't find old Fish account")
            return None

        ocean_data = await self.get_ocean()
        if not ocean_data:
            print("[!] Couldn't fetch Ocean")
            return None

        old_fish_pda, _ = derive_fish(signer, my_fish["fish_id"])
        new_fish_pda, _ = derive_fish(signer, ocean_data["next_fish_id"])
        name_reg, _ = derive_name_registry(name)

        name_bytes = name.encode("utf-8")
        data = (
            DISC["resurrect_fish"]
            + struct.pack("<I", len(name_bytes))
            + name_bytes
            + struct.pack("<Q", deposit)
        )
        ix = Instruction(
            program_id=HODL_PROGRAM,
            accounts=[
                AccountMeta(self.ocean, is_signer=False, is_writable=True),
                AccountMeta(old_fish_pda, is_signer=False, is_writable=True),
                AccountMeta(new_fish_pda, is_signer=False, is_writable=True),
                AccountMeta(name_reg, is_signer=False, is_writable=True),
                AccountMeta(self.vault, is_signer=False, is_writable=True),
                AccountMeta(signer, is_signer=True, is_writable=True),
                AccountMeta(HODL_ADMIN, is_signer=False, is_writable=True),
                AccountMeta(SYSTEM_PROGRAM, is_signer=False, is_writable=False),
            ],
            data=data,
        )
        return await self._send_tx([ix], "ResurrectFish")

    # ── transfer_fish(new_owner) ─────────────────────────────────────────

    async def transfer_fish(self, new_owner: str | Pubkey, fish_id: int | None = None) -> str | None:
        if isinstance(new_owner, str):
            new_owner = Pubkey.from_string(new_owner)

        signer = self.sol.get_pubkey()
        my_fish = await self.get_my_fish(fish_id=fish_id)
        if not my_fish:
            print("[!] Couldn't find your Fish account")
            return None

        fish_pda, _ = derive_fish(signer, my_fish["fish_id"])
        new_fish_pda, _ = derive_fish(new_owner, my_fish["fish_id"])

        ix = Instruction(
            program_id=HODL_PROGRAM,
            accounts=[
                AccountMeta(self.ocean, is_signer=False, is_writable=True),
                AccountMeta(fish_pda, is_signer=False, is_writable=True),
                AccountMeta(new_fish_pda, is_signer=False, is_writable=True),
                AccountMeta(signer, is_signer=True, is_writable=True),
                AccountMeta(new_owner, is_signer=False, is_writable=True),
                AccountMeta(SYSTEM_PROGRAM, is_signer=False, is_writable=False),
            ],
            data=DISC["transfer_fish"],
        )
        return await self._send_tx([ix], "TransferFish")

    # ── find_prey ─────────────────────────────────────────────────────────

    async def find_prey(self, count: int = 4) -> list[dict]:
        
        my_fish = await self.get_my_fish()
        if not my_fish:
            print("[!] Couldn't find your Fish account")
            return []

        my_wallet = str(self.sol.get_pubkey())
        my_share = my_fish["share"]
        now = int(time.time())

        print(f"[*] My fish: '{my_fish['name']}' share={my_share / LAMPORTS_PER_SOL:.4f} SOL")

        all_fish = await self.get_all_fish()
        candidates = []
        for f in all_fish:
            if f["owner"] == my_wallet:
                continue
            if f["share"] == 0 or f["share"] >= my_share:
                continue
            if f["marked_by_hunter_id"] != 0:
                continue
            f["_value_sol"] = f["share"] / 1e9
            candidates.append(f)

        candidates.sort(key=lambda f: f["share"], reverse=True)

        print(f"[*] Found {len(candidates)} valid prey (out of {len(all_fish)} total)")
        for i, c in enumerate(candidates[:count]):
            print(f"  {i+1}. '{c['name']}' share={c['share']} (~{c['_value_sol']:.4f} SOL) id={c['fish_id']}")

        return candidates[:count]

    # ── batch_place_marks ────────────────────────────────────────────────

    async def batch_place_marks(self, targets: list[dict]) -> list[str | None]:
        
        signer = self.sol.get_pubkey()
        my_fish = await self.get_my_fish()
        if not my_fish:
            print("[!] Couldn't find your Fish account")
            return []

        hunter_pda, _ = derive_fish(signer, my_fish["fish_id"])
        bh = (await self.sol.client.get_latest_blockhash()).value.blockhash

        async def send_mark(target: dict) -> str | None:
            prey_wallet = Pubkey.from_string(target["owner"])
            prey_pda, _ = derive_fish(prey_wallet, target["fish_id"])

            ix = Instruction(
                program_id=HODL_PROGRAM,
                accounts=[
                    AccountMeta(self.ocean, is_signer=False, is_writable=True),
                    AccountMeta(hunter_pda, is_signer=False, is_writable=True),
                    AccountMeta(prey_pda, is_signer=False, is_writable=True),
                    AccountMeta(self.vault, is_signer=False, is_writable=True),
                    AccountMeta(signer, is_signer=True, is_writable=True),
                    AccountMeta(HODL_ADMIN, is_signer=False, is_writable=True),
                    AccountMeta(SYSTEM_PROGRAM, is_signer=False, is_writable=False),
                ],
                data=DISC["place_hunting_mark"],
            )
            all_ixns = [
                set_compute_unit_limit(self.cu_limit),
                set_compute_unit_price(self.cu_price),
                ix,
            ]
            msg = Message(all_ixns, signer)
            tx = Transaction([self.sol.KEYPAIR], msg, bh)
            try:
                opts = TxOpts(skip_preflight=True, preflight_commitment=Confirmed)
                resp = await self.sol.client.send_transaction(tx, opts=opts)
                sig = str(resp.value)
                print(f"[+] Mark '{target['name']}' (#{target['fish_id']}): {sig}")
                return sig
            except Exception as e:
                print(f"[!] Mark '{target['name']}' failed: {e}")
                return None

        print(f"\n[*] Sending {len(targets)} marks in parallel...")
        sigs = await asyncio.gather(*[send_mark(t) for t in targets])

        ok = sum(1 for s in sigs if s)
        print(f"\n[*] Result: {ok}/{len(targets)} marks sent")
        return list(sigs)

    # ── schedule_marks ───────────────────────────────────────────────────

    async def schedule_marks(
        self,
        count: int = 4,
        min_sol: float = 0.1,
        feeding_period: int = 7 * 24 * 3600,
        mark_window: int = 24 * 3600,
        advance_secs: int = 0,
    ) -> list[str | None]:
        """
        Планировщик меток.

        min_sol: минимальная SOL-стоимость жертвы (реальная, не raw share)
        feeding_period: через сколько после кормёжки рыба становится жертвой (7 дней)
        mark_window: за сколько до prey_time можно ставить метку (24 часа)
        advance_secs: задержка после открытия окна перед отправкой
        """
        my_fish = await self.get_my_fish(force=True)
        if not my_fish:
            print("[!] Couldn't find your Fish account")
            return []

        ocean = await self.get_ocean()
        if not ocean or ocean["total_shares"] == 0:
            print("[!] Couldn't fetch Ocean")
            return []

        share_price = ocean["balance_fishes"] / ocean["total_shares"]
        my_value_sol = my_fish["share"] * share_price / 1e9

        signer = self.sol.get_pubkey()
        my_wallet = str(signer)
        my_share = my_fish["share"]
        hunter_pda, _ = derive_fish(signer, my_fish["fish_id"])
        now = int(time.time())

        print(f"[*] My fish: '{my_fish['name']}' share={my_share} (~{my_value_sol:.4f} SOL)")
        print(f"[*] Share→SOL rate: {share_price:.4f} lamports/share")
        print(f"[*] Now: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}")
        print(f"[*] Scanning all fish...")

        all_fish = await self.get_all_fish()
        print(f"[*] Total fish fetched: {len(all_fish)}")

        skip_own = 0
        skip_heavy = 0
        skip_cheap = 0
        skip_marked = 0
        skip_prey_past = 0
        scheduled = []

        for f in all_fish:
            if f["owner"] == my_wallet:
                skip_own += 1
                continue
            if f["share"] >= my_share:
                skip_heavy += 1
                continue
            f_sol = f["share"] * share_price / 1e9
            if f_sol < min_sol:
                skip_cheap += 1
                continue
            if f["marked_by_hunter_id"] != 0:
                skip_marked += 1
                continue

            prey_time = f["last_fed_at"] + feeding_period
            mark_open = prey_time - mark_window

            if prey_time <= now:
                skip_prey_past += 1
                continue

            fire_at = mark_open + advance_secs
            wait = max(0, fire_at - now)

            f["_prey_time"] = prey_time
            f["_mark_open"] = mark_open
            f["_fire_at"] = fire_at
            f["_wait"] = wait
            f["_sol_value"] = f_sol
            scheduled.append(f)

        print(f"[*] Filters: own={skip_own} heavy={skip_heavy} <{min_sol}SOL={skip_cheap} marked={skip_marked} expired={skip_prey_past}")
        print(f"[*] Passed all filters: {len(scheduled)}")

        scheduled.sort(key=lambda f: (f["_fire_at"], -f["share"]))
        scheduled = scheduled[:count]

        if not scheduled:
            print("[!] No schedulable prey found")
            return []

        def fmt_delta(secs: float) -> str:
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

        print(f"\n{'─'*70}")
        print(f"  SCHEDULED MARKS ({len(scheduled)} targets)")
        print(f"{'─'*70}")
        for i, t in enumerate(scheduled):
            prey_str = time.strftime("%m-%d %H:%M", time.localtime(t["_prey_time"]))
            status = "WINDOW OPEN" if t["_mark_open"] <= now else f"fire in {fmt_delta(t['_wait'])}"
            print(
                f"  {i+1}. '{t['name']}' "
                f"{t['_sol_value']:.4f} SOL  "
                f"prey @ {prey_str}  "
                f"→ {status}"
            )
        print(f"{'─'*70}\n")

        async def scheduled_mark(target: dict) -> str | None:
            wait = target["_wait"]
            name = target["name"]

            if wait > 0:
                print(f"  [~] '{name}': sleeping {fmt_delta(wait)}...")
                await asyncio.sleep(wait)

            print(f"  [>] '{name}': sending mark NOW")

            prey_wallet = Pubkey.from_string(target["owner"])
            prey_pda, _ = derive_fish(prey_wallet, target["fish_id"])

            ix = Instruction(
                program_id=HODL_PROGRAM,
                accounts=[
                    AccountMeta(self.ocean, is_signer=False, is_writable=True),
                    AccountMeta(hunter_pda, is_signer=False, is_writable=True),
                    AccountMeta(prey_pda, is_signer=False, is_writable=True),
                    AccountMeta(self.vault, is_signer=False, is_writable=True),
                    AccountMeta(signer, is_signer=True, is_writable=True),
                    AccountMeta(HODL_ADMIN, is_signer=False, is_writable=True),
                    AccountMeta(SYSTEM_PROGRAM, is_signer=False, is_writable=False),
                ],
                data=DISC["place_hunting_mark"],
            )
            try:
                return await self._send_tx([ix], f"Mark '{name}'")
            except Exception as e:
                print(f"  [!] '{name}' failed: {e}")
                return None

        results = await asyncio.gather(*[scheduled_mark(t) for t in scheduled])

        ok = sum(1 for r in results if r)
        print(f"\n[*] Done: {ok}/{len(scheduled)} marks placed")
        return list(results)
    def __get_mark_by_fish_id(self,fish_id_id):
        api = f"https://api.hodlhunt.io/api/v1/fish/{fish_id_id}/info"


        dict_marks = {}




async def main():
    sol = SOL(
        rpc_url="https://api.mainnet-beta.solana.com",
        KEYPAIR="5GPm7ANTxp2ivmykSoHuh73b8T4XSv6iGa737sBUrpSMQVhDLjMH8aMHWC1sKjA3vbTm5buDamufUFNFHGe8Tc9Y",
    )

    hunt = HodlHunt(sol)
    fishes = await hunt.get_all_fish_by_wallet(sol.get_pubkey())
    for fish in fishes: 
        name_ui = fish["name"]
        name_derive = derive_fish(owner=sol.get_pubkey(), fish_id=fish["fish_id"])
        print(name_ui, name_derive, fish)


if __name__ == "__main__":
    asyncio.run(main())
