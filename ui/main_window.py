"""Главное окно HodlHunt — UI и обработчики."""
import sys
import os
import time
import uuid
import json
from datetime import datetime
from functools import partial

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QLineEdit, QDoubleSpinBox, QSpinBox, QCheckBox, QHeaderView,
    QMenu, QSplitter, QGroupBox, QGridLayout, QAbstractItemView, QDialog,
    QScrollArea, QComboBox, QDateTimeEdit, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtGui import QColor, QAction

LAMPORTS_PER_SOL = 1_000_000_000


from config import (
    load_wallets_config,
    save_wallets_config,
    all_sched_cache_paths,
    SCHEDULE_TRANSACTIONS_PATH,
    load_hunter_marks,
    file_logger,
    BASE_DIR,
)
from constants import DARK_STYLE, SETTINGS_GROUP
from logic.utils import fmt_delta, fmt_sol_usd, pubkey_from_keypair
from logic.storage import get_fishes, get_fish_by_id
from logic.worker import AsyncWorker, HAS_WEBSOCKETS
from ui.dialogs import AddToQueueTimeDialog, FeedScheduleDialog, DonateDialog, FishCardDialog
from ui.widgets import make_stat_card


class HodlHuntUI(QMainWindow):
    def __init__(self, rpc_url: str, keypair: str, wallets: list[str] | None = None, active_index: int = 0):
        super().__init__()
        self.setWindowTitle("HodlHunt")
        self.setMinimumSize(1100, 750)
        self.resize(1200, 800)

        self._wallets = wallets if wallets and len(wallets) > 0 else [keypair]
        self._active_wallet_index = max(0, min(active_index, len(self._wallets) - 1))
        self._keypair = self._wallets[self._active_wallet_index]

        self._share_price = 0.0
        self._is_storm = False
        self._feeding_pct = 0.05
        self._all_fish: list[dict] = []
        self._my_fish: dict | None = None
        self._my_fish_list: list[dict] = []
        self._marked_fish: list[dict] = []
        self._hunter_marks_from_file: list[dict] = []
        self._schedule_targets: list[dict] = []
        self._schedule_start_time = 0
        self._activity_list: list[dict] = []
        self._transaction_history: list[dict] = []

        self._worker = AsyncWorker(rpc_url, self._keypair)
        self._worker.sig_log.connect(self._on_log)
        self._worker.sig_my_fish.connect(self._on_my_fish)
        self._worker.sig_my_fish_list.connect(self._on_my_fish_list)
        self._worker.sig_ocean.connect(self._on_ocean)
        self._worker.sig_all_fish.connect(self._on_all_fish)
        self._worker.sig_error.connect(self._on_error)
        self._worker.sig_schedule_item.connect(self._on_schedule_item)
        self._worker.sig_schedule_done.connect(self._on_schedule_done)
        self._worker.sig_queue_item_done.connect(self._on_queue_item_done)
        self._worker.sig_schedule_finished.connect(self._on_schedule_finished)
        self._worker.sig_activity.connect(self._on_activity)
        self._worker.sig_tx_status.connect(self._on_tx_status)
        self._worker.sig_bite_check.connect(self._on_bite_check)
        self._worker.sig_mark_api_fetched.connect(self._on_mark_api_fetched)
        self._worker.sig_fish_updated.connect(self._on_fish_updated)
        self._worker.sig_ready.connect(self._on_worker_ready)
        self._worker.sig_all_wallets_fish.connect(self._on_all_wallets_fish)
        self._worker.start()

        self._bite_notified: set[tuple[str, int]] = set()  # (owner, fish_id) already notified
        self._bite_check_pending: set[tuple[str, int]] = set()  # check in progress
        self._pending_bite_after_api: set[tuple[str, int]] = set()  # ждём API перед bite check
        self._sched_cache_loaded = False
        self._transactions_loaded = False
        self._sched_auto_run_cooldown = 0
        self._sched_row_to_target: list[int] = []  # row -> target index (-1 = section)
        self._sched_target_to_row: dict[int, int] = {}  # target index -> table row
        self._run_queue_target_indices: list[int] = []
        self._sol_usd_price = 0.0

        self._build_ui()
        self._apply_wallet_fish(self._active_wallet_index)
        self._worker.sig_sol_price.connect(self._on_sol_price)
        self._worker.sig_wallet_balance.connect(self._on_wallet_balance)
        self._load_env_settings()
        self._update_scheduler_buttons()

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(1000)

        self._price_timer = QTimer(self)
        self._price_timer.timeout.connect(lambda: self._worker.send("get_sol_price"))
        self._price_timer.start(30_000)

        self._marks_api_timer = QTimer(self)
        self._marks_api_timer.timeout.connect(self._check_marks_via_api)
        self._marks_api_timer.start(30_000)
        QTimer.singleShot(5000, self._check_marks_via_api)

        QTimer.singleShot(600, lambda: self._worker.send("get_sol_price"))
        QTimer.singleShot(0, self._load_sched_cache)

    def _load_env_settings(self):
        env_path = os.path.join(BASE_DIR, ".env")
        env = dict(os.environ)
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()

        if "HODL_CU_LIMIT" in env:
            self.set_cu_limit.setValue(int(env["HODL_CU_LIMIT"]))
        if "HODL_CU_PRICE" in env:
            self.set_cu_price.setValue(int(env["HODL_CU_PRICE"]))
        if "HODL_FEED_PERIOD" in env:
            self.set_feed_period.setValue(int(env["HODL_FEED_PERIOD"]))
        if "HODL_MARK_WINDOW" in env:
            self.set_mark_window.setValue(int(env["HODL_MARK_WINDOW"]))
        if "HODL_MIN_SOL" in env:
            self.set_min_sol.setValue(float(env["HODL_MIN_SOL"]))
        if "HODL_MAX_TARGETS" in env:
            self.set_max_targets.setValue(int(env["HODL_MAX_TARGETS"]))
        if "HODL_AUTO_REFRESH" in env:
            self.set_auto_refresh.setValue(int(env["HODL_AUTO_REFRESH"]))
        if "HODL_TG_TOKEN" in env:
            self.set_tg_token.setText(env["HODL_TG_TOKEN"])
        if "HODL_TG_CHAT" in env:
            self.set_tg_chat.setText(env["HODL_TG_CHAT"])
        if "HODL_DISCORD_WEBHOOK" in env:
            self.set_discord_webhook.setText(env["HODL_DISCORD_WEBHOOK"])
        if "HODL_DONATE_ENABLED" in env:
            self.set_donate_enabled.setChecked(env["HODL_DONATE_ENABLED"].strip().lower() in ("1", "true", "yes", "on"))
        else:
            self.set_donate_enabled.setChecked(True)

        self._on_donate_toggled(self.set_donate_enabled.isChecked())
        self._apply_settings()
        self._populate_wallet_keys_edit()

    def _populate_wallet_combo(self):
        self.combo_settings_wallet.blockSignals(True)
        self.combo_settings_wallet.clear()
        for i, _ in enumerate(self._wallets):
            pub = pubkey_from_keypair(self._wallets[i])
            short = f"{pub[:6]}...{pub[-4:]}" if len(pub) > 12 else pub
            self.combo_settings_wallet.addItem(f"#{i+1} {short}", i)
        self.combo_settings_wallet.setCurrentIndex(self._active_wallet_index)
        self.combo_settings_wallet.blockSignals(False)

    def _populate_wallet_keys_edit(self):
        text = "\n".join(self._wallets)
        self.wallet_keys_edit.setPlainText(text)

    def _on_settings_wallet_changed(self, idx: int):
        if idx < 0 or idx >= len(self._wallets):
            return
        if hasattr(self, "combo_wallet"):
            self.combo_wallet.blockSignals(True)
            self.combo_wallet.setCurrentIndex(idx)
            self.combo_wallet.blockSignals(False)
        self._switch_wallet(idx)

    def _apply_wallets(self):
        lines = [ln.strip() for ln in self.wallet_keys_edit.toPlainText().strip().split("\n") if ln.strip()]
        if not lines:
            self._on_log("Add at least one private key")
            return
        if len(lines) > 20:
            self._on_log("Max 20 wallets")
            return
        for i, k in enumerate(lines):
            pub = pubkey_from_keypair(k)
            if pub == "?":
                self._on_log(f"Invalid key at line {i+1}")
                return
        self._wallets = lines
        self._active_wallet_index = min(self._active_wallet_index, len(self._wallets) - 1)
        save_wallets_config(self._wallets, self._active_wallet_index)
        self._populate_wallet_combo()
        self._populate_wallet_keys_edit()
        if hasattr(self, "combo_wallet"):
            self.combo_wallet.blockSignals(True)
            self.combo_wallet.clear()
            for i, _ in enumerate(self._wallets):
                pub = pubkey_from_keypair(self._wallets[i])
                short = f"{pub[:6]}...{pub[-4:]}" if len(pub) > 12 else pub
                self.combo_wallet.addItem(f"#{i+1} {short}", i)
            self.combo_wallet.setCurrentIndex(self._active_wallet_index)
            self.combo_wallet.blockSignals(False)
        if hasattr(self, "wallet_header_widget"):
            self.wallet_header_widget.setVisible(len(self._wallets) > 1)
        self._switch_wallet(self._active_wallet_index)
        QTimer.singleShot(1500, self._send_preload_fish)
        self._on_log(f"Wallets saved: {len(self._wallets)}")

    def _on_wallet_selected(self, idx: int):
        if idx < 0 or idx >= len(self._wallets):
            return
        if hasattr(self, "combo_settings_wallet"):
            self.combo_settings_wallet.blockSignals(True)
            self.combo_settings_wallet.setCurrentIndex(idx)
            self.combo_settings_wallet.blockSignals(False)
        self._switch_wallet(idx)

    def _switch_wallet(self, new_index: int):
        self._active_wallet_index = new_index
        self._keypair = self._wallets[self._active_wallet_index]
        save_wallets_config(self._wallets, self._active_wallet_index)

        self._worker.stop()
        self._worker.wait(5000)
        self._worker = AsyncWorker(self._worker._rpc_url, self._keypair)
        self._worker.sig_log.connect(self._on_log)
        self._worker.sig_my_fish.connect(self._on_my_fish)
        self._worker.sig_my_fish_list.connect(self._on_my_fish_list)
        self._worker.sig_ocean.connect(self._on_ocean)
        self._worker.sig_all_fish.connect(self._on_all_fish)
        self._worker.sig_error.connect(self._on_error)
        self._worker.sig_schedule_item.connect(self._on_schedule_item)
        self._worker.sig_schedule_done.connect(self._on_schedule_done)
        self._worker.sig_queue_item_done.connect(self._on_queue_item_done)
        self._worker.sig_schedule_finished.connect(self._on_schedule_finished)
        self._worker.sig_activity.connect(self._on_activity)
        self._worker.sig_tx_status.connect(self._on_tx_status)
        self._worker.sig_bite_check.connect(self._on_bite_check)
        self._worker.sig_mark_api_fetched.connect(self._on_mark_api_fetched)
        self._worker.sig_fish_updated.connect(self._on_fish_updated)
        self._worker.sig_sol_price.connect(self._on_sol_price)
        self._worker.sig_wallet_balance.connect(self._on_wallet_balance)
        self._worker.sig_ready.connect(self._on_worker_ready)
        self._worker.sig_all_wallets_fish.connect(self._on_all_wallets_fish)
        self._worker.start()

        self._my_fish = None
        self._my_fish_list = []
        self._all_fish = []
        self._marked_fish = []
        self._bite_notified.clear()
        self._bite_check_pending.clear()
        self._pending_bite_after_api.clear()
        self._sched_cache_loaded = False

        self._redraw_dashboard()
        self._rebuild_sched_table()
        self._apply_wallet_fish(new_index)
        self._populate_marks()

        def _refresh_after_switch():
            self._worker.send("refresh")
        def _load_after_switch():
            self._worker.send("load_fish")
        def _retry_refresh():
            self._worker.send("refresh")
            self._on_log("Retry refresh after wallet switch")
        QTimer.singleShot(1200, _refresh_after_switch)
        QTimer.singleShot(2500, _load_after_switch)
        QTimer.singleShot(5000, _retry_refresh)
        self._on_log(f"Switched to wallet #{new_index + 1}")

    def _redraw_dashboard(self):
        if hasattr(self, "lbl_wallet_balance"):
            self.lbl_wallet_balance.setText("Balance: —")
        self.lbl_name.setText("—")
        self.lbl_sol_value.setText("—")
        self.lbl_share.setText("—")
        self.lbl_fish_id.setText("—")
        self.lbl_total_shares.setText("—")
        self.lbl_balance.setText("—")
        self.lbl_storm.setText("—")
        self.lbl_fish_count.setText("—")
        self.lbl_feed_deadline.setText("—")
        self.lbl_feed_countdown.setText("—")
        self.lbl_feed_cost.setText("—")
        self.lbl_feed_pct.setText("")
        self.lbl_hunt_cd.setText("—")
        self.combo_my_fish.clear()
        self.combo_my_fish.addItem("— no fish —", None)
        self.fish_table.setRowCount(0)
        self.lbl_fish_stats.setText("Load All Fish to see list.")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        header = QHBoxLayout()
        self.wallet_header_widget = QWidget()
        wh = QHBoxLayout(self.wallet_header_widget)
        wh.setContentsMargins(0, 0, 0, 0)
        wh.addWidget(QLabel("Wallet:"))
        self.combo_wallet = QComboBox()
        self.combo_wallet.setMinimumWidth(200)
        for i, _ in enumerate(self._wallets):
            pub = pubkey_from_keypair(self._wallets[i])
            short = f"{pub[:6]}...{pub[-4:]}" if len(pub) > 12 else pub
            self.combo_wallet.addItem(f"#{i+1} {short}", i)
        self.combo_wallet.setCurrentIndex(self._active_wallet_index)
        self.combo_wallet.currentIndexChanged.connect(self._on_wallet_selected)
        wh.addWidget(self.combo_wallet)
        self.wallet_header_widget.setVisible(len(self._wallets) > 1)
        header.addWidget(self.wallet_header_widget)
        header.addSpacing(12)
        self.lbl_my_fish = QLabel("My Fish:")
        header.addWidget(self.lbl_my_fish)
        self.combo_my_fish = QComboBox()
        self.combo_my_fish.setMinimumWidth(180)
        self.combo_my_fish.currentIndexChanged.connect(self._on_fish_selected)
        header.addWidget(self.combo_my_fish)
        header.addStretch()
        self.lbl_wallet_balance = QLabel("Balance: —")
        self.lbl_wallet_balance.setStyleSheet("color: #8b949e; font-size: 12px; padding: 4px 10px; background: #161b22; border-radius: 6px;")
        header.addWidget(self.lbl_wallet_balance)
        self.lbl_sol_price = QLabel("SOL —")
        self.lbl_sol_price.setStyleSheet("color: #8b949e; font-size: 12px; padding: 4px 10px; background: #161b22; border-radius: 6px;")
        header.addWidget(self.lbl_sol_price)
        self.btn_donate = QPushButton("☕ Donate")
        self.btn_donate.setStyleSheet("padding: 4px 10px; font-size: 12px; background: #238636; color: white; border-radius: 6px;")
        self.btn_donate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_donate.clicked.connect(self._show_donate_dialog)
        header.addWidget(self.btn_donate)
        root.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.tabs = QTabWidget()
        self._build_dashboard_tab()
        self._build_fishlist_tab()
        self._build_marks_tab()
        self._build_scheduler_tab()
        self._build_analytics_tab()
        self._build_settings_tab()
        splitter.addWidget(self.tabs)

        self._build_log_panel()
        splitter.addWidget(self.log_frame)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

    # ── Dashboard Tab ────────────────────────────────────────────────

    def _build_dashboard_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)

        c1, self.lbl_name = make_stat_card("Fish Name", "—")
        c2, self.lbl_sol_value = make_stat_card("SOL Value", "—")
        c3, self.lbl_share = make_stat_card("Share", "—")
        c4, self.lbl_fish_id = make_stat_card("Fish ID", "—")

        for card in [c1, c2, c3, c4]:
            card.setStyleSheet("background-color: #161b22; border-radius: 8px;")
            stats_row.addWidget(card)

        lay.addLayout(stats_row)

        ocean_row = QHBoxLayout()
        ocean_row.setSpacing(16)
        c5, self.lbl_total_shares = make_stat_card("Total Shares", "—")
        c6, self.lbl_balance = make_stat_card("Pool Balance", "—")
        c7, self.lbl_storm = make_stat_card("Storm", "—")
        c8, self.lbl_fish_count = make_stat_card("Fish Count", "—")

        for card in [c5, c6, c7, c8]:
            card.setStyleSheet("background-color: #161b22; border-radius: 8px;")
            ocean_row.addWidget(card)

        lay.addLayout(ocean_row)

        feed_info = QGroupBox("My Fish — Feeding")
        fi_lay = QGridLayout(feed_info)
        fi_lay.setSpacing(8)

        fi_lay.addWidget(QLabel("Next Feed Deadline:"), 0, 0)
        self.lbl_feed_deadline = QLabel("—")
        self.lbl_feed_deadline.setStyleSheet("font-size: 14px; font-weight: bold; color: #f0f6fc;")
        fi_lay.addWidget(self.lbl_feed_deadline, 0, 1)

        self.lbl_feed_countdown = QLabel("—")
        self.lbl_feed_countdown.setStyleSheet("font-size: 16px; font-weight: bold; color: #f85149;")
        fi_lay.addWidget(self.lbl_feed_countdown, 0, 2)

        fi_lay.addWidget(QLabel("Feed Cost:"), 1, 0)
        self.lbl_feed_cost = QLabel("—")
        self.lbl_feed_cost.setStyleSheet("font-size: 14px; font-weight: bold; color: #d29922;")
        fi_lay.addWidget(self.lbl_feed_cost, 1, 1)

        self.lbl_feed_pct = QLabel("")
        self.lbl_feed_pct.setStyleSheet("color: #8b949e; font-size: 12px;")
        fi_lay.addWidget(self.lbl_feed_pct, 1, 2)

        fi_lay.addWidget(QLabel("Hunt Cooldown:"), 2, 0)
        self.lbl_hunt_cd = QLabel("—")
        self.lbl_hunt_cd.setStyleSheet("font-size: 14px; font-weight: bold; color: #8b949e;")
        fi_lay.addWidget(self.lbl_hunt_cd, 2, 1)

        lay.addWidget(feed_info)

        create_group = QGroupBox("Create Fish")
        cg_lay = QGridLayout(create_group)
        cg_lay.setSpacing(8)
        cg_lay.addWidget(QLabel("Name:"), 0, 0)
        self.inp_create_name = QLineEdit()
        self.inp_create_name.setPlaceholderText("Fish name (e.g. dazay)")
        self.inp_create_name.setMaxLength(32)
        cg_lay.addWidget(self.inp_create_name, 0, 1)
        cg_lay.addWidget(QLabel("Deposit (SOL):"), 1, 0)
        self.inp_create_deposit = QDoubleSpinBox()
        self.inp_create_deposit.setRange(0.01, 1000.0)
        self.inp_create_deposit.setValue(0.1)
        self.inp_create_deposit.setDecimals(4)
        self.inp_create_deposit.setSingleStep(0.05)
        cg_lay.addWidget(self.inp_create_deposit, 1, 1)
        self.btn_create_fish = QPushButton("Create Fish")
        self.btn_create_fish.setObjectName("blueBtn")
        self.btn_create_fish.setToolTip("Создать новую рыбу. Депозит — начальный баланс в SOL.")
        self.btn_create_fish.clicked.connect(self._do_create_fish)
        cg_lay.addWidget(self.btn_create_fish, 1, 2)
        cg_hint = QLabel("Имя как на веб — без лишних ограничений. 6003 = занято.")
        cg_hint.setStyleSheet("color: #6e7681; font-size: 11px;")
        cg_hint.setWordWrap(True)
        cg_lay.addWidget(cg_hint, 2, 1)
        lay.addWidget(create_group)

        actions_group = QGroupBox("Actions")
        actions_lay = QGridLayout(actions_group)
        actions_lay.setSpacing(10)

        actions_lay.addWidget(QLabel("Feed Amount (SOL):"), 0, 0)
        self.inp_feed = QDoubleSpinBox()
        self.inp_feed.setRange(0.01, 100.0)
        self.inp_feed.setValue(0.05)
        self.inp_feed.setDecimals(4)
        self.inp_feed.setSingleStep(0.01)
        actions_lay.addWidget(self.inp_feed, 0, 1)

        self.btn_feed = QPushButton("Feed Fish")
        self.btn_feed.setObjectName("greenBtn")
        self.btn_feed.setToolTip("Прокормить рыбу (см. Feed Cost в блоке выше)")
        self.btn_feed.clicked.connect(self._do_feed)
        actions_lay.addWidget(self.btn_feed, 0, 2)

        self.btn_feed_schedule = QPushButton("Feed Schedule")
        self.btn_feed_schedule.setObjectName("blueBtn")
        self.btn_feed_schedule.setToolTip("Добавить кормёжку в очередь на выбранное время")
        self.btn_feed_schedule.clicked.connect(self._do_feed_schedule)
        actions_lay.addWidget(self.btn_feed_schedule, 0, 3)

        self.btn_exit = QPushButton("Exit Game")
        self.btn_exit.setObjectName("redBtn")
        self.btn_exit.clicked.connect(self._do_exit_game)
        actions_lay.addWidget(self.btn_exit, 0, 4)

        actions_lay.addWidget(QLabel("Transfer to Wallet:"), 1, 0)
        self.inp_transfer = QLineEdit()
        self.inp_transfer.setPlaceholderText("Recipient wallet address")
        actions_lay.addWidget(self.inp_transfer, 1, 1, 1, 2)

        self.btn_transfer = QPushButton("Transfer")
        self.btn_transfer.setObjectName("blueBtn")
        self.btn_transfer.clicked.connect(self._do_transfer)
        actions_lay.addWidget(self.btn_transfer, 1, 3)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setToolTip("Обновить данные рыбы и океана")
        self.btn_refresh.clicked.connect(self._do_refresh)
        actions_lay.addWidget(self.btn_refresh, 2, 4)

        lay.addWidget(actions_group)
        lay.addStretch()
        self.tabs.addTab(tab, "🏠 Dashboard")

    # ── Fish List Tab ────────────────────────────────────────────────

    def _build_fishlist_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        filters = QHBoxLayout()
        filters.setSpacing(10)

        filters.addWidget(QLabel("Min SOL:"))
        self.fl_min_sol = QDoubleSpinBox()
        self.fl_min_sol.setRange(0, 1000)
        self.fl_min_sol.setValue(0.25)
        self.fl_min_sol.setDecimals(3)
        self.fl_min_sol.setSingleStep(0.05)
        filters.addWidget(self.fl_min_sol)

        self.fl_markable = QCheckBox("Only lighter than me")
        self.fl_markable.setChecked(False)
        filters.addWidget(self.fl_markable)

        self.fl_not_marked = QCheckBox("Not marked")
        self.fl_not_marked.setChecked(False)
        filters.addWidget(self.fl_not_marked)

        filters.addWidget(QLabel("Search:"))
        self.fl_search = QLineEdit()
        self.fl_search.setPlaceholderText("Fish name...")
        self.fl_search.setMaximumWidth(200)
        filters.addWidget(self.fl_search)

        self.btn_load_fish = QPushButton("Load All Fish")
        self.btn_load_fish.setObjectName("blueBtn")
        self.btn_load_fish.setToolTip("Загрузить список всех рыб из блокчейна")
        self.btn_load_fish.clicked.connect(self._do_load_fish)
        filters.addWidget(self.btn_load_fish)

        self.btn_apply_filter = QPushButton("Apply Filter")
        self.btn_apply_filter.clicked.connect(self._apply_fish_filter)
        filters.addWidget(self.btn_apply_filter)

        filters.addStretch()
        lay.addLayout(filters)

        self.fish_table = QTableWidget()
        self.fish_table.setColumnCount(7)
        self.fish_table.setHorizontalHeaderLabels([
            "Name", "SOL Value", "Share", "Owner", "Last Fed", "Prey Time", "Marked"
        ])
        self.fish_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.fish_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.fish_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.fish_table.setSortingEnabled(True)
        self.fish_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fish_table.customContextMenuRequested.connect(self._fish_context_menu)
        self.fish_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fish_table.doubleClicked.connect(self._open_fish_card)
        lay.addWidget(self.fish_table)

        self.lbl_fish_stats = QLabel("Нажмите «Load All Fish» для загрузки списка. ПКМ по строке — Mark / Hunt / Add to Queue.")
        self.lbl_fish_stats.setStyleSheet("color: #484f58; font-size: 12px;")
        self.lbl_fish_stats.setWordWrap(True)
        lay.addWidget(self.lbl_fish_stats)

        self.tabs.addTab(tab, "🐟 Fish List")

    # ── My Marks Tab ───────────────────────────────────────────────

    def _build_marks_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        self.btn_refresh_marks = QPushButton("Refresh Marks")
        self.btn_refresh_marks.setObjectName("blueBtn")
        self.btn_refresh_marks.clicked.connect(self._do_refresh_marks)
        top.addWidget(self.btn_refresh_marks)

        self.lbl_marks_info = QLabel("Загрузка...")
        self.lbl_marks_info.setStyleSheet("color: #8b949e; font-size: 12px;")
        top.addWidget(self.lbl_marks_info)
        top.addStretch()
        lay.addLayout(top)

        self.marks_table = QTableWidget()
        self.marks_table.setColumnCount(7)
        self.marks_table.setHorizontalHeaderLabels([
            "Name", "SOL Value", "Owner", "Prey Time", "Hunt In", "Mark Expires", "Actions"
        ])
        self.marks_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.marks_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.marks_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.marks_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.marks_table.doubleClicked.connect(self._open_mark_card)
        lay.addWidget(self.marks_table)

        self.tabs.addTab(tab, "📍 My Marks")

    def _do_refresh_marks(self):
        if not self._all_fish:
            self._on_log("💡 Сначала загрузите рыб: Fish List → Load All Fish")
            return
        self._populate_marks()

    def _populate_marks(self):
        if not hasattr(self, "marks_table"):
            return
        my_ids = set()
        if self._my_fish_list:
            my_ids = {f["fish_id"] for f in self._my_fish_list if f.get("fish_id") is not None}
        if self._my_fish and self._my_fish.get("fish_id") is not None:
            my_ids.add(self._my_fish["fish_id"])
        if not my_ids:
            fishes = get_fishes(self._active_wallet_index)
            if fishes:
                my_ids = {f["fish_id"] for f in fishes if f.get("fish_id") is not None}
        if not my_ids:
            if hasattr(self, "lbl_marks_info"):
                self.lbl_marks_info.setText("Создай рыбу в Dashboard — метки от твоих рыб появятся здесь")
            self.marks_table.setRowCount(0)
            return
        now = int(time.time())
        feeding_period = self.sch_feed_days.value() * 86400

        marked = [f for f in self._all_fish if f.get("marked_by_hunter_id", 0) in my_ids]
        marked_ids = {(f["owner"], f["fish_id"]) for f in marked}
        for entry in self._hunter_marks_from_file:
            key = (entry.get("owner", ""), entry.get("fish_id", 0))
            if key in marked_ids:
                continue
            found = next((f for f in self._all_fish if f.get("owner") == entry.get("owner") and f.get("fish_id") == entry.get("fish_id")), None)
            if found:
                if found.get("marked_by_hunter_id", 0) in my_ids:
                    continue
                marked.append(found)
            else:
                marked.append({
                    "owner": entry.get("owner", ""),
                    "fish_id": entry.get("fish_id", 0),
                    "name": entry.get("name", "?"),
                    "share": entry.get("share", 0),
                    "last_fed_at": entry.get("last_fed_at", 0),
                    "mark_expires_at": 0,
                })
            marked_ids.add(key)
        self.marks_table.setRowCount(0)

        for f in marked:
            row = self.marks_table.rowCount()
            self.marks_table.insertRow(row)

            self.marks_table.setItem(row, 0, QTableWidgetItem(f["name"]))

            sol_val = f["share"] * self._share_price / 1e9 if self._share_price else 0
            self.marks_table.setItem(row, 1, QTableWidgetItem(self._fmt_sol_usd(sol_val)))

            owner_short = f["owner"][:8] + "..." + f["owner"][-4:]
            ow_item = QTableWidgetItem(owner_short)
            ow_item.setToolTip(f["owner"])
            self.marks_table.setItem(row, 2, ow_item)

            prey_time = f["last_fed_at"] + feeding_period if f.get("last_fed_at") else 0
            prey_str = datetime.fromtimestamp(prey_time).strftime("%m-%d %H:%M") if prey_time > 0 else "—"
            self.marks_table.setItem(row, 3, QTableWidgetItem(prey_str))

            hunt_rem = prey_time - now if prey_time > 0 else -1
            if hunt_rem > 0:
                hunt_item = QTableWidgetItem(fmt_delta(hunt_rem))
                hunt_item.setForeground(QColor("#d29922"))
            else:
                hunt_item = QTableWidgetItem("READY")
                hunt_item.setForeground(QColor("#3fb950"))
            self.marks_table.setItem(row, 4, hunt_item)

            if f["mark_expires_at"] > 0:
                exp_rem = f["mark_expires_at"] - now
                if exp_rem > 0:
                    exp_item = QTableWidgetItem(fmt_delta(exp_rem))
                    exp_item.setForeground(QColor("#8b949e"))
                else:
                    exp_item = QTableWidgetItem("EXPIRED")
                    exp_item.setForeground(QColor("#f85149"))
            else:
                exp_item = QTableWidgetItem("—")
            self.marks_table.setItem(row, 5, exp_item)

            btn_hunt = QPushButton("Hunt")
            btn_hunt.setObjectName("greenBtn")
            btn_hunt.setEnabled(hunt_rem <= 0)
            btn_hunt.clicked.connect(partial(
                self._do_hunt_marked, f["owner"], f["fish_id"], f["name"], f["share"]
            ))
            self.marks_table.setCellWidget(row, 6, btn_hunt)

        self.lbl_marks_info.setText(f"{len(marked)} fish marked by you" if marked else "0 fish marked by you")
        self._marked_fish = marked

    def _do_hunt_marked(self, owner, fish_id, name, share):
        self._worker.send("hunt_fish", wallet=owner, fish_id=fish_id, name=name, share=share, hunter_fish_id=self._my_fish["fish_id"] if self._my_fish else None)

    def _open_mark_card(self, index):
        row = index.row()
        name_item = self.marks_table.item(row, 0)
        if not name_item:
            return
        name = name_item.text()
        fish = next((f for f in self._all_fish if f["name"] == name), None)
        if not fish:
            return
        dlg = FishCardDialog(
            fish, self._share_price,
            feeding_period=self.sch_feed_days.value() * 86400,
            mark_window=self.sch_mark_hours.value() * 3600,
            is_storm=self._is_storm,
            parent=self,
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()

    # ── Scheduler Tab ────────────────────────────────────────────────

    def _build_scheduler_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        params = QHBoxLayout()
        params.setSpacing(12)

        params.addWidget(QLabel("Count:"))
        self.sch_count = QSpinBox()
        self.sch_count.setRange(1, 10)
        self.sch_count.setValue(4)
        params.addWidget(self.sch_count)

        params.addWidget(QLabel("Min SOL:"))
        self.sch_min_sol = QDoubleSpinBox()
        self.sch_min_sol.setRange(0, 1000)
        self.sch_min_sol.setValue(0.25)
        self.sch_min_sol.setDecimals(3)
        params.addWidget(self.sch_min_sol)

        params.addWidget(QLabel("Feed Period (days):"))
        self.sch_feed_days = QSpinBox()
        self.sch_feed_days.setRange(1, 30)
        self.sch_feed_days.setValue(7)
        params.addWidget(self.sch_feed_days)

        params.addWidget(QLabel("Mark Window (hours):"))
        self.sch_mark_hours = QSpinBox()
        self.sch_mark_hours.setRange(1, 72)
        self.sch_mark_hours.setValue(24)
        params.addWidget(self.sch_mark_hours)

        params.addStretch()
        lay.addLayout(params)

        btns = QHBoxLayout()
        self.btn_start_sched = QPushButton("Start Scheduler")
        self.btn_start_sched.setObjectName("greenBtn")
        self.btn_start_sched.setToolTip("Нужна хотя бы одна рыба (Dashboard → Create Fish)")
        self.btn_start_sched.clicked.connect(self._do_start_schedule)
        btns.addWidget(self.btn_start_sched)

        self.btn_stop_sched = QPushButton("Stop")
        self.btn_stop_sched.setObjectName("redBtn")
        self.btn_stop_sched.setEnabled(False)
        self.btn_stop_sched.clicked.connect(self._do_stop_schedule)
        btns.addWidget(self.btn_stop_sched)

        self.btn_run_queue = QPushButton("Retry Failed")
        self.btn_run_queue.setObjectName("blueBtn")
        # Run queue button now retries FAILED tasks
        self.btn_run_queue.setToolTip("Restart tasks that failed or expired")
        self.btn_run_queue.clicked.connect(self._do_run_queue)
        btns.addWidget(self.btn_run_queue)

        self.btn_clear_queue = QPushButton("Clear")
        self.btn_clear_queue.clicked.connect(self._do_clear_queue)
        btns.addWidget(self.btn_clear_queue)

        btns.addStretch()
        lay.addLayout(btns)

        self.sched_table = QTableWidget()
        self.sched_table.setColumnCount(9)
        self.sched_table.setHorizontalHeaderLabels([
            "Wallet", "Name", "Fish ID", "SOL Value", "Type", "Prey Time", "Fire In", "Status", "Signature"
        ])
        self.sched_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sched_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sched_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sched_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sched_table.customContextMenuRequested.connect(self._sched_context_menu)
        self.sched_table.doubleClicked.connect(self._open_sched_card)
        lay.addWidget(self.sched_table)

        self.lbl_sched_hint = QLabel("💡 Сначала создай рыбу в Dashboard (Create Fish) — Scheduler ставит метки и охотится от её имени")
        self.lbl_sched_hint.setStyleSheet("color: #6e7681; font-size: 12px; padding: 8px 0;")
        self.lbl_sched_hint.setWordWrap(True)
        lay.addWidget(self.lbl_sched_hint)

        self.tabs.addTab(tab, "⏱ Scheduler")

    # ── Analytics Tab ───────────────────────────────────────────────────

    def _build_analytics_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Live Activity")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #f0f6fc;")
        subtitle = QLabel("Транзакции HodlHunt в реальном времени")
        subtitle.setStyleSheet("color: #8b949e; font-size: 12px;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addSpacing(16)
        self.lbl_activity_status = QLabel("Connecting..." if HAS_WEBSOCKETS else "WebSocket not available (pip install websockets)")
        self.lbl_activity_status.setStyleSheet("color: #8b949e; font-size: 12px; padding: 4px 10px; background: #161b22; border-radius: 6px;")
        header.addWidget(self.lbl_activity_status)
        header.addStretch()
        btn_clear = QPushButton("Clear")
        btn_clear.setMaximumWidth(70)
        btn_clear.setToolTip("Очистить ленту активности")
        btn_clear.clicked.connect(self._clear_activity)
        header.addWidget(btn_clear)
        lay.addLayout(header)

        self.activity_container = QWidget()
        self.activity_layout = QVBoxLayout(self.activity_container)
        self.activity_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_layout.setSpacing(6)

        self.activity_empty = QLabel(
            "Ожидание активности в сети…\n\n"
            "Транзакции HodlHunt (кормление, охота, метки) будут появляться здесь в реальном времени.\n"
            "Клик по карточке откроет транзакцию в Solscan."
        )
        self.activity_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.activity_empty.setStyleSheet(
            "color: #484f58; font-size: 14px; padding: 40px 20px; line-height: 1.6;"
        )
        self.activity_layout.addWidget(self.activity_empty)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.activity_container)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(scroll)

        self.tabs.addTab(tab, "📊 Analytics")

    def _clear_activity(self):
        self._activity_list.clear()
        for i in reversed(range(self.activity_layout.count())):
            w = self.activity_layout.itemAt(i).widget()
            if w and w != self.activity_empty:
                w.deleteLater()
        self.activity_empty.show()

    def _on_activity(self, act: dict):
        if hasattr(self, "lbl_activity_status") and "Connecting" in self.lbl_activity_status.text():
            self.lbl_activity_status.setText("Live")
            self.lbl_activity_status.setStyleSheet("color: #3fb950; font-size: 12px;")
        self._activity_list.insert(0, act)
        while len(self._activity_list) > 200:
            self._activity_list.pop()
        self._append_activity_card(act)

    def _append_activity_card(self, act: dict):
        self.activity_empty.hide()
        sig = act.get("signature", "")[:16] + "…" if len(act.get("signature", "")) > 16 else act.get("signature", "")
        action = act.get("action", "unknown")
        success = act.get("success", True)
        t = act.get("time", "")

        icons = {
            "feed_fish": ("🐟", "#3fb950"),
            "hunt_fish": ("🦈", "#f85149"),
            "place_hunting_mark": ("📍", "#d29922"),
            "create_fish": ("✨", "#58a6ff"),
            "exit_game": ("🚪", "#8b949e"),
            "transfer_fish": ("↔", "#a371f7"),
            "resurrect_fish": ("💀", "#58a6ff"),
        }
        icon, color = icons.get(action, ("•", "#8b949e"))

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 10px;
            }}
            QFrame:hover {{ border-color: #58a6ff; background: #1c2128; }}
        """)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setToolTip("Click to open transaction in Solscan")
        card_lay = QHBoxLayout(card)
        card_lay.setContentsMargins(12, 8, 12, 8)
        card_lay.setSpacing(12)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"font-size: 24px; color: {color};")
        icon_lbl.setFixedWidth(36)
        card_lay.addWidget(icon_lbl)

        info = QVBoxLayout()
        info.setSpacing(2)
        act_lbl = QLabel(action.replace("_", " ").upper())
        act_lbl.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color};")
        info.addWidget(act_lbl)
        sig_lbl = QLabel(sig)
        sig_lbl.setStyleSheet("font-size: 11px; color: #8b949e; font-family: monospace;")
        sig_lbl.setToolTip(act.get("signature", ""))
        info.addWidget(sig_lbl)
        card_lay.addLayout(info)

        status_box = QVBoxLayout()
        status_box.setSpacing(0)
        status = QLabel("✓ Success" if success else "✗ Failed")
        status.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {'#3fb950' if success else '#f85149'};")
        status_box.addWidget(status)
        card_lay.addLayout(status_box)

        time_lbl = QLabel(t)
        time_lbl.setStyleSheet("font-size: 12px; color: #484f58;")
        card_lay.addWidget(time_lbl)

        def open_solscan():
            sig_full = act.get("signature", "")
            if sig_full:
                os.system(f"xdg-open 'https://solscan.io/tx/{sig_full}' 2>/dev/null &")

        card.mousePressEvent = lambda e: open_solscan() if e.button() == Qt.MouseButton.LeftButton else None

        self.activity_layout.insertWidget(0, card)

    # ── Settings Tab ──────────────────────────────────────────────────

    def _build_settings_tab(self):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(20)

        # -- RPC + TX --
        conn_group = QGroupBox("RPC & Transaction")
        conn_group.setStyleSheet(SETTINGS_GROUP)
        cl = QGridLayout(conn_group)
        cl.setSpacing(12)

        cl.addWidget(QLabel("RPC URL"), 0, 0)
        self.set_rpc_url = QLineEdit(self._worker._rpc_url)
        self.set_rpc_url.setPlaceholderText("https://api.mainnet-beta.solana.com")
        self.set_rpc_url.setMinimumWidth(320)
        cl.addWidget(self.set_rpc_url, 0, 1)

        cl.addWidget(QLabel("Compute Unit Limit"), 1, 0)
        self.set_cu_limit = QSpinBox()
        self.set_cu_limit.setRange(50_000, 1_400_000)
        self.set_cu_limit.setSingleStep(50_000)
        self.set_cu_limit.setValue(200_000)
        self.set_cu_limit.setMinimumWidth(120)
        cl.addWidget(self.set_cu_limit, 1, 1)

        cl.addWidget(QLabel("Priority Fee"), 2, 0)
        self.set_cu_price = QSpinBox()
        self.set_cu_price.setRange(0, 10_000_000)
        self.set_cu_price.setSingleStep(50_000)
        self.set_cu_price.setValue(375_000)
        self.set_cu_price.setMinimumWidth(120)
        cl.addWidget(self.set_cu_price, 2, 1)

        rpc_hint = QLabel("RPC требует restart. Priority fee — чем выше, тем быстрее включение.")
        rpc_hint.setStyleSheet("color: #6e7681; font-size: 11px;")
        rpc_hint.setWordWrap(True)
        cl.addWidget(rpc_hint, 3, 1)

        lay.addWidget(conn_group)

        # -- Wallet --
        wallet_group = QGroupBox("Wallet")
        wallet_group.setStyleSheet(SETTINGS_GROUP)
        wl = QGridLayout(wallet_group)
        wl.setSpacing(12)
        wl.addWidget(QLabel("Active wallet"), 0, 0)
        self.combo_settings_wallet = QComboBox()
        self.combo_settings_wallet.setMinimumWidth(280)
        self._populate_wallet_combo()
        self.combo_settings_wallet.currentIndexChanged.connect(self._on_settings_wallet_changed)
        wl.addWidget(self.combo_settings_wallet, 0, 1)
        wl.addWidget(QLabel("Private keys (base58)"), 1, 0)
        self.wallet_keys_edit = QTextEdit()
        self.wallet_keys_edit.setPlaceholderText("One key per line, up to 20 wallets")
        self.wallet_keys_edit.setMaximumHeight(120)
        self.wallet_keys_edit.setMinimumWidth(320)
        wl.addWidget(self.wallet_keys_edit, 1, 1)
        btn_apply_wallets = QPushButton("Apply")
        btn_apply_wallets.clicked.connect(self._apply_wallets)
        wl.addWidget(btn_apply_wallets, 2, 1)
        lay.addWidget(wallet_group)

        # -- Scheduler + Automation --
        sched_group = QGroupBox("Scheduler")
        sched_group.setStyleSheet(SETTINGS_GROUP)
        sg = QGridLayout(sched_group)
        sg.setSpacing(12)

        sg.addWidget(QLabel("Feed Period (days)"), 0, 0)
        self.set_feed_period = QSpinBox()
        self.set_feed_period.setRange(1, 30)
        self.set_feed_period.setValue(7)
        sg.addWidget(self.set_feed_period, 0, 1)

        sg.addWidget(QLabel("Mark Window (hours)"), 1, 0)
        self.set_mark_window = QSpinBox()
        self.set_mark_window.setRange(1, 72)
        self.set_mark_window.setValue(24)
        sg.addWidget(self.set_mark_window, 1, 1)

        sg.addWidget(QLabel("Min SOL"), 2, 0)
        self.set_min_sol = QDoubleSpinBox()
        self.set_min_sol.setRange(0, 1000)
        self.set_min_sol.setDecimals(3)
        self.set_min_sol.setValue(0.1)
        sg.addWidget(self.set_min_sol, 2, 1)

        sg.addWidget(QLabel("Max Targets"), 3, 0)
        self.set_max_targets = QSpinBox()
        self.set_max_targets.setRange(1, 20)
        self.set_max_targets.setValue(4)
        sg.addWidget(self.set_max_targets, 3, 1)

        sg.addWidget(QLabel("Auto-refresh (min)"), 4, 0)
        self.set_auto_refresh = QSpinBox()
        self.set_auto_refresh.setRange(0, 60)
        self.set_auto_refresh.setValue(0)
        self.set_auto_refresh.setSpecialValueText("Off")
        sg.addWidget(self.set_auto_refresh, 4, 1)

        lay.addWidget(sched_group)

        # -- Telegram --
        tg_group = QGroupBox("Telegram")
        tg_group.setStyleSheet(SETTINGS_GROUP)
        tg = QGridLayout(tg_group)
        tg.setSpacing(12)

        tg.addWidget(QLabel("Bot Token"), 0, 0)
        self.set_tg_token = QLineEdit()
        self.set_tg_token.setPlaceholderText("From @BotFather")
        self.set_tg_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.set_tg_token.setMinimumWidth(280)
        tg.addWidget(self.set_tg_token, 0, 1)

        self.tg_show_token = QCheckBox("Show")
        self.tg_show_token.toggled.connect(
            lambda on: self.set_tg_token.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        tg.addWidget(self.tg_show_token, 0, 2)

        tg.addWidget(QLabel("Chat ID"), 1, 0)
        self.set_tg_chat = QLineEdit()
        self.set_tg_chat.setPlaceholderText("From @userinfobot")
        self.set_tg_chat.setMinimumWidth(120)
        tg.addWidget(self.set_tg_chat, 1, 1)

        tg_hint = QLabel("Статусы транзакций в этот чат. Сначала напиши боту /start")
        tg_hint.setStyleSheet("color: #6e7681; font-size: 11px;")
        tg.addWidget(tg_hint, 2, 1)

        btn_tg_test = QPushButton("Test")
        btn_tg_test.setToolTip("Отправить тестовое сообщение в Telegram")
        btn_tg_test.clicked.connect(self._tg_test)
        tg.addWidget(btn_tg_test, 2, 2)

        lay.addWidget(tg_group)

        # -- Discord --
        dc_group = QGroupBox("Discord")
        dc_group.setStyleSheet(SETTINGS_GROUP)
        dc = QGridLayout(dc_group)
        dc.setSpacing(12)
        dc.addWidget(QLabel("Webhook URL"), 0, 0)
        self.set_discord_webhook = QLineEdit()
        self.set_discord_webhook.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.set_discord_webhook.setMinimumWidth(320)
        dc.addWidget(self.set_discord_webhook, 0, 1)
        dc_hint = QLabel("Уведомления в Discord-канал. Создай webhook в настройках канала")
        dc_hint.setStyleSheet("color: #6e7681; font-size: 11px;")
        dc.addWidget(dc_hint, 1, 1)
        btn_dc_test = QPushButton("Test")
        btn_dc_test.setToolTip("Отправить тестовое сообщение в Discord")
        btn_dc_test.clicked.connect(self._discord_test)
        dc.addWidget(btn_dc_test, 1, 2)
        lay.addWidget(dc_group)

        # -- Donate --
        don_group = QGroupBox("Donate")
        don_group.setStyleSheet(SETTINGS_GROUP)
        don_lay = QHBoxLayout(don_group)
        self.set_donate_enabled = QCheckBox("Donate")
        self.set_donate_enabled.setStyleSheet("""
            QCheckBox { color: #c9d1d9; spacing: 10px; }
            QCheckBox::indicator { width: 44px; height: 22px; border-radius: 11px; background: #21262d; border: 1px solid #30363d; }
            QCheckBox::indicator:checked { background: #238636; border-color: #2ea043; }
        """)
        self.set_donate_enabled.toggled.connect(self._on_donate_toggled)
        don_lay.addWidget(self.set_donate_enabled)
        don_hint = QLabel("Включить/выключить кнопку Donate (кнопка остаётся видимой)")
        don_hint.setStyleSheet("color: #6e7681; font-size: 11px;")
        don_lay.addWidget(don_hint)
        don_lay.addStretch()
        lay.addWidget(don_group)

        # -- Buttons --
        btn_row = QHBoxLayout()
        btn_apply = QPushButton("Apply")
        btn_apply.setObjectName("greenBtn")
        btn_apply.setMinimumWidth(100)
        btn_apply.clicked.connect(self._apply_settings)
        btn_row.addWidget(btn_apply)

        btn_save = QPushButton("Save to .env")
        btn_save.setObjectName("blueBtn")
        btn_save.setMinimumWidth(120)
        btn_save.clicked.connect(self._save_settings_env)
        btn_row.addWidget(btn_save)

        btn_row.addStretch()
        lay.addLayout(btn_row)

        lay.addStretch()
        scroll.setWidget(content)

        main_lay = QVBoxLayout(tab)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.addWidget(scroll)

        self.tabs.addTab(tab, "⚙ Settings")

    def _apply_settings(self):
        self._worker.send(
            "update_settings",
            cu_limit=self.set_cu_limit.value(),
            cu_price=self.set_cu_price.value(),
        )

        self.sch_feed_days.setValue(self.set_feed_period.value())
        self.sch_mark_hours.setValue(self.set_mark_window.value())
        self.sch_min_sol.setValue(self.set_min_sol.value())
        self.sch_count.setValue(self.set_max_targets.value())

        interval = self.set_auto_refresh.value()
        if interval > 0:
            if not hasattr(self, "_auto_timer"):
                self._auto_timer = QTimer(self)
                self._auto_timer.timeout.connect(self._auto_refresh_tick)
            self._auto_timer.start(interval * 60_000)
            self._on_log(f"Auto-refresh enabled: every {interval} min")
        else:
            if hasattr(self, "_auto_timer"):
                self._auto_timer.stop()
            self._on_log("Auto-refresh disabled")

        self._on_log(f"Settings applied: CU limit={self.set_cu_limit.value()}, "
                     f"priority fee={self.set_cu_price.value()}")

    def _auto_refresh_tick(self):
        self._worker.send("refresh")
        self._worker.send("load_fish")
        self._on_log("Auto-refresh triggered")

    def _tg_send(self, text: str):
        try:
            from notify import send_all
            token = self.set_tg_token.text().strip() or None
            chat = self.set_tg_chat.text().strip() or None
            webhook = self.set_discord_webhook.text().strip() or None
            send_all(text, tg_token=token, tg_chat=chat, discord_webhook=webhook)
        except ImportError:
            pass

    def _tg_test(self):
        token = self.set_tg_token.text().strip()
        chat = self.set_tg_chat.text().strip()
        if not token or not chat:
            self._on_log("Заполни Bot Token и Chat ID")
            return
        self._tg_send("✅ HodlHunt: тест уведомлений — всё работает!")
        self._on_log("Тестовое сообщение отправлено. Проверь Telegram.")

    def _on_donate_toggled(self, enabled: bool):
        """Включить/выключить Donate кнопку (не скрывать)."""
        if hasattr(self, "btn_donate"):
            self.btn_donate.setEnabled(enabled)

    def _discord_test(self):
        webhook = self.set_discord_webhook.text().strip()
        if not webhook or "discord.com/api/webhooks" not in webhook:
            self._on_log("Введи корректный Discord Webhook URL")
            return
        try:
            from notify import send_discord
            send_discord("✅ HodlHunt: тест уведомлений — всё работает!", webhook_url=webhook)
            self._on_log("Тестовое сообщение отправлено. Проверь Discord.")
        except Exception as e:
            self._on_log(f"Discord: {e}")

    def _on_fish_updated(self, fish: dict):
        for i, f in enumerate(self._all_fish):
            if f["owner"] == fish["owner"] and f["fish_id"] == fish["fish_id"]:
                self._all_fish[i] = fish
                break

    def _check_marks_via_api(self):
        """Каждые 30 сек: для меток, которые ещё не истекли, запрос API и сверка."""
        now = int(time.time())
        for f in self._marked_fish:
            mark_exp = f.get("mark_expires_at", 0) or 0
            if mark_exp <= 0 or mark_exp <= now:
                continue
            self._worker.send(
                "check_mark_api",
                fish_id=f["fish_id"],
                owner=f["owner"],
                name=f["name"],
            )

    def _on_mark_api_fetched(self, data: dict):
        """Обновить рыбу из API: last_fed_at, mark_expires_at. Если поела за 24ч — не триггерить bite."""
        now = int(time.time())
        fish_id = data.get("fish_id")
        owner = data.get("owner", "")
        name = data.get("name", "")
        last_fed_at = data.get("last_fed_at", 0)
        mark_expires_at = data.get("mark_expires_at", 0)
        fed_in_last_24h = data.get("fed_in_last_24h", False)
        k = (owner, fish_id)

        if k in self._pending_bite_after_api:
            self._pending_bite_after_api.discard(k)
            if not fed_in_last_24h:
                feeding_period = self.sch_feed_days.value() * 86400
                self._bite_check_pending.add(k)
                self._on_log(f"Bite priority: checking {name} (API: не ела 24ч)")
                self._worker.send(
                    "check_bite_window",
                    owner=owner,
                    fish_id=fish_id,
                    name=name,
                    last_fed_at=last_fed_at,
                    feeding_period=feeding_period,
                )

        for i, f in enumerate(self._all_fish):
            if f["owner"] == owner and f["fish_id"] == fish_id:
                f["last_fed_at"] = last_fed_at
                f["mark_expires_at"] = mark_expires_at
                if fed_in_last_24h:
                    self._bite_notified.discard((owner, fish_id))
                    self._bite_check_pending.discard((owner, fish_id))
                break

        for i, f in enumerate(self._marked_fish):
            if f["owner"] == owner and f["fish_id"] == fish_id:
                f["last_fed_at"] = last_fed_at
                f["mark_expires_at"] = mark_expires_at
                break

        if hasattr(self, "marks_table"):
            for row in range(self.marks_table.rowCount()):
                name_item = self.marks_table.item(row, 0)
                if name_item and name_item.text() == name:
                    feeding_period = self.sch_feed_days.value() * 86400
                    prey_time = last_fed_at + feeding_period
                    exp_rem = mark_expires_at - now if mark_expires_at > 0 else 0
                    if exp_rem > 0:
                        exp_item = self.marks_table.item(row, 5)
                        if exp_item:
                            exp_item.setText(fmt_delta(exp_rem))
                    break

    def _on_bite_check(self, name: str, owner: str, fish_id: int, was_fed: bool, sol_value: float, hunt_in_sec: int):
        k = (owner, fish_id)
        self._bite_check_pending.discard(k)
        if was_fed:
            self._on_log(f"Bite priority: {name} покормилась, таймер сброшен")
            file_logger.info(f"Bite check: {name} was fed, hunt_in={hunt_in_sec}s")
        else:
            self._bite_notified.add(k)
            msg = (
                f"🎯 <b>Bite priority</b> — {name} ({sol_value:.4f} SOL) READY, "
                f"mark expires soon — кусай!"
            )
            self._tg_send(msg)
            self._on_log(f"Bite priority: {name} READY, не покормилась — уведомление отправлено")
            file_logger.info(f"Bite priority notified: {name} {sol_value:.4f} SOL hunt_in={hunt_in_sec}s")

    def _on_tx_status(self, action: str, success: bool, label: str, sig: str):
        if success and action == "mark":
            self._hunter_marks_from_file = load_hunter_marks()
            if hasattr(self, "marks_table"):
                self._populate_marks()
        if success and action == "create_fish":
            if hasattr(self, "inp_create_name"):
                self.inp_create_name.clear()
            QTimer.singleShot(3000, lambda: self._worker.send("refresh"))
        if success and action == "donate":
            QTimer.singleShot(2000, lambda: self._worker.send("refresh"))
        if not hasattr(self, "set_tg_token"):
            return
        token = self.set_tg_token.text().strip()
        chat = self.set_tg_chat.text().strip()
        webhook = self.set_discord_webhook.text().strip() if hasattr(self, "set_discord_webhook") else ""
        if (not token or not chat) and "discord.com/api/webhooks" not in (webhook or ""):
            return
        if success:
            icon = "✅"
            link = f"https://solscan.io/tx/{sig}" if sig and len(sig) > 20 else ""
            text = f"{icon} <b>{label}</b>"
            if link:
                text += f"\n<a href=\"{link}\">Solscan</a>"
        else:
            from error_parser import format_queue_error_html, parse_tx_error
            if action in ("mark", "hunt", "feed", "create_fish", "transfer", "exit_game", "donate"):
                text = format_queue_error_html(action, label, sig or "Unknown error")
            else:
                parsed = parse_tx_error(sig) if sig else "❌ Ошибка"
                text = f"🔴 <b>{label}</b>\n\n{parsed}"
        self._tg_send(text)

    def _save_settings_env(self):
        env_path = os.path.join(BASE_DIR, ".env")
        lines = {}
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        lines[k.strip()] = v.strip()

        lines["HODL_RPC"] = self.set_rpc_url.text().strip()
        lines["HODL_CU_LIMIT"] = str(self.set_cu_limit.value())
        lines["HODL_CU_PRICE"] = str(self.set_cu_price.value())
        lines["HODL_FEED_PERIOD"] = str(self.set_feed_period.value())
        lines["HODL_MARK_WINDOW"] = str(self.set_mark_window.value())
        lines["HODL_MIN_SOL"] = str(self.set_min_sol.value())
        lines["HODL_MAX_TARGETS"] = str(self.set_max_targets.value())
        lines["HODL_AUTO_REFRESH"] = str(self.set_auto_refresh.value())
        lines["HODL_TG_TOKEN"] = self.set_tg_token.text().strip()
        lines["HODL_TG_CHAT"] = self.set_tg_chat.text().strip()
        lines["HODL_DISCORD_WEBHOOK"] = self.set_discord_webhook.text().strip()
        lines["HODL_DONATE_ENABLED"] = "1" if self.set_donate_enabled.isChecked() else "0"

        with open(env_path, "w") as f:
            for k, v in lines.items():
                f.write(f"{k}={v}\n")

        self._on_log(f"Settings saved to {env_path}")

    # ── Log Panel ────────────────────────────────────────────────────

    def _build_log_panel(self):
        self.log_frame = QFrame()
        log_lay = QVBoxLayout(self.log_frame)
        log_lay.setContentsMargins(0, 4, 0, 0)
        log_lay.setSpacing(2)

        header = QHBoxLayout()
        header.addWidget(QLabel("Transaction Log"))
        btn_clear = QPushButton("Clear")
        btn_clear.setMaximumWidth(60)
        btn_clear.clicked.connect(lambda: self.log_box.clear())
        header.addStretch()
        header.addWidget(btn_clear)
        log_lay.addLayout(header)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(200)
        log_lay.addWidget(self.log_box)

    def _on_sol_price(self, usd: float):
        self._sol_usd_price = usd
        if hasattr(self, "lbl_sol_price"):
            self.lbl_sol_price.setText(f"SOL ≈ ${usd:,.2f}" if usd > 0 else "SOL —")

    def _on_wallet_balance(self, lamports: int):
        sol_val = lamports / LAMPORTS_PER_SOL
        if hasattr(self, "lbl_wallet_balance"):
            if self._sol_usd_price > 0:
                txt = f"Balance: {sol_val:.4f} SOL (${sol_val * self._sol_usd_price:,.2f})"
            else:
                txt = f"Balance: {sol_val:.4f} SOL"
            self.lbl_wallet_balance.setText(txt)

    def _show_donate_dialog(self):
        env_path = os.path.join(BASE_DIR, ".env")
        addr = ""
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    if line.strip().startswith("HODL_DONATE_ADDRESS="):
                        addr = line.split("=", 1)[1].strip()
                        break
        if not addr:
            addr = "YOUR_SOLANA_ADDRESS_HERE"
        dlg = DonateDialog(addr, parent=self)
        dlg.exec()

    def _fmt_sol_usd(self, sol_val: float) -> str:
        if sol_val <= 0:
            return f"{sol_val:.4f} SOL"
        if self._sol_usd_price > 0:
            return f"{sol_val:.4f} SOL (${sol_val * self._sol_usd_price:,.2f})"
        return f"{sol_val:.4f} SOL"

    # ── Signals / Slots ──────────────────────────────────────────────

    def _on_log(self, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"<span style='color:#484f58'>[{ts}]</span> {text}")
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())
        file_logger.info(text)
        if "Activity feed connected" in text and hasattr(self, "lbl_activity_status"):
            self.lbl_activity_status.setText("Connected")
            self.lbl_activity_status.setStyleSheet("color: #3fb950; font-size: 12px;")

    def _on_error(self, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"<span style='color:#f85149'>[{ts}] ERROR: {text}</span>")
        file_logger.error(text)

    def _on_fish_selected(self, index: int):
        if index < 0 or index >= len(self._my_fish_list):
            return
        fish_id = self.combo_my_fish.currentData()
        if fish_id is None:
            return
        self._my_fish = next((f for f in self._my_fish_list if f["fish_id"] == fish_id), None)
        if self._my_fish:
            self._on_my_fish(self._my_fish)

    def _on_all_wallets_fish(self, fish_by_wallet: dict):
        """Кэш рыб по кошелькам (уже в storage). Подставляем для активного кошелька."""
        if not isinstance(fish_by_wallet, dict):
            return
        self._apply_wallet_fish(self._active_wallet_index)
        self._populate_marks()
        self._update_scheduler_buttons()

    def _apply_wallet_fish(self, wallet_index: int):
        """Подставить рыб из storage для кошелька."""
        self._my_fish_list = get_fishes(wallet_index)
        self._my_fish = self._my_fish_list[0] if self._my_fish_list else None
        if not hasattr(self, "combo_my_fish"):
            return
        self.combo_my_fish.blockSignals(True)
        self.combo_my_fish.clear()
        if not self._my_fish_list:
            self.combo_my_fish.addItem("— no fish —", None)
            QTimer.singleShot(600, lambda: self._worker.send("refresh"))
        for f in self._my_fish_list:
            share = f.get("share", 0)
            sol = share * self._share_price / 1e9 if self._share_price else 0
            name = f.get("name", "?")
            fid = f.get("fish_id")
            self.combo_my_fish.addItem(f"{name} ({sol:.2f} SOL)", fid)
        if self._my_fish and self._my_fish.get("fish_id") is not None:
            idx = self.combo_my_fish.findData(self._my_fish["fish_id"])
            self.combo_my_fish.setCurrentIndex(max(0, idx))
        self.combo_my_fish.blockSignals(False)
        if self._my_fish:
            self._on_my_fish(self._my_fish)
        self._update_scheduler_buttons()

    def _on_my_fish_list(self, fishes: list):
        from logic.storage import set_wallet_fish, get_fishes
        # Если refresh вернул пусто (RPC 429 и т.п.), не перезаписывать storage — использовать кэш
        if not fishes:
            cached = get_fishes(self._active_wallet_index)
            if cached:
                fishes = cached
        self._my_fish_list = fishes or []
        if fishes:
            set_wallet_fish(self._active_wallet_index, self._my_fish_list)
            # Синхронизировать _my_fish, чтобы Start Scheduler был активен
            if not self._my_fish or self._my_fish.get("fish_id") not in [f.get("fish_id") for f in fishes if f.get("fish_id") is not None]:
                self._my_fish = fishes[0]
        if not hasattr(self, "combo_my_fish"):
            return
        multi = len(self._my_fish_list) > 1 or len(self._wallets) > 1
        self.lbl_my_fish.setVisible(True)
        self.combo_my_fish.setVisible(True)
        self.combo_my_fish.blockSignals(True)
        self.combo_my_fish.clear()
        if not self._my_fish_list:
            self.combo_my_fish.addItem("— no fish —", None)
        for f in self._my_fish_list:
            sol = f["share"] * self._share_price / 1e9 if self._share_price else 0
            self.combo_my_fish.addItem(f"{f['name']} ({sol:.2f} SOL)", f["fish_id"])
        sel_id = self._my_fish["fish_id"] if self._my_fish else (self._my_fish_list[0]["fish_id"] if self._my_fish_list else None)
        if sel_id is not None:
            idx = self.combo_my_fish.findData(sel_id)
            self.combo_my_fish.setCurrentIndex(max(0, idx))
        self.combo_my_fish.blockSignals(False)
        self._update_scheduler_buttons()
        if self._all_fish:
            self._populate_marks()

    def _on_my_fish(self, fish: dict | None):
        self._my_fish = fish
        self._update_scheduler_buttons()
        if self._all_fish:
            self._populate_marks()
        if not fish:
            self.lbl_name.setText("Not found")
            return
        self.lbl_name.setText(fish["name"])
        self.lbl_share.setText(f'{fish["share"]:,}')
        self.lbl_fish_id.setText(str(fish["fish_id"]))
        if self._share_price > 0:
            sol_val = fish["share"] * self._share_price / 1e9
            self.lbl_sol_value.setText(self._fmt_sol_usd(sol_val))
            self._update_feed_info()

    def _on_ocean(self, ocean: dict | None):
        if not ocean:
            return
        vault_bal = ocean.get("vault_balance", ocean["balance_fishes"])
        if ocean["total_shares"] > 0:
            self._share_price = vault_bal / ocean["total_shares"]
        self._is_storm = ocean["is_storm"]
        self._feeding_pct = ocean.get("feeding_percentage", 500) / 10000

        self.lbl_total_shares.setText(f'{ocean["total_shares"]:,}')
        self.lbl_balance.setText(self._fmt_sol_usd(vault_bal / 1e9))
        self.lbl_storm.setText("STORM" if ocean["is_storm"] else "Calm")
        if ocean["is_storm"]:
            self.lbl_storm.setStyleSheet("color: #f85149; font-weight: bold; font-size: 20px;")
        else:
            self.lbl_storm.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 20px;")
        self.lbl_fish_count.setText(str(ocean["total_fish_count"]))

        if self._my_fish and self._share_price > 0:
            sol_val = self._my_fish["share"] * self._share_price / 1e9
            self.lbl_sol_value.setText(self._fmt_sol_usd(sol_val))
            self._update_feed_info()
        elif self._my_fish:
            self.lbl_name.setText(self._my_fish["name"])
            self.lbl_share.setText(f'{self._my_fish["share"]:,}')
            self.lbl_fish_id.setText(str(self._my_fish["fish_id"]))

        if not self._sched_cache_loaded and hasattr(self, "sched_table"):
            self._sched_cache_loaded = True
            self._load_sched_cache()

    def _update_feed_info(self):
        fish = self._my_fish
        if not fish or self._share_price <= 0:
            return
        feeding_period = self.sch_feed_days.value() * 86400
        sol_val = fish["share"] * self._share_price / 1e9
        feed_pct = getattr(self, "_feeding_pct", 0.05)
        feed_cost = sol_val * feed_pct
        prey_time = fish["last_fed_at"] + feeding_period

        self.lbl_feed_deadline.setText(datetime.fromtimestamp(prey_time).strftime("%Y-%m-%d %H:%M:%S"))
        self.lbl_feed_cost.setText(self._fmt_sol_usd(feed_cost))
        self.lbl_feed_pct.setText(f"({feed_pct*100:.0f}% of {sol_val:.4f} SOL)")

        now = int(time.time())
        cd_end = fish["can_hunt_after"]
        if cd_end > now:
            self.lbl_hunt_cd.setText(fmt_delta(cd_end - now))
            self.lbl_hunt_cd.setStyleSheet("font-size: 14px; font-weight: bold; color: #d29922;")
        else:
            self.lbl_hunt_cd.setText("Ready to hunt")
            self.lbl_hunt_cd.setStyleSheet("font-size: 14px; font-weight: bold; color: #3fb950;")

    def _on_all_fish(self, fish_list: list):
        self._all_fish = fish_list
        self._apply_fish_filter()
        self._populate_marks()

    def _on_schedule_item(self, target: dict):
        self._add_to_queue(target, target.get("_action", "mark"))

    def _add_to_queue(self, target: dict, action: str = "mark", wallet_index: int | None = None, fire_at: int | None = None):
        sol_val = target.get("_sol_value", target["share"] * self._share_price / 1e9 if self._share_price else 0)
        prey_time = target.get("_prey_time", target["last_fed_at"] + self.sch_feed_days.value() * 86400)
        now = int(time.time())
        if fire_at is not None and fire_at > 0:
            wait = max(0, fire_at - now)
        elif action == "feed":
            wait = target.get("_wait", max(0, target.get("_fire_at", 0) - now))
        else:
            wait = target.get("_wait", max(0, prey_time - self.sch_mark_hours.value() * 3600 - now))
        target["_action"] = action
        target["_sol_value"] = sol_val
        target["_prey_time"] = prey_time
        target["_wait"] = wait
        target["_fire_at"] = fire_at if (fire_at and fire_at > 0) else (now + wait)
        wi = wallet_index if wallet_index is not None else target.get("_wallet_index", self._active_wallet_index)
        target["_wallet_index"] = wi
        target["my_fish_id"] = self._my_fish["fish_id"] if self._my_fish else None
        target["_hunter_fish_name"] = self._my_fish["name"] if self._my_fish else None
        target["_wallet_pubkey"] = pubkey_from_keypair(self._wallets[wi]) if wi < len(self._wallets) else ""
        target["_status"] = "QUEUED"
        target["_sig"] = ""
        target["_qid"] = str(uuid.uuid4())
        self._schedule_targets.append(target)
        self._append_queued_transaction(target)
        self._rebuild_sched_table()
        self._save_sched_cache()
        self._worker.send("enqueue_item", qid=target["_qid"], target=target)

    def _rebuild_sched_table(self):
        """Rebuild scheduler table with wallet sections."""
        self.sched_table.setRowCount(0)
        self._sched_row_to_target.clear()
        self._sched_target_to_row.clear()
        if not self._schedule_targets:
            return
        sorted_targets = sorted(
            enumerate(self._schedule_targets),
            key=lambda x: (x[1].get("_fire_at", 0), x[1].get("_wallet_index", 0)),
        )
        prev_wi = -1
        now = int(time.time())
        for target_idx, t in sorted_targets:
            wi = t.get("_wallet_index", 0)
            if wi != prev_wi:
                row = self.sched_table.rowCount()
                self.sched_table.insertRow(row)
                wallet_short = f"#{wi+1}" if wi < len(self._wallets) else "?"
                if wi < len(self._wallets):
                    pub = pubkey_from_keypair(self._wallets[wi])
                    wallet_short = f"#{wi+1} {pub[:6]}...{pub[-4:]}" if len(pub) > 12 else f"#{wi+1}"
                sect = QTableWidgetItem(f"━━ Wallet {wallet_short} ━━")
                sect.setForeground(QColor("#58a6ff"))
                sect.setBackground(QColor("#161b22"))
                self.sched_table.setItem(row, 0, sect)
                self.sched_table.setSpan(row, 0, 1, 9)
                self._sched_row_to_target.append(-1)
                prev_wi = wi
            row = self.sched_table.rowCount()
            self.sched_table.insertRow(row)
            sol_val = t.get("_sol_value", 0)
            prey_time = t.get("_prey_time", 0)
            wait = t.get("_wait", max(0, t.get("_fire_at", 0) - now))
            action = t.get("_action", "mark")
            wallet_short = f"#{wi+1} {pubkey_from_keypair(self._wallets[wi])[:6]}.." if wi < len(self._wallets) else "?"
            self.sched_table.setItem(row, 0, QTableWidgetItem(wallet_short))
            self.sched_table.setItem(row, 1, QTableWidgetItem(t["name"]))
            self.sched_table.setItem(row, 2, QTableWidgetItem(str(t.get("fish_id", "—"))))
            self.sched_table.setItem(row, 3, QTableWidgetItem(self._fmt_sol_usd(sol_val)))
            type_item = QTableWidgetItem(action.upper())
            type_item.setForeground(QColor("#58a6ff" if action == "mark" else "#3fb950" if action == "feed" else "#f85149"))
            self.sched_table.setItem(row, 4, type_item)
            self.sched_table.setItem(row, 5, QTableWidgetItem(datetime.fromtimestamp(prey_time).strftime("%m-%d %H:%M")))
            self.sched_table.setItem(row, 6, QTableWidgetItem(fmt_delta(max(0, wait))))
            status = t.get("_status", "QUEUED")
            status_colors = {"QUEUED": "#d29922", "SENDING": "#58a6ff", "DONE": "#3fb950", "FAILED": "#f85149", "WAITING": "#d29922"}
            status_item = QTableWidgetItem(status)
            status_item.setForeground(QColor(status_colors.get(status, "#c9d1d9")))
            self.sched_table.setItem(row, 7, status_item)
            self.sched_table.setItem(row, 8, QTableWidgetItem(t.get("_sig", "")))
            self._sched_row_to_target.append(target_idx)
            self._sched_target_to_row[target_idx] = row

    def _append_queued_transaction(self, target: dict):
        """Append planned transaction to schedule.transactions when adding to queue (time:tx format)."""
        try:
            ts = int(time.time())
            fire_at = target.get("_fire_at", 0)
            name = target.get("name", "")
            action = target.get("_action", "mark")
            wallet = target.get("_wallet_pubkey", "")
            my_fish_id = target.get("my_fish_id", "")
            hunter = target.get("_hunter_fish_name", "")
            line = f"{ts}:{fire_at}\t{name}\t{action}\t{wallet}\t{my_fish_id}\t{hunter}"
            with open(SCHEDULE_TRANSACTIONS_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            file_logger.warning(f"Failed to append queued transaction: {e}")

    def _load_transactions(self):
        """Load schedule.transactions on startup into _transaction_history."""
        if not os.path.exists(SCHEDULE_TRANSACTIONS_PATH):
            try:
                open(SCHEDULE_TRANSACTIONS_PATH, "a").close()
            except Exception:
                pass
            return
        try:
            with open(SCHEDULE_TRANSACTIONS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("\t")
                    ts_fire = parts[0]
                    if ":" in ts_fire:
                        a, b = ts_fire.split(":", 1)
                        try:
                            ts = int(a)
                            fire_at = int(b) if b.isdigit() else 0
                        except ValueError:
                            continue
                        rec = {"timestamp": ts, "fire_at": fire_at}
                        if len(parts) >= 6:
                            rec["target_name"] = parts[1]
                            rec["action"] = parts[2]
                            rec["wallet_pubkey"] = parts[3]
                            rec["my_fish_id"] = int(parts[4]) if parts[4] and str(parts[4]).isdigit() else None
                            rec["hunter_fish_name"] = parts[5]
                        self._transaction_history.append(rec)
        except Exception as e:
            file_logger.warning(f"Failed to load transactions: {e}")

    def _save_sched_cache(self):
        def make_entry(target_idx, t):
            status = t.get("_status", "QUEUED")
            if status not in ("WAITING", "QUEUED", "SENDING", ""):
                return None
            entry = {
                "owner": t["owner"], "fish_id": t["fish_id"], "name": t["name"], "share": t["share"],
                "last_fed_at": t["last_fed_at"], "_action": t.get("_action", "mark"),
                "_prey_time": t.get("_prey_time"), "_sol_value": t.get("_sol_value", 0),
                "_fire_at": t.get("_fire_at", 0), "_wallet_index": t.get("_wallet_index", 0),
                "_amount": t.get("_amount", 0), "my_fish_id": t.get("my_fish_id"),
                "_hunter_fish_name": t.get("_hunter_fish_name"),
                "_wallet_pubkey": t.get("_wallet_pubkey") or "",
            }
            for k in ("created_at", "last_hunt_at", "can_hunt_after", "is_protected", "total_hunts",
                      "total_hunt_income", "hunting_marks_placed", "marked_by_hunter_id",
                      "mark_placed_at", "mark_expires_at", "mark_cost"):
                if k in t:
                    entry[k] = t[k]
            return entry

        by_wallet: dict[int, list] = {}
        for target_idx, t in enumerate(self._schedule_targets):
            entry = make_entry(target_idx, t)
            if entry:
                wi = entry.get("_wallet_index", 0)
                by_wallet.setdefault(wi, []).append(entry)
        for wi, path in all_sched_cache_paths(len(self._wallets)):
            pending = by_wallet.get(wi, [])
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(pending, f, indent=2, ensure_ascii=False)
            except Exception as e:
                file_logger.warning(f"Sched cache save [{wi}]: {e}")

    def _load_sched_cache(self):
        if not self._transactions_loaded:
            self._transactions_loaded = True
            self._load_transactions()
        self._hunter_marks_from_file = load_hunter_marks()
        legacy = os.path.join(BASE_DIR, "scheduler_cache.json")
        paths = all_sched_cache_paths(len(self._wallets))
        if not any(os.path.exists(p) for _, p in paths) and os.path.exists(legacy):
            try:
                import shutil
                shutil.copy(legacy, paths[0][1])
            except Exception:
                pass
        self._schedule_targets.clear()
        now = int(time.time())
        loaded = 0
        to_add: list[dict] = []
        for wi, path in paths:
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    pending = json.load(f)
            except Exception as e:
                file_logger.warning(f"Sched cache load [{wi}]: {e}")
                continue
            for entry in pending:
                fire_at = entry.get("_fire_at", 0)
                wait = max(0, fire_at - now)
                t = dict(entry)
                t["_wait"] = wait
                t.setdefault("created_at", 0)
                t.setdefault("last_hunt_at", 0)
                t.setdefault("can_hunt_after", 0)
                t.setdefault("is_protected", False)
                t.setdefault("total_hunts", 0)
                t.setdefault("total_hunt_income", 0)
                t.setdefault("hunting_marks_placed", 0)
                t.setdefault("marked_by_hunter_id", 0)
                t.setdefault("mark_placed_at", 0)
                t.setdefault("mark_expires_at", 0)
                t.setdefault("mark_cost", 0)
                t.setdefault("_amount", 0)
                t["_wallet_index"] = t.get("_wallet_index", wi)
                t["_qid"] = str(uuid.uuid4())
                t.setdefault("_hunter_fish_name", None)
                if not t.get("_wallet_pubkey") and wi < len(self._wallets):
                    t["_wallet_pubkey"] = pubkey_from_keypair(self._wallets[wi])
                if not t.get("_hunter_fish_name") and t.get("my_fish_id") is not None:
                    hf = get_fish_by_id(wi, t["my_fish_id"])
                    t["_hunter_fish_name"] = hf["name"] if hf else f"Fish #{t['my_fish_id']}"
                if 0 < fire_at < now:
                    t["_status"] = "FAILED"
                    t["_sig"] = "Expired while closed"
                else:
                    t.setdefault("_status", "QUEUED")
                    t.setdefault("_sig", "")
                to_add.append(t)
                loaded += 1
                if loaded % 20 == 0:
                    QApplication.processEvents()
        to_add.sort(key=lambda x: x.get("_fire_at", 0))
        for t in to_add:
            if t.get("my_fish_id") is None and self._my_fish and t.get("_wallet_index") == self._active_wallet_index:
                t["my_fish_id"] = self._my_fish["fish_id"]
            self._schedule_targets.append(t)
            # Не кидать в очередь при загрузке — только отобразить. Юзер сам нажмёт Retry/Run Queue.
        if to_add:
            self._rebuild_sched_table()
        if loaded:
            self._on_log(f"Loaded {loaded} pending targets from cache (all wallets)")

    def _sched_context_menu(self, pos):
        row = self.sched_table.indexAt(pos).row()
        if row < 0 or row >= len(self._sched_row_to_target):
            return
        target_idx = self._sched_row_to_target[row]
        if target_idx < 0:
            return
        menu = QMenu(self)
        act = QAction("Remove from queue", self)
        act.triggered.connect(lambda: self._remove_sched_row(target_idx))
        menu.addAction(act)
        act_boost = QAction("Update Priority Fee", self)
        act_boost.setToolTip("Увеличить комиссию для быстрого включения. Берёт HODL_CU_PRICE_BOOST из .env или удваивает текущий fee.")
        act_boost.triggered.connect(self._do_update_priority_fee)
        menu.addAction(act_boost)
        menu.exec(self.sched_table.viewport().mapToGlobal(pos))

    def _do_update_priority_fee(self):
        """Увеличить priority fee: из HODL_CU_PRICE_BOOST в .env или удвоить текущий."""
        env_path = os.path.join(BASE_DIR, ".env")
        env = dict(os.environ)
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()
        current = self.set_cu_price.value()
        if "HODL_CU_PRICE_BOOST" in env:
            try:
                new_val = int(env["HODL_CU_PRICE_BOOST"])
                self.set_cu_price.setValue(new_val)
                self._on_log(f"Priority fee: {current} → {new_val} (из HODL_CU_PRICE_BOOST)")
            except ValueError:
                self._on_log("HODL_CU_PRICE_BOOST должен быть числом")
                return
        else:
            new_val = min(current * 2, 10_000_000)
            self.set_cu_price.setValue(new_val)
            self._on_log(f"Priority fee: {current} → {new_val} (x2)")
        self._apply_settings()
        self._save_settings_env()

    def _remove_sched_row(self, target_idx: int):
        if target_idx < 0 or target_idx >= len(self._schedule_targets):
            return
        t = self._schedule_targets.pop(target_idx)
        qid = t.get("_qid")
        if qid:
            self._worker.send("cancel_item", qid=qid)
        self._rebuild_sched_table()
        self._save_sched_cache()
        self._on_log("Removed from queue")

    def _on_schedule_done(self, idx: int, status: str, detail: str):
        pass  # Kept for backward compatibility if any old _run_schedule tasks finish.

    def _on_queue_item_done(self, qid: str, status: str, detail: str):
        target_idx = -1
        for i, t in enumerate(self._schedule_targets):
            if t.get("_qid") == qid:
                target_idx = i
                break
        if target_idx < 0:
            return
        t = self._schedule_targets[target_idx]
        t["_status"] = status.upper()
        if detail:
            t["_sig"] = detail
        row = self._sched_target_to_row.get(target_idx, -1)
        if row < 0 or row >= self.sched_table.rowCount():
            if status in ("done", "failed"):
                self._save_sched_cache()
            return
        colors = {
            "waiting": "#d29922",
            "sending": "#58a6ff",
            "done": "#3fb950",
            "failed": "#f85149",
        }
        status_upper = status.upper()
        item = QTableWidgetItem(status_upper)
        item.setForeground(QColor(colors.get(status, "#c9d1d9")))
        self.sched_table.setItem(row, 7, item)

        name_item = self.sched_table.item(row, 1)
        fish_name = name_item.text() if name_item else f"#{target_idx}"

        if detail:
            sig_item = QTableWidgetItem(detail[:30] + "..." if len(detail) > 30 else detail)
            sig_item.setToolTip(detail)
            self.sched_table.setItem(row, 8, sig_item)

        if status == "failed":
            self._on_log(f"FAILED [{fish_name}]: {detail}")
            file_logger.error(f"Schedule mark failed [{fish_name}]: {detail}")
        elif status == "done":
            self._on_log(f"OK [{fish_name}]: {detail}")
        elif status == "sending":
            self._on_log(f"Sending [{fish_name}]...")

        if status in ("done", "failed"):
            self._save_sched_cache()
        if status in ("done", "failed") and hasattr(self, "set_tg_token"):
            act = "mark"
            if target_idx < len(self._schedule_targets):
                act = self._schedule_targets[target_idx].get("_action", "mark")
            label = f"{act.upper()} '{fish_name}'"
            self._on_tx_status(act, status == "done", label, detail if status == "done" else "")

    def _on_schedule_finished(self):
        self.btn_stop_sched.setEnabled(False)
        self._update_scheduler_buttons()
        self.btn_run_queue.setEnabled(True)

    def _update_scheduler_buttons(self):
        """Включить Start Scheduler только если есть рыба (и планировщик не запущен)."""
        if hasattr(self, "btn_start_sched"):
            has_fish = bool(self._my_fish) or bool(self._my_fish_list)
            can_start = has_fish and not self.btn_stop_sched.isEnabled()
            self.btn_start_sched.setEnabled(can_start)

    # ── Actions ──────────────────────────────────────────────────────

    def _send_preload_fish(self):
        """Загрузить рыб по всем кошелькам."""
        pubkeys = [(i, pubkey_from_keypair(kp)) for i, kp in enumerate(self._wallets) if pubkey_from_keypair(kp) != "?"]
        if pubkeys:
            self._worker.send("preload_fish_by_wallets", wallet_pubkeys=pubkeys)

    def _on_worker_ready(self):
        QTimer.singleShot(100, lambda: self._worker.send("refresh"))
        QTimer.singleShot(300, self._send_preload_fish)
        QTimer.singleShot(500, lambda: self._worker.send("load_fish"))
        QTimer.singleShot(1500, self._update_scheduler_buttons)

    def _do_refresh(self):
        self._worker.send("refresh")

    def _do_load_fish(self):
        self.btn_load_fish.setEnabled(False)
        self.btn_load_fish.setText("Loading...")
        self._worker.send("load_fish")
        QTimer.singleShot(3000, lambda: (self.btn_load_fish.setEnabled(True), self.btn_load_fish.setText("Load All Fish")))

    def _do_create_fish(self):
        name = self.inp_create_name.text().strip()
        if not name:
            self._on_log("Введите имя рыбы")
            return
        if not name.replace("_", "").replace("-", "").isalnum():
            self._on_log("Имя: только латиница, цифры, _, -")
            return
        existing = next((f for f in self._all_fish if f["name"].lower() == name.lower()), None)
        if existing:
            self._on_log(f"Имя '{name}' уже занято. Выбери другое.")
            return
        deposit = int(self.inp_create_deposit.value() * LAMPORTS_PER_SOL)
        self._worker.send("create_fish", name=name, deposit=deposit, label=f"Create '{name}'")

    def _do_feed(self):
        amount = int(self.inp_feed.value() * LAMPORTS_PER_SOL)
        self._worker.send("feed", amount=amount, fish_id=self._my_fish["fish_id"] if self._my_fish else None, label=f"Feed {self.inp_feed.value():.4f} SOL")

    def _do_feed_schedule(self):
        if not self._my_fish:
            self._on_log("Сначала выбери рыбу")
            return
        dlg = FeedScheduleDialog(self._my_fish, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        fire_at = dlg.get_fire_at()
        amount = dlg.get_amount_lamports()
        target = {
            "owner": self._my_fish["owner"],
            "fish_id": self._my_fish["fish_id"],
            "name": self._my_fish["name"],
            "share": self._my_fish["share"],
            "last_fed_at": self._my_fish["last_fed_at"],
            "_action": "feed",
            "_amount": amount,
            "_fire_at": fire_at,
            "_prey_time": fire_at,
            "_sol_value": self._my_fish["share"] * self._share_price / 1e9 if self._share_price else 0,
        }
        self._add_to_queue(target, "feed", self._active_wallet_index)
        self._on_log(f"Queued FEED for '{self._my_fish['name']}' at {datetime.fromtimestamp(fire_at).strftime('%d.%m %H:%M')}")

    def _do_exit_game(self):
        self._worker.send("exit_game", fish_id=self._my_fish["fish_id"] if self._my_fish else None)

    def _do_transfer(self):
        wallet = self.inp_transfer.text().strip()
        if not wallet:
            return
        self._worker.send("transfer", wallet=wallet, fish_id=self._my_fish["fish_id"] if self._my_fish else None)

    def _open_sched_card(self, index):
        row = index.row()
        if row < 0 or row >= len(self._sched_row_to_target):
            return
        target_idx = self._sched_row_to_target[row]
        if target_idx < 0:
            return
        fish = self._schedule_targets[target_idx]
        dlg = FishCardDialog(
            fish, self._share_price,
            feeding_period=self.sch_feed_days.value() * 86400,
            mark_window=self.sch_mark_hours.value() * 3600,
            is_storm=self._is_storm,
            parent=self,
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()

    def _do_start_schedule(self):
        fish = self._my_fish or (self._my_fish_list[0] if self._my_fish_list else None)
        if not fish:
            self._on_log("Сначала создай рыбу (Dashboard → Create Fish) или выбери кошелёк с рыбой")
            self._on_error("Нет рыбы — Scheduler требует хотя бы одну рыбу для охоты")
            return

        self._my_fish = fish
        self.sched_table.setRowCount(0)
        self._schedule_targets.clear()
        self._schedule_start_time = int(time.time())
        self._save_sched_cache()
        self.btn_start_sched.setEnabled(False)
        self.btn_stop_sched.setEnabled(True)

        self._worker.send(
            "schedule",
            count=self.sch_count.value(),
            min_sol=self.sch_min_sol.value(),
            feeding_period=self.sch_feed_days.value() * 86400,
            mark_window=self.sch_mark_hours.value() * 3600,
            fish_id=fish["fish_id"],
            fish_owner=fish["owner"],
        )

    def _do_stop_schedule(self):
        self._worker.send("stop_schedule")
        self.sched_table.setRowCount(0)
        self._schedule_targets.clear()
        self.btn_start_sched.setEnabled(True)
        self.btn_stop_sched.setEnabled(False)
        self.btn_run_queue.setEnabled(True)
        self._save_sched_cache()
        self._on_log("Scheduler stopped & queue cleared")

    def _do_clear_queue(self):
        self.sched_table.setRowCount(0)
        self._schedule_targets.clear()
        self._save_sched_cache()
        self._on_log("Queue cleared")

    def _do_run_queue(self):
        count = 0
        now = int(time.time())
        for t in self._schedule_targets:
            if t.get("_status") in ("FAILED", "QUEUED") and t.get("_wallet_index", 0) == self._active_wallet_index:
                t["_status"] = "QUEUED"
                t["_sig"] = ""
                # Adjust wait time if it's already in the past
                fire_at = t.get("_fire_at", 0)
                if fire_at > 0:
                    t["_wait"] = max(0, fire_at - now)
                t["my_fish_id"] = self._my_fish["fish_id"] if self._my_fish else None
                self._worker.send("enqueue_item", qid=t["_qid"], target=t)
                count += 1
                
        if count > 0:
            self._rebuild_sched_table()
            self._on_log(f"Re-enqueued {count} tasks for current wallet")
        else:
            self._on_log("No failed/queued tasks to run for current wallet")

    def _apply_fish_filter(self):
        min_sol = self.fl_min_sol.value()
        only_lighter = self.fl_markable.isChecked()
        not_marked = self.fl_not_marked.isChecked()
        search = self.fl_search.text().strip().lower()
        my_share = self._my_fish["share"] if self._my_fish else 0

        self.fish_table.setSortingEnabled(False)
        self.fish_table.setRowCount(0)

        now = int(time.time())
        shown = 0
        for f in self._all_fish:
            sol_val = f["share"] * self._share_price / 1e9 if self._share_price else 0
            if sol_val < min_sol:
                continue
            if only_lighter and my_share and f["share"] >= my_share:
                continue
            if not_marked and f["marked_by_hunter_id"] != 0:
                continue
            if search and search not in f["name"].lower():
                continue

            row = self.fish_table.rowCount()
            self.fish_table.insertRow(row)

            self.fish_table.setItem(row, 0, QTableWidgetItem(f["name"]))

            sol_item = QTableWidgetItem(self._fmt_sol_usd(sol_val))
            sol_item.setData(Qt.ItemDataRole.UserRole, sol_val)
            self.fish_table.setItem(row, 1, sol_item)

            share_item = QTableWidgetItem()
            share_item.setData(Qt.ItemDataRole.DisplayRole, f["share"])
            self.fish_table.setItem(row, 2, share_item)

            self.fish_table.setItem(row, 3, QTableWidgetItem(f["owner"][:8] + "..."))

            fed_str = datetime.fromtimestamp(f["last_fed_at"]).strftime("%m-%d %H:%M")
            self.fish_table.setItem(row, 4, QTableWidgetItem(fed_str))

            prey_time = f["last_fed_at"] + 7 * 86400
            prey_str = datetime.fromtimestamp(prey_time).strftime("%m-%d %H:%M")
            self.fish_table.setItem(row, 5, QTableWidgetItem(prey_str))

            marked = "Yes" if f["marked_by_hunter_id"] != 0 else "No"
            m_item = QTableWidgetItem(marked)
            if marked == "Yes":
                m_item.setForeground(QColor("#f85149"))
            self.fish_table.setItem(row, 6, m_item)

            shown += 1

        self.fish_table.setSortingEnabled(True)
        self.lbl_fish_stats.setText(f"Showing {shown} / {len(self._all_fish)} fish")

    def _open_fish_card(self, index):
        row = index.row()
        name_item = self.fish_table.item(row, 0)
        if not name_item:
            return
        name = name_item.text()
        fish = next((f for f in self._all_fish if f["name"] == name), None)
        if not fish:
            return
        dlg = FishCardDialog(
            fish, self._share_price,
            feeding_period=self.sch_feed_days.value() * 86400,
            mark_window=self.sch_mark_hours.value() * 3600,
            is_storm=self._is_storm,
            parent=self,
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()

    def _fish_context_menu(self, pos):
        row = self.fish_table.rowAt(pos.y())
        if row < 0:
            return

        name_item = self.fish_table.item(row, 0)
        if not name_item:
            return
        name = name_item.text()

        fish = next((f for f in self._all_fish if f["name"] == name), None)
        if not fish:
            return

        menu = QMenu(self)
        act_mark = menu.addAction(f"Place Mark on '{name}'")
        act_hunt = menu.addAction(f"Hunt '{name}'")
        menu.addSeparator()
        act_queue_mark = menu.addAction(f"Add to Queue → Mark")
        act_queue_hunt = menu.addAction(f"Add to Queue → Hunt")

        action = menu.exec(self.fish_table.viewport().mapToGlobal(pos))
        if action == act_mark:
            self._worker.send("place_mark", wallet=fish["owner"], fish_id=fish["fish_id"], name=fish["name"], share=fish.get("share", 0), last_fed_at=fish.get("last_fed_at", 0), hunter_fish_id=self._my_fish["fish_id"] if self._my_fish else None, label=f"Mark '{fish['name']}'")
        elif action == act_hunt:
            self._worker.send("hunt_fish", wallet=fish["owner"], fish_id=fish["fish_id"], name=fish["name"], share=fish["share"], hunter_fish_id=self._my_fish["fish_id"] if self._my_fish else None, label=f"Hunt '{fish['name']}'")
        elif action == act_queue_mark:
            prey_time = fish["last_fed_at"] + self.sch_feed_days.value() * 86400
            default_fire = prey_time - self.sch_mark_hours.value() * 3600
            dlg = AddToQueueTimeDialog(name, "mark", default_fire, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                fire_at = dlg.get_fire_at()
                self._add_to_queue(fish, "mark", self._active_wallet_index, fire_at=fire_at)
                self._on_log(f"Queued MARK for '{name}' (wallet #{self._active_wallet_index+1})")
        elif action == act_queue_hunt:
            prey_time = fish["last_fed_at"] + self.sch_feed_days.value() * 86400
            default_fire = prey_time - self.sch_mark_hours.value() * 3600
            dlg = AddToQueueTimeDialog(name, "hunt", default_fire, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                fire_at = dlg.get_fire_at()
                self._add_to_queue(fish, "hunt", self._active_wallet_index, fire_at=fire_at)
                self._on_log(f"Queued HUNT for '{name}' (wallet #{self._active_wallet_index+1})")

    # ── Timer tick (scheduler countdown) ─────────────────────────────

    def _tick(self):
        now = int(time.time())

        if self._my_fish:
            feeding_period = self.sch_feed_days.value() * 86400
            prey_time = self._my_fish["last_fed_at"] + feeding_period
            rem = prey_time - now
            if rem > 0:
                self.lbl_feed_countdown.setText(fmt_delta(rem))
                self.lbl_feed_countdown.setStyleSheet("font-size: 16px; font-weight: bold; color: #f85149;")
            else:
                self.lbl_feed_countdown.setText("HUNGRY!")
                self.lbl_feed_countdown.setStyleSheet("font-size: 16px; font-weight: bold; color: #f85149; background: #3d1214; padding: 2px 6px; border-radius: 4px;")

            cd_end = self._my_fish["can_hunt_after"]
            if cd_end > now:
                self.lbl_hunt_cd.setText(fmt_delta(cd_end - now))
                self.lbl_hunt_cd.setStyleSheet("font-size: 14px; font-weight: bold; color: #d29922;")
            else:
                self.lbl_hunt_cd.setText("Ready to hunt")
                self.lbl_hunt_cd.setStyleSheet("font-size: 14px; font-weight: bold; color: #3fb950;")

        now_cooldown = now
        for target_idx, t in enumerate(self._schedule_targets):
            row = self._sched_target_to_row.get(target_idx, -1)
            if row < 0:
                continue
            status_item = self.sched_table.item(row, 7)
            if not status_item:
                continue
            status = status_item.text()
            if status in ("DONE", "FAILED", "SENDING"):
                continue
            fire_at = t.get("_fire_at", 0)
            if fire_at > 0:
                remaining = fire_at - now
            else:
                remaining = t["_wait"] - (now - self._schedule_start_time)
            fire_item = self.sched_table.item(row, 6)
            if fire_item:
                fire_item.setText(fmt_delta(max(0, remaining)))
            # The background worker handles execution now.

        # Приоритет: Hunt In=0 (READY), Mark Expires ≤ 30 min — окно на укус
        BITE_MARK_EXPIRES_SEC = 30 * 60
        feeding_period = self.sch_feed_days.value() * 86400
        for i in range(self.marks_table.rowCount()):
            name_item = self.marks_table.item(i, 0)
            if not name_item:
                continue
            fish = next((f for f in self._all_fish if f["name"] == name_item.text()), None)
            if not fish:
                continue

            prey_time = fish["last_fed_at"] + feeding_period
            hunt_rem = prey_time - now
            mark_exp = fish.get("mark_expires_at", 0) or 0
            mark_exp_rem = mark_exp - now if mark_exp > 0 else 0
            k = (fish["owner"], fish["fish_id"])

            if hunt_rem > 0 or mark_exp_rem <= 0 or mark_exp_rem > BITE_MARK_EXPIRES_SEC:
                self._bite_notified.discard(k)
                self._pending_bite_after_api.discard(k)
            elif hunt_rem <= 0 and 0 < mark_exp_rem <= BITE_MARK_EXPIRES_SEC:
                if k not in self._bite_notified and k not in self._bite_check_pending and k not in self._pending_bite_after_api:
                    self._pending_bite_after_api.add(k)
                    self._on_log(f"Bite priority: API check {fish['name']} (Hunt In=0, Mark expires {fmt_delta(mark_exp_rem)})")
                    self._worker.send("check_mark_api", fish_id=fish["fish_id"], owner=fish["owner"], name=fish["name"])
            hunt_item = self.marks_table.item(i, 4)
            if hunt_item:
                if hunt_rem > 0:
                    hunt_item.setText(fmt_delta(hunt_rem))
                    hunt_item.setForeground(QColor("#d29922"))
                else:
                    hunt_item.setText("READY")
                    hunt_item.setForeground(QColor("#3fb950"))

            exp_item = self.marks_table.item(i, 5)
            if exp_item and fish["mark_expires_at"] > 0:
                exp_rem = fish["mark_expires_at"] - now
                if exp_rem > 0:
                    exp_item.setText(fmt_delta(exp_rem))
                    exp_item.setForeground(QColor("#8b949e"))
                else:
                    exp_item.setText("EXPIRED")
                    exp_item.setForeground(QColor("#f85149"))

            btn = self.marks_table.cellWidget(i, 6)
            if btn and isinstance(btn, QPushButton):
                btn.setEnabled(hunt_rem <= 0)

    def closeEvent(self, event):
        self._worker.stop()
        self._worker.wait(3000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    rpc_url = os.environ.get("HODL_RPC", "https://api.mainnet-beta.solana.com")
    wallets, active = load_wallets_config()
    keypair = wallets[active] if wallets else os.environ.get("HODL_KEYPAIR", "")

    window = HodlHuntUI(rpc_url, keypair, wallets=wallets, active_index=active)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
