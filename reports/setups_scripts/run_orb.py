"""ORB su equities 5m (~60gg Yahoo): backtest semplice senza ML. SL = 1 ATR (approssimazione del midpoint del
range), TP = 2R, flatten a fine sessione. Confronto con always_long (flatten_eod) sugli stessi simboli/periodo."""
import json
import sys
from argparse import Namespace

import pandas as pd

from quant.backtest import ExitRules, run_portfolio
from quant.cli import load_universe
from quant.research.dataset import primary_side

end = pd.Timestamp.now(tz="UTC").normalize()
a = Namespace(universe="equities", interval="5m", start=str((end - pd.Timedelta(days=58)).date()), end=str(end.date()),
              synthetic=False, n_synth=0)
uni, bench = load_universe(a)
rules = ExitRules(sl_atr=1.0, tp_atr=None, tp_rr=2.0, max_hold_bars=78, flatten_eod=True)
out = {"period": [a.start, a.end], "symbols": sorted(uni)}
for name in ("orb", "always_long"):
    port = {}
    for s, (b, sp) in uni.items():
        side = primary_side(name, b, sp, "5m", None if b is bench else bench)
        port[s] = (b, pd.DataFrame({"side": side}), sp)
    res = run_portfolio(port, rules, "5m")
    out[name] = {k: v for k, v in res.metrics.items() if not isinstance(v, dict)}
json.dump(out, open("reports/setups_orb_5m.json", "w"), indent=2, default=str)
print(json.dumps(out, indent=1, default=str))
