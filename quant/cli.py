"""CLI: python -m quant.cli {fetch,backtest,research,train-gate} ..."""
from __future__ import annotations

import argparse
import json
import logging
import sys

import numpy as np
import pandas as pd

from quant.backtest import LEGACY_BOT_RULES, ExitRules, run_portfolio
from quant.core import AssetSpec, crypto_perp, equity, index, interval_to_hours

CRYPTO = "BTC ETH SOL XRP LINK AVAX ADA DOGE SUI NEAR".split()
EQUITIES = "SPY QQQ AAPL MSFT NVDA AMZN GOOGL META TSLA JPM".split()
INDICES = ["^GSPC", "^NDX", "^STOXX50E"]


def make_spec(sym: str) -> AssetSpec:
    if sym.endswith("USDT"):
        return crypto_perp(sym)
    return index(sym) if sym.startswith("^") else equity(sym)


def resolve_universe(name: str) -> tuple[list[AssetSpec], str | None]:
    """-> (specs, simbolo benchmark)."""
    if name == "crypto":
        return [crypto_perp(c + "USDT") for c in CRYPTO], "BTCUSDT"
    if name == "equities":
        return [equity(s) for s in EQUITIES], "SPY"
    if name == "indices":
        return [index(s) for s in INDICES], None
    syms = [s.strip() for s in name.split(",") if s.strip()]
    specs = [make_spec(s) for s in syms]
    return specs, specs[0].benchmark if specs else None


DEFAULT_HOLD = {"1h": 48, "4h": 30, "1d": 20}   # max_hold_bars di default per intervallo


def make_rules(name: str, interval: str, flatten_eod: bool = False) -> ExitRules:
    if name == "legacy":
        return LEGACY_BOT_RULES
    hold = DEFAULT_HOLD.get(interval, 48)
    return ExitRules(sl_atr=1.5, tp_atr=3.0, max_hold_bars=hold, flatten_eod=flatten_eod)


def load_universe(args):
    """-> (universe sym->(bars,spec), benchmark_bars|None)."""
    from quant.data import generate_bars, load_bars
    specs, bsym = resolve_universe(args.universe)
    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.now(tz="UTC").normalize()
    start = pd.Timestamp(args.start) if args.start else end - pd.Timedelta(days=730)
    uni, bench = {}, None
    for i, sp in enumerate(specs):
        try:
            bars = (generate_bars(args.n_synth, args.interval, seed=i + 1, start=str(start.date()))
                    if args.synthetic else load_bars(sp, args.interval, start, end))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {sp.symbol}: {e}", file=sys.stderr)
            continue
        if len(bars):
            uni[sp.symbol] = (bars, sp)
    if not uni:
        raise SystemExit("nessun dato caricato")
    if bsym:
        if bsym in uni:
            bench = uni[bsym][0]
        elif not args.synthetic:
            try:
                bench = load_bars(make_spec(bsym), args.interval, start, end)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] benchmark {bsym}: {e}", file=sys.stderr)
        else:
            bench = next(iter(uni.values()))[0]
    return uni, bench


def _bars_per_day(uni) -> float:
    idx = None
    for b, _ in uni.values():
        idx = b.index if idx is None else idx.union(b.index)
    days = max((idx[-1] - idx[0]).total_seconds() / 86400, 1.0)
    return len(idx) / days


def _common(p):
    p.add_argument("--universe", default="crypto", help="crypto|equities|indices|SYM,SYM")
    p.add_argument("--interval", default="1h")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--synthetic", action="store_true", help="dati sintetici offline (demo)")
    p.add_argument("--n-synth", type=int, default=6000)


def _strategy_args(p):
    p.add_argument("--strategy", required=True)
    p.add_argument("--rules", default="default", choices=["legacy", "default"])
    p.add_argument("--flatten-eod", action="store_true")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m quant.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    _common(p)
    p = sub.add_parser("backtest")
    _common(p)
    _strategy_args(p)
    p = sub.add_parser("research")
    _common(p)
    _strategy_args(p)
    p.add_argument("--kinds", default="base_rate,gbm_montecarlo,logit,hgb,rf,ensemble")
    p.add_argument("--train-days", type=float, default=240)
    p.add_argument("--test-days", type=float, default=60)
    p.add_argument("--embargo-days", type=float, default=2)
    p.add_argument("--threshold", default="breakeven")
    p.add_argument("--sizing", default="kelly", choices=["kelly", "fixed"])
    p.add_argument("--no-ablation", action="store_true")
    p.add_argument("--out")
    p = sub.add_parser("train-gate")
    _common(p)
    _strategy_args(p)
    p.add_argument("--kind", default="hgb")
    p.add_argument("--report", help="report.json della ricerca da cui ereditare il verdetto")
    p.add_argument("--out")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("quant.research.walkforward").setLevel(logging.INFO)
    uni, bench = load_universe(a)

    if a.cmd == "fetch":
        for s, (b, _) in uni.items():
            print(f"{s}: {len(b)} barre {b.index[0]} -> {b.index[-1]}")
        return 0

    from quant.research.dataset import primary_side
    rules = make_rules(a.rules, a.interval, a.flatten_eod)
    print(f"ExitRules effettive ({a.rules}, {a.interval}): {rules!r}", file=sys.stderr, flush=True)

    if a.cmd == "backtest":
        port = {}
        for s, (b, sp) in uni.items():
            side = primary_side(a.strategy, b, sp, a.interval, None if b is bench else bench)
            port[s] = (b, pd.DataFrame({"side": side}), sp)
        res = run_portfolio(port, rules, a.interval)
        print(json.dumps({k: v for k, v in res.metrics.items() if not isinstance(v, dict)}, indent=2, default=str))
        return 0

    if a.cmd == "research":
        from quant.research import run_walkforward, write_report
        bpd = _bars_per_day(uni)
        thr = a.threshold if a.threshold == "breakeven" else float(a.threshold)
        res = run_walkforward(uni, a.interval, a.strategy, rules, tuple(a.kinds.split(",")),
                              train_bars=int(a.train_days * bpd), test_bars=int(a.test_days * bpd),
                              embargo_bars=max(int(a.embargo_days * bpd), rules.max_hold_bars),
                              threshold=thr, sizing=a.sizing, benchmark=bench, ablation=not a.no_ablation)
        out = a.out or f"reports/{a.strategy}"
        d = write_report(res, out, a.strategy)
        print(f"{d['verdict']}\nreport: {out}/report.json, {out}/report.md")
        return 0

    if a.cmd == "train-gate":
        from quant.live.gate import train_gate
        rep = json.load(open(a.report)) if a.report else None
        g = train_gate(uni, a.interval, a.strategy, rules, a.kind, bench, rep)
        out = a.out or f"models/{a.strategy}.pkl"
        import os
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        g.save(out)
        print(f"gate salvato: {out} | deployable={g.deployable} | verdict={g.meta['verdict']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
