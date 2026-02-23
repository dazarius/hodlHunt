"""Точка входа HodlHunt UI."""
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from config import load_wallets_config
from constants import DARK_STYLE
from ui.main_window import HodlHuntUI


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
