"""Caricamento barre multi-venue con cache e validazione del contratto BARRE."""
from __future__ import annotations

import logging

import pandas as pd

from quant.core import AssetSpec, validate_bars
from quant.data import binance_vision, bybit, cache, synthetic, yahoo  # noqa: F401
from quant.data.bybit import BybitProvider
from quant.data.synthetic import generate_bars, generate_bars_with_signal  # noqa: F401

log = logging.getLogger(__name__)


def _ts(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def load_bars(spec: AssetSpec, interval: str, start, end, use_cache: bool = True,
              research_proxy: bool = True) -> pd.DataFrame:
    start, end = _ts(start), _ts(end)
    v = spec.venue
    if v == "bybit":
        try:
            df = BybitProvider().get_bars(spec.symbol, interval, start, end, use_cache=use_cache)
            if df is None or df.empty:
                raise RuntimeError("bybit: nessun dato")
        except Exception as e:  # rete / geo-block
            if not research_proxy:
                raise
            log.warning("Bybit non raggiungibile (%s): uso Binance Vision come proxy di ricerca per %s",
                        e, spec.symbol)
            df = binance_vision.get_bars(spec.symbol, interval, start, end, use_cache=use_cache)
    elif v == "binance":
        df = binance_vision.get_bars(spec.symbol, interval, start, end, use_cache=use_cache)
    elif v == "yahoo":
        df = yahoo.get_bars(spec.symbol, interval, start, end)
    elif v == "csv":
        df = pd.read_csv(spec.extra["path"], index_col=0, parse_dates=True)
        df.index = pd.DatetimeIndex(df.index)
        df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
        df.index.name = "ts"
        df = df.sort_index()
        df = df.loc[(df.index >= start) & (df.index <= end)]
    else:
        raise ValueError(f"venue non supportato: {v}")
    return validate_bars(df)
