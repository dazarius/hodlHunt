# HodlHunt Sol

Desktop tool for [CryptoFish](https://cryptofish.gg) game on Solana. Create fish, place hunting marks, hunt prey, and schedule automated actions with a PyQt6 GUI or CLI.

## Features

- **Dashboard** — Your fish, balance, feed deadline, hunt cooldown
- **Fish Table** — Browse all fish, filter by SOL value, mark status
- **Scheduler** — Queue mark/hunt/feed actions with timers (prey time − mark window)
- **Multi-wallet** — Switch between wallets without clearing the queue
- **Transaction log** — All queued transactions saved to `schedule.transactions`
- **CLI mode** — Full terminal interface: dashboard, fish info, marks, batch operations, interactive menu

## Requirements

- Python 3.10+
- Solana wallet (keypair)

## Installation

```bash
cd hodlhuntSol
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your HODL_KEYPAIR
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```env
# Required
HODL_KEYPAIR=your_base58_keypair

# Optional
HODL_RPC=https://api.mainnet-beta.solana.com
HODL_CU_LIMIT=200000
HODL_CU_PRICE=375000
HODL_FEED_PERIOD=7
HODL_MARK_WINDOW=24
HODL_MIN_SOL=0.1
HODL_MAX_TARGETS=5

# Notifications (optional)
HODL_TG_TOKEN=your_telegram_bot_token
HODL_TG_CHAT=your_chat_id

# Donate (optional)
HODL_DONATE_ENABLED=1
HODL_DONATE_ADDRESS=your_solana_address
```

## Usage

### GUI

```bash
python ui.py
```

- **Dashboard** — Create fish, feed, view stats
- **Fish** — Load all fish, add to queue (mark/hunt)
- **Marks** — Your placed marks
- **Scheduler** — Start scheduler, retry failed, run queue, clear

### CLI

```bash
python cli.py                    # Dashboard
python cli.py -i                 # Interactive menu
python cli.py my                 # My fish
python cli.py fish -o ADDR -f 1  # Fish info (PDA, etc.)
python cli.py list -m 0.1        # List fish (min SOL)
python cli.py find -n 10        # Find prey
python cli.py mark -o ADDR -f 1 # Place mark
python cli.py hunt -o ADDR -f 1 -n Name -s 1000000
python cli.py feed -a 0.01       # Feed
python cli.py create -n Name -d 0.1
python cli.py schedule -n 4 -m 0.1
python cli.py batch -n 4
python cli.py wallets           # List wallets
python cli.py wallets 2         # Switch to wallet #2
```

## Project Structure

```
hodlhuntSol/
├── ui.py           # GUI entry point
├── cli.py          # CLI entry point
├── main.py         # HodlHunt logic, Solana instructions
├── config.py       # Paths, wallets config
├── logic/
│   ├── worker.py   # Async queue worker
│   ├── storage.py  # Fish cache by wallet
│   └── utils.py    # Helpers
├── ui/
│   ├── main_window.py
│   ├── dialogs.py
│   └── widgets.py
├── schedule.transactions   # Queued transactions log
├── scheduler_cache_*.json  # Per-wallet queue cache
└── wallets_config.json     # Wallets list
```

## License

MIT
