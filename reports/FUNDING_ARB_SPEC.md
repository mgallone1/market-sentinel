# Test minimo: arbitraggio di funding Bybit ↔ Binance (non eseguibile da questo ambiente)

**Perché non è stato eseguito:** l'API di Bybit è geo-bloccata dal container di ricerca (HTTP 403). Nessun risultato è stato prodotto o stimato: questa pagina definisce solo il test.

## Ipotesi
Lo stesso perpetual USDT su due exchange paga funding diversi, perché la domanda di leva si distribuisce in modo diverso tra le due basi di utenti. Si va **long sul perpetual con funding più basso** e **short su quello con funding più alto**, a parità di nozionale: l'esposizione al prezzo è circa zero e si incassa il differenziale di funding, meno costi e rischio di basis tra i due exchange.

## Dati necessari
| Dato | Fonte | Storia minima |
|---|---|---|
| Funding storico Bybit (linear USDT) | `GET /v5/market/funding/history` (pubblico, paginato) | ≥ 2 anni, 10 simboli |
| Funding storico Binance USD-M | `data.binance.vision/data/futures/um/monthly/fundingRate/` (già supportato da `quant/data/binance_vision.py`) | stesso periodo |
| Prezzi mark/last 1h di entrambi | Bybit `/v5/market/kline` e Binance Vision klines 1h | stesso periodo |
| Fee effettive del conto | tier VIP reale di entrambi i conti | — |

Bybit fissa il funding ogni 8h (per alcuni simboli ogni 4h o 1h); Binance ogni 8h (per alcuni ogni 4h). Il test deve allineare i timestamp reali dei pagamenti, non assumere cadenze fisse.

## Regola pre-registrata (nessuna ottimizzazione)
- Segnale al pagamento k: `d = media(funding_bybit − funding_binance)` sugli ultimi 9 pagamenti allineati.
- Ingresso se `|d|` annualizzato > 8% (soglia fissata ora): short sull'exchange che paga di più, long sull'altro; uscita se `|d|` annualizzato < 2%.
- Costi: taker su entrambe le gambe in entrata e in uscita, 2 bps di slippage per gamba, più il costo di trasferire o mantenere margine separato sui due exchange (capitale immobilizzato x2).
- Rischio: P&L di basis tra i due prezzi marcato ogni ora; liquidazione simulata se il margine di una gamba scende sotto il mantenimento con leva 3x per gamba.

## Criteri per tenerlo
1. Rendimento netto annualizzato sul capitale totale impegnato (le due gambe) > T-bill.
2. Positivo in ogni semestre con almeno 30 giorni di esposizione.
3. Nessuna liquidazione simulata con leva 3x.
4. Il differenziale incassato non viene eroso dal P&L di basis per più del 50%.

## Come eseguirlo
Dal server di produzione (dove Bybit è raggiungibile): `quant/data/bybit.py` scarica il funding storico; per il backtest a due gambe si riusa `quant/backtest/carry.py`, sostituendo la gamba spot con il perpetual dell'altro exchange.
