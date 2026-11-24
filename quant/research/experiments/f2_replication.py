"""
Replica pre-registrata del fattore F2 (carry del funding cross-sezionale) su un universo DISGIUNTO.
Stesse identiche regole di quant/portfolio/crypto_factors.py (nessun parametro cambiato).
Criterio di conferma (fissato prima di eseguire): Sharpe netto > 0.5, limite inferiore bootstrap > 0,
almeno 4 anni su 6 positivi. Include anche il DSR con varianza nulla teorica 1/T (sensibilita').
"""
import json, sys
import numpy as np, pandas as pd
import quant.portfolio.crypto_factors as cf
from quant.validation import deflated_sharpe_ratio

DISJOINT = ("ICP HBAR VET GRT SNX COMP YFI SUSHI 1INCH ZEC DASH KSM CHZ ENJ BAT ZIL IOTA ONT QTUM NEO "
            "WAVES KAVA BAND STORJ IMX STX FLOW EGLD ROSE AR APE GMT BLUR 1000PEPE WLD SEI TIA ORDI ENS LRC").split()

def main():
    assert not set(DISJOINT) & set(cf.SYMS if isinstance(cf.SYMS, (list, tuple)) else cf.SYMS.split()), "universo non disgiunto"
    cf.UNIVERSE = [s + "USDT" for s in DISJOINT]
    close, fund, missing = cf.load_data()
    close = close.loc["2021-01-01":"2026-10-31"]; fund = fund.reindex(close.index)
    res = cf.run_factor(close, fund, cf.weekly_weights(close, fund, "F2"))
    r = res["net"].dropna()
    sh = r.mean() / r.std(ddof=1) * np.sqrt(52)
    lo, hi = cf.boot_sharpe_ci(r.values)
    yrs = (1 + r).groupby(r.index.year).prod() - 1
    T = len(r)
    dsr_null = float(deflated_sharpe_ratio(r.values, 100, 1.0 / T))
    out = dict(universe=DISJOINT, missing=missing, n_loaded=int(close.shape[1]), weeks=T, sharpe=float(sh),
               boot_ci95=[float(lo), float(hi)], years={int(k): float(v) for k, v in yrs.items()},
               years_pos=int((yrs > 0).sum()), cagr=float((1 + r).prod() ** (52 / T) - 1),
               maxdd=float(((1 + r).cumprod() / (1 + r).cumprod().cummax() - 1).min()),
               sharpe_post2023=float(r.loc["2023":].mean() / r.loc["2023":].std(ddof=1) * np.sqrt(52)),
               dsr_n100_null_var=dsr_null)
    out["confirmed"] = bool(sh > 0.5 and lo > 0 and out["years_pos"] >= 4)
    print(json.dumps(out, indent=1))
    return out

if __name__ == "__main__":
    main()
