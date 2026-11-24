# Griglia coperta sul petrolio (strategia storica dell'utente) — simulazione su dati reali

**Regola simulata:** a ogni attraversamento di un livello (passo 0,5 / 1 / 2 $) si apre 1 long e 1 short da 1 barile; ogni posizione si chiude a +1 passo; le perdenti restano aperte (`hold`) oppure si chiude tutto a fine giornata (`eod`). Costi: spread 0,04 $ per posizione, finanziamento overnight 0% o 5% annuo su ogni posizione aperta (long e short pagano entrambi, come sui CFD). Dati Yahoo: WTI (CL=F) giornaliero 2005–2026, Brent (BZ=F) giornaliero 2007–2026, WTI orario ultimi 2 anni. Codice: `quant/research/oil_grid.py`; tabella completa: `results.csv`. Valori in $ per 1 barile per livello (moltiplicare per la dimensione del lotto, es. ×100 o ×1000).

**Limite del test:** si usano solo i prezzi di chiusura delle barre, quindi gli attraversamenti dentro la barra non vengono visti. I guadagni realizzati sono sottostimati, soprattutto sui dati giornalieri. Il dato orario degli ultimi 2 anni è il più fedele.

## Il petrolio ritorna verso la media? (Brent, log-prezzi giornalieri)
- Coefficiente AR(1) −0,0028 → emivita ≈ 244 giorni (ritorno verso la media molto lento).
- Variance ratio 5g 0,98 · 20g 0,99 · 60g 1,21 · 250g 0,88 → alle scale da giorni a mesi è indistinguibile da una passeggiata casuale.
- Il range non è stabile: nel campione WTI va da 145,29 $ (luglio 2008) a −37,63 $ (20 aprile 2020).

## Risultati principali (`hold`, finanziamento 5%)
| serie | passo | realizzato | non realizzato a fine periodo | P&L totale | peggior equity (data) | costo finanziamento |
|---|---|---|---|---|---|---|
| WTI giornaliero 2005–26 | 1 $ | −2.440 | −9.146 | −11.586 | −18.320 (2020-04-20) | 7.009 |
| Brent giornaliero 2007–26 | 2 $ | −193 | −2.061 | −2.254 | −4.388 (2020-04-21) | 3.339 |
| WTI orario ultimi 2 anni | 1 $ | +1.325 | −947 | +379 | −1.363 (2026-03-09) | 231 |

Senza costi di finanziamento il P&L **realizzato** è sempre positivo (es. WTI passo 1 $: +4.570), ma il **totale** resta negativo o circa zero sull'intero ciclo. La variante che chiude tutto a fine giornata (`eod`) perde in tutte le configurazioni.

## Lettura
1. La griglia incassa guadagni piccoli e frequenti e "parcheggia" le perdite come posizioni aperte. Il conto realizzato sale, quello vero no: il profilo è quello di chi vende volatilità (short gamma). La perdita non realizzata cresce con il quadrato dello spostamento del prezzo dal centro della griglia.
2. Funziona nei periodi laterali (ultimi 2 anni orari: positivo), ma il valore atteso sull'intero ciclo è ≤ 0, perché le uscite dal range (2008, 2014–16, 2020, 2022) producono perdite che superano anni di incassi.
3. Il finanziamento su long e short contemporaneamente è un costo puro, che non dipende dal prezzo, e trasforma in perdita anche le configurazioni in pareggio.
4. Con leva 1:500 il margine è irrilevante: conta la perdita non realizzata, che arriva a 1–4 volte quanto incassato in anni. Una chiamata di margine nel momento peggiore (aprile 2020) chiude tutto al minimo.
