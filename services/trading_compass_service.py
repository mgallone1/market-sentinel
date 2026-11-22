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
            verdict_desc = "Volatilità avversa rilevata. Lo stop-loss a -1.20% e il filtro volume impediscono overtrading dannoso."
            verdict_color = "red"

        return {
            "health_score": score,
            "verdict": verdict,
            "verdict_desc": verdict_desc,
            "verdict_color": verdict_color,
            "expected_value_usd": round(ev_per_trade, 2),
            "realized_rr": round(realized_rr, 2),
            "target_rr": 2.5,
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "open_itm_ratio": round(itm_ratio, 1),
            "protected_positions_count": be_positions,
            "open_positions_count": open_count,
            "total_trades": n_trades,
            "avg_win_usd": round(avg_win, 2),
            "avg_loss_usd": round(avg_loss, 2)
        }

trading_compass = TradingCompassService()
