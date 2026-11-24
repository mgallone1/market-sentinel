import sys; sys.path.insert(0,"/home/user/market-sentinel")
import numpy as np, pandas as pd, yfinance as yf
from quant.portfolio.run_experiment import load, CRYPTO, six_forty
from quant.portfolio.tsmom import tsmom_weights, n_active
from quant.portfolio.backtest import run_weights, block_bootstrap_sharpe_diff
from quant.validation import deflated_sharpe_ratio
df,_=load(); crypto={c for c in CRYPTO if c in df.columns}
cost=pd.Series({c:(10.0 if c in crypto else 2.0) for c in df.columns}); borrow=pd.Series({c:(0.0 if c in crypto else 0.01) for c in df.columns})
irx=yf.download("^IRX",start="2005-01-01",progress=False)["Close"]; irx=irx.iloc[:,0] if isinstance(irx,pd.DataFrame) else irx
irx.index=pd.DatetimeIndex(irx.index).tz_localize("UTC") if irx.index.tz is None else irx.index
rf=(irx.reindex(df.index,method="ffill").ffill().bfill()/100/252)   # tasso giornaliero
na=n_active(df); start=na[na>=10].index[0]
def fin(res):
    cash=1-res.weights.sum(axis=1)
    f=np.where(cash>=0, cash*rf, cash*(rf+0.005/252))   # liquidita' rende rf; leva paga rf+0.5%
    return res.net+pd.Series(f,index=res.net.index)
R={}; lev={}
for mode in ("long_short","long_only","risk_parity"):
    for fr in (("weekly","monthly") if mode!="risk_parity" else ("weekly",)):
        res=run_weights(df,tsmom_weights(df,crypto,fr,mode),cost,borrow)
        k=f"{mode}_{fr}"; R[k]=fin(res); lev[k]=(res.weights.abs().sum(axis=1).loc[start:].mean(), res.weights.sum(axis=1).loc[start:].mean())
R["60_40"]=six_forty(df); R["SPY"]=df["SPY"].ffill().pct_change().fillna(0.0)
R={k:v.loc[start:] for k,v in R.items()}; rfs=rf.loc[start:]
def sh(r): x=r-rfs; return x.mean()/x.std()*np.sqrt(252)
print(f"{'strategia':22s} CAGR   excess-Sharpe  post2013  maxDD   lev_gross lev_net")
for k,r in R.items():
    eq=(1+r).cumprod(); dd=(eq/eq.cummax()-1).min(); cagr=eq.iloc[-1]**(252/len(r))-1
    p=r.loc["2013":]; s13=((p-rfs.loc["2013":]).mean()/(p-rfs.loc["2013":]).std()*np.sqrt(252))
    lg,ln=lev.get(k,(np.nan,np.nan))
    pass #*100:5.1f}%  {sh(r):6.2f}        {s13:5.2f}   {dd*100:6.1f}%  {lg:5.2f}   {ln:5.2f}")
ex={k:(R[k]-rfs) for k in R}
var_sr=np.var([ex[k].mean()/ex[k].std() for k in ("long_short_weekly","long_short_monthly","long_only_weekly","long_only_monthly")])
for k in ("long_short_weekly","long_short_monthly","long_only_weekly","long_only_monthly"):
    dsr=deflated_sharpe_ratio(ex[k].to_numpy(),4,var_sr)
    blend=0.5*ex[k]+0.5*ex["risk_parity_weekly"]
    ci=block_bootstrap_sharpe_diff(blend.to_numpy(),ex["risk_parity_weekly"].to_numpy())
    p=ex[k].loc["2013":]; s13=p.mean()/p.std()*np.sqrt(252)
    keep=(dsr>0.95) and (s13>0) and (ci[1]>0)
    print(f"{k:22s} DSR {dsr:.3f}  post2013 {s13:.2f}  blend-RP diff {ci[0]:+.3f} CI95 [{ci[1]:+.3f},{ci[2]:+.3f}]  -> {'KEEP' if keep else 'DISCARD'}")
