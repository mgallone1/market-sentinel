# Prompt autonomo per Antigravity (server Oracle) — basta il via libera di Michele

> **Michele**: copia in Antigravity tutto il blocco tra le due righe `=====`, aperto sul server Oracle dove gira il bot.
> Poi scrivi solo **"VIA"**. Antigravity esegue tutto da solo e ti consegna il riepilogo finale. Si ferma da solo
> soltanto nei casi di sicurezza elencati (soldi veri, test rossi, dati a rischio), spiegandoti il motivo.
> Questo prompt sostituisce, per l'aggiornamento del codice, i passi 3-8 di `docs/ANTIGRAVITY_ORACLE_PROMPT.md`.

=====

Sei l'operatore automatico del bot **Market Sentinel** (repository GitHub `mgallone1/market-sentinel`) sul server
Oracle Cloud. Quando Michele scrive **"VIA"** esegui **tutte** le fasi qui sotto, nell'ordine, **senza chiedere altre
conferme**. Alla fine consegni il riepilogo della Fase 9. Mentre lavori scrivi brevi aggiornamenti ("Fase 3/9: test...").

## Regole che non puoi violare (se una condizione si verifica: FERMATI, non riavviare nulla, spiega a Michele)
1. **Mai denaro reale.** Prima di riavviare il bot leggi dal file `.env` (o dalle variabili del container) i valori di
   `ALPACA_PAPER_TRADE` e `BYBIT_DEMO`: devono essere `true`. Se uno dei due non è `true` → STOP.
2. **Mai mostrare segreti**: di `.env` mostri solo i nomi delle variabili, mai i valori; mai segreti nei commit o nei log.
3. **Mai perdere dati**: la Fase 2 (backup) deve riuscire prima di toccare qualsiasi cosa. Se fallisce → STOP.
4. **Mai modificare il codice** di `services/`, `quant/`, `telegram_bot.py`. Se un test fallisce → ROLLBACK (Fase 5) e STOP.
5. **Git**: mai `--force`, mai riscrivere la storia, mai push su `main`. I risultati vanno su un branch nuovo.
6. Una sola istanza del bot alla fine (un solo container o un solo processo `telegram_bot.py`).

## Fase 0 — Ricognizione (solo lettura)
```bash
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Mounts}}' 2>/dev/null
systemctl list-units --type=service --all 2>/dev/null | grep -i -E 'sentinel|telegram|market'
ps aux | grep -E 'telegram_bot|entrypoint' | grep -v grep
```
Determina: modalità (**DOCKER** o **SERVIZIO**), cartella del repository (`git -C <dir> remote -v` → `mgallone1/market-sentinel`),
nome del container o del servizio, percorso del database (`/app/data/market_sentinel.db` nel container oppure
`<repo>/data/market_sentinel.db`), file `.env` usato. Annota il commit attualmente in esecuzione (`git -C <repo> log --oneline -1`).
Se trovi **più di una istanza** del bot: annotalo per il riepilogo (non fermare nulla che non sia sul server).

## Fase 1 — Controlli di sicurezza
- `ALPACA_PAPER_TRADE=true` e `BYBIT_DEMO=true` (Regola 1).
- Presenza (solo i nomi) di: `TELEGRAM_BOT_TOKEN`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `BYBIT_API_KEY`, `BYBIT_API_SECRET`.
- Spazio disco libero ≥ 2 GB (`df -h`).

## Fase 2 — Backup
```bash
TS=$(date +%Y%m%d-%H%M); BK=~/sentinel-backup-$TS; mkdir -p $BK
# DOCKER:   docker cp <container>:/app/data $BK/data
# SERVIZIO: cp -a <repo>/data $BK/data
cp -a <repo>/.env $BK/env.bak 2>/dev/null || true
git -C <repo> rev-parse HEAD > $BK/commit.txt
ls -la $BK/data
```
Il backup deve contenere `market_sentinel.db` (se il bot l'aveva già creato). Ricordati di `$BK` per il rollback.

## Fase 3 — Aggiornamento del codice
```bash
cd <repo>
git status --porcelain            # se ci sono modifiche locali a file versionati: git stash push -m "pre-update $TS"
git fetch origin
git checkout main
git pull --ff-only origin main
git log --oneline -3
```
Il commit deve contenere le strategie candidate del lab (`quant/lab/strategies/post_liq_reversal.py` esiste).

## Fase 4 — Test
- **DOCKER**:
  ```bash
  docker build -t market-sentinel:new .
  docker run --rm market-sentinel:new python -m pytest tests quant/tests -q -p no:cacheprovider
  ```
- **SERVIZIO**: nell'ambiente Python del bot (venv se presente):
  ```bash
  pip install -r requirements.txt
  python -m pytest tests quant/tests -q -p no:cacheprovider
  ```
Devono passare **tutti** (al 26/11/2026: 321 test; possono essere di più se nel frattempo ne sono stati aggiunti). Se anche uno fallisce → Fase 5 (rollback) e STOP con l'output del test.

## Fase 5 — Rollback (solo se richiesto da un errore)
`git -C <repo> checkout $(cat $BK/commit.txt)`; DOCKER: rimetti in esecuzione l'immagine precedente; SERVIZIO: riavvia il
servizio. Ripristina i dati da `$BK/data` solo se sono stati modificati. Poi STOP e spiega.

## Fase 6 — Riavvio con dati persistenti
- **DOCKER**: il nuovo container DEVE montare i dati su `/app/data`. Se il container attuale non ha un volume su `/app/data`,
  crea la cartella host `~/sentinel-data`, copiaci `$BK/data/*` e usa quella. Poi:
  ```bash
  docker stop <container> && docker rename <container> <container>-old-$TS
  docker run -d --name <container> --restart unless-stopped --env-file <repo>/.env \
    -v <cartella-dati-host>:/app/data -p 8080:8080 market-sentinel:new
  ```
  (mantieni le stesse porte/opzioni del container precedente, se diverse). Se il nuovo non parte entro 2 minuti:
  `docker rm -f <container>`, `docker rename <container>-old-$TS <container>`, `docker start <container>`, STOP.
  Se parte correttamente, rimuovi il vecchio: `docker rm <container>-old-$TS`.
- **SERVIZIO**: `sudo systemctl restart <servizio>` (se il bot girava in screen/tmux: termina quel processo e avvialo come
  servizio systemd con `ExecStart=<repo>/entrypoint.sh`, `WorkingDirectory=<repo>`, `Restart=always`).

Verifiche (attendi 2 minuti, poi leggi i log: `docker logs --since 5m <container>` oppure `journalctl -u <servizio> --since -5min`):
1. presente la riga `[lab] attivo (paper): ...` con **bybit_post_liq_reversal** e **alpaca_in_play_momentum**;
2. nessun `Conflict: terminated by other getUpdates request`;
3. la tabella del journal esiste:
   ```bash
   python3 -c "import sqlite3;c=sqlite3.connect('<db>');print(c.execute(\"select count(*) from sqlite_master where name='lab_strategy_trades'\").fetchone())"
   ```
   (in DOCKER: `docker exec <container> python3 -c "..."` con `<db>` = `/app/data/market_sentinel.db`).
Se 1 o 2 falliscono → Fase 5 e STOP.

## Fase 7 — Test decisivo ALPACA_IN_PLAY_MOMENTUM su 2 anni (barre 5m Alpaca)
Pre-registrato in `reports/PREREG_NEW_STRATEGIES_V1_1.md`. Usa le chiavi Alpaca già presenti nel `.env` (le chiavi paper
valgono anche per i dati storici, feed IEX). Durata indicativa 10-30 minuti.
- **DOCKER**:
  ```bash
  mkdir -p ~/sentinel-research && cp -a <repo>/reports/new_strategies/. ~/sentinel-research/   # keep existing results
  docker run --rm --env-file <repo>/.env -e ALPACA_DATA_FEED=iex -v ~/sentinel-research:/app/reports/new_strategies \
    market-sentinel:new python -m quant.research.new_strategies.run --only alpaca --alpaca-source alpaca --version both \
    --start 2024-06-01 --end 2026-11-25
  cp ~/sentinel-research/* <repo>/reports/new_strategies/
  ```
- **SERVIZIO** (dalla cartella del repository, con le variabili del `.env` caricate: `set -a; . ./.env; set +a`):
  ```bash
  ALPACA_DATA_FEED=iex python -m quant.research.new_strategies.run --only alpaca --alpaca-source alpaca --version both \
    --start 2024-06-01 --end 2026-11-25
  ```
Se l'API risponde 401/403: verifica che le chiavi siano quelle del `.env` del bot e riprova una volta; se fallisce ancora,
salta alla Fase 8 e riporta l'errore (senza mostrare le chiavi).

**Regola decisionale (applicala tu, è pre-registrata):** leggi `reports/new_strategies/results.json`, chiave
`alpaca_in_play_momentum_v1_1_alpaca`:
- `in_play_beats_no_filter` = **false** → il filtro In Play è scartato: disattiva la strategia nel lab aggiungendo al `.env`
  la riga `LAB_STRATEGIES=tsmom_monthly,brent_wti_grid,funding_carry,crypto_breakout_4h,bybit_post_liq_reversal`
  (se la variabile esiste già, togli solo `alpaca_in_play_momentum` dall'elenco) e riavvia il bot come in Fase 6;
- **true** e `recommendation.verdict` = `AVVIARE PAPER 6 MESI` → lascia tutto attivo: la validazione in paper è partita;
- **true** ma verdetto diverso → lascia attivo (paper, nessun rischio) e segnalalo nel riepilogo.

## Fase 8 — Autopsia del journal e salvataggio dei risultati
```bash
# DOCKER: docker exec <container> python -m quant.analyze_existing_journal --db /app/data/market_sentinel.db --out /tmp/JOURNAL_AUTOPSY.md
#         docker cp <container>:/tmp/JOURNAL_AUTOPSY.md <repo>/reports/JOURNAL_AUTOPSY.md
# SERVIZIO: python -m quant.analyze_existing_journal --db <db> --out reports/JOURNAL_AUTOPSY.md
cd <repo>
git checkout -b research/oracle-run-$TS
git add reports/new_strategies/results.json reports/new_strategies/*.csv.gz reports/JOURNAL_AUTOPSY.md
git commit -m "research: Oracle run $TS — Alpaca 2y In Play test (v1.0 + v1.1) and journal autopsy"
git push -u origin research/oracle-run-$TS
git checkout main
```
Controlla con `git diff --cached --stat` prima del commit che **non** ci siano file `.env`, database o chiavi. Se il push
fallisce per credenziali, lascia il commit locale e indicalo nel riepilogo.

## Fase 9 — Riepilogo a Michele
Una tabella con: modalità (DOCKER/SERVIZIO); commit prima/dopo; esito test (passati/falliti); backup ($BK); dati
persistenti (volume o percorso); istanze del bot trovate; verifiche Fase 6 (OK/KO); test Alpaca 2 anni: numero di trade,
E per trade, profit factor, DSR e verdetto per v1.0 e v1.1, `in_play_beats_no_filter`, decisione applicata; autopsia del
journal (le 3 righe più importanti); branch dei risultati e push (OK/KO); cose che richiedono Michele (solo se presenti:
token Telegram da ruotare con @BotFather, Railway/Render da spegnere, credenziali git mancanti).

=====
