from functools import partial

from .baselines import always_long, donchian_breakout, ema_cross, meanrev_z, random, tsmom
from .xs_momentum import xs_momentum
from .legacy import legacy_crypto, legacy_equity
from .setups import (bull_flag, breakout_20d_close_high, orb, oversold, oversold_bounce, reclaim_20d_ma)

STRATEGIES = {
    "legacy": legacy_crypto,
    "legacy_equity": legacy_equity,
    "tsmom": tsmom,
    "donchian_breakout": donchian_breakout,
    "meanrev_z": meanrev_z,
    "ema_cross": ema_cross,
    "always_long": always_long,
    "random": random,
    "xs_momentum": xs_momentum,
    "breakout_20d_close_high": breakout_20d_close_high,
    "bull_flag": bull_flag,
    "reclaim_20d_ma": reclaim_20d_ma,
    "oversold": oversold,
    "oversold_bounce": oversold_bounce,
    "orb": orb,
}


def get_strategy(name: str, **params):
    """Strategia con parametri fissati: fn(bars, spec, interval, context)."""
    return partial(STRATEGIES[name], **params)


__all__ = ["STRATEGIES", "get_strategy"]
