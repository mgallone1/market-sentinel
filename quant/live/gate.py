"""MetaGate: filtro/sizing live basato sul modello secondario. Usa solo barre CHIUSE."""
from __future__ import annotations

import pickle
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from quant.core import interval_to_hours
from quant.features import regime_features
from quant.models import MetaModel, uniqueness_weights
from quant.research.dataset import (add_side_columns, bar_features, build_event_dataset, fit_hmm, t1_series)
from quant.research.walkforward import payoff_stats, size_fractions

NOT_DEPLOYABLE = "model not deployable"


def closed_bars(bars: pd.DataFrame, interval: str, now=None) -> pd.DataFrame:
    """Scarta l'eventuale barra ancora in formazione (open + durata > now)."""
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    dur = pd.Timedelta(hours=interval_to_hours(interval))
    return bars[bars.index + dur <= now]


class MetaGate:
    def __init__(self, model: MetaModel, hmm, columns: list, p_star: float, kelly: dict, meta: dict):
        self.model, self.hmm, self.columns = model, hmm, list(columns)
        self.p_star, self.kelly, self.meta = float(p_star), dict(kelly), dict(meta)

    @property
    def deployable(self) -> bool:
        return bool(self.meta.get("deployable", False))

    def save(self, path) -> None:
        with open(path, "wb") as f:
            pickle.dump(dict(version=1, model=self.model, hmm=self.hmm, columns=self.columns, p_star=self.p_star,
                             kelly=self.kelly, meta=self.meta), f)

    @classmethod
    def load(cls, path) -> "MetaGate":
        with open(path, "rb") as f:                      # solo file prodotti da save() e fidati
            d = pickle.load(f)
        return cls(d["model"], d["hmm"], d["columns"], d["p_star"], d["kelly"], d["meta"])

    def _features(self, bars, spec, interval, side, benchmark):
        F = bar_features(bars, spec, interval, benchmark, tuple(self.meta.get("extra_cols", ())))
        row = F.iloc[[-1]].copy()
        row["aux_mc_h"] = float(self.meta.get("max_hold_bars", 48))
        row = add_side_columns(row, [float(side)])
        row["side"] = float(side)
        if self.hmm is not None:
            R = regime_features(bars, self.hmm).iloc[[-1]]
            R["reg_trend_sa"] = R["reg_trend"].to_numpy() * float(side)
            row = row.join(R)
        return row

    def decide(self, bars, spec, interval, side, benchmark=None, force: bool = False, now=None) -> dict:
        out = dict(allow=False, p=float("nan"), p_star=self.p_star, size_frac=0.0, reason="")
        if not self.deployable and not force:
            out["reason"] = NOT_DEPLOYABLE
            return out
        if not side:
            out["reason"] = "no side"
            return out
        b = closed_bars(bars, interval, now)
        if len(b) < 50:
            out["reason"] = "insufficient closed bars"
            return out
        bm = None if benchmark is None else closed_bars(benchmark, interval, now)
        X = self._features(b, spec, interval, side, bm)
        p = float(self.model.predict_proba(X)[0])
        out["p"] = p
        if not self.deployable:
            out["reason"] = "forced (model not deployable)"
        if p <= self.p_star:
            out["reason"] = "p <= p*"
            return out
        k = self.kelly
        sz = float(size_fractions([p], k["payoff"], [X["aux_sigma_ann"].iloc[0]], k.get("sizing", "kelly"),
                                  k.get("lam", 0.25), k.get("cap", 0.25), k.get("vol_target", 0.30),
                                  k.get("fixed", 0.10))[0])
        out.update(allow=True, size_frac=sz, reason=out["reason"] or "p > p*")
        return out


def train_gate(universe: dict, interval: str, primary, rules, kind: str, benchmark=None, report: dict | None = None,
               sizing: str = "kelly", extra_cols=(), hmm_kwargs: dict | None = None, seed: int = 0,
               kelly: dict | None = None) -> MetaGate:
    """Fit su TUTTO lo storico; verdetto/deployable ereditati dal report di ricerca (se assente: non deployable)."""
    hmm = fit_hmm(universe, **(hmm_kwargs or {}))
    ev = build_event_dataset(universe, interval, primary, rules, benchmark, hmm=hmm, extra_cols=extra_cols)
    w = uniqueness_weights(ev).to_numpy()
    model = MetaModel(kind, seed=seed).fit(ev, ev["label"].to_numpy(float), t1_series(ev), w)
    ps = payoff_stats(ev["ret_net"])
    cols = list(getattr(model, "columns_", []))
    rep = report or {}
    dep = bool(rep.get("deployable")) and kind in (rep.get("deployable_kinds") or [])
    ts = ev.index.get_level_values("ts")
    meta = dict(kind=kind, interval=interval, symbols=list(universe), n_events=int(len(ev)),
                data_start=str(min(b.index[0] for b, _ in universe.values())),
                data_end=str(max(b.index[-1] for b, _ in universe.values())),
                events_start=str(ts.min()), events_end=str(ts.max()), base_rate=float(ev["label"].mean()),
                verdict=rep.get("verdict", "no research report: not deployable"), deployable=dep,
                trained_at=datetime.now(timezone.utc).isoformat(), max_hold_bars=int(rules.max_hold_bars),
                extra_cols=list(extra_cols), avg_win=ps["avg_win"], avg_loss=ps["avg_loss"])
    kp = dict(payoff=ps["payoff"], sizing=sizing, lam=0.25, cap=0.25, vol_target=0.30, fixed=0.10)
    kp.update(kelly or {})
    return MetaGate(model, hmm, cols, ps["p_star"], kp, meta)
