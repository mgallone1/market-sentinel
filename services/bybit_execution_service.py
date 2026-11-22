import os
from typing import Dict, Any, List, Optional
from pybit.unified_trading import HTTP

class BybitExecutionService:
    """
    Servizio di Trading Ufficiale per Bybit (Unified Trading Account - Linear USDT Perpetuals).
    Supporta Trading 24/7/365, ordini LONG e SHORT reali, Take Profit e Stop Loss bracket
    sul conto Demo (Paper Trading) senza rischio di capitale reale.
    """
    def __init__(self):
        self.api_key = os.getenv("BYBIT_API_KEY", "iOkhd2tFhimfMP9xwC").strip()
        self.api_secret = os.getenv("BYBIT_API_SECRET", "QAvEzfyiV1lVEhKgAcwPgR3ULIAXWrHloA3m").strip()
        self.demo = os.getenv("BYBIT_DEMO", "true").lower() in ["true", "1", "yes"]

        self.session = HTTP(
            demo=self.demo,
            api_key=self.api_key,
            api_secret=self.api_secret
        )

    def get_wallet_summary(self) -> Dict[str, Any]:
        """Restituisce il saldo del conto Unificato Bybit Demo."""
        try:
            res = self.session.get_wallet_balance(accountType="UNIFIED")
            if res.get("retCode") == 0:
                acc = res.get("result", {}).get("list", [{}])[0]
                total_equity = float(acc.get("totalEquity", 0.0))
                total_margin_bal = float(acc.get("totalMarginBalance", 0.0))
                total_avail = float(acc.get("totalAvailableBalance", 0.0))
                coins = {}
                for c in acc.get("coin", []):
                    wb = float(c.get("walletBalance", 0.0))
                    if wb > 0:
                        coins[c.get("coin")] = wb
                return {
                    "total_equity": total_equity,
                    "available_balance": total_avail,
                    "margin_balance": total_margin_bal,
                    "coins": coins
                }
            return {"error": res.get("retMsg", "Errore saldo Bybit")}
        except Exception as e:
            return {"error": str(e)}

    def get_open_positions(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Restituisce tutte le posizioni aperte (Long e Short) sui futures USDT."""
        try:
            res = self.session.get_positions(category="linear", settleCoin="USDT")
            if res.get("retCode") == 0:
                pos_list = res.get("result", {}).get("list", [])
                active = []
                for p in pos_list:
                    size = float(p.get("size", 0.0))
                    if size > 0:
                        sym = p.get("symbol")
                        # Recupera candele recenti (15m, ultimi 12 periodi) per mini sparkline
                        sparkline = []
                        try:
                            k_res = self.session.get_kline(category="linear", symbol=sym, interval="15", limit=12)
                            if k_res.get("retCode") == 0:
                                k_list = k_res.get("result", {}).get("list", [])
                                sparkline = [float(k[4]) for k in reversed(k_list)]
                        except Exception:
                            pass

                        active.append({
                            "symbol": sym,
                            "side": p.get("side").upper(), # 'BUY' -> Long, 'SELL' -> Short
                            "size": size,
                            "entry_price": float(p.get("avgPrice", 0.0)),
                            "mark_price": float(p.get("markPrice", 0.0)),
                            "take_profit": float(p.get("takeProfit", 0.0) or 0.0),
                            "stop_loss": float(p.get("stopLoss", 0.0) or 0.0),
                            "unrealized_pnl": float(p.get("unrealisedPnl", 0.0)),
                            "pnl_pct": (float(p.get("unrealisedPnl", 0.0)) / (float(p.get("positionValue", 1.0)) or 1.0)) * 100,
                            "position_value": float(p.get("positionValue", 0.0)),
                            "leverage": p.get("leverage"),
                            "sparkline": sparkline
                        })
                return active
            return []
        except Exception as e:
            print(f"[!] Errore recupero posizioni Bybit: {e}")
            return []

    def get_realtime_tickers(self, symbols: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """Recupera le quotazioni live dei contratti USDT perpetual."""
        try:
            # Se è richiesto un solo simbolo, lo passiamo direttamente come parametro per evitare payload enormi e rate limit
            params = {"category": "linear"}
            if symbols and len(symbols) == 1:
                params["symbol"] = symbols[0]
            res = self.session.get_tickers(**params)
            if res.get("retCode") == 0:
                data = {}
                target_syms = set(symbols) if symbols else None
                for t in res.get("result", {}).get("list", []):
                    sym = t.get("symbol")
                    if not target_syms or sym in target_syms:
                        data[sym] = {
                            "last_price": float(t.get("lastPrice", 0.0)),
                            "price_24h_pc": float(t.get("price24hPcnt", 0.0)) * 100,
                            "high_24h": float(t.get("highPrice24h", 0.0)),
                            "low_24h": float(t.get("lowPrice24h", 0.0)),
                            "volume_24h": float(t.get("volume24h", 0.0))
                        }
                return data
            
            # Fallback pubblico REST se il server demo restituisce rate limit da IP cloud
            import urllib.request
            import json
            req_sym = symbols[0] if symbols and len(symbols) == 1 else "BTCUSDT"
            url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={req_sym}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                pub_data = json.loads(resp.read().decode())
                if pub_data.get("retCode") == 0:
                    t_item = pub_data.get("result", {}).get("list", [])[0]
                    return {
                        req_sym: {
                            "last_price": float(t_item.get("lastPrice", 0.0)),
                            "price_24h_pc": float(t_item.get("price24hPcnt", 0.0)) * 100,
                            "high_24h": float(t_item.get("highPrice24h", 0.0)),
                            "low_24h": float(t_item.get("lowPrice24h", 0.0)),
                            "volume_24h": float(t_item.get("volume24h", 0.0))
                        }
                    }
            return {}
        except Exception as e:
            # Secondo fallback da CoinGecko o Yahoo se Bybit è rate-limited
            try:
                import urllib.request, json
                req_sym = symbols[0] if symbols and len(symbols) == 1 else "BTCUSDT"
                url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={req_sym}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    pub_data = json.loads(resp.read().decode())
                    if pub_data.get("retCode") == 0:
                        t_item = pub_data.get("result", {}).get("list", [])[0]
                        return {
                            req_sym: {
                                "last_price": float(t_item.get("lastPrice", 0.0)),
                                "price_24h_pc": float(t_item.get("price24hPcnt", 0.0)) * 100,
                                "high_24h": float(t_item.get("highPrice24h", 0.0)),
                                "low_24h": float(t_item.get("lowPrice24h", 0.0)),
                                "volume_24h": float(t_item.get("volume24h", 0.0))
                            }
                        }
            except Exception:
                pass
            print(f"[!] Errore tickers Bybit: {e}")
            return {}

    def get_orderbook_imbalance(self, symbol: str, limit: int = 15) -> Dict[str, Any]:
        """
        Calcola l'Order Book Imbalance (OBI) sui primi N livelli del book.
        Valori positivi (> +0.30): forte pressione in acquisto (muri di Bid).
        Valori negativi (< -0.30): forte pressione in vendita (muri di Ask).
        """
        clean_sym = symbol.upper().replace("/", "").replace("-", "")
        try:
            res = self.session.get_orderbook(category="linear", symbol=clean_sym, limit=limit)
            if res.get("retCode") == 0:
                bids = res.get("result", {}).get("b", [])
                asks = res.get("result", {}).get("a", [])
                bid_vol = sum(float(b[1]) for b in bids)
                ask_vol = sum(float(a[1]) for a in asks)
                tot_vol = bid_vol + ask_vol
                imbalance = (bid_vol - ask_vol) / tot_vol if tot_vol > 0 else 0.0
                return {
                    "imbalance": round(imbalance, 3),
                    "bid_vol": round(bid_vol, 2),
                    "ask_vol": round(ask_vol, 2),
                    "bias": "BUY_WALL" if imbalance > 0.35 else ("SELL_WALL" if imbalance < -0.35 else "BALANCED")
                }
            return {"imbalance": 0.0, "bias": "BALANCED"}
        except Exception as e:
            return {"imbalance": 0.0, "bias": "BALANCED", "error": str(e)}

    def place_order(
        self,
        symbol: str,
        side: str, # 'Buy' o 'Sell'
        notional_usd: float = 2500.0,
        take_profit_pct: Optional[float] = 2.5,
        stop_loss_pct: Optional[float] = 1.5,
        leverage: int = 1
    ) -> Dict[str, Any]:
        """
        Piazza un ordine di apertura LONG o SHORT su Bybit Linear USDT.
        Calcola automaticamente la quantità di contratti in base al notional in dollari
        e imposta leva, Take Profit e Stop Loss se specificati.
        """
        clean_sym = symbol.upper().replace("/", "").replace("-", "")
        if not clean_sym.endswith("USDT"):
            clean_sym = f"{clean_sym}USDT"

        side_fmt = "Buy" if side.lower() in ["buy", "long", "compra"] else "Sell"

        # 1. Recupera prezzo corrente per calcolare qty corretta
        tickers = self.get_realtime_tickers([clean_sym])
        curr_price = tickers.get(clean_sym, {}).get("last_price", 0.0)
        if curr_price <= 0:
            return {"error": f"Impossibile determinare il prezzo live per {clean_sym}"}

        # Calcola qty
        raw_qty = notional_usd / curr_price
        # Precisione per symbol
        if "BTC" in clean_sym:
            qty_str = str(round(raw_qty, 3))
        elif "ETH" in clean_sym:
            qty_str = str(round(raw_qty, 2))
        elif "SOL" in clean_sym:
            qty_str = str(round(raw_qty, 1))
        else:
            qty_str = str(round(raw_qty, 1))

        # Imposta Leva (1x di default per zero rischio liquidazione)
        try:
            self.session.set_leverage(
                category="linear",
                symbol=clean_sym,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)
            )
        except Exception:
            pass

        # Calcola TP e SL
        tp_str = ""
        sl_str = ""
        if side_fmt == "Buy":
            if take_profit_pct:
                tp_str = str(round(curr_price * (1 + take_profit_pct / 100), 2))
            if stop_loss_pct:
                sl_str = str(round(curr_price * (1 - stop_loss_pct / 100), 2))
        else: # SHORT
            if take_profit_pct:
                tp_str = str(round(curr_price * (1 - take_profit_pct / 100), 2))
            if stop_loss_pct:
                sl_str = str(round(curr_price * (1 + stop_loss_pct / 100), 2))

        order_params: Dict[str, Any] = {
            "category": "linear",
            "symbol": clean_sym,
            "side": side_fmt,
            "orderType": "Market",
            "qty": qty_str,
            "timeInForce": "GTC"
        }
        if tp_str:
            order_params["takeProfit"] = tp_str
        if sl_str:
            order_params["stopLoss"] = sl_str

        try:
            res = self.session.place_order(**order_params)
            if res.get("retCode") == 0:
                return {
                    "status": "success",
                    "order_id": res.get("result", {}).get("orderId"),
                    "symbol": clean_sym,
                    "side": "LONG" if side_fmt == "Buy" else "SHORT",
                    "qty": qty_str,
                    "notional": notional_usd,
                    "price": curr_price,
                    "take_profit": tp_str,
                    "stop_loss": sl_str
                }
            return {"error": res.get("retMsg", "Errore piazzamento ordine Bybit")}
        except Exception as e:
            return {"error": str(e)}

    def update_stop_loss(self, symbol: str, new_stop_loss: float) -> Dict[str, Any]:
        """Aggiorna lo Stop Loss di una posizione aperta (es. spostamento a Break-Even protettivo)."""
        clean_sym = symbol.upper().replace("/", "").replace("-", "")
        if not clean_sym.endswith("USDT"):
            clean_sym = f"{clean_sym}USDT"
        try:
            res = self.session.set_trading_stop(
                category="linear",
                symbol=clean_sym,
                stopLoss=str(round(new_stop_loss, 4)),
                tpslMode="Full"
            )
            if res.get("retCode") == 0:
                return {"status": "success", "symbol": clean_sym, "new_stop_loss": new_stop_loss}
            return {"error": res.get("retMsg", "Errore aggiornamento stop loss")}
        except Exception as e:
            return {"error": str(e)}

    def close_position(self, symbol: str) -> Dict[str, Any]:
        """Chiude a mercato qualsiasi posizione aperta (Long o Short) su un asset."""
        clean_sym = symbol.upper().replace("/", "").replace("-", "")
        if not clean_sym.endswith("USDT"):
            clean_sym = f"{clean_sym}USDT"

        try:
            pos_list = self.get_open_positions([clean_sym])
            target_pos = next((p for p in pos_list if p["symbol"] == clean_sym), None)
            if not target_pos:
                return {"error": f"Nessuna posizione aperta trovata per {clean_sym}"}

            close_side = "Sell" if target_pos["side"] == "BUY" else "Buy"
            res = self.session.place_order(
                category="linear",
                symbol=clean_sym,
                side=close_side,
                orderType="Market",
                qty=str(target_pos["size"]),
                reduceOnly=True,
                timeInForce="GTC"
            )
            if res.get("retCode") == 0:
                return {
                    "status": "closed",
                    "symbol": clean_sym,
                    "closed_side": target_pos["side"],
                    "qty": target_pos["size"],
                    "unrealized_pnl": target_pos["unrealized_pnl"]
                }
            return {"error": res.get("retMsg", "Errore chiusura posizione Bybit")}
        except Exception as e:
            return {"error": str(e)}
