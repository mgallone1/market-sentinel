"""Genera report.md (italiano) da report.json."""
import json

r = json.load(open('reports/tsmom_multiasset/report.json'))
M, C, Y, V, T = r['metrics'], r['crisis'], r['yearly'], r['verdicts'], r['turnover_cost']
ks = list(M)
p = lambda x: f"{x*100:.1f}%"  # noqa: E731
o = ["# TSMOM multi-asset: test pre-registrato\n\n"]
o.append(f"Finestra 'full': {r['start_full']} .. {r['end']} (prima data con >=10 asset attivi, cioe' con 252 giorni di storia). Post-pubblicazione: 2013-01-01 .. fine. Parametri fissi dalla letteratura (Moskowitz-Ooi-Pedersen 2012, Hurst-Ooi-Pedersen 2017), nessuna calibrazione. Codice: `quant/portfolio/` (`python -m quant.portfolio.run_experiment`).\n\n")
o.append("""## Ipotesi e specifiche
- Segnale: media dei segni dei rendimenti 21/63/252 giorni (chiusure fino a t); 0 se storia < 252 giorni.
- Peso: segnale x (0,40/sigma) / N_attivi; sigma = vol EWMA (com=60), annualizzata sqrt(252) per ETF e sqrt(365) per crypto, calcolata su rendimenti dei giorni lavorativi come da specifica (per le crypto sovrastima la vol di circa sqrt(365/252); il vol targeting di portafoglio riporta il livello totale al 10% ma i pesi relativi restano sottopesati sulle crypto).
- Vol targeting: scala i pesi per vol ex-ante di portafoglio 10% con covarianza campionaria a 252g (as of t); leva lorda massima 2,0.
- Ribilanciamento: settimanale (ultimo giorno lavorativo della settimana) o mensile; pesi target costanti tra i ribilanciamenti (senza drift); banda no-trade: salta se |dw| < 0,10 |w_nuovo|.
- Esecuzione: pesi decisi a close t, applicati da close t a close t+1. Calendario: unione dei giorni lavorativi lun-ven; festivi ETF = rendimento 0; i rendimenti crypto del weekend si compongono nel lunedi'.
- Costi: ETF 2 bps one-way su |dw| + borrow 1%/anno sui corti; crypto 10 bps one-way, costo di short 0 (gli short su perp spesso RICEVONO funding: ignorato, nota). Tasso cash/finanziamento: 0.
- Benchmark: risk_parity (solo long, segnale +1, stesso sizing, settimanale); 60/40 SPY/IEF ribilanciato a fine mese con drift (2 bps); SPY buy&hold (senza costi).
- Regola KEEP (tutte): (a) DSR > 0,95 sulla finestra full con n_trials=4 (varianza dello Sharpe giornaliero tra le 4 varianti = VARSR); (b) Sharpe > 0 post-2013; (c) blend 50/50 giornaliero variante/risk_parity con Sharpe maggiore di risk_parity da solo, CI95 bootstrap (blocchi stazionari, media 20gg, 2000 repliche) della differenza > 0.

""".replace("VARSR", f"{r['var_sr_trials']:.2e}"))
o.append(f"## Universo effettivamente usato\n{', '.join(r['universe_used'])}. Asset scartati per errore di download: {r['dropped'] or 'nessuno'}.\nPrime date Yahoo successive al 2005: " + ", ".join(f"{k} {v}" for k, v in r['first_date'].items() if v > '2005-06-01') + ".\n\n")


def tab(w):
    s = "| Strategia | CAGR | Vol | Sharpe | Sortino | MaxDD | Calmar | Skew | Peggior mese | % mesi+ | Corr SPY |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
    for k in ks:
        m = M[k][w]
        s += f"| {k} | {p(m['cagr'])} | {p(m['vol'])} | {m['sharpe']:.2f} | {m['sortino']:.2f} | {p(m['maxdd'])} | {m['calmar']:.2f} | {m['skew']:.2f} | {p(m['worst_month'])} | {p(m['pct_pos_months'])} | {m['corr_bench']:.2f} |\n"
    return s


o.append("## Metriche, finestra full (netto)\n" + tab('full'))
o.append("\n## Metriche, post-2013\n" + tab('post2013'))
o.append("\n## Turnover e costi (finestra full)\n| Variante | Turnover annuo (somma abs dw) | Costi+borrow annui | Sharpe lordo | Sharpe netto | Leva lorda media |\n|---|---|---|---|---|---|\n")
for k, t in T.items():
    o.append(f"| {k} | {t['turnover_ann']:.1f} | {p(t['cost_drag_ann'])} | {t['gross_sharpe']:.2f} | {M[k]['full']['sharpe']:.2f} | {t['avg_gross_lev']:.2f} |\n")
cs = list(C[ks[0]])
o.append("\n## Finestre di crisi (rendimento cumulato)\n| Strategia | " + " | ".join(cs) + " |\n|---|" + "---|" * len(cs) + "\n")
for k in ks:
    o.append(f"| {k} | " + " | ".join(p(C[k][c]) for c in cs) + " |\n")
yrs = sorted({int(y) for k in ks for y in Y[k]})
o.append("\n## Rendimenti per anno solare (2006 e 2026 parziali)\n| Anno | " + " | ".join(ks) + " |\n|---|" + "---|" * len(ks) + "\n")
for y in yrs:
    o.append(f"| {y} | " + " | ".join(p(Y[k][str(y)]) if str(y) in Y[k] else '' for k in ks) + " |\n")
o.append("\n## DSR, bootstrap e verdetto (4 prove)\n| Variante | DSR (a: >0,95) | Sharpe post-2013 (b: >0) | Sharpe blend con RP | Delta Sharpe blend-RP | CI95 (c: >0) | CI95 Delta Sharpe variante-SPY | Verdetto | Criteri falliti |\n|---|---|---|---|---|---|---|---|---|\n")
for k, v in V.items():
    o.append(f"| {k} | {v['dsr']:.3f} | {v['sharpe_post2013']:.2f} | {v['blend_sharpe']:.2f} | {v['blend_minus_rp_sharpe']:.2f} | [{v['ci95'][0]:.2f}, {v['ci95'][1]:.2f}] | [{v['vs_spy_sharpe_diff_ci95'][0]:.2f}, {v['vs_spy_sharpe_diff_ci95'][1]:.2f}] | {v['verdict']} | {','.join(v['failed']) or '-'} |\n")
o.append("""
## Lettura (solo fatti)
- Regola pre-registrata: una sola variante su 4 (long_only_monthly) soddisfa tutti i criteri; long_only_weekly passa (a) e (b) ma non (c); le due long_short falliscono (a) e (c).
- Le long_short hanno Sharpe netto inferiore a risk_parity sull'intera finestra (0,35 e 0,55 vs 0,65), correlazione con SPY negativa e rendimenti positivi in tutte e tre le finestre di crisi; Sharpe post-2013 0,26 e 0,53.
- Nessuna variante ha uno Sharpe significativamente diverso da SPY buy&hold (CI95 della differenza include 0 in tutti i casi). Post-2013: SPY 0,87; 60/40 0,92; long_only_monthly 0,86.
- Mensile > settimanale in entrambe le coppie; il turnover settimanale costa piu' del mensile (vedi tabella costi). Il verdetto KEEP e' ottenuto su un solo campione storico; il limite inferiore del CI95 del blend e' 0,02, vicino a 0; long_only_monthly ha correlazione con SPY 0,27 (full) e 0,44 (post-2013).

## Caveat
- Sopravvivenza/inception: ETF attuali scelti con conoscenza ex post; entrano alle date di lancio (HYG, UUP, FXY nel 2007, ecc.), quindi 2006-2007 usa un universo ristretto; le crypto entrano dal 2014/2017 e la loro inclusione e' una scelta ex post.
- Yahoo adjusted close: serie aggiustate per dividendi/split, non esattamente tradabili, soggette a revisioni. Futures veri (roll, margini) non modellati: ETF come proxy (USO/DBC/DBA hanno roll/contango interno).
- Tasso di finanziamento/cash = 0 e leva fino a 2x senza costo di finanziamento: sovrastima i rendimenti, in particolare dal 2022 con tassi alti.
- Crypto: costo short 0 (il funding reale puo' essere positivo o negativo); 10 bps one-way possono essere ottimistici in stress; vol annualizzata con sqrt(365) su rendimenti dei soli giorni lavorativi (specifica).
- Pesi senza drift infra-periodo; esecuzione a close senza slippage di apertura ne' impatto di mercato.
- Potenza limitata del bootstrap (circa 21 anni); i DSR contano 4 prove, non la ricerca storica da cui provengono i parametri.
""")
open('reports/tsmom_multiasset/report.md', 'w').write("".join(o))
