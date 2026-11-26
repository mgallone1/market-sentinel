"""Runs both pre-registered backtests and writes reports/new_strategies/results.json + the audit report.

python -m quant.research.new_strategies.run [--only bybit|alpaca] [--alpaca-source yahoo|alpaca --start ... --end ...]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

import pandas as pd

from . import common as cm

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports" / "new_strategies"


def _clean(o):
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def evaluate(res: dict, tz: str, periods: float, main: str, control: str, beta_adj: bool, n_trials_names) -> dict:
    trades = res["trades"]
    allt = [t for t in trades.values() if len(t)]
    if not allt:
        return {"variants": {}, "note": "nessun trade"}
    t0 = min(pd.DatetimeIndex(t["exit_time"]).min() for t in allt).tz_convert(tz).normalize().tz_localize(None)
    t1 = max(pd.DatetimeIndex(t["exit_time"]).max() for t in allt).tz_convert(tz).normalize().tz_localize(None)
    bench = res["bench_daily"]
    cal = bench.loc[t0:t1].index if tz != "UTC" else pd.date_range(t0, t1, freq="D")
    daily, out = {}, {}
    for name, t in trades.items():
        d = cm.daily_series(t, cal, tz)
        exc = cm.beta_adjusted(d, bench) if beta_adj else d
        st = {**cm.trade_stats(t), **{f"net_{k}": v for k, v in cm.series_stats(d, periods).items()},
              **{f"excess_{k}": v for k, v in cm.series_stats(exc, periods).items()}, "quarters": cm.by_quarter(t)}
        out[name] = st
        if name in n_trials_names:
            daily[name] = exc
    dp = cm.dsr_and_pbo(daily)
    for name in daily:
        out[name]["dsr"] = dp[name]["dsr"]
    m = out.get(main, {})
    ctrl = out.get(control, {}).get("expectancy")
    rec = cm.recommend(m, ctrl, m.get("quarters", []), m.get("dsr", float("nan"))) if m.get("n_trades") else \
        {"verdict": "NON VALUTABILE", "criteria": {"n_trades>=30": False}}
    span_days = max((t1 - t0).days, 1)
    return {"variants": out, "pbo": dp["_pbo"], "recommendation": rec,
            "frequency_per_month": (m.get("n_trades", 0) / span_days * 30.4) if m else 0.0,
            "period": [str(t0.date()), str(t1.date())]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["bybit", "alpaca"])
    ap.add_argument("--version", default="1.0", choices=["1.0", "1.1", "both"])
    ap.add_argument("--alpaca-source", default="yahoo", choices=["yahoo", "alpaca"])
    ap.add_argument("--start")
    ap.add_argument("--end")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "results.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    versions = ["1.0", "1.1"] if a.version == "both" else [a.version]
    if a.only in (None, "bybit"):
        from . import postliq
        for ver in versions:
            r = postliq.run(ver)
            names = list(r["trades"])
            ev = evaluate(r, "UTC", 365.0, "a_spec_active", "control_random", False,
                          [n for n in names if n != "control_random"])
            ev["rejects"] = r["rejects"]
            sfx = "" if ver == "1.0" else "_v1_1"
            results["bybit_post_liq_reversal" + sfx] = ev
            for k, t in r["trades"].items():
                if len(t):
                    t.to_csv(OUT / f"bybit{sfx}_{k}.csv.gz", index=False)
            path.write_text(json.dumps(_clean(results), indent=2, default=str))
    if a.only in (None, "alpaca"):
        from . import inplay
        bars = None
        for ver in versions:
            r = inplay.run(a.alpaca_source, a.start, a.end, version=ver, bars=bars)
            bars = r.pop("bars")
            ev = evaluate(r, "America/New_York", 252.0, "a_active", "control_no_filter", True, ["a_active", "b_fixed"])
            ev.update({"n_sessions_evaluated": r["n_sessions_evaluated"], "source": r["source"],
                       "days_with_picks": sum(1 for s in r["selections"] if s["n_qualified"] > 0),
                       "selections": r["selections"], "version": ver})
            ctrl = ev["variants"].get("control_no_filter", {}).get("expectancy")
            main_e = ev["variants"].get("a_active", {}).get("expectancy")
            ev["in_play_beats_no_filter"] = bool(ctrl is not None and main_e is not None and main_e > ctrl)
            sfx = ("" if ver == "1.0" else "_v1_1") + ("_alpaca" if a.alpaca_source == "alpaca" else "")
            results["alpaca_in_play_momentum" + sfx] = ev
            for k, t in r["trades"].items():
                if len(t):
                    t.to_csv(OUT / f"alpaca{sfx}_{k}.csv.gz", index=False)
            path.write_text(json.dumps(_clean(results), indent=2, default=str))
    logging.info("scritto %s", path)


if __name__ == "__main__":
    main()
