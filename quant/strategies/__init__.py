from functools import partial

from .baselines import always_long, donchian_breakout, ema_cross, meanrev_z, random, tsmom
from .legacy import legacy_crypto, legacy_equity

STRATEGIES = {
    "legacy": legacy_crypto,
    "legacy_equity": legacy_equity,
    "tsmom": tsmom,
    "donchian_breakout": donchian_breakout,
    "meanrev_z": meanrev_z,
    "ema_cross": ema_cross,
    "always_long": always_long,
    "random": random,
}


def get_strategy(name: str, **params):
    """Strategia con parametri fissati: fn(bars, spec, interval, context)."""
    return partial(STRATEGIES[name], **params)


__all__ = ["STRATEGIES", "get_strategy"]
