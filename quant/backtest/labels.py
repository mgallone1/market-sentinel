"""Etichette triple-barrier con la stessa logica di uscita e costi del backtester."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import Ctx, finish_trade, plan_trade


def triple_barrier_labels(bars, side, rules, spec, interval, maker_entry=False,
                          ref_notional: float = 10_000.0) -> pd.DataFrame:
    ctx = Ctx(bars, spec, interval)
    n = len(bars)
    if np.isscalar(side):
        sd = np.full(n, float(side))
    else:
        sd = pd.Series(side).reindex(bars.index).fillna(0).to_numpy(float)
    idx = bars.index
    rows = []
    for t in np.flatnonzero(sd != 0):
        s = 1 if sd[t] > 0 else -1
        pl = plan_trade(ctx, int(t), s, rules)
        if pl is None:
            continue
        r = finish_trade(ctx, pl, ref_notional / pl["entry"], maker_entry)
        rows.append((idx[t], s, r["ret_net"], int(r["ret_net"] > 0), r["exit_ts"], r["reason"], r["R"]))
    out = pd.DataFrame(rows, columns=["ts", "side", "ret_net", "label", "t1", "exit_reason", "R"])
    return out.set_index("ts")
