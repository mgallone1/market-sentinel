import sys; sys.path.insert(0,"/home/user/market-sentinel")
import numpy as np, pandas as pd
from quant.core import crypto_perp
from quant.data import load_bars
from quant.strategies import get_strategy
from quant.backtest import run_backtest, LEGACY_BOT_RULES, ExitRules
SY=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","LINKUSDT","AVAXUSDT","ADAUSDT","DOGEUSDT","SUIUSDT","NEARUSDT"]
st,en="2023-11-01","2026-11-01"
def run(strat, iv, rules, params={}):
    bench=load_bars(crypto_perp("BTCUSDT","binance"),iv,st,en)
    out={}
    for inv in (1,-1):
        T=[]
        for s in SY:
            b=bench if s=="BTCUSDT" else load_bars(crypto_perp(s,"binance"),iv,st,en)
            sig=get_strategy(strat,**params)(b,crypto_perp(s,"binance"),iv,{"benchmark":bench})*inv
            T.append(run_backtest(b,sig.to_frame("side"),crypto_perp(s,"bybit"),rules,iv).trades)
        t=pd.concat(T); g=t.gross_pnl/t.notional; n=t.ret_net
        out[inv]=(len(t),(n>0).mean(),g.mean(),n.mean(),n.std()/np.sqrt(len(n)))
    return out
cases=[("legacy","1h",LEGACY_BOT_RULES),("donchian_breakout","1h",ExitRules(sl_atr=1.5,tp_atr=3.0,max_hold_bars=48)),
       ("tsmom","4h",ExitRules(sl_atr=1.5,tp_atr=3.0,max_hold_bars=30)),("meanrev_z","1h",ExitRules(sl_atr=1.5,tp_atr=3.0,max_hold_bars=48))]
print(f"{'strategia':18s} {'verso':9s} trade   win    lordo/trade  netto/trade (±SE)")
for s,iv,r in cases:
    o=run(s,iv,r)
    for inv,lab in ((1,"originale"),(-1,"INVERSA")):
        n,w,g,m,se=o[inv]; print(f"{s:18s} {lab:9s} {n:6d} {w:6.1%}  {g*100:+.3f}%     {m*100:+.3f}% (±{se*100:.3f})")
