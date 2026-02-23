"""Диалоги HodlHunt."""
import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QDoubleSpinBox, QCheckBox, QDateTimeEdit, QDialogButtonBox, QPushButton,
    QScrollArea, QFrame, QGroupBox, QWidget,
)
from PyQt6.QtCore import Qt, QDateTime, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication, QDesktopServices

from constants import DIALOG_STYLE
from logic.utils import fmt_delta, fmt_sol_usd

LAMPORTS_PER_SOL = 1_000_000_000



class AddToQueueTimeDialog(QDialog):
    def __init__(self, fish_name: str, action: str, default_fire_at: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Add to Queue → {action.upper()}")
        self.setMinimumWidth(360)
        self.setStyleSheet(DIALOG_STYLE)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"'{fish_name}' — {action.upper()}"))
        self.use_custom = QCheckBox("Указать своё время")
        self.use_custom.setChecked(False)
        lay.addWidget(self.use_custom)
        now = int(time.time())
        self.dt_edit = QDateTimeEdit(QDateTime.fromSecsSinceEpoch(default_fire_at))
        self.dt_edit.setCalendarPopup(True)
        self.dt_edit.setDisplayFormat("dd.MM.yyyy HH:mm")
        self.dt_edit.setMinimumDateTime(QDateTime.fromSecsSinceEpoch(now))
        self.dt_edit.setEnabled(False)
        self.use_custom.toggled.connect(lambda on: self.dt_edit.setEnabled(on))
        lay.addWidget(self.dt_edit)
        lay.addWidget(QLabel("Сними галочку — добавится с дефолтным временем (prey_time − mark_window)"))
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def get_fire_at(self) -> int | None:
        if not self.use_custom.isChecked():
            return None
        return self.dt_edit.dateTime().toSecsSinceEpoch()


class FeedScheduleDialog(QDialog):
    def __init__(self, fish: dict, parent=None):
        super().__init__(parent)
        self.fish = fish
        self.setWindowTitle(f"Feed Schedule: {fish['name']}")
        self.setMinimumWidth(360)
        self.setStyleSheet(DIALOG_STYLE)
        lay = QGridLayout(self)
        lay.setSpacing(12)
        now = datetime.now()
        default_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if default_time < now:
            default_time = default_time.replace(day=default_time.day + 1)
        lay.addWidget(QLabel("Время кормёжки:"), 0, 0)
        self.dt_edit = QDateTimeEdit(QDateTime.fromSecsSinceEpoch(int(default_time.timestamp())))
        self.dt_edit.setCalendarPopup(True)
        self.dt_edit.setDisplayFormat("dd.MM.yyyy HH:mm")
        self.dt_edit.setMinimumDateTime(QDateTime.fromSecsSinceEpoch(int(time.time())))
        lay.addWidget(self.dt_edit, 0, 1)
        lay.addWidget(QLabel("Сумма (SOL):"), 1, 0)
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.01, 1000)
        self.amount_spin.setValue(0.05)
        self.amount_spin.setDecimals(4)
        lay.addWidget(self.amount_spin, 1, 1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns, 2, 0, 1, 2)

    def get_fire_at(self) -> int:
        return self.dt_edit.dateTime().toSecsSinceEpoch()

    def get_amount_lamports(self) -> int:
        return int(self.amount_spin.value() * LAMPORTS_PER_SOL)


class DonateDialog(QDialog):
    def __init__(self, address: str, parent=None):
        super().__init__(parent)
        self._address = address
        self.setWindowTitle("☕ Donate")
        self.setMinimumWidth(420)
        self.setStyleSheet(DIALOG_STYLE)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.addWidget(QLabel("Поддержи разработку HodlHunt:"))
        lay.addWidget(QLabel("Адрес для доната:"))
        self.addr_edit = QLineEdit()
        self.addr_edit.setReadOnly(True)
        self.addr_edit.setText(address)
        self.addr_edit.setStyleSheet("font-family: monospace; padding: 8px;")
        lay.addWidget(self.addr_edit)
        lay.addWidget(QLabel("Сумма (SOL):"))
        amount_row = QHBoxLayout()
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.001, 100.0)
        self.amount_spin.setValue(0.01)
        self.amount_spin.setDecimals(4)
        self.amount_spin.setSingleStep(0.01)
        amount_row.addWidget(self.amount_spin)
        lay.addLayout(amount_row)
        btns = QHBoxLayout()
        btn_copy = QPushButton("📋 Copy address")
        btn_copy.setObjectName("blueBtn")
        btn_copy.clicked.connect(self._copy)
        btns.addWidget(btn_copy)
        self.btn_send = QPushButton("💸 Send Donation")
        self.btn_send.setObjectName("greenBtn")
        self.btn_send.clicked.connect(self._send)
        btns.addWidget(self.btn_send)
        lay.addLayout(btns)
        if address == "YOUR_SOLANA_ADDRESS_HERE":
            lay.addWidget(QLabel("Добавь HODL_DONATE_ADDRESS=твой_адрес в .env"))
        lay.addWidget(QLabel("Спасибо за поддержку! 🙏"))

    def _copy(self):
        addr = self.addr_edit.text().strip()
        if addr and addr != "YOUR_SOLANA_ADDRESS_HERE":
            cb = QGuiApplication.clipboard()
            cb.setText(addr)
            p = self.parent()
            if p and hasattr(p, "_on_log"):
                p._on_log("Donate address copied to clipboard")

    def _send(self):
        addr = self._address.strip()
        if not addr or addr == "YOUR_SOLANA_ADDRESS_HERE":
            p = self.parent()
            if p and hasattr(p, "_on_log"):
                p._on_log("Set HODL_DONATE_ADDRESS in .env first")
            return
        amount = self.amount_spin.value()
        if amount <= 0:
            return
        p = self.parent()
        if p and hasattr(p, "_worker"):
            p._worker.send("donate", to=addr, amount=amount)
            p._on_log(f"Sending {amount:.4f} SOL donation...")
            self.accept()


class FishCardDialog(QDialog):
    def __init__(self, fish: dict, share_price: float, feeding_period: int = 7 * 86400,
                 mark_window: int = 24 * 3600, is_storm: bool = False, sol_usd_price: float = 0, parent=None):
        super().__init__(parent)
        self.fish = fish
        self.share_price = share_price
        self.sol_usd_price = sol_usd_price if sol_usd_price > 0 else (getattr(parent, "_sol_usd_price", 0) if parent else 0)
        self.feeding_period = feeding_period
        self.mark_window = mark_window
        self.setWindowTitle(f"Fish: {fish['name']}")
        self.setMinimumSize(460, 700)
        self.setStyleSheet(DIALOG_STYLE)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)
        scroll.setWidget(container)
        dlg_lay = QVBoxLayout(self)
        dlg_lay.setContentsMargins(0, 0, 0, 0)
        dlg_lay.addWidget(scroll)
        now = int(time.time())
        sol_val = fish["share"] * share_price / 1e9 if share_price else 0
        feed_pct = 0.10 if is_storm else 0.05
        feed_cost = sol_val * feed_pct
        hunt_profit_80 = sol_val * 0.80
        hunt_profit_10_fish = sol_val * 0.10
        mark_cost_est = sol_val * 0.05
        prey_time = fish["last_fed_at"] + feeding_period
        mark_open = prey_time - mark_window
        priority_end = prey_time + 1800
        cooldown_end = fish["can_hunt_after"]
        title = QLabel(fish["name"])
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #f0f6fc;")
        lay.addWidget(title)
        val_row = QHBoxLayout()
        sol_lbl = QLabel(fmt_sol_usd(sol_val, self.sol_usd_price))
        sol_lbl.setStyleSheet("font-size: 18px; color: #3fb950; font-weight: bold;")
        val_row.addWidget(sol_lbl)
        val_row.addStretch()
        ocean_lbl = QLabel("STORM" if is_storm else "CALM")
        ocean_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: bold; padding: 2px 8px; border-radius: 4px; "
            f"color: white; background: {'#f85149' if is_storm else '#238636'};"
        )
        val_row.addWidget(ocean_lbl)
        lay.addLayout(val_row)
        econ_group = QGroupBox("Economics")
        eg = QGridLayout(econ_group)
        eg.setSpacing(6)
        fmt = lambda v: fmt_sol_usd(v, self.sol_usd_price)
        for i, (k, v, color) in enumerate([
            ("Balance", fmt(sol_val), "#3fb950"),
            (f"Feed Cost ({int(feed_pct*100)}%)", fmt(feed_cost), "#d29922"),
            ("Mark Cost (~5%)", fmt(mark_cost_est), "#d29922"),
            ("Hunt Profit (80%)", f"+{fmt(hunt_profit_80)}", "#3fb950"),
            ("→ to other fish (10%)", fmt(hunt_profit_10_fish), "#8b949e"),
            ("→ to admins (10%)", fmt(hunt_profit_10_fish), "#8b949e"),
        ]):
            kl, vl = QLabel(k), QLabel(v)
            kl.setStyleSheet("color: #8b949e; font-size: 12px;")
            vl.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")
            eg.addWidget(kl, i, 0)
            eg.addWidget(vl, i, 1)
        lay.addWidget(econ_group)
        info_group = QGroupBox("Fish Info")
        ig = QGridLayout(info_group)
        ig.setSpacing(6)
        is_prey = prey_time <= now
        has_mark = fish["marked_by_hunter_id"] != 0
        hunt_cd = cooldown_end > now
        info_rows = [
            ("Fish ID", str(fish["fish_id"])),
            ("Owner", fish["owner"][:16] + "..."),
            ("Share (raw)", f'{fish["share"]:,}'),
            ("Created", datetime.fromtimestamp(fish["created_at"]).strftime("%Y-%m-%d %H:%M")),
            ("Last Fed", datetime.fromtimestamp(fish["last_fed_at"]).strftime("%Y-%m-%d %H:%M")),
            ("Last Hunt", datetime.fromtimestamp(fish["last_hunt_at"]).strftime("%Y-%m-%d %H:%M") if fish["last_hunt_at"] else "Never"),
            ("Protected", "Yes" if fish["is_protected"] else "No"),
            ("Total Hunts", str(fish["total_hunts"])),
            ("Hunt Income", f'{fish["total_hunt_income"]:,}'),
            ("Marks Placed", str(fish["hunting_marks_placed"])),
        ]
        if has_mark:
            info_rows.append(("Marked By ID", str(fish["marked_by_hunter_id"])))
            if fish["mark_placed_at"]:
                info_rows.append(("Mark Placed", datetime.fromtimestamp(fish["mark_placed_at"]).strftime("%Y-%m-%d %H:%M")))
            if fish["mark_cost"]:
                mc_sol = fish["mark_cost"] * share_price / 1e9 if share_price else 0
                info_rows.append(("Mark Cost (actual)", f"{mc_sol:.4f} SOL"))
        for i, (k, v) in enumerate(info_rows):
            kl, vl = QLabel(k), QLabel(v)
            kl.setStyleSheet("color: #8b949e; font-size: 12px;")
            vl.setStyleSheet("color: #f0f6fc; font-size: 13px; font-weight: bold;")
            vl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            ig.addWidget(kl, i, 0)
            ig.addWidget(vl, i, 1)
        lay.addWidget(info_group)
        status_row = QHBoxLayout()
        def badge(text, color, bg):
            b = QLabel(text)
            b.setStyleSheet(f"color: {color}; background: {bg}; font-size: 11px; font-weight: bold; padding: 3px 10px; border-radius: 4px;")
            return b
        status_row.addWidget(badge("PREY" if is_prey else "SAFE", "white", "#f85149" if is_prey else "#238636"))
        if has_mark:
            status_row.addWidget(badge("MARKED", "white", "#d29922"))
        if hunt_cd:
            status_row.addWidget(badge("HUNT CD", "white", "#6e7681"))
        if fish["is_protected"]:
            status_row.addWidget(badge("PROTECTED", "white", "#58a6ff"))
        status_row.addStretch()
        lay.addLayout(status_row)
        # Scheduler / Transaction info (when opened from queue)
        if fish.get("_sig") or fish.get("_action"):
            tx_group = QGroupBox("Queue / Transaction")
            tx_lay = QGridLayout(tx_group)
            r = 0
            if fish.get("_action"):
                tx_lay.addWidget(QLabel("Action:"), r, 0)
                tx_lay.addWidget(QLabel(str(fish["_action"]).upper()), r, 1)
                r += 1
            if fish.get("_sig"):
                tx_lay.addWidget(QLabel("Transaction:"), r, 0)
                sig = fish["_sig"]
                sig_row = QWidget()
                sig_h = QHBoxLayout(sig_row)
                sig_h.setContentsMargins(0, 0, 0, 0)
                sig_lbl = QLabel(sig[:20] + "..." + sig[-8:] if len(sig) > 32 else sig)
                sig_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                sig_lbl.setToolTip(sig)
                sig_lbl.setStyleSheet("color: #58a6ff; font-family: monospace;")
                sig_h.addWidget(sig_lbl)
                solscan_btn = QPushButton("Solscan")
                solscan_btn.setMaximumWidth(70)
                solscan_btn.clicked.connect(lambda checked=False, s=sig: QDesktopServices.openUrl(QUrl(f"https://solscan.io/tx/{s}")))
                sig_h.addWidget(solscan_btn)
                tx_lay.addWidget(sig_row, r, 1)
                r += 1
            if fish.get("_hunter_fish_name"):
                tx_lay.addWidget(QLabel("Hunter Fish:"), r, 0)
                tx_lay.addWidget(QLabel(fish["_hunter_fish_name"]), r, 1)
                r += 1
            if fish.get("_wallet_pubkey"):
                tx_lay.addWidget(QLabel("Signing Wallet:"), r, 0)
                w = fish["_wallet_pubkey"]
                wl = QLabel(w[:8] + "..." + w[-4:] if len(w) > 16 else w)
                wl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                wl.setToolTip(w)
                tx_lay.addWidget(wl, r, 1)
            lay.addWidget(tx_group)
        timer_group = QGroupBox("Timers")
        tg_lay = QGridLayout(timer_group)
        tg_lay.setSpacing(6)
        r = 0
        tg_lay.addWidget(QLabel("Becomes Prey:"), r, 0)
        self.lbl_prey_timer = QLabel("—")
        self.lbl_prey_timer.setStyleSheet("font-size: 16px; font-weight: bold; color: #f85149;")
        tg_lay.addWidget(self.lbl_prey_timer, r, 1)
        tg_lay.addWidget(QLabel(datetime.fromtimestamp(prey_time).strftime("%m-%d %H:%M:%S")), r, 2)
        r += 1
        tg_lay.addWidget(QLabel("Mark Window Opens:"), r, 0)
        self.lbl_mark_timer = QLabel("—")
        self.lbl_mark_timer.setStyleSheet("font-size: 16px; font-weight: bold; color: #d29922;")
        tg_lay.addWidget(self.lbl_mark_timer, r, 1)
        r += 1
        tg_lay.addWidget(QLabel("Priority Window Ends:"), r, 0)
        self.lbl_priority_timer = QLabel("—")
        self.lbl_priority_timer.setStyleSheet("font-size: 16px; font-weight: bold; color: #58a6ff;")
        tg_lay.addWidget(self.lbl_priority_timer, r, 1)
        if hunt_cd:
            r += 1
            tg_lay.addWidget(QLabel("Hunt Cooldown:"), r, 0)
            self.lbl_cd_timer = QLabel("—")
            self.lbl_cd_timer.setStyleSheet("font-size: 16px; font-weight: bold; color: #6e7681;")
            tg_lay.addWidget(self.lbl_cd_timer, r, 1)
        else:
            self.lbl_cd_timer = None
        if has_mark and fish.get("mark_expires_at", 0) > 0:
            r += 1
            tg_lay.addWidget(QLabel("Mark Expires:"), r, 0)
            self.lbl_mark_exp_timer = QLabel("—")
            self.lbl_mark_exp_timer.setStyleSheet("font-size: 16px; font-weight: bold; color: #d29922;")
            tg_lay.addWidget(self.lbl_mark_exp_timer, r, 1)
        else:
            self.lbl_mark_exp_timer = None
        lay.addWidget(timer_group)
        self._prey_time = prey_time
        self._mark_open = mark_open
        self._priority_end = priority_end
        self._cooldown_end = cooldown_end
        self._mark_expires = fish.get("mark_expires_at", 0) if has_mark else 0
        self._update_timers()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_timers)
        self._timer.start(1000)
        lay.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        lay.addWidget(close_btn)

    def _update_timers(self):
        now = int(time.time())
        for lbl, end, default_style, done_style, done_text in [
            (self.lbl_prey_timer, self._prey_time, "color: #f85149;", "color: #3fb950;", "HUNGRY"),
            (self.lbl_mark_timer, self._mark_open, "color: #d29922;", "color: #3fb950;", "OPEN"),
            (self.lbl_priority_timer, self._priority_end, "color: #58a6ff;", "color: #8b949e;", "PUBLIC"),
        ]:
            rem = end - now
            lbl.setText(fmt_delta(rem) if rem > 0 else done_text)
            lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; {default_style if rem > 0 else done_style}")
        if self.lbl_cd_timer:
            cd_rem = self._cooldown_end - now
            self.lbl_cd_timer.setText(fmt_delta(cd_rem) if cd_rem > 0 else "READY")
            self.lbl_cd_timer.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {'#6e7681' if cd_rem > 0 else '#3fb950'};")
        if self.lbl_mark_exp_timer:
            me_rem = self._mark_expires - now
            self.lbl_mark_exp_timer.setText(fmt_delta(me_rem) if me_rem > 0 else "EXPIRED")
            self.lbl_mark_exp_timer.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {'#d29922' if me_rem > 0 else '#f85149'};")
