"""AsyncWorker — фоновый поток с async-логикой HodlHunt."""
import sys
import os
import io
import time
import asyncio
import queue
import json
import re
import threading
from datetime import datetime

# Path setup: hodlhuntSol and OrbisPayClean
_hodlhunt_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tools_dir = os.path.dirname(_hodlhunt_dir)
sys.path.insert(0, _hodlhunt_dir)
_orbis = os.path.join(_tools_dir, "OrbisPayClean")
if os.path.exists(_orbis):
    sys.path.insert(0, _orbis)

from PyQt6.QtCore import QThread, pyqtSignal
from OrbisPaySDK.interface.sol import SOL
from OrbisPaySDK.const import LAMPORTS_PER_SOL

try:
    from OrbisPaySDK.utils import utils as _price_utils
    HAS_SOL_PRICE = True
except ImportError:
    HAS_SOL_PRICE = False

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

from main import HodlHunt, HODL_PROGRAM


class LogStream(io.TextIOBase):
    def __init__(self, signal):
        super().__init__()
        self._signal = signal

    def write(self, text):
        if text and text.strip():
            self._signal.emit(text.rstrip())
        return len(text) if text else 0


class AsyncWorker(QThread):
    sig_log = pyqtSignal(str)
    sig_my_fish = pyqtSignal(object)
    sig_my_fish_list = pyqtSignal(list)
    sig_ocean = pyqtSignal(object)
    sig_all_fish = pyqtSignal(list)
    sig_tx = pyqtSignal(str, str)
    sig_schedule_item = pyqtSignal(dict)
    sig_schedule_done = pyqtSignal(int, str, str)
    sig_schedule_finished = pyqtSignal()
    sig_error = pyqtSignal(str)
    sig_activity = pyqtSignal(dict)
    sig_tx_status = pyqtSignal(str, bool, str, str)
    sig_bite_check = pyqtSignal(str, str, int, bool, float, int)
    sig_fish_updated = pyqtSignal(dict)
    sig_sol_price = pyqtSignal(float)
    sig_wallet_balance = pyqtSignal(int)
    sig_queue_item_done = pyqtSignal(str, str, str)
    sig_ready = pyqtSignal()
    sig_all_wallets_fish = pyqtSignal(dict)  # {wallet_index: [fish, ...]}

    def __init__(self, rpc_url: str, keypair: str):
        super().__init__()
        self._rpc_url = rpc_url
        self._keypair = keypair
        self._queue: queue.Queue = queue.Queue()
        self._running = True
        self._hunt: HodlHunt | None = None

    def stop(self):
        self._running = False

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        old_stdout = sys.stdout
        sys.stdout = LogStream(self.sig_log)
        try:
            sol = SOL(rpc_url=self._rpc_url, KEYPAIR=self._keypair)
            self._hunt = HodlHunt(sol)
            self.sig_log.emit("Backend ready")
            self.sig_ready.emit()
        except Exception as e:
            self.sig_error.emit(f"Init failed: {e}")
            sys.stdout = old_stdout
            return
        loop.run_until_complete(self._main_loop())
        sys.stdout = old_stdout
        loop.close()

    def _ws_url(self) -> str:
        u = self._rpc_url.replace("https://", "wss://").replace("http://", "ws://")
        return u if u != self._rpc_url else "wss://api.mainnet-beta.solana.com"

    async def _run_activity_subscription(self):
        if not HAS_WEBSOCKETS:
            return
        ws_url = self._ws_url()
        program_id = str(HODL_PROGRAM)
        instr_pattern = re.compile(r"(?:Instruction|instruction):\s*(\w+)", re.IGNORECASE)
        instr_map = {
            "feedfish": "feed_fish", "huntfish": "hunt_fish", "placehuntingmark": "place_hunting_mark",
            "createfish": "create_fish", "exitgame": "exit_game", "transferfish": "transfer_fish",
            "resurrectfish": "resurrect_fish",
        }
        while self._running:
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                        "params": [{"mentions": [program_id]}, {"commitment": "confirmed"}],
                    }))
                    resp = json.loads(await ws.recv())
                    if "error" in resp:
                        self.sig_error.emit(f"Activity WS: {resp['error']}")
                        await asyncio.sleep(30)
                        continue
                    self.sig_log.emit("Activity feed connected")
                    async for msg in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(msg)
                            val = data.get("params", {}).get("result", {}).get("value", {})
                            sig = val.get("signature", "")
                            err = val.get("err")
                            logs = val.get("logs", [])
                            action = "unknown"
                            for line in logs:
                                m = instr_pattern.search(line)
                                if m:
                                    key = m.group(1).lower().replace("_", "")
                                    action = instr_map.get(key, m.group(1))
                                    break
                            self.sig_activity.emit({
                                "signature": sig, "action": action, "success": err is None,
                                "time": datetime.now().strftime("%H:%M:%S"),
                            })
                        except Exception:
                            pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    self.sig_log.emit(f"Activity WS reconnect: {e}")
                await asyncio.sleep(5)

    async def _main_loop(self):
        self._sched_task: asyncio.Task | None = None
        self._ws_task: asyncio.Task | None = None
        self._queue_tasks: dict[str, asyncio.Task] = {}
        if HAS_WEBSOCKETS:
            self._ws_task = asyncio.create_task(self._run_activity_subscription())
        try:
            while self._running:
                try:
                    cmd, args = self._queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.1)
                    continue
                try:
                    if cmd == "enqueue_item":
                        qid = args["qid"]
                        task = asyncio.create_task(self._do_single_queue_item(qid, args["target"]))
                        self._queue_tasks[qid] = task
                        task.add_done_callback(lambda t, q=qid: self._queue_tasks.pop(q, None))
                        continue
                    elif cmd == "cancel_item":
                        if args["qid"] in self._queue_tasks:
                            self._queue_tasks[args["qid"]].cancel()
                        continue
                    elif cmd in ("schedule", "run_queue"):
                        if self._sched_task and not self._sched_task.done():
                            self.sig_log.emit("Scheduler already running")
                            continue
                        self._sched_task = asyncio.create_task(
                            self._run_schedule(args) if cmd == "schedule" else self._run_queue(args)
                        )
                    elif cmd == "stop_schedule":
                        if self._sched_task and not self._sched_task.done():
                            self._sched_task.cancel()
                            self.sig_log.emit("Scheduler cancelled")
                            self.sig_schedule_finished.emit()
                    elif cmd == "preload_fish_by_wallets":
                        await self._preload_fish_by_wallets(args)
                    else:
                        await self._dispatch(cmd, args)
                except Exception as e:
                    err_str = str(e)
                    self.sig_error.emit(f"{cmd} error: {err_str}")
                    if cmd not in ("refresh", "load_fish", "update_settings"):
                        label = args.get("label", "Manual Action") if isinstance(args, dict) else "Action"
                        self._send_tg_error(cmd, label, err_str)
        finally:
            if self._sched_task and not self._sched_task.done():
                self._sched_task.cancel()
                try:
                    await self._sched_task
                except asyncio.CancelledError:
                    pass
            for t in list(self._queue_tasks.values()):
                if not t.done():
                    t.cancel()
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass
            if self._ws_task and not self._ws_task.done():
                self._ws_task.cancel()
                try:
                    await self._ws_task
                except asyncio.CancelledError:
                    pass

    def _send_tg_error(self, action: str, label: str, err_str: str):
        def _do():
            try:
                from notify import send_all
                from error_parser import format_queue_error_html
                send_all(format_queue_error_html(action, label, err_str))
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    def _safe_emit(self, sig, *args):
        try:
            sig.emit(*args)
        except RuntimeError:
            pass

    async def _preload_fish_by_wallets(self, args: dict):
        """Загрузить рыб по всем кошелькам. wallet_pubkeys: [(index, pubkey_str), ...]"""
        h = self._hunt
        if not h:
            return
        wallet_pubkeys = args.get("wallet_pubkeys", [])
        if not wallet_pubkeys:
            return
        result: dict[int, list] = {}
        for i, (idx, pubkey) in enumerate(wallet_pubkeys):
            if i > 0:
                await asyncio.sleep(0.4)
            try:
                fishes = await h.get_all_fish_by_wallet(pubkey)
                result[idx] = fishes if fishes else []
                ids = [f["fish_id"] for f in result[idx] if f.get("fish_id") is not None]
                self._safe_emit(self.sig_log, f"Preload wallet #{idx+1}: {len(result[idx])} fish, actual_fish_ids {ids}")

            except Exception as e:
                self._safe_emit(self.sig_log, f"Preload wallet #{idx+1}: {e}")
                result[idx] = []
        from logic.storage import set_all_wallets_fish
        set_all_wallets_fish(result)
        self._safe_emit(self.sig_all_wallets_fish, result)

    async def _dispatch(self, cmd: str, args: dict):
        h = self._hunt
        if cmd == "refresh":
            fishes = await h.get_my_fish_list(force=True)
            self.sig_my_fish_list.emit(fishes)
            self.sig_my_fish.emit(fishes[0] if fishes else None)
            ocean = await h.get_ocean()
            self.sig_ocean.emit(ocean)
            try:
                bal = await h._get_balance(h.sol.get_pubkey())
                self.sig_wallet_balance.emit(bal)
            except Exception:
                pass
        elif cmd == "load_fish":
            all_f = await h.get_all_fish()
            ocean = await h.get_ocean()
            self.sig_ocean.emit(ocean)
            self.sig_all_fish.emit(all_f)
        elif cmd == "feed":
            sig = await h.feed_fish(args["amount"], fish_id=args.get("fish_id"))
            ok = sig is not None
            label = args.get("label", "Feed")
            self.sig_tx_status.emit("feed", ok, label, sig or "")
        elif cmd == "exit_game":
            sig = await h.exit_game(fish_id=args.get("fish_id"))
            ok = sig is not None
            self.sig_tx_status.emit("exit_game", ok, "Exit Game", sig or "")
        elif cmd == "transfer":
            sig = await h.transfer_fish(args["wallet"], fish_id=args.get("fish_id"))
            ok = sig is not None
            self.sig_tx_status.emit("transfer", ok, "Transfer", sig or "")
        elif cmd == "create_fish":
            sig = await h.create_fish(args["name"], args["deposit"])
            ok = sig is not None
            label = args.get("label", "Create Fish")
            self.sig_tx_status.emit("create_fish", ok, label, sig or "")
        elif cmd == "place_mark":
            sig = await h.place_hunting_mark(args["wallet"], args["fish_id"], hunter_fish_id=args.get("hunter_fish_id"))
            ok = sig is not None
            label = args.get("label", "Mark")
            self.sig_tx_status.emit("mark", ok, label, sig or "")
        elif cmd == "hunt_fish":
            sig = await h.hunt_fish(args["wallet"], args["fish_id"], args["name"], args["share"], hunter_fish_id=args.get("hunter_fish_id"))
            ok = sig is not None
            label = args.get("label", "Hunt")
            self.sig_tx_status.emit("hunt", ok, label, sig or "")
        elif cmd == "update_settings":
            h.cu_limit = args["cu_limit"]
            h.cu_price = args["cu_price"]
            self.sig_log.emit(f"CU updated: limit={h.cu_limit}, price={h.cu_price}")
        elif cmd == "check_bite_window":
            fresh = await h.get_fish(args["owner"], args["fish_id"])
            ocean = await h.get_ocean()
            share_price = 0
            if ocean and ocean.get("total_shares"):
                vault = ocean.get("vault_balance", ocean.get("balance_fishes", 0))
                share_price = vault / ocean["total_shares"]
            if not fresh:
                self.sig_bite_check.emit(args["name"], args["owner"], args["fish_id"], True, 0, 0)
                return
            was_fed = fresh["last_fed_at"] != args["last_fed_at"]
            if was_fed:
                self.sig_fish_updated.emit(fresh)
            feeding_period = args.get("feeding_period", 7 * 86400)
            prey_time = fresh["last_fed_at"] + feeding_period
            now = int(time.time())
            hunt_in_sec = max(0, prey_time - now)
            sol_val = fresh["share"] * share_price / 1e9 if share_price else 0
            self.sig_bite_check.emit(args["name"], args["owner"], args["fish_id"], was_fed, sol_val, hunt_in_sec)
        elif cmd == "get_sol_price":
            if HAS_SOL_PRICE:
                try:
                    price = await _price_utils.get_native_price("sol", "usd")
                    self.sig_sol_price.emit(float(price) if price else 0.0)
                except Exception:
                    pass
        elif cmd == "donate":
            to_addr = args.get("to", "").strip()
            amount_sol = float(args.get("amount", 0))
            if not to_addr or to_addr == "YOUR_SOLANA_ADDRESS_HERE" or amount_sol <= 0:
                self.sig_error.emit("Invalid donate: check address and amount")
                return
            lamports = int(amount_sol * LAMPORTS_PER_SOL)
            if lamports <= 0:
                self.sig_error.emit("Donate amount too small")
                return
            try:
                sig = await h.transfer_sol(to_addr, lamports)
                ok = sig is not None
                label = f"Donate {amount_sol:.4f} SOL"
                self.sig_tx_status.emit("donate", ok, label, str(sig) if sig else "")
                if sig:
                    self.sig_log.emit(f"Donate sent: {sig}")
                else:
                    self.sig_error.emit("Donate tx failed")
            except Exception as e:
                self.sig_error.emit(f"Donate: {e}")
        elif cmd == "schedule":
            pass

    async def _run_schedule(self, args: dict):
        h = self._hunt
        fish_id = args.get("fish_id")
        fish_owner = args.get("fish_owner")
        self._safe_emit(self.sig_log, "Scheduler: fetching my fish...")
        my_fish = await h.get_my_fish(force=True, fish_id=fish_id)
        if not my_fish and fish_id is not None and fish_owner:
            my_fish = await h.get_fish(fish_owner, fish_id)
        if not my_fish:
            for _ in range(3):
                await asyncio.sleep(2)
                if not self._running:
                    return
                my_fish = await h.get_my_fish(force=True, fish_id=fish_id)
                if not my_fish and fish_id is not None and fish_owner:
                    my_fish = await h.get_fish(fish_owner, fish_id)
                if my_fish:
                    break
        if not my_fish:
            self._safe_emit(self.sig_error, "Couldn't find your fish")
            self._safe_emit(self.sig_schedule_finished)
            return
        ocean = await h.get_ocean()
        if not ocean or ocean["total_shares"] == 0:
            self._safe_emit(self.sig_error, "Couldn't fetch ocean")
            self._safe_emit(self.sig_schedule_finished)
            return
        vault_bal = ocean.get("vault_balance", ocean["balance_fishes"])
        share_price = vault_bal / ocean["total_shares"]
        my_share = my_fish["share"]
        my_value = my_share * share_price / 1e9
        my_wallet = str(h.sol.get_pubkey())
        now = int(time.time())
        feeding_period = args.get("feeding_period", 7 * 86400)
        mark_window = args.get("mark_window", 24 * 3600)
        min_sol = args.get("min_sol", 0.1)
        count = args.get("count", 4)
        self._safe_emit(self.sig_log, f"Scheduler: my fish '{my_fish['name']}' ~{my_value:.4f} SOL (share={my_share})")
        self._safe_emit(self.sig_log, "Scheduler: loading all fish...")
        all_fish = await h.get_all_fish()
        self._safe_emit(self.sig_log, f"Scheduler: {len(all_fish)} fish loaded")
        skip_own = skip_heavy = skip_cheap = skip_marked = skip_expired = 0
        candidates = []
        for f in all_fish:
            if f["owner"] == my_wallet:
                skip_own += 1
                continue
            if f["share"] >= my_share or f["share"] == 0:
                skip_heavy += 1
                continue
            if f["marked_by_hunter_id"] != 0:
                skip_marked += 1
                continue
            f_sol = f["share"] * share_price / 1e9
            if f_sol < min_sol:
                skip_cheap += 1
                continue
            prey_time = f["last_fed_at"] + feeding_period
            if prey_time <= now:
                skip_expired += 1
                continue
            mark_open = prey_time - mark_window
            wait = max(0, mark_open - now)
            f["_prey_time"] = prey_time
            f["_wait"] = wait
            f["_sol_value"] = f_sol
            candidates.append(f)
        self._safe_emit(self.sig_log,
            f"Scheduler: filters — own={skip_own} heavy={skip_heavy} "
            f"<{min_sol}SOL={skip_cheap} marked={skip_marked} expired={skip_expired} → {len(candidates)} candidates"
        )
        candidates.sort(key=lambda x: (x["_wait"], -x["share"]))
        candidates = candidates[:count]
        if not candidates:
            self._safe_emit(self.sig_log, "Scheduler: no schedulable prey found")
            self._safe_emit(self.sig_schedule_finished)
            return
        for c in candidates:
            self._safe_emit(self.sig_schedule_item, c)
        self._safe_emit(self.sig_log, f"Scheduler: {len(candidates)} targets found and sent to queue.")
        self._safe_emit(self.sig_schedule_finished)

    async def _run_queue(self, args: dict):
        pass  # Legacy — run_queue now uses enqueue_item

    async def _do_single_queue_item(self, qid: str, target: dict):
        h = self._hunt
        action = target.get("_action", "mark")
        now = int(time.time())
        fire_at = target.get("_fire_at", 0)
        wait = max(0, fire_at - now) if fire_at > 0 else target.get("_wait", 0)
        my_fish_id = target.get("my_fish_id")
        my_fish = await h.get_my_fish(force=False, fish_id=my_fish_id)
        if not my_fish and my_fish_id is not None:
            my_fish = await h.get_fish(str(h.sol.get_pubkey()), my_fish_id)
        if not my_fish and "my_fish_id" not in target:
            my_fish_list = await h.get_my_fish_list()
            my_fish = my_fish_list[0] if my_fish_list else None
        if not my_fish:
            self._safe_emit(self.sig_queue_item_done, qid, "failed", "could not find your fish")
            return
        from solders.pubkey import Pubkey
        ix = None
        label = ""
        try:
            if action == "feed":
                amount = target.get("_amount", 0)
                if amount <= 0:
                    self._safe_emit(self.sig_queue_item_done, qid, "failed", "feed amount is 0")
                    return
                sol_val = target.get("_sol_value", 0.1)
                max_lamports = int(0.05 * sol_val * LAMPORTS_PER_SOL)
                amount = min(amount, max_lamports)
                fish_id = target.get("fish_id", my_fish["fish_id"])
                ix = await h.build_feed_fish_ix(amount, fish_id=fish_id)
                label = f"Feed {amount/LAMPORTS_PER_SOL:.4f} SOL"
            elif action == "mark":
                prey_wallet = Pubkey.from_string(target["owner"])
                ix = await h.build_place_hunting_mark_ix(
                    prey_wallet, target["fish_id"], hunter_fish_id=my_fish["fish_id"]
                )
                label = f"Mark '{target['name']}'"
            else:
                prey_wallet = Pubkey.from_string(target["owner"])
                ix = await h.build_hunt_fish_ix(
                    prey_wallet, target["fish_id"], target["name"], target["share"],
                    hunter_fish_id=my_fish["fish_id"]
                )
                label = f"Hunt '{target['name']}'"
            if not ix:
                self._safe_emit(self.sig_queue_item_done, qid, "failed", "could not build instruction")
                self._safe_emit(self.sig_log, f"Queue [{qid[:4]}]: Failed to build instruction for {label}")
                return
            self._safe_emit(self.sig_log, f"Queue [{qid[:4]}]: Successfully built instruction for '{label}'")
        except Exception as e:
            self._safe_emit(self.sig_queue_item_done, qid, "failed", f"build error: {e}")
            return
        if wait > 0:
            self._safe_emit(self.sig_queue_item_done, qid, "waiting", "")
            self._safe_emit(self.sig_log, f"Queue [{qid[:4]}]: Sleeping for {wait}s before '{label}'...")
            await asyncio.sleep(wait)
        now = int(time.time())
        if fire_at > 0 and now < fire_at:
            remain = fire_at - now
            self._safe_emit(self.sig_log, f"Queue [{qid[:4]}]: Timer not expired yet, {remain}s left — skipping")
            return
        self._safe_emit(self.sig_queue_item_done, qid, "sending", "")
        self._safe_emit(self.sig_log, f"Queue [{qid[:4]}]: Timer expired, fetching blockhash & sending '{label}'...")
        try:
            sig = await h._send_tx([ix], label)
            if sig:
                self._safe_emit(self.sig_queue_item_done, qid, "done", sig)
            else:
                self._safe_emit(self.sig_queue_item_done, qid, "failed", "tx rejected (see log)")
        except Exception as e:
            err_str = str(e)
            self._safe_emit(self.sig_queue_item_done, qid, "failed", err_str)
            self._safe_emit(self.sig_log, f"Queue [{qid[:4]}]: Error sending '{label}' -> {err_str[:100]}")

    def send(self, cmd: str, **kwargs):
        self._queue.put((cmd, kwargs))
