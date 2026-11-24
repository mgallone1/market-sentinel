"""Valutazione pre-registrata setup daily: stessi parametri di `quant.cli research` ma ExitRules fissate
(stop 2 ATR, target 2R = tp_atr 4, max_hold 20 barre). Un run per strategia, nessun tuning."""
import sys
from argparse import Namespace

from quant.backtest import ExitRules
from quant.cli import _bars_per_day, load_universe
from quant.research import run_walkforward, write_report

name = sys.argv[1]
kinds = tuple(sys.argv[2].split(",")) if len(sys.argv) > 2 else ("base_rate", "logit", "rf")
a = Namespace(universe="equities", interval="1d", start="2010-01-01", end="2026-11-24", synthetic=False, n_synth=0)
uni, bench = load_universe(a)
rules = ExitRules(sl_atr=2.0, tp_atr=4.0, max_hold_bars=20, flatten_eod=False)
bpd = _bars_per_day(uni)
res = run_walkforward(uni, "1d", name, rules, kinds, train_bars=int(1825 * bpd), test_bars=int(365 * bpd),
                      embargo_bars=max(int(2 * bpd), rules.max_hold_bars), threshold="breakeven", sizing="kelly",
                      benchmark=bench, ablation=True)
d = write_report(res, f"reports/setups_{name}_1d", name)
print(name, d["verdict"])
