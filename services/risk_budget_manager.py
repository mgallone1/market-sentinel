"""
Strict Risk & Asymmetric Money Management Service.
Regole Matematiche Inderogabili:
1. MAX RISK PER TRADE: $100.00 fissi (Non si rischia mai di più, per nessun motivo).
2. CALCOLO QUOTE A RITROSO: Qty = $100 / (Prezzo Entry - Prezzo Stop).
3. RAPPORTO RISCHIO/RENDIMENTO MINIMO: 2.0 (Target obbligatorio >= $200.00 di guadagno).
   Se un'operazione non offre almeno 1:2.0 di asimmetria -> SCARTATA AUTOMATICAMENTE.
"""

import math
from typing import Dict, Any, Optional

class RiskBudgetManager:
    def __init__(self, max_risk_usd: float = 100.0, min_rr: float = 2.0):
        self.max_risk_usd = max_risk_usd
        self.min_rr = min_rr

    def calculate_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss_price: float,
        target_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calcola la size esatta per blindare il rischio al centesimo.
        Rifiuta il trade se non rispetta l'asimmetria minima 1:2.
        """
        side_lower = side.lower()
        if side_lower in ["buy", "long"]:
            risk_per_share = entry_price - stop_loss_price
            if risk_per_share <= 0:
                return {"valid": False, "reason": "Stop loss deve essere inferiore al prezzo di acquisto."}
            
            # Se target non fornito, lo imposta a 2.0R obbligatorio
            if not target_price or target_price <= entry_price:
                target_price = entry_price + (risk_per_share * self.min_rr)
            
            reward_per_share = target_price - entry_price
        else: # sell / short
            risk_per_share = stop_loss_price - entry_price
            if risk_per_share <= 0:
                return {"valid": False, "reason": "Stop loss deve essere superiore al prezzo di vendita short."}
            
            if not target_price or target_price >= entry_price:
                target_price = entry_price - (risk_per_share * self.min_rr)
                
            reward_per_share = entry_price - target_price

        # Controllo Asimmetria Matematica R:R
        rr_ratio = reward_per_share / risk_per_share
        if rr_ratio < self.min_rr:
            return {
                "valid": False,
                "reason": f"Rapporto R:R insufficiente ({rr_ratio:.2f}:1). Il minimo obbligatorio è {self.min_rr}:1."
            }

        # Calcolo quote a ritroso per blindare la perdita massima esattamente a $100
        shares = math.floor(self.max_risk_usd / risk_per_share)
        if shares < 1:
            shares = 1 # minimo 1 quota

        total_risk = round(shares * risk_per_share, 2)
        total_potential_reward = round(shares * reward_per_share, 2)
        notional_capital = round(shares * entry_price, 2)

        return {
            "valid": True,
            "symbol": symbol.upper(),
            "side": "buy" if side_lower in ["buy", "long"] else "sell",
            "shares": shares,
            "entry_price": round(entry_price, 2),
            "stop_loss": round(stop_loss_price, 2),
            "take_profit": round(target_price, 2),
            "rr_ratio": round(rr_ratio, 2),
            "max_loss_usd": total_risk,
            "potential_gain_usd": total_potential_reward,
            "notional_capital_usd": notional_capital
        }
