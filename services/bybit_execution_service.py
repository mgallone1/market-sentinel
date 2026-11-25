import os
from typing import Dict, Any, List, Optional
from pybit.unified_trading import HTTP


import re as _re


def make_order_link_id(symbol: str, side: str, bar_open_ts) -> str:
    """Id deterministico (<=36 char, [A-Za-z0-9_-]) da simbolo, lato e open-time della barra chiusa del segnale.
    bar_open_ts: epoch in secondi (int/float) o pandas.Timestamp/datetime."""
    sym = _re.sub(r"[^A-Za-z0-9]", "", str(symbol).upper())[:8]
    s = "L" if str(side).lower() in ("l", "long", "buy", "compra") else "S"
    ts = bar_open_ts.timestamp() if hasattr(bar_open_ts, "timestamp") else float(bar_open_ts)
    return f"ms{sym}{s}{int(ts // 60)}"[:36]


def is_duplicate_link_id_response(res) -> bool:
    """True se Bybit segnala orderLinkId duplicato (retCode 10014 o retMsg 'duplicate')."""
    if not isinstance(res, dict):
        return False
    if res.get("retCode") == 10014:
        return True
    return "duplicate" in str(res.get("retMsg", "")).lower()


def classify_btc_bias(closes_4h, closes_1h) -> str:
    """Classificazione macro BTC (EMA20/50 su 4h e 1h; serie dalla piu' vecchia alla piu' recente, solo barre chiuse)."""
    def _ema(vals, span):
        a = 2.0 / (span + 1.0)
        e = vals[0]
        for v in vals[1:]:
            e = a * v + (1.0 - a) * e
        return e
    ema20_4h, ema50_4h, last_4h = _ema(closes_4h, 20), _ema(closes_4h, 50), closes_4h[-1]
    ema50_1h, last_1h = _ema(closes_1h, 50), closes_1h[-1]
    if last_4h > ema50_4h and ema20_4h >= ema50_4h:
        return "BULLISH"
    if last_4h < ema50_4h and last_1h < ema50_1h:
        return "BEARISH"
    return "NEUTRAL"


def hysteresis_bias(current: str, previous: str) -> str:
    """Bias confermato solo se le due valutazioni consecutive concordano, altrimenti NEUTRAL."""
    return current if current == previous else "NEUTRAL"


def format_bybit_price(price: float, ref_price: float) -> str:
    """
    Formatta un prezzo Bybit Linear USDT adattando i decimali alla scala dell'asset (`ref_price`),
    evitando troncamenti fatali su monete sub-dollaro (DOGE, XRP, ADA, SUI) e rispettando il tickSize BTC (0.1).
    """
    p = float(price or 0.0)
    if p <= 0:
        return "0"
    r = abs(float(ref_price or p))
    if r >= 10000.0:
        dec = 1
    elif r >= 100.0:
        dec = 2
    elif r >= 5.0:
        dec = 3
    elif r >= 0.5:
        dec = 4
    elif r >= 0.05:
        dec = 5
    elif r >= 0.005:
        dec = 6
    else:
        dec = 7
    return f"{round(p, dec):.{dec}f}"


def format_bybit_qty(raw_qty: float, clean_sym: str) -> str:
    """Formatta la quantità contratti compatibile con i step size standard Bybit Linear USDT."""
    q = max(0.0, float(raw_qty or 0.0))
    sym = str(clean_sym or "").upper()
    if "BTC" in sym:
        return str(round(q, 3))
    if "ETH" in sym:
        return str(round(q, 2))
    if any(tok in sym for tok in ("DOGE", "XRP", "ADA", "SUI", "PEPE", "SHIB", "TRX", "XLM")) or q >= 100.0:
        return str(max(1, int(round(q))))
    if q >= 1.0:
        return str(round(q, 1))
    return str(round(q, 2))


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


    def get_cumulative_volume_delta(self, symbol: str, limit: int = 50) -> Dict[str, Any]:
        """
        Calcola il Cumulative Volume Delta (CVD) sui trade eseguiti a mercato più recenti.
        Restituisce buy_vol, sell_vol, delta (CVD) e ratio tra compratori e venditori aggressivi.
        """
        try:
            res = self.session.get_public_trade_history(category="linear", symbol=symbol, limit=limit)
            trades = res.get("result", {}).get("list", [])
            if not trades:
                return {"cvd": 0.0, "ratio": 1.0, "bias": "NEUTRAL"}
            
            buy_vol = sum(float(t.get("size", 0.0)) for t in trades if t.get("side") == "Buy")
            sell_vol = sum(float(t.get("size", 0.0)) for t in trades if t.get("side") == "Sell")
            cvd = buy_vol - sell_vol
            total = buy_vol + sell_vol
            ratio = (buy_vol / (sell_vol + 1e-6)) if total > 0 else 1.0
            
            bias = "BULLISH" if ratio > 1.35 else ("BEARISH" if ratio < 0.70 else "NEUTRAL")
            return {
                "cvd": round(cvd, 4),
                "buy_vol": round(buy_vol, 4),
                "sell_vol": round(sell_vol, 4),
                "ratio": round(ratio, 2),
                "bias": bias
            }
        except Exception as e:
            return {"cvd": 0.0, "ratio": 1.0, "bias": "NEUTRAL", "error": str(e)}

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
        side: str,  # 'Buy' o 'Sell'
        notional_usd: float = 2500.0,
        take_profit_pct: Optional[float] = 2.5,
        stop_loss_pct: Optional[float] = 1.5,
        leverage: int = 1,
        order_link_id: Optional[str] = None,
        order_type: str = "Market",
        limit_price: Optional[float] = None,
        post_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Piazza un ordine di apertura LONG o SHORT su Bybit Linear USDT (Market o Limit/PostOnly).
        order_link_id: id idempotente (max 36 char, [A-Za-z0-9_-]) inviato come orderLinkId:
        Bybit rifiuta un secondo ordine con lo stesso id (-> {"duplicate": True}).
        Calcola automaticamente la quantità di contratti in base al notional in dollari
        e imposta leva, Take Profit e Stop Loss con precisione adattiva al prezzo dell'asset.
        """
        clean_sym = symbol.upper().replace("/", "").replace("-", "")
        if not clean_sym.endswith("USDT"):
            clean_sym = f"{clean_sym}USDT"

        side_fmt = "Buy" if side.lower() in ["buy", "long", "compra"] else "Sell"

        # 1. Recupera prezzo corrente per calcolare qty e validare riferimento
        tickers = self.get_realtime_tickers([clean_sym])
        curr_price = float(tickers.get(clean_sym, {}).get("last_price", 0.0) or 0.0)
        is_limit = str(order_type or "Market").strip().lower() == "limit" and limit_price is not None and float(limit_price) > 0
        if curr_price <= 0 and not is_limit:
            return {"error": f"Impossibile determinare il prezzo live per {clean_sym}"}

        ref_price = float(limit_price) if is_limit else curr_price
        if curr_price <= 0:
            curr_price = ref_price

        # Calcola qty adattiva per symbol
        raw_qty = notional_usd / ref_price
        qty_str = format_bybit_qty(raw_qty, clean_sym)

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

        # Calcola TP e SL rispetto al prezzo di riferimento (limit_price se Limit, altrimenti curr_price)
        tp_str = ""
        sl_str = ""
        if side_fmt == "Buy":
            if take_profit_pct:
                tp_str = format_bybit_price(ref_price * (1 + take_profit_pct / 100), ref_price)
            if stop_loss_pct:
                sl_str = format_bybit_price(ref_price * (1 - stop_loss_pct / 100), ref_price)
        else:  # SHORT
            if take_profit_pct:
                tp_str = format_bybit_price(ref_price * (1 - take_profit_pct / 100), ref_price)
            if stop_loss_pct:
                sl_str = format_bybit_price(ref_price * (1 + stop_loss_pct / 100), ref_price)

        order_params: Dict[str, Any] = {
            "category": "linear",
            "symbol": clean_sym,
            "side": side_fmt,
            "orderType": "Limit" if is_limit else "Market",
            "qty": qty_str,
            "timeInForce": ("PostOnly" if post_only else "GTC") if is_limit else "GTC",
        }
        if is_limit:
            order_params["price"] = format_bybit_price(float(limit_price), curr_price)
        if tp_str:
            order_params["takeProfit"] = tp_str
        if sl_str:
            order_params["stopLoss"] = sl_str
        if order_link_id:
            order_params["orderLinkId"] = str(order_link_id)

        try:
            res = self.session.place_order(**order_params)
            if is_duplicate_link_id_response(res):
                return {"error": "duplicate_order_link_id", "duplicate": True}
            if res.get("retCode") == 0:
                return {
                    "status": "success",
                    "order_id": res.get("result", {}).get("orderId"),
                    "symbol": clean_sym,
                    "side": "LONG" if side_fmt == "Buy" else "SHORT",
                    "order_type": order_params["orderType"],
                    "qty": qty_str,
                    "notional": notional_usd,
                    "price": ref_price,
                    "take_profit": tp_str,
                    "stop_loss": sl_str
                }
            return {"error": res.get("retMsg", "Errore piazzamento ordine Bybit")}
        except Exception as e:
            if is_duplicate_link_id_response({"retMsg": str(e), "retCode": getattr(e, "status_code", None)}):
                return {"error": "duplicate_order_link_id", "duplicate": True}
            return {"error": str(e)}

    def update_stop_loss(self, symbol: str, new_stop_loss: float) -> Dict[str, Any]:
        """Aggiorna lo Stop Loss di una posizione aperta (es. spostamento a Break-Even protettivo)."""
        clean_sym = symbol.upper().replace("/", "").replace("-", "")
        if not clean_sym.endswith("USDT"):
            clean_sym = f"{clean_sym}USDT"
        try:
            sl_formatted = format_bybit_price(new_stop_loss, new_stop_loss)
            res = self.session.set_trading_stop(
                category="linear",
                symbol=clean_sym,
                stopLoss=sl_formatted,
                tpslMode="Full"
            )
            if res.get("retCode") == 0:
                return {"status": "success", "symbol": clean_sym, "new_stop_loss": float(sl_formatted)}
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
