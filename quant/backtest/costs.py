"""Costi di un trade in valuta."""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.core import AssetSpec


def trade_costs(spec: AssetSpec, side, entry_price, exit_price, qty, entry_ts, exit_ts, bars=None,
                maker_entry=False, maker_exit=False, stop_exit=False) -> dict:
    cm = spec.costs
    side = 1 if side > 0 else -1
    n_in, n_out = qty * entry_price, qty * exit_price
    fees = 0.0
    for notional, maker in ((n_in, maker_entry), (n_out, maker_exit)):
        if cm.per_share > 0:
            f = cm.per_share * qty
        else:
            f = (cm.maker_fee if maker else cm.taker_fee) * notional
        if cm.min_ticket > 0:
            f = max(f, cm.min_ticket)
        fees += f
    slippage = cm.slippage_bps / 1e4 * (n_in + n_out)
    if stop_exit:
        slippage += cm.stop_slippage_bps / 1e4 * n_out
    funding = 0.0
    if cm.apply_funding and bars is not None and "funding_rate" in bars.columns:
        idx = bars.index
        i0 = idx.searchsorted(entry_ts, side="right")
        i1 = idx.searchsorted(exit_ts, side="right")
        if i1 > i0:
            f = bars["funding_rate"].to_numpy()[i0:i1]
            cl = bars["close"].to_numpy()[i0:i1]
            m = ~np.isnan(f)
            funding = float(side * np.sum(f[m] * qty * cl[m]))
    borrow = 0.0
    if side < 0 and cm.borrow_rate_annual > 0 and spec.asset_class in ("equity", "etf", "index"):
        hours = (pd.Timestamp(exit_ts) - pd.Timestamp(entry_ts)).total_seconds() / 3600.0
        borrow = cm.borrow_rate_annual * n_in * hours / 8760.0
    return dict(fees=fees, slippage=slippage, funding=funding, borrow=borrow,
                total=fees + slippage + funding + borrow)
