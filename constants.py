"""Стили и константы UI."""
DARK_STYLE = """
QWidget { background-color: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', 'Ubuntu', monospace; font-size: 13px; }
QTabWidget::pane { border: 1px solid #30363d; border-radius: 6px; }
QTabBar::tab { background: #161b22; border: 1px solid #30363d; padding: 8px 20px; color: #8b949e; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }
QTabBar::tab:selected { background: #0d1117; color: #58a6ff; border-bottom: 2px solid #58a6ff; }
QTabBar::tab:hover { color: #c9d1d9; }
QTableWidget { background-color: #0d1117; gridline-color: #21262d; border: 1px solid #30363d; border-radius: 6px; }
QTableWidget::item { padding: 4px 8px; border-bottom: 1px solid #161b22; }
QTableWidget::item:selected { background-color: #1f6feb33; color: #f0f6fc; }
QHeaderView::section { background-color: #161b22; color: #8b949e; border: none; border-bottom: 1px solid #30363d; padding: 6px 8px; font-weight: bold; }
QLineEdit, QDoubleSpinBox, QSpinBox { background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 6px; color: #f0f6fc; }
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus { border: 1px solid #58a6ff; }
QTextEdit { background-color: #0d1117; border: 1px solid #30363d; border-radius: 6px; color: #8b949e; font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: 12px; }
QPushButton { background-color: #21262d; border: 1px solid #30363d; border-radius: 6px; padding: 8px 16px; color: #c9d1d9; font-weight: bold; }
QPushButton:hover { background-color: #30363d; border-color: #8b949e; }
QPushButton:disabled { color: #484f58; background-color: #161b22; }
QPushButton#greenBtn { background-color: #238636; border-color: #2ea043; color: white; }
QPushButton#greenBtn:hover { background-color: #2ea043; }
QPushButton#redBtn { background-color: #da3633; border-color: #f85149; color: white; }
QPushButton#redBtn:hover { background-color: #f85149; }
QPushButton#blueBtn { background-color: #1f6feb; border-color: #388bfd; color: white; }
QPushButton#blueBtn:hover { background-color: #388bfd; }
QGroupBox { border: 1px solid #30363d; border-radius: 8px; margin-top: 12px; padding-top: 20px; font-weight: bold; color: #58a6ff; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QCheckBox { color: #c9d1d9; spacing: 6px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #30363d; border-radius: 3px; background: #161b22; }
QCheckBox::indicator:checked { background: #238636; border-color: #2ea043; }
QSplitter::handle { background: #30363d; height: 2px; }
QLabel#statValue { font-size: 20px; font-weight: bold; color: #f0f6fc; }
QLabel#statLabel { font-size: 11px; color: #484f58; font-weight: normal; }
QLabel#statusOk { color: #3fb950; font-weight: bold; }
QLabel#statusWarn { color: #d29922; font-weight: bold; }
"""

SETTINGS_GROUP = """
QGroupBox {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 10px;
    margin-top: 14px;
    padding: 16px 16px 8px 16px;
    font-weight: normal;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: #8b949e;
    font-size: 12px;
}
"""

DIALOG_STYLE = DARK_STYLE + "QDialog { border: 1px solid #30363d; border-radius: 10px; }"
