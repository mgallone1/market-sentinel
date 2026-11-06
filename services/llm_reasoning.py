"""
LLM Reasoning & Vision Service con Google Gemini AI Studio.
Modello: gemini-3.5-flash-lite
Combina i dati quantitativi in tempo reale con capacità di ragionamento umano,
analisi macro e visione artificiale per screenshot di Trade Republic.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo
from datetime import datetime
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

class LLMReasoningService:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.client = None
        self.models_to_try = ["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.5-flash-lite"]
        if HAS_GENAI and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                print(f"[LLMReasoningService] Errore init client Gemini: {e}")

    @staticmethod
    def _get_current_time_str() -> str:
        return datetime.now(ZoneInfo("Europe/Rome")).strftime("%A %d %B %Y ore %H:%M CET")

    def _call_gemini(self, contents) -> str:
        if not self.client:
            return ""
        for model in self.models_to_try:
            try:
                res = self.client.models.generate_content(model=model, contents=contents)
                if res and res.text:
                    return res.text.strip()
            except Exception as e:
                print(f"[LLMReasoningService] Modello {model} non disponibile: {e}")
        return ""

    def classify_intent(self, text: str, recent_history_summary: str = "") -> Dict[str, Any]:
        """
        Classifica l'intenzione dell'utente (analisi ticker, verifica portafoglio/numeri, panoramica mercato, o chat libera)
        tenendo conto del contesto e degli ultimi scambi della conversazione.
        """
        context_block = f"CONTESTO DELLA CHAT RECENTE:\n{recent_history_summary}\n" if recent_history_summary else ""
        prompt = f"""
Sei un classificatore di intenti finanziari avanzato. Analizza attentamente il messaggio dell'utente considerando il contesto recente.

{context_block}MESSAGGIO UTENTE:
"{text}"

DISTINZIONE CRITICA DEGLI INTENTI:
1. "update_portfolio_ticker":
   - Se l'utente chiede di correggere, cambiare, modificare o sostituire uno o più ticker nel portafoglio (es. "hai sbagliato i ticket dei due etf sono XDWD e XDEM", "aggiorna il portafoglio con i ticker giusti", "cambia il ticker di BYD in BY6.F", "sostituisci URTH con XDWD").
2. "portfolio":
   - Se l'utente chiede di vedere il portafoglio o chiarimenti sui calcoli/numeri/controvalore mostrati senza specificare cambi di ticker (es. "mostra portafoglio", "ricontrolla i calcoli", "non si trovano i numeri").
3. "ticker_analysis":
   - Solo ed esclusivamente quando l'utente chiede una NUOVA analisi tecnica/fondamentale/ciclica di un'azione o crypto (es. "cosa ne pensi di Apple", "analizza Nvidia", "Marvell", "dimmi di Bitcoin").
4. "market_overview":
   - Se chiede cosa è successo sul mercato, news generali o il briefing (es. "cosa succede oggi in borsa", "briefing").
5. "general_chat":
   - Domande generiche, concettuali o saluti.

Restituisci ESCLUSIVAMENTE un JSON valido:
{{
  "intent": "update_portfolio_ticker" | "portfolio" | "ticker_analysis" | "market_overview" | "general_chat",
  "ticker": "SIMBOLO_TICKER" o null,
  "replacements": [
     {{"old_ticker_or_name": "...", "new_ticker": "..."}}
  ]
}}
"""
        res = self._call_gemini(prompt)
        if res:
            try:
                clean_json = res.replace("```json", "").replace("```", "").strip()
                return json.loads(clean_json)
            except Exception as e:
                print(f"[LLMReasoningService] Errore parse JSON intent: {e}")
        return {"intent": "general_chat", "ticker": None}

    def generate_executive_market_brief(
        self,
        ticker: str,
        pred_data: Dict[str, Any],
        fund_data: Dict[str, Any],
        news_list: list,
        cycle_data: Optional[Dict[str, Any]] = None,
        memory_context: str = ""
    ) -> str:
        """
        Genera la sintesi esecutiva Focalizzata sul Momento Attuale:
        Spiega COSA sta succedendo (catalyst, correlazione Wall Street/crypto, news),
        DOVE siamo nel ciclo e COSA fare oggi, senza affogare l'utente nei tecnicismi.
        """
        if not self.client:
            return ""

        cycle_data = cycle_data or {}
        news_details = []
        for n in news_list[:5]:
            t_str = n.get("title", "")
            s_str = n.get("summary", "")
            if t_str:
                news_details.append(f"• Titolo: {t_str}\n  Dettaglio: {s_str}")
        news_block_text = "\n".join(news_details) if news_details else "Nessuna notizia recente rilevante."

        now_str = self._get_current_time_str()
        mem_block = f"\nContesto e decisioni precedenti dell'utente negli ultimi 7-30 giorni:\n{memory_context}\n" if memory_context else ""

        prompt = f"""
Sei un Senior Investment Strategist e Portfolio Manager.
DATA E ORA ATTUALE DI RIFERIMENTO: {now_str}.
Il tuo obiettivo è spiegare in modo chiaro, asciutto, analitico, istituzionale e professionale cosa sta succedendo ORA allo strumento {fund_data.get('short_name', ticker)} ({ticker}).
{mem_block}
DATI FONDAMENTALI & PREZZO:
- Prezzo Attuale in Euro: {pred_data.get('current_price_eur')} €
- Variazione/Trend: {pred_data.get('trend_macro', 'N/D')} (Probabilità rimbalzo statistico: {pred_data.get('mean_reversion_probability')})
- Notizie & Catalyst recenti:
{news_block_text}
- Fase Ciclica di Migliorino: {cycle_data.get('tempo_battleplan', 'N/D')} ({cycle_data.get('descrizione_battleplan', '')})
- Consiglio del ciclo: {cycle_data.get('consiglio_pratico', '')}
- Mancano circa ~{cycle_data.get('candele_al_minimo', 'N/D')} sedute al minimo ciclico

LINEE GUIDA RIGOROSE DI RISPOSTA:
1. DIVIETO ASSOLUTO DI APERTURE COLLOQUIALI, PATERNALISTICHE O AFFETTATE: NON usare MAI formule come 'Caro amico', 'Mettiamoci comodi', 'Mio caro', 'Entriamo nel vivo/merito'. Inizia DIRETTAMENTE con l'analisi dei fatti e dei dati.
2. ANCORAGGIO TEMPORALE ASSOLUTO (DIVIETO DI ANACRONISMI): Siamo a {now_str}. È tassativamente vietato citare anni passati (come 2025 o 2024, es. DeepSeek 2025 o vecchi accordi) per giustificare i movimenti di oggi. Concentrati unicamente sulle dinamiche e notizie odierne delle ultime ore.
3. Spiega con chiarezza e rigore analitico la CAUSA REALE del movimento odierno (dinamiche di Wall Street, macro, trimestrali, correlazioni). Se è una crypto (es. Bitcoin), spiega la correlazione con la liquidità istituzionale, il VIX e i tassi USA.
4. Spiega in un breve paragrafo dove ci troviamo nel ciclo attuale e se ha senso attendere o impostare un ordine limite.
5. Tono sobrio, istituzionale, posato, privo di enfasi teatrale o formule paternalistiche.
6. Tutte le cifre RIGOROSAMENTE in Euro (€).
"""
        return self._call_gemini(prompt)

    def generate_financial_commentary(
        self,
        ticker: str,
        pred_data: Dict[str, Any],
        fund_data: Dict[str, Any],
        news_list: list,
        cycle_data: Optional[Dict[str, Any]] = None,
        advanced_data: Optional[Dict[str, Any]] = None,
        memory_context: str = ""
    ) -> str:
        """
        Genera un'analisi predittiva e strategica di massimo livello integrando:
        Monte Carlo (10.000 iterazioni), VIX & Tassi Treasury 10Y, Onde di Elliott, Cicli Hurst & Migliorino.
        """
        if not self.client:
            return ""

        cycle_data = cycle_data or {}
        advanced_data = advanced_data or {}
        mc = advanced_data.get("monte_carlo", {})
        macro = advanced_data.get("macro", {})
        elliott = advanced_data.get("elliott", {})

        news_details = []
        for n in news_list[:5]:
            t_str = n.get("title", "")
            s_str = n.get("summary", "")
            if t_str:
                news_details.append(f"• Titolo: {t_str}\n  Dettaglio: {s_str}")
        news_block_text = "\n".join(news_details) if news_details else "Nessuna notizia recente rilevante."

        now_str = self._get_current_time_str()
        mem_block = f"\nContesto e decisioni precedenti dell'utente negli ultimi 7-30 giorni:\n{memory_context}\n" if memory_context else ""

        prompt = f"""
Sei un Senior Quantitative Strategist e Portfolio Manager di livello hedge fund globale.
DATA E ORA ATTUALE DI ANALISI: {now_str}.
Il tuo interlocutore è un investitore intelligente ma non un addetto ai lavori finanziari: per questo, la tua dote più grande è spiegare in modo chiaro, logico, trasparente e collegato TUTTI i pezzi del puzzle, senza dare nulla per scontato e senza tecnicismi fini a se stessi.
{mem_block}
QUADRO QUANTITATIVO COMPLETO SUL TITOLO (tutto espresso in Euro €):
- Strumento: {fund_data.get('short_name', ticker)} ({ticker})
- Prezzo Attuale in Euro: {pred_data.get('current_price_eur')} € (Prezzo nativo: ${pred_data.get('raw_price')})
- Volatilità Giornaliera (ATR): {pred_data.get('daily_atr_eur')} € ({pred_data.get('volatility_daily_pct')}%) | Storica Annualizzata: {mc.get('annualized_vol_pct', 'N/D')}%
- Cono Previsionale a 5 sedute: {pred_data.get('forecast_cone_5d_eur')}
- Z-Score statistico (distanza da SMA20): {pred_data.get('z_score')}
- Probabilità Statistica di Rimbalzo: {pred_data.get('mean_reversion_probability')}

1. SIMULAZIONE STOCASTICA MONTE CARLO (10.000 scenari a 20 sedute):
- Valore Mediano Atteso (50° percentile): {mc.get('median_price_eur', 'N/D')} €
- Intervallo di Confidenza al 68% (1 Sigma): {mc.get('ci_68_range_eur', 'N/D')}
- Intervallo di Confidenza al 95% (2 Sigma): {mc.get('ci_95_range_eur', 'N/D')}
- Value at Risk (VaR 95% massimo rischio atteso): {mc.get('var_95_eur', 'N/D')} €
- Probabilità di Rendimento Positivo a 20 sedute: {mc.get('probability_positive_trend', 'N/D')}

2. REGIME MACROECONOMICO & VOLATILITÀ:
- Indice VIX: {macro.get('vix_value', 'N/D')} ({macro.get('vix_regime', 'N/D')})
- Rendimento Treasury USA a 10 Anni (^TNX): {macro.get('tnx_10y_yield', 'N/D')}% (impatto sui multipli P/E)
- Tasso EUR/USD: {macro.get('eur_usd_rate', 'N/D')}

3. MODELLO FRATTALE ONDE DI ELLIOTT:
- Fase Identificata: {elliott.get('wave_label', 'N/D')}
- Diagnosi Strutturale: {elliott.get('analysis', '')}

4. ANALISI CICLICA (HURST & MIGLIORINO):
- Battleplan Migliorino (Ciclo Mensile T+2): {cycle_data.get('tempo_battleplan', 'N/D')} ({cycle_data.get('descrizione_battleplan', '')})
- Conteggio Barre dal Minimo: {cycle_data.get('bars_since_mensile_min', 'N/D')} barre su mensile; {cycle_data.get('bars_since_intermedio_min', 'N/D')} su intermedio T+3
- Vincolo Ciclico di Migliorino: {cycle_data.get('vincolo_migliorino', 'N/D')}
- FLD di Hurst (Future Line of Demarcation): {cycle_data.get('hurst_fld_value', 'N/D')} € ({cycle_data.get('hurst_fld_signal', '')})
- Divergenza RSI: {cycle_data.get('divergence', 'N/D')} ({cycle_data.get('div_details', '')})
- Livello Aureo Fibonacci (0.618 Golden Pocket): {cycle_data.get('fib_618_eur', 'N/D')} €
- Take Profit 1 a mercato: {pred_data.get('take_profit_1_eur')} € | Stop Loss: {pred_data.get('stop_loss_eur')} €

5. CATALYST, NEWS AZIENDALI & M&A FONDAMENTALI:
{news_block_text}

LINEE GUIDA DI COMPOSIZIONE (OBBLIGATORIE):
- NON limitarti a snocciolare formule tecniche: spiega chiaramente la CAUSA FONDAMENTALE, MACROECONOMICA e AZIENDALE del movimento.
- Per le CRIPTOVALUTE (Bitcoin, Ethereum, Solana, etc.), DEVI SEMPRE spiegare il legame diretto con Wall Street e il quadro macro: la correlazione con il sell-off delle Big Tech / Nasdaq, il rialzo dei rendimenti obbligazionari (^TNX) che drena liquidità dagli asset rischiosi, il picco di volatilità (VIX) che costringe gli hedge fund al deleveraging forzato (chiusura posizioni a leva su crypto), e l'impatto sui flussi degli ETF Spot (es. deflussi da IBIT/FBTC).
- Per le AZIONI spiega le cause specifiche (es. M&A, diluizioni azionarie, trimestrali, tassi e colli di bottiglia energetici dei Data Center AI).
- Spiega in parole semplici cosa significano insieme i numeri: ad esempio come la discesa fondamentale si incastra con l'Onda correttiva di Elliott e il minimo del ciclo di Hurst/Migliorino.
- Spiega PERCHÉ è fondamentale impostare un ORDINE LIMITE scontato (es. sui supporti statistici dell'intervallo 1-Sigma di Monte Carlo) invece di comprare a mercato: mostra come l'ordine limite abbatte il rischio e fa schizzare il rapporto Rischio/Rendimento (Risk/Reward) a livelli vantaggiosi (es. da 1:0.8 a mercato a oltre 1:2.5 o 1:3 con limite).
- DIVIETO ASSOLUTO DI APERTURE COLLOQUIALI, PATERNALISTICHE O AFFETTATE: Non usare MAI formule come 'Caro amico', 'Mettiamoci comodi', 'Mio caro', 'Entriamo subito nel merito'. Inizia DIRETTAMENTE con il quadro oggettivo, i dati e i livelli tecnici.
- ANCORAGGIO TEMPORALE E FATTUALE: Siamo a {now_str}. È severamente vietato inventare o citare notizie e crolli del passato (come il rilascio di DeepSeek del gennaio 2025 o vecchi sell-off storici) attribuendoli a oggi. Se non ci sono notizie specifiche recenti nei dati forniti, spiega l'andamento basandoti rigorosamente sulla pura dinamica tecnica dei prezzi, sui flussi macro (tassi ^TNX, VIX, dollaro) e sui cicli.
- Tono: Istituzionale, didattico, posato, lucido, autorevole ma accessibile e privo di melodrammi.
- Tutte le cifre RIGOROSAMENTE in Euro (€).
"""
        return self._call_gemini(prompt)

    def analyze_screenshot(self, image_bytes: bytes, mime_type: str = "image/png") -> Dict[str, Any]:
        """
        Analizza con visione artificiale uno screenshot inviato dall'utente su Telegram.
        Estrae posizioni di Trade Republic o interpreta grafici e notizie.
        """
        if not self.client:
            return {"type": "unknown", "text": "Modulo AI non attivo"}

        prompt = """
Sei un esperto di analisi visiva di schermate finanziarie (in particolare broker come Trade Republic, Degiro, TradingView).
Analizza questa immagine inviata dall'utente:

1. Se è una schermata di POSIZIONE di Trade Republic:
   Estrai i dati in formato JSON valido:
   ```json
   {
      "is_position": true,
      "asset_name": "Nome strumento es. MSCI World Momentum",
      "ticker_candidate": "Ticker o sigla presunta es. XDEM.DE o XDWD.DE",
      "shares": 32.2419,
      "average_buy_price": 81.50,
      "total_value": 2393.64,
      "currency": "EUR"
   }
   ```

2. Se è un GRAFICO o una NOTIZIA:
   Fornisci un'analisi visiva e una sintesi esecutiva chiara di cosa mostra l'immagine in lingua italiana.
"""
        part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        text_resp = self._call_gemini([part, prompt])
        if not text_resp:
            return {"type": "error", "text": "Impossibile analizzare l'immagine in questo momento."}

        pos_data = None
        if "```json" in text_resp:
            try:
                json_str = text_resp.split("```json")[1].split("```")[0].strip()
                pos_data = json.loads(json_str)
            except Exception:
                pass

        return {
            "type": "position" if (pos_data and pos_data.get("is_position")) else "visual_analysis",
            "position_data": pos_data,
            "text": text_resp
        }

    def generate_macro_market_briefing(self, indices_data: list, news_list: list, slot: str = "morning", previous_briefing_context: str = "") -> str:
        """
        Genera un briefing macro periodico (mattino ore 07:00 o pomeriggio ore 15:00):
        - Ore 07:00: Sintesi delle ultime 12 ore (chiusura Asia, Wall Street overnight, futures europei, geopolitica e dati macro).
        - Ore 15:00: Sintesi delle ultime ore e pre-apertura USA (apertura borse europee, dati lavoro/inflazione USA, futures pre-market).
        - Si ricorda e si collega direttamente a quanto detto nel briefing precedente, evitando ripetizioni e mostrando l'evoluzione.
        - Conciso, ad altissima densità informativa e rigorosamente basato su dati reali aggiornati in Euro (€).
        """
        if not self.client:
            return ""

        now_str = self._get_current_time_str()
        indices_str = "\n".join([f"- {item['label']}: {item['price_eur']} € ({item['change']:+.2f}%)" for item in indices_data])
        news_str = "\n".join([f"• [{n.get('source', 'Top Media')}] ({n.get('published', 'Oggi')}): {n.get('title', '')}: {n.get('summary', '')[:160]}" for n in news_list[:12]])

        prev_block = f"\nCOSA AVEVI DETTO NEL BRIEFING PRECEDENTE (DA RICORDARE E COLLEGARE):\n{previous_briefing_context}\n" if previous_briefing_context else ""

        now_dt = datetime.now(ZoneInfo("Europe/Rome"))
        cur_hhmm = now_dt.strftime("%H:%M")
        if slot == "morning":
            time_focus = (
                f"FASCIA ORARIA: MATTINO (ORE {cur_hhmm} CET). "
                "Sintesi ragionata e densa delle ultime 12 ore: chiusura sessione asiatica, overnight USA, futures europei e catalizzatori in apertura borse europee (ore 09:00 CET)."
            )
        elif slot == "afternoon":
            time_focus = (
                f"FASCIA ORARIA: POMERIGGIO (ORE {cur_hhmm} CET). "
                "Sintesi delle contrattazioni europee a metà seduta, dati macro USA (ore 14:30) e sessione attiva di Wall Street."
            )
        elif slot == "evening":
            time_focus = (
                f"FASCIA ORARIA: SERA / CHIUSURA MERCATI (ORE {cur_hhmm} CET). "
                "Borse europee CHIUSE (alle 17:30 CET). Focus su: andamento e chiusura di Wall Street (ore 22:00 CET), bilancio giornaliero definitivo, flussi crypto e prospettive per la seduta successiva."
            )
        else:
            time_focus = (
                f"FASCIA ORARIA: NOTTE / OVERNIGHT (ORE {cur_hhmm} CET). "
                "Mercati azionari occidentali chiusi. Focus su: bilancio finale di Wall Street, futures notturni, crypto 24/7 e prime indicazioni dall'Asia."
            )

        prompt = f"""
Sei il Chief Investment Officer (CIO) e Senior Market Strategist.
DATA E ORA ATTUALE DI REDAZIONE: {now_str}.
{time_focus}
{prev_block}
DATI DI MERCATO LIVE DI OGGI (Tutti espressi in Euro €):
{indices_str}

NOTIZIE, BREAKING NEWS & RASSEGNA STAMPA INTERNAZIONALE IN TEMPO REALE (Bloomberg, CNBC, BBC, CoinDesk):
{news_str}

LINEE GUIDA RIGOROSE DI REDAZIONE E ANCORAGGIO TEMPORALE:
1. ANCORAGGIO TEMPORALE ASSOLUTO (ANTI-ALLUCINAZIONE & ZERO ANACRONISMI):
   - Oggi è {now_str}. Fai riferimento ESCLUSIVAMENTE a questa data e ai dati e alle breaking news fornite sopra.
   - DIVIETO ASSOLUTO E CATEGORICO di citare date passate o anni precedenti (come '2025', '2024', 'ottobre 2025', 'gennaio 2025') o trattati passati. Questa regola è inflessibile: l'utente non deve MAI leggere riferimenti ad anni passati che creano l'illusione di notizie vecchie.
   - Concentrati unicamente sull'impatto odierno ({now_str}) e sui fatti delle ultime ore.
   - Se una notizia o spiegazione non è documentata nelle news o nei dati forniti sopra, NON INVENTARE catalizzatori passati. Riporta solo i fatti confermati o la pura dinamica tecnica e ciclica dei prezzi.
2. DIVIETO ASSOLUTO DI FORMULE COLLOQUIALI O PATERNALISTICHE:
   - VIETATO iniziare con 'Caro amico', 'Mettiamoci comodi', 'Mio caro', 'Entriamo nel merito/vivo', 'Buongiorno caro'.
   - Inizia SUBITO e DIRETTAMENTE con il punto 1 e l'analisi dei catalyst.
3. CONCISO MA COMPLETO: Niente giri di parole, niente melodramma, niente padding. Struttura il briefing in 3 o 4 punti chiave rapidi ma densi di contenuto informativo:
   - *1. Catalyst Notturno / Ultime Ore:* Il fatto politico, macroeconomico o geopolitico più rilevante e la reazione di Asia ed Europa.
   - *2. Wall Street & Big Tech / Crypto:* Il driver principale (tassi ^TNX, petrolio, trimestrali, o sentiment AI/crypto).
   - *3. Connessione con il Briefing Precedente:* Ricollegati in 1-2 frasi a quanto avevi segnalato prima per mostrare se l'ipotesi si è confermata o se c'è stata una svolta.
   - *4. Bussola Operativa per la Seduta:* Livelli di attenzione, orario dei dati macro cruciali e disciplina su Trade Republic.
4. Tono istituzionale, posato, lucido ed elegante.
5. Tutte le quotazioni rigorosamente in Euro (€).
"""
        return self._call_gemini(prompt)

    def answer_general_query(self, query: str, memory_context: str = "") -> str:
        """
        Risponde a domande finanziarie, macroeconomiche o teoriche con registro sobrio e istituzionale.
        """
        now_str = self._get_current_time_str()
        mem_block = f"\nMemoria storica e conversazioni recenti con l'utente:\n{memory_context}\n" if memory_context else ""
        prompt = f"""
Sei un Senior Financial Advisor, Portfolio Manager e Maestro dell'Analisi Ciclica (Hurst & Giuseppe Migliorino).
DATA E ORA ATTUALE DI RIFERIMENTO: {now_str}.
{mem_block}
L'utente ti pone questa domanda su Telegram:
"{query}"

LINEE GUIDA RIGOROSE:
1. ANCORAGGIO TEMPORALE REALE E ANTI-ALLUCINAZIONE:
   - Siamo a {now_str}. Sii trasparente e accurato sulle date degli eventi.
   - Non confondere mai eventi del passato della tua base di conoscenza pregressa (come DeepSeek R1 uscito a gennaio 2025) con i movimenti odierni di mercato. DIVIETO ASSOLUTO di attribuire i movimenti di oggi a eventi del 2025 o 2024.
   - Se l'utente ti chiede spiegazioni su una notizia o un evento, specifica sempre chiaramente quando è accaduto realmente e non spacciare eventi datati come spiegazioni dei movimenti di oggi.
2. STILE E REGISTRO ISTITUZIONALE:
   - DIVIETO CATEGORICO DI APERTURE COLLOQUIALI, PATERNALISTICHE O AFFETTATE: VIETATO iniziare con "Caro amico", "Mettiamoci comodi", "Caro investitore", "Entriamo subito nel vivo/merito", "Capisco perfettamente la tua curiosità", o salamelecchi analoghi.
   - Inizia SUBITO e DIRETTAMENTE con la risposta analitica, oggettiva, chiara, priva di preamboli o convenevoli.
   - Tono da Senior Portfolio Manager e CIO: lucido, asciutto, autorevole, analitico, rispettoso del tempo dell'interlocutore.
   - Zero enfasi melodrammatica, zero allarmismo, zero padding.
3. Prezzi sempre in Euro (€).
"""
        return self._call_gemini(prompt)
