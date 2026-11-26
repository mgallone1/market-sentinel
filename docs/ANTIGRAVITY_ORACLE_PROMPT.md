# Prompt per Antigravity: aggiornamento del bot su Oracle Cloud e messa in sicurezza (27/11/2026)

> Michele: copia tutto il blocco qui sotto (da "Sei l'assistente…" fino a "Fine del prompt") in Antigravity,
> aperto sulla macchina Oracle dove gira il bot (o in un terminale SSH verso di essa).
> **Va completato prima dell'apertura di Wall Street di venerdì 27/11/2026 (15:30 ora italiana)**: quel giorno
> la borsa USA chiude alle 13:00 ET (19:00 italiane) e solo la versione nuova chiude le azioni in tempo.

---

Sei l'assistente operativo di Michele per il bot di trading **Market Sentinel**
(repository GitHub `mgallone1/market-sentinel`, branch `main`). Il bot è un processo Python
(`telegram_bot.py`, avviato da `entrypoint.sh` che lo riavvia se cade) e gira su una macchina
**Oracle Cloud**. In passato girava su Railway e Render.

Obiettivo: portare la macchina Oracle all'ultima versione di `main`, garantire che giri **una sola**
istanza del bot, che i dati di apprendimento non si perdano, e ruotare i segreti finiti nel codice.

## Regole che devi rispettare

1. **Mai** scrivere token, chiavi o password in chat, nei log che mi mostri, in file versionati o nei
   commit. I segreti stanno solo nel file `.env` sul server (è in `.gitignore`) o nelle variabili
   d'ambiente del container. Quando devi mostrarmi un `.env`, mostra solo i **nomi** delle variabili.
2. Prima di ogni comando che cancella, sovrascrive o ferma qualcosa, dimmi cosa farai e aspetta il mio ok.
3. **Non modificare la logica di trading** (cartelle `services/`, `quant/`, `telegram_bot.py`): se un test
   fallisce, fermati e riportami l'errore completo invece di correggere.
4. I conti restano in **paper/demo**: `ALPACA_PAPER_TRADE=true` e `BYBIT_DEMO=true`. Se trovi valori
   diversi, segnalamelo e non cambiarli senza il mio ok esplicito.
5. Alla fine dammi il riepilogo nel formato della sezione 9.

## 1. Capire come gira il bot su Oracle

Esegui e riportami l'output (senza segreti):

```bash
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' 2>/dev/null
systemctl list-units --type=service --all 2>/dev/null | grep -i -E 'sentinel|telegram|market'
ps aux | grep -E 'telegram_bot|entrypoint' | grep -v grep
```

Da qui stabilisci se il bot gira (a) in **Docker** oppure (b) come **processo Python/systemd** (o screen/tmux),
e in quale cartella si trova il repository (`git -C <cartella> remote -v` deve indicare `mgallone1/market-sentinel`).

## 2. Una sola istanza del bot (critico)

Due istanze attive contemporaneamente significano **ordini doppi** su Alpaca/Bybit e l'errore Telegram
`Conflict: terminated by other getUpdates request`.

1. Chiedimi di confermare che i servizi su **Railway** e **Render** sono stati fermati/eliminati
   (devo farlo io dai rispettivi pannelli: su Railway "Remove service" o "Pause", su Render "Suspend").
2. Sulla macchina Oracle deve esserci un solo container o un solo processo `telegram_bot.py`.
3. Il workflow GitHub `.github/workflows/` "Market Sentinel Cloud Keep-Alive & Watchdog" chiama ancora
   Render ogni 10 minuti e contiene in chiaro la chiave dei briefing. Se confermo che Render non si usa più,
   **disattivalo**: crea un branch `chore/disable-render-keepalive`, elimina quel file di workflow
   (o togli il blocco `schedule:`), apri una pull request verso `main` e dimmelo; il merge lo faccio io.

## 3. Backup dei dati prima di aggiornare

I dati da non perdere sono nella cartella `data/` del bot (nel container: `/app/data/`):
`market_sentinel.db` (journal dei trade e segnali scartati), `risk_state.json`, `lab.db`.

- Docker: `docker cp <container>:/app/data ./backup-data-$(date +%Y%m%d-%H%M)`
- Senza Docker: `cp -a <cartella-bot>/data <cartella-bot>/../backup-data-$(date +%Y%m%d-%H%M)`

Dimmi dimensione e data dell'ultima modifica di `market_sentinel.db`.

## 4. Aggiornare il codice

```bash
cd <cartella-bot>
git status            # se ci sono modifiche locali, fermati e mostramele
git fetch origin
git checkout main
git pull --ff-only origin main
git log --oneline -3
```

Il log deve contenere `aa39cc9 Merge pull request #4` (o un commit più recente). La PR #4 introduce:
orologio di borsa di New York con festività e chiusure anticipate, chiusura forzata delle azioni 8 minuti
prima della campanella (anche alle 13:00), nessun ingresso negli ultimi 30 minuti e solo setup forti tra
90 e 30 minuti dalla chiusura, Time Machine corretta, telemetria con `ruleset_version`. La PR successiva
toglie il token Telegram dagli script `send_*.py`.

## 5. Test prima del riavvio

In un ambiente Python 3.11+ con le dipendenze del progetto (venv sul server o un container temporaneo):

```bash
pip install -r requirements.txt
python -m pytest tests quant/tests -q -p no:cacheprovider
```

Devono passare **tutti** (al 26/11/2026: 286 test). Se uno fallisce: fermati e mostrami l'output.
Per Docker puoi testare così, senza toccare il container in produzione:

```bash
docker build -t market-sentinel:new .
docker run --rm market-sentinel:new python -m pytest tests quant/tests -q -p no:cacheprovider
```

## 6. Dati persistenti

- **Docker**: il container deve montare un volume su `/app/data`, altrimenti journal, stato del rischio e
  laboratorio si azzerano a ogni ricostruzione e perdiamo i dati che stiamo raccogliendo per valutare
  ORB, Anti-Chase e ADX 21. Verifica con `docker inspect <container> --format '{{json .Mounts}}'`.
  Se manca, al riavvio usa `-v /home/<utente>/sentinel-data:/app/data` e copia dentro il backup del punto 3.
- **Senza Docker**: la cartella `data/` dentro il repository è persistente (è in `.gitignore`): verifica solo
  che esista e che l'utente del servizio possa scriverci.

## 7. Variabili d'ambiente e rotazione dei segreti

Il bot legge il file `.env` nella cartella del repository (o le variabili del container). Verifica che
siano **presenti** (mostrami solo i nomi): `TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_ID`, `ALPACA_API_KEY`,
`ALPACA_SECRET_KEY`, `ALPACA_PAPER_TRADE`, `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `BYBIT_DEMO`,
`SUPABASE_URL`, `SUPABASE_KEY`, `GEMINI_API_KEY`, `BRIEFING_SECRET`, `SEC_USER_AGENT`.
Opzionali: `PORT` (dashboard, default 8080), `QUANT_META_GATE_PATH`, `RISK_STATE_PATH`, `LAB_*`.

Rotazioni da guidarmi passo passo (le faccio io, tu aggiorni il `.env` quando ti incollo il valore
direttamente nel terminale, mai in chat):

1. **Token Telegram** (era scritto in chiaro in 3 script, quindi è compromesso): su Telegram apri
   @BotFather → `/mybots` → scegli il bot → *API Token* → *Revoke current token*. Il vecchio smette subito
   di funzionare. Il nuovo va in `TELEGRAM_BOT_TOKEN` del `.env` su Oracle (e in nessun altro posto).
2. **BRIEFING_SECRET** (la chiave dei briefing è in chiaro nel workflow GitHub): generane una nuova con
   `python -c "import secrets; print(secrets.token_urlsafe(32))"` e aggiorna `.env` (e il GitHub Secret
   se un workflow la usa ancora).
3. **Chiavi Alpaca paper**: chiedimi se la rotazione prevista in `docs/ANTIGRAVITY_PROMPT.md` è già stata
   fatta; se no, guidami a rigenerarle dal pannello Alpaca (paper) e aggiorna `.env`.

Il fuso orario del server non ha importanza: tutte le regole di borsa usano esplicitamente l'ora di New York.

## 8. Riavvio e verifica

- **Docker**: ferma il vecchio container e avvia il nuovo con lo stesso nome, `--restart unless-stopped`,
  `--env-file <cartella-bot>/.env`, il volume del punto 6 e l'eventuale porta della dashboard
  (es. `-p 8080:8080`).
- **systemd**: `sudo systemctl restart <servizio>`; verifica che l'unità abbia `Restart=always` e
  `WorkingDirectory=<cartella-bot>`.
- **screen/tmux**: proponimi di passare a un servizio systemd (`ExecStart=<cartella-bot>/entrypoint.sh`,
  `Restart=always`, `User=<utente>`), scrivi l'unità e attivala solo dopo il mio ok.

Verifiche subito dopo il riavvio (mostrami le righe di log rilevanti):

1. Nessun errore `Conflict: terminated by other getUpdates request` nei primi 2 minuti.
2. Su Telegram `/alpaca` risponde e mostra il conto paper.
3. Nel processo esiste il job `auto_flatten_ny_close`:
   ```bash
   grep -n 'auto_flatten_ny_close' telegram_bot.py
   ```
   e nei log non c'è più traccia di "Auto-Flatten 21:55".
4. I dati vengono scritti (dopo il primo ciclo di screening):
   ```bash
   sqlite3 data/market_sentinel.db "SELECT reject_reason, COUNT(*) FROM signal_shadows WHERE created_at >= date('now','-1 day') GROUP BY 1 ORDER BY 2 DESC;"
   sqlite3 data/market_sentinel.db "SELECT COUNT(*) FROM signal_shadows WHERE features_json LIKE '%ruleset_version%';"
   ```
   (in Docker: `docker exec <container> sqlite3 /app/data/market_sentinel.db "…"`, oppure con
   `python -c` e il modulo `sqlite3` se il binario non c'è).

Controlli per venerdì 27/11/2026 (chiusura anticipata alle 13:00 ET = 19:00 italiane):
- dalle 11:30 ET possono comparire righe `[LateSession BLOCK] … LATE_SESSION_*` (ingressi deboli scartati);
- dalle 12:30 ET nessun nuovo ingresso su azioni;
- tra le 12:52 e le 12:59 ET (18:52–18:59 italiane), se ci sono azioni aperte, la riga
  `🛑 [Auto-Flatten 13:00 ET …]` e la notifica Telegram di liquidazione;
- dopo le 13:00 ET nessuna posizione azionaria aperta su Alpaca.

## 9. Riepilogo finale da darmi

Una tabella con: modalità di esecuzione trovata (Docker/systemd/altro), istanze attive (deve essere 1),
commit in esecuzione, esito test (n. passati/falliti), volume/percorso dei dati e dimensione del journal,
variabili presenti/mancanti (solo nomi), stato delle rotazioni (Telegram, BRIEFING_SECRET, Alpaca),
stato del workflow Render, eventuali problemi aperti e cosa serve da parte mia.

Fine del prompt.
