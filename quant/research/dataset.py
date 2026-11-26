"""Dataset di eventi per il meta-labeling: feature alla barra di segnale + etichette triple-barrier side-aware."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from quant.backtest import ExitRules, triple_barrier_labels
from quant.backtest.engine import periods_per_year
from quant.core import AssetSpec, interval_to_hours
from quant.features import GaussianHMM, build_features, hmm_inputs, regime_features

DIRECTIONAL = re.compile(r"^(trend_ret|trend_ema_dist|rev_z|rev_rsi|rev_bb|volu_taker|xs_excess|struct_fld|"
                         r"struct_aroon|struct_dc|ext_|reg_trend|phys_pe|phys_fp_edge|phys_drift)")


def resolve_primary(primary):
    """callable fn(bars, spec, interval, context) -> Series side, oppure nome nel registro quant.strategies."""
    if callable(primary):
        return primary
    from quant.strategies import get_strategy  # import lazy: scritto da un altro modulo
    return get_strategy(primary)


def primary_side(primary, bars, spec, interval, benchmark=None) -> pd.Series:
    fn = resolve_primary(primary)
    s = fn(bars, spec, interval, {"benchmark": benchmark})
    return pd.Series(s).reindex(bars.index).fillna(0).astype(int)


def bar_features(bars, spec: AssetSpec, interval: str, benchmark=None, extra_cols=(), mc_window: int = 100,
                 vol_window: int = 168, physics: bool = False) -> pd.DataFrame:
    """Feature per barra (causali) + colonne ausiliarie aux_* (statistiche GBM e vol annua per il sizing)."""
    F = build_features(bars, spec, interval, benchmark, physics=physics)
    for c in extra_cols:
        F[f"ext_{c}"] = bars[c]
    lr = np.log(bars["close"]).diff()
    F["aux_mc_mu"] = lr.rolling(mc_window, min_periods=mc_window // 2).mean()
    F["aux_mc_sigma"] = lr.rolling(mc_window, min_periods=mc_window // 2).std()
    ppy = periods_per_year(spec, interval_to_hours(interval))
    F["aux_sigma_ann"] = lr.rolling(vol_window, min_periods=vol_window // 3).std() * np.sqrt(ppy)
    return F


def add_side_columns(rows: pd.DataFrame, side) -> pd.DataFrame:
    """meta_side + copie allineate al lato (<col>_sa = side * col) per le feature direzionali."""
    rows = rows.copy()
    s = np.asarray(side, float)
    for c in [c for c in rows.columns if DIRECTIONAL.match(str(c))]:
        rows[f"{c}_sa"] = rows[c].to_numpy(float) * s
    rows["meta_side"] = s
    return rows


def fit_hmm(universe: dict, until=None, since=None, n_states: int = 2, n_init: int = 2, n_iter: int = 40, seed: int = 0) -> GaussianHMM:
    """HMM pooled sulle osservazioni (ret, logvol) di tutti i simboli, SOLO fino a `until` incluso."""
    parts = []
    for bars, _ in universe.values():
        b = bars.loc[since:until]
        parts.append(hmm_inputs(b).dropna().to_numpy(float))
    X = np.vstack([p for p in parts if len(p)])
    return GaussianHMM(n_states=n_states, n_init=n_init, n_iter=n_iter, seed=seed).fit(X)


def add_regime_features(events: pd.DataFrame, universe: dict, hmm: GaussianHMM) -> pd.DataFrame:
    """Aggiunge reg_p_state*, reg_trend, reg_trend_sa usando un HMM GIA' adattato (filtro causale)."""
    out = events.drop(columns=[c for c in events.columns if str(c).startswith("reg_")], errors="ignore")
    blocks = []
    for sym, (bars, _) in universe.items():
        if sym not in events.index.get_level_values(0):
            continue
        ts = events.loc[sym].index
        R = regime_features(bars, hmm).loc[ts]
        R["reg_trend_sa"] = R["reg_trend"].to_numpy() * events.loc[sym, "side"].to_numpy(float)
        R.index = pd.MultiIndex.from_arrays([[sym] * len(ts), ts], names=["symbol", "ts"])
        blocks.append(R)
    return out.join(pd.concat(blocks))


def _same(a, b) -> bool:
    return b is not None and len(a) == len(b) and np.array_equal(a["close"].to_numpy(), b["close"].to_numpy())


def build_event_dataset(universe: dict, interval: str, primary, rules: ExitRules, benchmark=None,
                        hmm=True, extra_cols=(), min_gap_bars: int = 0, hmm_kwargs: dict | None = None,
                        physics: bool = False) -> pd.DataFrame:
    """universe: sym -> (bars, spec). Eventi poolati (MultiIndex (symbol, ts), ordinati per ts).
    hmm: False/None = niente feature di regime; GaussianHMM adattato = usato cosi' com'e';
    True = HMM adattato su TUTTO il campione (ammesso solo per il fit finale/gate, NON per il walk-forward)."""
    frames = []
    for sym, (bars, spec) in universe.items():
        bm = None if _same(bars, benchmark) else benchmark
        side = primary_side(primary, bars, spec, interval, bm)
        lab = triple_barrier_labels(bars, side, rules, spec, interval)
        if lab.empty:
            continue
        if min_gap_bars > 0:
            pos = bars.index.get_indexer(lab.index)
            keep, last = [], -10 ** 9
            for i, p in enumerate(pos):
                if p - last >= min_gap_bars:
                    keep.append(i)
                    last = p
            lab = lab.iloc[keep]
        F = bar_features(bars, spec, interval, bm, extra_cols, physics=physics).loc[lab.index]
        F["aux_mc_h"] = float(rules.max_hold_bars)
        F = add_side_columns(F, lab["side"].to_numpy())
        ev = pd.concat([lab, F], axis=1)
        ev.index = pd.MultiIndex.from_arrays([[sym] * len(ev), ev.index], names=["symbol", "ts"])
        frames.append(ev)
    if not frames:
        raise ValueError("nessun evento: il primario non ha prodotto segnali eseguibili")
    events = pd.concat(frames).sort_index(level="ts", kind="stable")
    if hmm is True:
        hmm = fit_hmm(universe, **(hmm_kwargs or {}))
    if hmm:
        events = add_regime_features(events, universe, hmm)
        events.attrs["hmm"] = hmm
    return events


def t1_series(events: pd.DataFrame) -> pd.Series:
    """t1 indicizzato per istante di segnale (come richiesto da PurgedKFold / MetaModel.fit)."""
    return pd.Series(events["t1"].to_numpy(), index=events.index.get_level_values("ts"), name="t1")
