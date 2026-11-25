# Prompt per Antigravity: messa in produzione del laboratorio e delle protezioni

Copia il blocco qui sotto in Antigravity, aperto sulla repository `market-sentinel`. Le parti che richiedono accesso a pannelli esterni (Supabase, Railway, Alpaca) sono indicate come **[AZIONE MANUALE]**: l'agente deve guidarti, non inventare valori o chiavi.

---

```text
Sei nella repository market-sentinel (bot Telegram di trading, deploy su Railway tramite Dockerfile, WORKDIR /app).
Devi mettere in produzione la PR "Laboratorio di paper trading" (branch feature/quant-crypto-alpha, PR #3) e
completare le configurazioni che il codice richiede. Lavora per passi, mostrami ogni comando prima di eseguirlo,
non inserire mai chiavi o segreti nei file del repository e non fare commit di file .env.

PASSO 1 — Verifica del codice prima del merge
1. git fetch origin && git checkout feature/quant-crypto-alpha && git pull
2. pip install -r requirements.txt
3. python -m pytest quant/tests tests -q -p no:cacheprovider   -> devono passare tutti (attesi 224).
4. python -m quant.lab.runner --once --synthetic               -> deve completare senza errori per le 4 strategie.
5. Se tutto è verde, fai il merge della PR #3 su main (o dimmi di farlo da GitHub). Non modificare la logica delle
   strategie, dei limiti di rischio o del bot: questa operazione è solo di messa in produzione.

PASSO 2 — Tabelle Supabase per i registri del laboratorio [AZIONE MANUALE guidata]
I registri del laboratorio (decisioni, esecuzioni simulate, equity, revisioni settimanali) vanno su Supabase perché
il disco del container Railway si cancella a ogni deploy.
1. Mostrami il contenuto di quant/lab/sql/supabase_lab.sql (crea 7 tabelle lab_* nello schema public, idempotente
   con "create table if not exists").
2. Guidami a eseguirlo nel pannello Supabase -> SQL Editor -> New query -> incolla -> Run.
3. Row Level Security: se le tabelle lab_* risultano con RLS attivo e SUPABASE_KEY su Railway è la chiave "anon",
   le scritture verranno rifiutate e il laboratorio ripiegherà in silenzio su SQLite locale (perdendo i dati al
   deploy). Verifica in Supabase -> Table Editor -> lab_decisions -> RLS. Opzioni (scegline una e spiegami il
   rischio): (a) usare su Railway la chiave service_role (solo lato server, mai nel frontend); oppure
   (b) creare policy che consentano insert/update/select su lab_* al ruolo usato dal bot.
4. Test di scrittura dal mio computer, con le stesse variabili di Railway esportate nel terminale (non salvarle su file):
     python -c "from quant.lab.storage import make_storage; s=make_storage(); print(type(s).__name__)"
   Deve stampare SupabaseStorage. Poi:
     python -m quant.lab.runner --once
   e controlla in Supabase che lab_decisions contenga 4 righe nuove (una per strategia). Se compare un avviso
   "fallback SQLite", fermati e risolvi la causa (chiave, RLS, nome tabelle).

PASSO 3 — Variabili d'ambiente su Railway [AZIONE MANUALE guidata]
Elencami le variabili attuali del servizio (senza mostrarmi i valori dei segreti) e aggiungi/verifica:
- LAB_ENABLED=true            (laboratorio attivo, solo paper trading: non invia ordini reali)
- LAB_STORAGE                 (non impostarla, oppure "supabase"; "sqlite" forza il disco locale)
- SUPABASE_URL, SUPABASE_KEY  (già usate dal bot; vedi passo 2.3 per quale chiave)
- RISK_ENABLED=true           (circuit breaker attivo; i valori di default dei limiti sono in services/risk_limits.py:
                               perdita giornaliera 2%, max 6 operazioni aperte contemporaneamente, rischio aperto 3%,
                               perdita massima per trade 0.75%, rapporto rischio/rendimento minimo 1.5,
                               pausa 240 minuti dopo 4 perdite consecutive)
- BYBIT_DEMO=true             (lasciare true finché non si decide diversamente)
- QUANT_META_GATE_PATH        (NON impostarla: il filtro del meta-modello deve restare spento)
Opzionale: LAB_STRATEGIES per attivare solo alcune strategie
(tsmom_monthly, brent_wti_grid, funding_carry, crypto_breakout_4h).

PASSO 4 — Persistenza dello stato del circuit breaker [AZIONE MANUALE guidata]
Il circuit breaker salva il suo stato giornaliero (perdite, operazioni, pause) in data/risk_state.json
(variabile RISK_STATE_PATH). Su Railway quel file si perde a ogni deploy, azzerando i limiti a metà giornata.
Guidami a creare un Volume su Railway montato su /app/data per il servizio del bot. Dopo il deploy verifica dai log
che il file /app/data/risk_state.json venga creato e sopravviva a un secondo deploy.

PASSO 5 — Una sola istanza del bot [AZIONE MANUALE guidata]
Verifica su Railway che il servizio abbia 1 sola replica e controlla nei log del deploy che non ci siano due
container attivi contemporaneamente durante il rilascio (due istanze eseguirebbero il ciclo ogni 2 minuti due volte;
gli ordini Bybit hanno già un orderLinkId deterministico che blocca i duplicati, ma il laboratorio e le notifiche
verrebbero comunque eseguiti due volte).

PASSO 6 — Sicurezza: rotazione delle chiavi esposte nella storia git [AZIONE MANUALE guidata]
Le vecchie chiavi Alpaca (paper) e il vecchio segreto del trigger dei briefing erano scritti nel codice e restano
leggibili nella storia git pubblica. Guidami a:
1. rigenerare le chiavi API nel pannello Alpaca (paper) e aggiornare ALPACA_API_KEY / ALPACA_SECRET_KEY su Railway;
2. generare un nuovo segreto per il trigger dei briefing, aggiornarlo su Railway e nei GitHub Secrets usati dal
   workflow .github/workflows/keep_alive.yml, verificando che il workflow lo invii nell'header X-Trigger-Key e non
   più nella query string.
Non stampare mai le chiavi nella chat o nei log.

PASSO 7 — Verifica finale in produzione
Dopo il deploy:
1. nei log di Railway devono comparire l'avvio del laboratorio e, entro 5 minuti, una riga per ciascuna strategia
   eseguita (nessun "Errore" o "fallback SQLite");
2. su Telegram il comando /lab deve mostrare le 4 strategie con equity e ultima nota;
3. /lab_log brent_wti_grid deve mostrare l'ultima decisione con la motivazione;
4. in Supabase lab_marks deve ricevere nuove righe a ogni esecuzione.
Riassumimi alla fine cosa è stato fatto, cosa è rimasto da fare e qualsiasi errore incontrato.
```

---

## Riferimenti
- Laboratorio: `docs/LAB.md`, codice in `quant/lab/`, SQL in `quant/lab/sql/supabase_lab.sql`.
- Circuit breaker: `services/risk_limits.py`, test in `tests/test_risk_limits.py`.
- Ricerca e risultati: cartella `reports/` (riepiloghi in `reports/HORIZON_SUMMARY.md` e `reports/SETUPS_SUMMARY.md`).
