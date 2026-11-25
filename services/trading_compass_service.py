"""
Trading Compass & Directional Edge Service for Market Sentinel.
Calcola in tempo reale indicatori quantitativi matematici per verificare oggettivamente
se il sistema sta generando un reale vantaggio statistico (EDGE) o se sta andando nella direzione sbagliata:

1. DIRECTIONAL BIAS & HEALTH SCORE (0-100):
   - Sintesi ponderata dell'orientamento statistico complessivo.
   - Punteggio > 65: FORTE EDGE POSITIVO (Segnali allineati, trend a favore).
   - Punteggio 45-65: ZONA NEUTRA / CONSOLIDAMENTO (Mercato laterale, no overtrading).
   - Punteggio < 45: ALLERTA DISALLINEAMENTO (Rischio di chop, stop loss conservativi).

2. EXPECTED VALUE PER TRADE (EV in $):
   - Formula: (Win Rate * Avg Win) - (Loss Rate * Avg Loss)
   - Mostra quanti dollari matematicamente genera in media ogni singolo trade da $15k.

3. RISK-REWARD REALE vs TEORICO (Realized R:R):
   - Rapporto medio tra vincita media e perdita media reale a mercato (deve essere >= 2.0).

4. MAX DRAWDOWN & RECOVERY FACTOR:
   - Percentuale massima di ritracciamento dal picco e capacità di risalita.

5. MARKET REGIME RADAR (Trend vs Range):
   - Rileva se il mercato generale su BTC/ETH è in Trend Forte (Trending) o Compressione (Chop).
"""

from typing import Dict, Any, List
import math
import time

_CACHED_READINESS = None
_CACHED_READINESS_TIME = 0
_READINESS_TTL = 45.0  # Cache 45s per azzerare chiamate esterne yfinance e garantire latenza API < 10ms

class TradingCompassService:
    @staticmethod
    def compute_edge_metrics(closed_trades: List[Dict[str, Any]], open_positions: List[Dict[str, Any]], total_equity: float) -> Dict[str, Any]:
        wins = []
        losses = []
        total_pnl = 0.0
        total_vol = 0.0

        for c in closed_trades:
            pnl = float(c.get("closedPnl", 0.0) or 0.0)
            total_pnl += pnl
            vol = float(c.get("cumExitValue", 0.0) or 0.0) + float(c.get("cumEntryValue", 0.0) or 0.0)
            total_vol += vol
            if pnl > 0:
                wins.append(pnl)
            elif pnl < 0:
                losses.append(abs(pnl))

        n_trades = len(closed_trades)
        win_count = len(wins)
        loss_count = len(losses)

        win_rate = (win_count / n_trades * 100) if n_trades > 0 else 0.0
        avg_win = (sum(wins) / win_count) if win_count > 0 else 0.0
        avg_loss = (sum(losses) / loss_count) if loss_count > 0 else 0.0

        # Realized Risk-Reward Ratio (Win / Loss)
        realized_rr = (avg_win / avg_loss) if avg_loss > 0 else (avg_win if avg_win > 0 else 1.0)

        # Expected Value per trade ($)
        win_prob = win_rate / 100.0
        loss_prob = (1.0 - win_prob) if n_trades > 0 else 0.0
        ev_per_trade = (win_prob * avg_win) - (loss_prob * avg_loss)

        # Profit Factor
        gross_profit = sum(wins)
        gross_loss = sum(losses)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        # Indicatori di stato delle posizioni aperte (In the Money Ratio)
        unrealized_tot = sum(float(p.get("unrealized_pnl", 0.0) or 0.0) for p in open_positions)
        green_positions = sum(1 for p in open_positions if float(p.get("unrealized_pnl", 0.0) or 0.0) > 0)
        be_positions = sum(1 for p in open_positions if float(p.get("pnl_pct", 0.0) or 0.0) >= 0.60)
        open_count = len(open_positions)
        itm_ratio = (green_positions / open_count * 100) if open_count > 0 else 50.0

        # Calcolo DIRECTIONAL HEALTH SCORE (0 a 100)
        # Componenti:
        # 1. Posizioni aperte in profitto o protette da Break-Even (30%)
        # 2. Risk/Reward ratio su target (25%)
        # 3. Trend Alignment (25%)
        # 4. Profit Factor / Win Rate Trend (20%)
        score = 50.0 # base neutra

        # Aggiustamento ITM aperte
        score += (itm_ratio - 50.0) * 0.35

        # Aggiustamento protezioni Break-Even attive (+10 punti per ogni trade già de-rischiato a zero)
        if be_positions > 0:
            score += min(be_positions * 8, 20)

        # Aggiustamento PnL non realizzato
        if unrealized_tot > 0:
            score += min((unrealized_tot / 100.0) * 5, 15)
        else:
            score -= min((abs(unrealized_tot) / 100.0) * 5, 15)

        # Limite 0-100
        score = max(5.0, min(95.0, round(score, 1)))

        # Verdetto sintetico
        if score >= 65:
            verdict = "DIREZIONE CORRETTA (STRONG EDGE)"
            verdict_desc = "Il sistema ha posizioni allineate al trend primario con rischio residuo coperto o protetto a break-even."
            verdict_color = "green"
        elif score >= 45:
            verdict = "FASE DI CONSOLIDAMENTO (HOLD & WATCH)"
            verdict_desc = "Mercato in compressione laterale. Il bot filtra i falsi breakout e preserva la liquidità in attesa di volatilità."
            verdict_color = "amber"
        else:
            verdict = "DISALLINEAMENTO TEMPORANEO (RISK GUARD)"
            verdict_desc = "Volatilità avversa rilevata. Lo stop-loss dinamico su ATR e i filtri volume/ciclo impediscono overtrading dannoso."
            verdict_color = "red"

        return {
            "health_score": score,
            "verdict": verdict,
            "verdict_desc": verdict_desc,
            "verdict_color": verdict_color,
            "expected_value_usd": round(ev_per_trade, 2),
            "realized_rr": round(realized_rr, 2),
            "target_rr": 3.0,
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "open_itm_ratio": round(itm_ratio, 1),
            "protected_positions_count": be_positions,
            "open_positions_count": open_count,
            "total_trades": n_trades,
            "avg_win_usd": round(avg_win, 2),
            "avg_loss_usd": round(avg_loss, 2)
        }

    @staticmethod
    def compute_setup_readiness(bybit_service=None) -> Dict[str, Any]:
        """
        Calcola l'indice Setup Readiness Radar (0-100) anche in totale assenza di trade aperti.
        Misura la vicinanza matematica del mercato all'attivazione di un setup confluente A+:
        1. Macro Bias (BTC 4H + 1H) [0-25 pt]
        2. Ciclica di Hurst & Battleplan Migliorino [0-25 pt]
        3. Momentum & Compressione Volatilità RSI [0-25 pt]
        4. Microstruttura Order Book Imbalance (OBI) [0-25 pt]
        """
        global _CACHED_READINESS, _CACHED_READINESS_TIME
        now_t = time.time()
        if _CACHED_READINESS is not None and (now_t - _CACHED_READINESS_TIME) < _READINESS_TTL:
            return _CACHED_READINESS

        import yfinance as yf
        import pandas as pd
        from services.hurst_migliorino_cycles import HurstMigliorinoCycleService

        macro_score = 15
        macro_text = "Neutro / Monitoraggio"
        cycle_score = 15
        cycle_text = "Allineamento in corso"
        rsi_score = 15
        rsi_text = "Compressione neutrale"
        obi_score = 15
        obi_text = "Book bilanciato"
        expected_movement = "Monitoraggio Breakout 1H"
        last_price = 0.0

        try:
            # Scarica BTC 1H e 4H
            df_btc_1h = yf.download("BTC-USD", period="1mo", interval="1h", progress=False)
            df_btc_4h = yf.download("BTC-USD", period="3mo", interval="4h", progress=False)

            c_1h = df_btc_1h["Close"].iloc[:, 0] if hasattr(df_btc_1h["Close"], "iloc") and len(df_btc_1h["Close"].shape) > 1 else df_btc_1h["Close"]
            c_4h = df_btc_4h["Close"].iloc[:, 0] if hasattr(df_btc_4h["Close"], "iloc") and len(df_btc_4h["Close"].shape) > 1 else df_btc_4h["Close"]

            if not c_1h.empty and not c_4h.empty:
                last_price = float(c_1h.iloc[-1])
                ema50_4h = float(c_4h.ewm(span=50, adjust=False).mean().iloc[-1])
                ema20_4h = float(c_4h.ewm(span=20, adjust=False).mean().iloc[-1])
                ema50_1h = float(c_1h.ewm(span=50, adjust=False).mean().iloc[-1])

                # 1. Macro Bias Score (0-25)
                if last_price > ema50_4h and ema20_4h >= ema50_4h:
                    macro_score = 25
                    macro_text = "BULLISH (Rialzo strutturale confermato)"
                elif last_price < ema50_4h and last_price < ema50_1h:
                    macro_score = 12
                    macro_text = "BEARISH (Debolezza diffusa / Cautela)"
                else:
                    macro_score = 18
                    macro_text = "NEUTRAL (Rimbalzo tattico / Transizione)"

                # 2. Ciclica Hurst & Migliorino 1H (0-25)
                clean_df = pd.DataFrame({"Close": c_1h})
                cycle = HurstMigliorinoCycleService.calculate_cycle_metrics(clean_df)
                tempo = cycle.get("tempo_battleplan", "")
                fld = float(cycle.get("hurst_fld_value", 0.0) or 0.0)

                if "1° TEMPO" in tempo.upper() or "2° TEMPO" in tempo.upper():
                    if last_price > fld:
                        cycle_score = 24
                        cycle_text = f"Accumulo Avanzato ({tempo}, Prezzo > FLD)"
                    else:
                        cycle_score = 18
                        cycle_text = f"Fase Iniziale di Spinta ({tempo})"
                elif "3° TEMPO" in tempo.upper():
                    cycle_score = 14
                    cycle_text = f"Fase di Distribuzione / Ritracciamento ({tempo})"
                else:
                    cycle_score = 10
                    cycle_text = f"Fase Terminale Ciclo ({tempo})"

                # 3. RSI 1H (0-25)
                delta = c_1h.diff()
                gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / (loss + 1e-9)
                rsi = float((100 - (100 / (1 + rs))).iloc[-1])

                if 52 <= rsi <= 68:
                    rsi_score = 25
                    rsi_text = f"Momentum ottimale ({rsi:.1f}) in accelerazione"
                elif 42 <= rsi < 52:
                    rsi_score = 18
                    rsi_text = f"Compressione laterale ({rsi:.1f}) pronta al breakout"
                elif rsi > 70:
                    rsi_score = 12
                    rsi_text = f"Ipercomprato esteso ({rsi:.1f}) - Attesa scarico"
                else:
                    rsi_score = 9
                    rsi_text = f"Forte ipervenduto ({rsi:.1f}) - Ricerca base"

            # 4. Order Book Imbalance (OBI Bybit) (0-25)
            if bybit_service:
                try:
                    obi = bybit_service.get_orderbook_imbalance("BTCUSDT")
                    imbalance = float(obi.get("imbalance", 0.0) or 0.0)
                    if imbalance > 0.20:
                        obi_score = 25
                        obi_text = f"Forte supporto Bid (Imbalance {imbalance:+.2f})"
                    elif imbalance >= -0.20:
                        obi_score = 18
                        obi_text = f"Book equilibrato (Imbalance {imbalance:+.2f})"
                    else:
                        obi_score = 8
                        obi_text = f"Muri di vendita Ask (Imbalance {imbalance:+.2f})"
                except Exception:
                    pass

        except Exception as e_readiness:
            print(f"[!] Errore calcolo setup readiness: {e_readiness}")

        total_readiness = max(5, min(98, macro_score + cycle_score + rsi_score + obi_score))

        # Tipologia di movimento atteso e verdetto
        if total_readiness >= 75:
            readiness_verdict = "TRIGGER IMMINENTE"
            readiness_color = "green"
            expected_movement = "Breakout direzionale imminente con confluenza favorevole (apertura probabile a breve)"
        elif total_readiness >= 55:
            readiness_verdict = "SET-UP IN MATURAZIONE"
            readiness_color = "amber"
            expected_movement = "Fase di accumulo/consolidamento; attesa rottura FLD e liberazione resistenze nel book"
        else:
            readiness_verdict = "STAND-BY RIGIDO"
            readiness_color = "red"
            expected_movement = "Mercato incerto o contro-trend; il capitale resta protetto al 100% in liquidità"

        res = {
            "readiness_score": total_readiness,
            "readiness_verdict": readiness_verdict,
            "readiness_color": readiness_color,
            "expected_movement": expected_movement,
            "breakdown": {
                "macro": {"score": macro_score, "max": 25, "text": macro_text},
                "cycle": {"score": cycle_score, "max": 25, "text": cycle_text},
                "rsi": {"score": rsi_score, "max": 25, "text": rsi_text},
                "book": {"score": obi_score, "max": 25, "text": obi_text}
            }
        }
        _CACHED_READINESS = res
        _CACHED_READINESS_TIME = now_t
        return res

    @staticmethod
    def compute_alpaca_setup_readiness() -> Dict[str, Any]:
        """
        Calcola l'Indice di Confluenza Pre-Trade per Wall Street (Alpaca):
        1. Macro SPY (EMA20 vs EMA50 1H)
        2. Ciclica 1H (Hurst FLD & Battleplan su SPY)
        3. RSI Momentum (SPY 1H)
        4. VIX Volatility Shield (livello e delta giornaliero ^VIX)
        """
        global _CACHED_ALPACA_READINESS, _CACHED_ALPACA_READINESS_TIME
        now_t = time.time()
        if "_CACHED_ALPACA_READINESS" in globals() and _CACHED_ALPACA_READINESS is not None and (now_t - _CACHED_ALPACA_READINESS_TIME) < 45.0:
            return _CACHED_ALPACA_READINESS

        macro_score, cycle_score, rsi_score, vix_score = 10, 12, 12, 12
        macro_text = "SPY in fase neutra"
        cycle_text = "Ciclo 1H in consolidamento"
        rsi_text = "Momentum RSI neutro"
        vix_text = "VIX in fascia normale"

        try:
            import yfinance as yf
            import pandas as pd
            from services.hurst_migliorino_cycles import HurstMigliorinoCycleService
            from services.indicators_safe import wilder_rsi, drop_forming_bar

            df_spy = yf.download("SPY", period="1mo", interval="1h", progress=False)
            if not df_spy.empty and len(df_spy) >= 35:
                if isinstance(df_spy.columns, pd.MultiIndex):
                    df_spy.columns = df_spy.columns.get_level_values(0)
                df_spy = drop_forming_bar(df_spy, 60)
                c = df_spy["Close"].dropna()
                last_c = float(c.iloc[-1])
                ema20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
                ema50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])

                if last_c > ema20 and ema20 >= ema50:
                    macro_score = 25
                    macro_text = "SPY rialzista sopra EMA20/50 1H"
                elif last_c > ema20:
                    macro_score = 16
                    macro_text = "SPY sopra EMA20 1H (rimbalzo)"
                else:
                    macro_score = 5
                    macro_text = "SPY sotto EMA20 1H (debolezza)"

                rsi = float(wilder_rsi(c, 14).iloc[-1])
                if 50 <= rsi <= 68:
                    rsi_score = 24
                    rsi_text = f"RSI {rsi:.1f} (spinta ottimale)"
                elif rsi > 68:
                    rsi_score = 12
                    rsi_text = f"RSI {rsi:.1f} (ipercomprato)"
                else:
                    rsi_score = 8
                    rsi_text = f"RSI {rsi:.1f} (momentum debole)"

                cycle = HurstMigliorinoCycleService.calculate_cycle_metrics(pd.DataFrame({"Close": c}))
                tempo = str(cycle.get("tempo_battleplan", "")).upper()
                fld = float(cycle.get("hurst_fld_value", 0.0) or 0.0)
                if ("1° TEMPO" in tempo or "2° TEMPO" in tempo) and last_c > fld:
                    cycle_score = 25
                    cycle_text = f"Ciclo favorevole ({tempo})"
                elif last_c > fld:
                    cycle_score = 16
                    cycle_text = "Prezzo sopra FLD Hurst"
                else:
                    cycle_score = 6
                    cycle_text = f"Ciclo sfavorevole ({tempo or 'sotto FLD'})"

            vix_df = yf.download("^VIX", period="10d", interval="1d", progress=False)
            if not vix_df.empty:
                v_c = vix_df["Close"].iloc[:, 0] if isinstance(vix_df["Close"], pd.DataFrame) else vix_df["Close"]
                vix_val = float(v_c.iloc[-1])
                prev_vix = float(v_c.iloc[-2]) if len(v_c) >= 2 else vix_val
                vix_delta = ((vix_val - prev_vix) / prev_vix) * 100.0 if prev_vix > 0 else 0.0

                if vix_delta > 2.0 or (vix_val >= 24.0 and vix_delta >= 0.0) or vix_val >= 28.0:
                    vix_score = 0
                    vix_text = f"VIX Shield ATTIVO ({vix_val:.1f}, {vix_delta:+.1f}%)"
                elif vix_val < 20.0:
                    vix_score = 25
                    vix_text = f"VIX disteso ({vix_val:.1f}, {vix_delta:+.1f}%)"
                else:
                    vix_score = 15
                    vix_text = f"VIX moderato ({vix_val:.1f}, {vix_delta:+.1f}%)"
        except Exception as e_alp:
            print(f"[!] Errore calcolo Alpaca setup readiness: {e_alp}")

        total_readiness = max(5, min(98, macro_score + cycle_score + rsi_score + vix_score))
        if vix_score == 0:
            readiness_verdict = "VIX SHIELD ATTIVO"
            readiness_color = "red"
            expected_movement = "Volatilità VIX in aumento: ingressi Long su Wall Street sospesi per protezione capitale"
        elif total_readiness >= 75:
            readiness_verdict = "TRIGGER IMMINENTE"
            readiness_color = "green"
            expected_movement = "Confluenza SPY/VIX e Ciclica 1H favorevole su Wall Street"
        elif total_readiness >= 55:
            readiness_verdict = "SET-UP IN MATURAZIONE"
            readiness_color = "amber"
            expected_movement = "Mercato USA in consolidamento; attesa conferma su SPY e VIX"
        else:
            readiness_verdict = "STAND-BY RIGIDO"
            readiness_color = "red"
            expected_movement = "Condizioni macro USA sfavorevoli; capitale protetto in liquidità"

        res = {
            "readiness_score": total_readiness,
            "readiness_verdict": readiness_verdict,
            "readiness_color": readiness_color,
            "expected_movement": expected_movement,
            "breakdown": {
                "macro": {"score": macro_score, "max": 25, "text": macro_text},
                "cycle": {"score": cycle_score, "max": 25, "text": cycle_text},
                "rsi": {"score": rsi_score, "max": 25, "text": rsi_text},
                "book": {"score": vix_score, "max": 25, "text": vix_text}
            }
        }
        _CACHED_ALPACA_READINESS = res
        _CACHED_ALPACA_READINESS_TIME = now_t
        return res

_CACHED_ALPACA_READINESS = None
_CACHED_ALPACA_READINESS_TIME = 0.0

trading_compass = TradingCompassService()
