"""Переиспользуемые виджеты."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


def make_stat_card(label: str, value: str = "—", obj_name: str = "") -> tuple[QWidget, QLabel]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(12, 8, 12, 8)
    lay.setSpacing(2)
    val_lbl = QLabel(value)
    val_lbl.setObjectName("statValue")
    if obj_name:
        val_lbl.setObjectName(obj_name)
    desc = QLabel(label)
    desc.setObjectName("statLabel")
    lay.addWidget(val_lbl, alignment=Qt.AlignmentFlag.AlignLeft)
    lay.addWidget(desc, alignment=Qt.AlignmentFlag.AlignLeft)
    return w, val_lbl
