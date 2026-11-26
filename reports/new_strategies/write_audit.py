"""Builds reports/NEW_STRATEGIES_POTENTIAL_AUDIT.md from reports/new_strategies/results.json.

    python reports/new_strategies/write_audit.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = json.loads((ROOT / "reports" / "new_strategies" / "results.json").read_text())


def f(x, d=2, pct=False):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x * 100:.{d}f}%" if pct else f"{x:.{d}f}"


def table(variants: dict, beta: bool) -> list:
    L = ["| variante | trade | win% | payoff | E/trade | E (R) | PF | Sharpe netto | Sharpe beta-adj | max DD | DSR | TP1% | uscite |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in variants.items():
        if not v.get("n_trades"):
            L.append(f"| {k} | 0 | | | | | | | | | | | |")
            continue
        ex = ", ".join(f"{a} {b}" for a, b in sorted((v.get("exits") or {}).items(), key=lambda kv: -kv[1]))
        L.append(f"| {k} | {v['n_trades']} | {f(v['win_rate'], 1, True)} | {f(v['payoff'])} | {f(v['expectancy'], 3, True)} | "
                 f"{f(v.get('expectancy_r'))} | {f(v['profit_factor'])} | {f(v.get('net_sharpe'))} | "
                 f"{f(v.get('excess_sharpe')) if beta else '—'} | {f(v.get('net_max_drawdown'), 2, True)} | {f(v.get('dsr'), 3)} | "
                 f"{f(v.get('tp1_rate'), 0, True)} | {ex} |")
    return L


def main():
    b = RES["bybit_post_liq_reversal"]
    a = RES["alpaca_in_play_momentum"]
    L = ["# Audit del potenziale: BYBIT_POST_LIQ_REVERSAL e ALPACA_IN_PLAY_MOMENTUM", "",
         "Protocollo: `reports/PREREG_NEW_STRATEGIES.md` (commit 5aac5a2, prima di ogni backtest). Codice delle regole: "
         "`services/strategy_engines_service.py` §8 (solo lab/shadow); backtest: `quant/research/new_strategies/`; dati grezzi "
         "dei trade: `reports/new_strategies/*.csv.gz`; numeri: `reports/new_strategies/results.json`.", "",
         "## Verdetto in breve", "",
         f"| strategia | trade nel periodo | frequenza | verdetto pre-registrato |", "|---|---|---|---|",
         f"| BYBIT_POST_LIQ_REVERSAL | {b['variants']['a_spec_active']['n_trades']} in 2 anni (10 perp) | "
         f"{b['frequency_per_month']:.2f} trade/mese | **{b['recommendation']['verdict']}** |",
         f"| ALPACA_IN_PLAY_MOMENTUM | {a['variants']['a_active']['n_trades']} in {a['n_sessions_evaluated']} sedute | "
         f"{a['frequency_per_month']:.1f} trade/mese | **{a['recommendation']['verdict']}** |", "",
         "Nessuna delle due ha dati sufficienti per un giudizio statistico. I numeri **non** giustificano di per sé l'avvio dei",
         "6 mesi di paper come validazione: per la strategia crypto il problema è strutturale (troppo rara, vedi sotto); per",
         "quella azionaria serve prima un backtest su 2+ anni di barre 5m (script pronto, chiavi Alpaca sul server). Le due",
         "strategie sono comunque installate nel lab in paper, senza capitale reale: raccolgono dati senza rischio.", "",
         "## 1. BYBIT_POST_LIQ_REVERSAL (15m, 10 perp, " + f"{b['period'][0]} → {b['period'][1]})", "",
         "Costi: taker 0.055% per lato + slippage 5 bps in ingresso (dopo uno spike), 2 bps in uscita, 5 bps sugli stop.", ""]
    L += table(b["variants"], False)
    rj = b["rejects"]["a_spec_active"]
    L += ["", "### Imbuto dei segnali (variante a)", "",
          "Su ogni barra 15m con spike ≥ 2.5 ATR (condizione necessaria) si valuta il resto della regola:", "",
          "| esito | barre |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(rj.items(), key=lambda kv: -kv[1])]
    L += [f"| **TRIGGERED** | **{b['variants']['a_spec_active']['n_trades']}** |", "",
          "- **Il funding estremo è il filtro che decide**: il 91% degli spike cade fuori dal 5% estremo del funding a 30 giorni.",
          "  Il funding Binance resta spesso fermo al valore base (0.01%), quindi molti print sono identici e il percentile",
          "  supera 95 solo quando il funding si discosta davvero dal valore base.",
          "- Con tutte e quattro le condizioni la strategia scatta **~3 volte l'anno su 10 simboli**: anche 6 mesi di paper",
          "  produrrebbero 1-2 trade, cioè nessuna informazione. È il risultato principale: la specifica è troppo restrittiva",
          "  per essere validata, sia sul passato sia in paper.",
          "- Le 4 varianti (specifica / speculare × uscite attive / fisse) hanno tutte meno di 11 trade; il controllo casuale",
          "  con le stesse uscite ne ha 6. Nessun confronto è informativo. PBO = "
          f"{f(b['pbo']['pbo'], 3)} su {b['pbo']['n_configs']} varianti: con così pochi trade non significa nulla.",
          "- **Rischio per trade molto disomogeneo**: SL = estremo dello spike ± 0.25 ATR dà rischi da 0.03% (BTC, con costi",
          "  ~0.2% il trade vale -7.4R) a 7.1% (DOGE). La media in R è quindi distorta; vale il rendimento %. Rifinitura",
          "  proposta: rischio minimo 0.5 ATR e massimo 3 ATR.",
          "- Riferimento passivo: BTC sullo stesso periodo +9.95%, Sharpe 0.34, max DD -53%. Riferimento strategie live attuali:",
          "  la replica dei motori crypto del bot sul periodo nov 2025 → ott 2026 perde il 52% (Sharpe -2.97,",
          "  `reports/METALABELING_KELLY_AUDIT.md`, branch `feat/quant-metalabeling-kelly`).", "",
          "**Cosa rifinire (nuova pre-registrazione, conta come prova in più)**: percentile del funding 90/10 invece di 95/5,",
          "OI z ≤ -1.5, timeframe 5m, universo più ampio (es. i 30 perp più liquidi) per arrivare ad almeno 100 eventi in 2 anni;",
          "in alternativa sostituire il funding con il rapporto long/short dei top trader (disponibile nello stesso file metrics).", "",
          f"## 2. ALPACA_IN_PLAY_MOMENTUM (5m, 8 titoli, {a['period'][0]} → {a['period'][1]})", "",
          f"Dati Yahoo 5m: {a['n_sessions_evaluated']} sedute valutabili dopo 20 di riscaldamento per l'RVOL; giorni con almeno "
          f"un titolo In Play: {a['days_with_picks']}. Costi: spread + slippage 3 bps per lato, +3 bps sugli stop.", ""]
    L += table(a["variants"], True)
    L += ["", "- **22 trade in 40 sedute: NON VALUTABILE.** E ≈ 0 (+0.01%/trade), PF 1.02, Sharpe beta-adjusted negativo.",
          "- **Il filtro In Play non migliora il controllo senza filtro** (stesse regole di ingresso/uscita su tutti gli 8 titoli,",
          "  302 trade): E +0.09%/trade, PF 1.25, Sharpe 3.25 netto / 2.26 beta-adjusted. Ma il periodo è di sole 8 settimane",
          "  e SPY ha perso il 6.2% (Sharpe -1.63): i numeri del controllo non sono generalizzabili.",
          "- Nel controllo gli ingressi PULLBACK rendono in media +0.36%/trade (106 trade), gli ORB -0.06% (196): indizio, non",
          "  prova, che il pullback sull'EMA9 sia la parte utile della regola di ingresso.",
          "- **E in R distorta**: la regola \"SL al lato opposto dell'opening range\" produce, sui pullback vicini al bordo del",
          "  range, rischi minuscoli (fino a 0.006% del prezzo, un trade a -15R). Il rendimento % è affidabile, la media in R no.",
          "  Rifinitura proposta: rischio minimo pari a 0.5 ATR(5m).", "",
          "## 3. Uscite attive contro uscite fisse (ablazione)", "",
          "| campione | uscite attive (50% a 1.5R + BE + trailing + time-stop) | uscite fisse (TP 2R) |", "|---|---|---|"]
    def short(v):
        return f"E {f(v['expectancy'], 3, True)}, PF {f(v['profit_factor'])}, WR {f(v['win_rate'], 0, True)}, n {v['n_trades']}"
    L += [f"| Bybit specifica | {short(b['variants']['a_spec_active'])} | {short(b['variants']['b_spec_fixed'])} |",
          f"| Alpaca In Play | {short(a['variants']['a_active'])} | {short(a['variants']['b_fixed'])} |",
          f"| Alpaca senza filtro (prova extra dichiarata) | {short(a['variants']['control_no_filter'])} | "
          f"{short(a['variants']['control_no_filter_fixed'])} |", "",
          "Sull'unico campione con numerosità sufficiente (302 trade) le uscite attive **non aggiungono valore atteso** rispetto",
          "al TP fisso a 2R: cambiano la forma della distribuzione (più vincenti piccoli, meno TP pieni) ma non l'aspettativa.", "",
          "## 4. Autopsia del journal esistente", "",
          "`quant/analyze_existing_journal.py` (sola lettura) raggruppa trade chiusi e segnali shadow per motore, broker, ora",
          "NY/Roma, VIX e regime macro, e i trade del lab per motivo di uscita. **La copia locale di `data/market_sentinel.db` è",
          "vuota** (creata dalla suite di test): il journal reale è sul server Oracle. Comando da eseguire lì:",
          "`python -m quant.analyze_existing_journal --db /app/data/market_sentinel.db --out reports/JOURNAL_AUTOPSY.md`.", "",
          "## 5. Cosa fare adesso", "",
          "1. **Alpaca**: rieseguire il backtest su 2+ anni di barre 5m dal server Oracle (le chiavi Alpaca sono lì):",
          "   `python -m quant.research.new_strategies.run --only alpaca --alpaca-source alpaca --start 2024-06-01 --end 2026-11-25`.",
          "   È l'unico modo per valutare davvero il filtro In Play. Se in quel test non batte il controllo senza filtro, va scartato.",
          "2. **Bybit**: con la specifica attuale non è validabile in tempi utili; se interessa, pre-registrare una versione meno",
          "   restrittiva (sopra) e testarla sugli stessi dati prima di qualsiasi paper.",
          "3. Il lab le fa già girare in paper (nessun capitale reale), con ogni segnale e ogni scarto nel journal: costa poco e",
          "   misura fill e costi reali. Promozione a capitale reale solo con i criteri di `docs/LAB.md`.", "",
          "## 6. Versione 1.1 (pre-registrata in `reports/PREREG_NEW_STRATEGIES_V1_1.md`, prima di ogni run)", "",
          "Modifiche: stop minimo 0.5 ATR per entrambe; Bybit funding 90/10, OI z ≤ -1.5, stop massimo 6 ATR, 20 perp.", "",
          "### BYBIT_POST_LIQ_REVERSAL v1.1 (20 perp, 2 anni)", ""]
    b1 = RES.get("bybit_post_liq_reversal_v1_1")
    if b1:
        L += table(b1["variants"], False)
        L += ["", f"Frequenza: {b1['frequency_per_month']:.2f} trade/mese. Verdetto pre-registrato: **{b1['recommendation']['verdict']}** "
              "(meno di 30 trade).", "",
              "- 24 trade: E +0.36%/trade con uscite attive (errore standard 0.39%, t = 0.92) e +0.61% con TP fisso 2R",
              "  (t = 1.21); il controllo casuale con le stesse uscite fa -0.18%. Direzione incoraggiante, **non significativa**.",
              "- Ritmo ~1 trade/mese su 20 simboli: 6 mesi di paper ≈ 6 trade. Servono ~2 anni di paper o un universo più ampio",
              "  per arrivare a 30-50 trade; la v1.1 è nel lab proprio per accumularli senza rischio.",
              "- Ancora una volta il TP fisso 2R non è peggiore delle uscite attive.", ""]
    a1 = RES.get("alpaca_in_play_momentum_v1_1")
    if a1:
        L += ["### ALPACA_IN_PLAY_MOMENTUM v1.1 (Yahoo 40 sedute, descrittivo)", ""] + table(a1["variants"], True)
        L += ["", "- Con lo stop minimo la media in R diventa coerente (-0.25R invece di -0.76R); E -0.12%/trade su 22 trade,",
              f"  sotto il controllo senza filtro (+0.09%): `in_play_beats_no_filter` = {a1.get('in_play_beats_no_filter')}.",
              "- Decisione rimandata al test su 2 anni di barre Alpaca (Fase 7 di `docs/ANTIGRAVITY_PROMPT_AUTONOMO.md`), che",
              "  applica automaticamente la regola pre-registrata (filtro scartato se non batte il controllo).", ""]
    L += ["## Avvertenze", "",
          "- Bybit è geo-bloccato da qui: prezzi, funding e open interest sono di Binance (proxy di ricerca); su Bybit i valori",
          "  differiscono (soprattutto funding e OI). Nel lab su Oracle si usano gli endpoint Bybit v5 con fallback Binance.",
          "- Nessun parametro è stimato sui dati: l'intero campione è fuori campione rispetto ai parametri; le metriche per",
          "  trimestre sono in `results.json`.",
          "- Prove dichiarate: v1.0 7 (4 Bybit + 2 Alpaca + 1 extra), v1.1 4, test Alpaca 2 anni 4: totale 15.", ""]
    (ROOT / "reports" / "NEW_STRATEGIES_POTENTIAL_AUDIT.md").write_text("\n".join(L) + "\n")
    print("ok")


if __name__ == "__main__":
    main()
