"""
LLM Reasoning & Vision Service con Google Gemini AI Studio.
Modello: gemini-3.5-flash-lite
Combina i dati quantitativi in tempo reale con capacità di ragionamento umano,
analisi macro e visione artificiale per screenshot di Trade Republic.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
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
        self.models_to_try = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"]
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
1. "opportunities":
   - Se l'utente chiede le migliori occasioni, opportunità di mercato, titoli a sconto statistico, idee di trading o cosa comprare (es. "le migliori occasioni", "quali sono le occasioni", "cosa comprare oggi", "titoli a sconto", "migliori opportunità", "occasioni").
2. "update_portfolio_ticker":
   - Se l'utente chiede di correggere, cambiare, modificare o sostituire uno o più ticker nel portafoglio (es. "hai sbagliato i ticket dei due etf sono XDWD e XDEM", "aggiorna il portafoglio con i ticker giusti", "cambia il ticker di BYD in BY6.F", "sostituisci URTH con XDWD").
3. "portfolio":
   - Se l'utente chiede di vedere il portafoglio o chiarimenti sui calcoli/numeri/controvalore mostrati senza specificare cambi di ticker (es. "mostra portafoglio", "ricontrolla i calcoli", "non si trovano i numeri").
4. "ticker_analysis":
   - Solo ed esclusivamente quando l'utente chiede una NUOVA analisi tecnica/fondamentale/ciclica di un'azione o crypto (es. "cosa ne pensi di Apple", "analizza Nvidia", "Marvell", "dimmi di Bitcoin").
5. "market_overview":
   - Se chiede cosa è successo sul mercato in generale, news o il briefing (es. "cosa succede oggi in borsa", "briefing", "aggiornamento mercato").
6. "general_chat":
   - Domande generiche, concettuali o saluti.

Restituisci ESCLUSIVAMENTE un JSON valido:
{{
  "intent": "opportunities" | "update_portfolio_ticker" | "portfolio" | "ticker_analysis" | "market_overview" | "general_chat",
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

    def generate_advisor_consultation(
        self,
        ticker: str,
        pred_data: Dict[str, Any],
        fund_data: Dict[str, Any],
        news_list: list,
        cycle_data: Optional[Dict[str, Any]] = None,
        advanced_data: Optional[Dict[str, Any]] = None,
        existing_position: Optional[Dict[str, Any]] = None,
        portfolio_summary: Optional[Dict[str, Any]] = None,
        user_profile: Optional[Dict[str, Any]] = None,
        tr_quote: Optional[Dict[str, Any]] = None,
        memory_context: str = ""
    ) -> str:
        """
        Genera una vera consulenza strategica, umana, autorevole e ad alta convinzione
        da Senior Portfolio Manager / Chief Investment Officer (CIO) personale per Michele.
        Sostituisce gli elenchi grezzi di formule con un ragionamento economico chiaro,
        integrato con il portafoglio esistente e con condotta tattica su Trade Republic.
        """
        if not self.client:
            return ""

        now_str = self._get_current_time_str()
        cycle_data = cycle_data or {}
        advanced_data = advanced_data or {}
        user_profile = user_profile or {}

        asset_name = fund_data.get("short_name") or fund_data.get("long_name") or ticker
        cur_price_eur = pred_data.get("current_price_eur", 0.0)

        # Trade Republic Lang & Schwarz Bid/Ask
        tr_bid_str = f"{tr_quote['bid']:.2f} €" if (tr_quote and "bid" in tr_quote) else "N/D"
        tr_ask_str = f"{tr_quote['ask']:.2f} €" if (tr_quote and "ask" in tr_quote) else "N/D"

        # Posizione esistente in portafoglio
        if existing_position:
            sh = existing_position.get("shares", 0.0)
            pmc = existing_position.get("pmc", 0.0)
            pnl_pct = existing_position.get("pnl_pct", 0.0)
            pnl_eur = existing_position.get("pnl_eur", 0.0)
            icon = "🟢" if pnl_eur >= 0 else "🔴"
            existing_pos_block = (
                f"Michele possiede GIÀ questo strumento in portafoglio: {sh:.4f} quote in carico a un PMC di {pmc:.2f} €. "
                f"Situazione P&L attuale: {icon} {pnl_eur:+.2f} € ({pnl_pct:+.2f}%)."
            )
        else:
            existing_pos_block = "Michele NON possiede ancora questo strumento nel proprio portafoglio (nuova potenziale allocazione)."

        # Rassegna notizie
        news_details = []
        for n in news_list[:4]:
            t_str = n.get("title", "")
            s_str = n.get("summary", "")
            if t_str:
                news_details.append(f"• {t_str}: {s_str}")
        news_str = "\n".join(news_details) if news_details else "Nessuna notizia rilevante nelle ultime ore."

        # Profilo Investitore
        profile_str = (
            f"Orizzonte: {user_profile.get('horizon', 'Lungo termine')} | "
            f"Strategia: {user_profile.get('strategy', 'Core-Satellite')} | "
            f"PAC Mensile stimato: {user_profile.get('monthly_pac_eur', 500)} € | "
            f"Profilo Rischio: {user_profile.get('risk_profile', 'Dinamico')} | "
            f"Broker: {user_profile.get('broker', 'Trade Republic')}"
        )

        limit_price = pred_data.get("limit_price_eur", round(cur_price_eur, 2))
        tp1 = pred_data.get("take_profit_1_eur", round(cur_price_eur * 1.05, 2))
        stop_loss = pred_data.get("stop_loss_eur", round(cur_price_eur * 0.94, 2))
        rebound_prob = pred_data.get("mean_reversion_probability", "75%")
        tempo_cycle = cycle_data.get("tempo_battleplan", "Consolidamento")
        consiglio_cycle = cycle_data.get("consiglio_pratico", "Attesa")

        prompt = f"""
Sei il Chief Investment Officer (CIO) e Senior Wealth Advisor personale di Michele.
DATA E ORA ATTUALE: {now_str}.

Michele ti ha chiesto un parere su: {asset_name} ({ticker}).
Tu NON sei un bot né un motore di ricerca che elenca dati grezzi. Tu sei il suo consulente di fiducia che ragiona, analizza, si assume una responsabilità strategica e gli dà un parere chiaro, netto e umano.

DATI TECNICI ED ECONOMICI (USALI COME TUA INTELLIGENZA INTERNA, NON COPIARE FORMULE A RAFFICA):
- Strumento: {asset_name} ({ticker})
- Prezzo Live in Euro: {cur_price_eur:.2f} € (Trade Republic L&S: Denaro/Bid {tr_bid_str} | Lettera/Ask {tr_ask_str})
- Portafoglio di Michele: {existing_pos_block}
- Profilo Investitore: {profile_str}
- Notizie e Catalyst delle ultime ore:
{news_str}
- Analisi Quantitativa Interna: Probabilità statistica di rimbalzo {rebound_prob}, Fase Ciclica di Migliorino: {tempo_cycle} ({consiglio_cycle}), Limite anti-spread stimato: {limit_price:.2f} €, Target rimbalzo TP1: {tp1:.2f} €, Livello allerta/SL: {stop_loss:.2f} €.

LINEE GUIDA RIGOROSE DI REDAZIONE:
1. DIVIETO ASSOLUTO DI ELENCHI MECCANICI DI INDICATORI:
   - NON inserire elenchi puntati con 'RSI: 32', 'Z-Score: -2.1', 'Monte Carlo 10.000', 'Wyckoff Phase'.
   - Traduci queste metriche in UN DISCORSO ECONOMICO E STRATEGICO FLUENTE.
2. DIVIETO ASSOLUTO DI APERTURE COLLOQUIALI O PATERNALISTICHE ('Caro amico', 'Mettiamoci comodi', 'Mio caro', 'Entriamo nel vivo').
   - Inizia con una riga istituzionale di testata e poi parla direttamente a Michele in tono sobrio, lucido, autorevole e rassicurante.
3. STRUTTURA DELLA CONSULENZA (3 PUNTI FOCALI):
   - 🔍 *1. La Situazione di Mercato (Cosa muove il titolo oggi):* Spiega in poche frasi limpide qual è il vero driver delle ultime ore (macro, rotazione, trimestrali, o sentiment).
   - 🧭 *2. La Mia Valutazione (La Tesi del CIO):* Esprimi una convinzione netta. È una reale occasione a sconto o una trappola? Se Michele ha già il titolo in portafoglio, commenta l'impatto sul suo PMC (es. 'avendo un PMC a 81,50 €, comprare qui a 75 € abbassa la media e aumenta il rendimento atteso...'). Se non lo possiede, spiega come si colloca nella sua strategia Core-Satellite.
   - ⚡ *3. Condotta Operativa su Trade Republic:* Spiega esattamente come operare (NON comprare a mercato per evitare lo spread di L&S; inserire un Ordine Limite a circa {limit_price:.2f} €; monitorare il target a {tp1:.2f} € e allerta a {stop_loss:.2f} €).
4. Tutte le quotazioni RIGOROSAMENTE in Euro (€).
"""
        return self._call_gemini(prompt)

    def generate_portfolio_strategic_diagnosis(
        self,
        portfolio_items: List[Dict[str, Any]],
        total_invested: float,
        total_current: float,
        user_profile: Dict[str, Any]
    ) -> str:
        """
        Genera la diagnosi complessiva di portafoglio da Senior Wealth Manager / CIO:
        - Asset Allocation & Ripartizione del rischio (ETF Core vs Factor vs Crypto vs Single Stock)
        - Analisi di correlazione e drawdown
        - Prossima mossa esecutiva di ribilanciamento con il PAC o con la liquidità libera su Trade Republic.
        """
        if not self.client:
            return ""

        now_str = self._get_current_time_str()
        items_summary = []
        for p in portfolio_items:
            items_summary.append(
                f"• {p['asset_name']} ({p['ticker']}): Peso nel portafoglio: {p.get('weight_pct', 0.0):.1f}% | "
                f"Controvalore: {p.get('current_val', 0.0):.2f} € | P&L: {p.get('pnl_eur', 0.0):+.2f} € ({p.get('pnl_pct', 0.0):+.2f}%)"
            )
        holdings_str = "\n".join(items_summary)

        tot_pnl_eur = total_current - total_invested
        tot_pnl_pct = ((total_current - total_invested) / total_invested) * 100 if total_invested > 0 else 0.0

        prompt = f"""
Sei il Chief Investment Officer (CIO) e Private Wealth Advisor di Michele.
DATA E ORA ATTUALE: {now_str}.

COMPOSIZIONE REALE DEL PORTAFOGLIO ATTUALE DI MICHELE:
{holdings_str}
- Capitale Totale Investito: {total_invested:.2f} €
- Controvalore Totale Attuale: {total_current:.2f} €
- Risultato Complessivo: {tot_pnl_eur:+.2f} € ({tot_pnl_pct:+.2f}%)
- Profilo e Obiettivi dell'investitore: Orizzonte {user_profile.get('horizon', '5-10 anni')} | PAC Mensile {user_profile.get('monthly_pac_eur', 500)} € | Strategia: {user_profile.get('strategy', 'Core-Satellite')} | Broker: {user_profile.get('broker', 'Trade Republic')}.

COMPITO OBBLIGATORIO:
Redigi la *Diagnosi Strategica del Portafoglio* con il tono di un Senior Portfolio Manager in carne ed ossa (lucido, analitico, propositivo, che ragiona con lui).

STRUTTURA LA CONSULENZA IN 2 SEZIONI CHIARE:
🧭 *1. Diagnosi di Asset Allocation & Rischio:*
- Analizza come è distribuito il capitale: qual è la quota dell'azionario globale Core (XDWD), quanto pesa il fattore Momentum (XDEM), quanto pesa la componente speculativa/satellitare (crypto Bitcoin/Cardano, single stock BYD).
- Esprimi un giudizio schietto: il portafoglio è ben difeso o è troppo esposto alla volatilità? Sta lavorando bene per l'orizzonte di lungo termine?

⚖️ *2. Ribilanciamento & Prossima Mossa Esecutiva:*
- Dai un consiglio chiaro sulla prossima mossa: con la prossima tranche di liquidità o il prossimo PAC mensile, dove conviene incrementare? (Es. conviene abbassare il PMC sul titolo che ha corretto di più, oppure rafforzare il Core?).
- Ricorda brevemente la gestione della liquidità su Trade Republic (mantenere una percentuale di liquidità remunerata al tasso del broker in attesa di cali di mercato).

LINEE GUIDA RIGOROSE:
- DIVIETO ASSOLUTO DI APERTURE PATERNALISTICHE ('Caro amico', 'Mettiamoci comodi', 'Mio caro').
- Inizia direttamente con la diagnosi.
- Parla in prima persona con autorevolezza istituzionale.
- Tutte le cifre RIGOROSAMENTE in Euro (€).
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

    def analyze_video(self, video_path: str, user_prompt: str = "") -> Dict[str, Any]:
        """
        Analizza un video multimodale (audio, parlato, grafica e fotogrammi) caricato su Telegram
        o scaricato da un link social (YouTube, Shorts, TikTok, Instagram Reels, X/Twitter).
        Supporta:
        1. Registrazioni schermo di broker (Trade Republic, Degiro): estrae le posizioni per l'importazione automatica.
        2. Video social di finanza/investimenti: sintesi della tesi, fact-checking critico e verdetto operativo del CIO.
        """
        if not self.client:
            return {"type": "error", "text": "Modulo AI Gemini non attivo o client non configurato."}

        now_str = self._get_current_time_str()
        user_note_block = f"\nNOTA/RICHIESTA DELL'UTENTE ALLEGATA:\n\"{user_prompt}\"\n" if user_prompt else ""
        
        prompt = f"""
Sei il Chief Investment Officer (CIO), Senior Quantitative Strategist ed esperto di analisi multimodale.
DATA E ORA ATTUALE DI ANALISI: {now_str}.
{user_note_block}
Hai davanti a te un video (con traccia audio, trascrizione del parlato e sequenza di fotogrammi).

COMPITO:
1. IDENTIFICA LA NATURA DEL VIDEO:
   - CASO A: REGISTRAZIONE SCHERMO PORTAFOGLIO / BROKER (Trade Republic, Scalable, Degiro, TradingView).
     Se mostra una schermata di portafoglio o una lista di titoli:
     Estrai tassativamente tutte le posizioni visibili in un blocco JSON valido:
     ```json
     {{
       "is_portfolio_recording": true,
       "positions": [
          {{
            "asset_name": "Nome strumento es. MSCI World Momentum",
            "ticker_candidate": "XDEM.DE",
            "shares": 32.2419,
            "average_buy_price": 75.10,
            "currency": "EUR"
          }}
       ]
     }}
     ```
     Accompagnalo con un commento esecutivo di sintesi delle posizioni rilevate.

   - CASO B: VIDEO SOCIAL / ANALISI FINANZIARIA / MARKET COMMENTARY (TikTok, Instagram Reel, YouTube Shorts, X/Twitter, TV/Web clip).
     Fornisci un'analisi di qualità istituzionale e alta densità informativa strutturata esattamente così:
     🎬 *Contenuto & Tesi Esposta:* Chi parla e qual è il punto focale del video (asset citati, previsioni, strategie o promesse dichiarate).
     🔍 *Fact-Checking & Valutazione Critica:* Verifica se le affermazioni corrispondono alla realtà dei dati macroeconomici odierni ({now_str}), dei multipli di mercato, della liquidità e dei rischi reali. Metti in guardia da claim fuorvianti, hype social o commissioni occulte/spread.
     🧭 *Verdetto del CIO & Guida Operativa:* Giudizio chiaro e netto: ha senso operare su questa idea? Con quale strategia di accumulo o protezione su Trade Republic in Euro (€)?

LINEE GUIDA RIGOROSE:
- DIVIETO ASSOLUTO DI FORMULE COLLOQUIALI O PATERNALISTICHE ('Caro amico', 'Mettiamoci comodi', 'Mio caro', 'Entriamo nel vivo'). Inizia DIRETTAMENTE con il report analitico.
- ANCORAGGIO TEMPORALE: Siamo a {now_str}. Tassativamente vietato citare anni passati (2024, 2025) per giustificare i mercati di oggi.
- Prezzi e valutazioni RIGOROSAMENTE in Euro (€).
- Formattazione Markdown pulita, con elenchi puntati ed emoji sobrie per una lettura perfetta su Telegram.
"""
        upload = None
        try:
            import time
            upload = self.client.files.upload(file=video_path)
            
            # Attesa elaborazione file su Gemini
            max_wait_secs = 60
            waited = 0
            while upload.state.name == "PROCESSING" and waited < max_wait_secs:
                time.sleep(2)
                waited += 2
                upload = self.client.files.get(name=upload.name)
            
            if upload.state.name != "ACTIVE":
                return {
                    "type": "error",
                    "text": f"Impossibile elaborare il video su Gemini (stato: {upload.state.name})."
                }

            text_resp = ""
            for model in self.models_to_try:
                try:
                    res = self.client.models.generate_content(
                        model=model,
                        contents=[upload, prompt]
                    )
                    if res and res.text:
                        text_resp = res.text.strip()
                        break
                except Exception as me:
                    print(f"[LLMReasoningService] Tentativo video con {model} fallito: {me}")

            if not text_resp:
                return {"type": "error", "text": "Non è stato possibile ottenere una risposta per questo video dai modelli AI."}

            positions = []
            is_portfolio = False
            if "```json" in text_resp:
                try:
                    json_str = text_resp.split("```json")[1].split("```")[0].strip()
                    data = json.loads(json_str)
                    if data.get("is_portfolio_recording") or "positions" in data or data.get("is_position"):
                        is_portfolio = True
                        if "positions" in data and isinstance(data["positions"], list):
                            positions = data["positions"]
                        elif data.get("is_position"):
                            positions = [data]
                except Exception as je:
                    print(f"[LLMReasoningService] Errore parsing JSON video: {je}")

            return {
                "type": "portfolio" if is_portfolio else "social_analysis",
                "is_portfolio": is_portfolio,
                "positions": positions,
                "text": text_resp
            }
        except Exception as e:
            print(f"[LLMReasoningService] Errore analyze_video: {e}")
            return {"type": "error", "text": f"Errore durante l'analisi del video: {str(e)}"}
        finally:
            if upload and hasattr(upload, "name"):
                try:
                    self.client.files.delete(name=upload.name)
                except Exception:
                    pass

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

    def generate_detailed_opportunities_report(
        self,
        opportunities: List[Dict[str, Any]]
    ) -> str:
        """
        Genera un report approfondito e discorsivo per le 10 migliori occasioni di mercato.
        Per ciascuno strumento analizza in modo discorsivo il PERCHÉ è un'occasione,
        la tesi fondamentale/macro, l'asimmetria tecnica quantitativa e la condotta operativa su Trade Republic.
        """
        if not self.client or not opportunities:
            return ""

        now_str = self._get_current_time_str()
        
        items_text = []
        for i, o in enumerate(opportunities, 1):
            tr_part = f" (Trade Republic L&S: Bid {o.get('tr_bid')} € / Ask {o.get('tr_ask')} €)" if o.get('tr_bid') else ""
            items_text.append(
                f"{i}. {o['name']} ({o['ticker']}):\n"
                f"   - Prezzo: {o['price_eur']} €{tr_part} | Variazione odierna: {o.get('change_pct', 0.0):+.2f}%\n"
                f"   - RSI (14): {o.get('rsi')} | Z-Score (distanza da SMA20): {o.get('z_score')}\n"
                f"   - Probabilità Rimbalzo Statistico: {o.get('rebound_prob')}\n"
                f"   - Target TP1: {o.get('tp1_eur')} € | Stop Loss: {o.get('sl_eur')} € | Rapporto R:R: {o.get('rr_ratio')}\n"
                f"   - Azione Algoritmica: {o.get('primary_action')}\n"
            )
        data_block = "\n".join(items_text)

        prompt = f"""
Sei il Chief Investment Officer (CIO) e Senior Quantitative Strategist.
DATA E ORA ATTUALE: {now_str}.
L'algoritmo quantitativo ha selezionato e ordinato le 10 migliori occasioni di mercato con il massimo sconto statistico e asimmetria favorevole:

{data_block}

COMPITO OBBLIGATORIO:
Redigi il report strategico ufficiale '💎 TOP 10 MIGLIORI OCCASIONI DI MERCATO (APPROFONDIMENTO ESECUTIVO)'.
Per TUTTI e 10 gli strumenti elencati sopra (senza saltarne alcuno, rigorosamente da 1 a 10), devi fornire una scheda dettagliata e un APPROFONDIMENTO DISCORSIVO (un paragrafo denso e articolato di 3-4 frasi per ciascuno) che spieghi con chiarezza:
1. *Perché è un'occasione reale:* Quale catalyst macro, settoriale o societario ha creato la discesa (es. rotazione dai titoli growth, sell-off tecnologico, colli di bottiglia energetici, reazione a tassi o flussi ETF) e perché i fondamentali non giustificano questo sconto.
2. *Asimmetria Tecnica & Statistica:* Spiega cosa significa il livello di RSI e Z-Score (es. distanza dalla media a 20 sedute, probabilità di rimbalzo statistico / mean reversion).
3. *Guida Tattica su Trade Republic:* Suggerisci l'approccio migliore (uso dell'Ordine Limite qualche frazione sotto mercato per proteggersi dallo spread di Lang & Schwarz, orizzonte temporale, livello di Take Profit e Stop Loss).

LINEE GUIDA RIGOROSE:
- DIVIETO ASSOLUTO DI APERTURE O CHIUSURE COLLOQUIALI ('Caro amico', 'Mettiamoci comodi', 'Mio caro', 'Entriamo nel vivo'). Inizia DIRETTAMENTE con il report.
- ANCORAGGIO TEMPORALE REALE: Siamo a {now_str}. È tassativamente vietato citare anni passati (2025, 2024) per giustificare i movimenti di oggi.
- Tutte le quotazioni RIGOROSAMENTE in Euro (€).
- Per ciascuno dei 10 strumenti mantieni la numerazione (1, 2, 3... 10), il nome, il ticker, i prezzi in Euro e il paragrafo di approfondimento discorsivo '📝 Perché è un'occasione:'.
- Mantieni una formattazione Markdown ordinata con elenchi puntati e grassetti per rendere la lettura chiara e piacevole su Telegram.
"""
        return self._call_gemini(prompt)
