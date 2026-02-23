"""Утилиты для HodlHunt."""


def fmt_delta(secs: int) -> str:
    if secs <= 0:
        return "NOW"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    parts.append(f"{m:02d}m {s:02d}s")
    return " ".join(parts)


def fmt_sol_usd(sol_val: float, sol_usd: float) -> str:
    if sol_val <= 0:
        return f"{sol_val:.4f} SOL"
    if sol_usd > 0:
        return f"{sol_val:.4f} SOL (${sol_val * sol_usd:,.2f})"
    return f"{sol_val:.4f} SOL"


def pubkey_from_keypair(keypair_b58: str) -> str:
    try:
        from solders.keypair import Keypair
        kp = Keypair.from_base58_string(keypair_b58)
        return str(kp.pubkey())
    except Exception:
        return "?"
