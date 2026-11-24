"""
Alpaca Execution Service for Market Sentinel.
Provides live & paper order execution, bracket orders, position monitoring, and emergency liquidation.
Reads credentials from local env or cloud environment variables.
"""

import os
import json
import urllib.request
import urllib.error
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class AlpacaExecutionService:
    def __init__(self):
        self.api_key = os.environ.get("ALPACA_API_KEY", "").strip()
        self.secret_key = os.environ.get("ALPACA_SECRET_KEY", "").strip()
        self.is_paper = os.environ.get("ALPACA_PAPER_TRADE", "true").lower() == "true"
        self._load_credentials()

    def _load_credentials(self):
        # Fallback to local ~/.alpaca_paper.env if not in environment
        env_path = os.path.expanduser("~/.alpaca_paper.env")
        if (not self.api_key or not self.secret_key) and os.path.exists(env_path):
            try:
                with open(env_path) as f:
                    env = dict(line.strip().split('=', 1) for line in f if '=' in line)
                    self.api_key = env.get('ALPACA_API_KEY', '').strip()
                    self.secret_key = env.get('ALPACA_SECRET_KEY', '').strip()
                    self.is_paper = env.get('ALPACA_PAPER_TRADE', 'true').lower() == 'true'
            except Exception as e:
                logger.error(f"Error reading local alpaca env: {e}")

        # Se le credenziali mancano, errore esplicito: vietato qualsiasi fallback o valore di default
        if not self.api_key or not self.secret_key:
            raise ValueError(
                "CRITICAL SECURITY ERROR: Credenziali Alpaca assenti! "
                "ALPACA_API_KEY e ALPACA_SECRET_KEY devono essere fornite tramite variabili d'ambiente. "
                "È vietato l'uso di chiavi hardcoded o credenziali di default."
            )

        self.base_url = "https://paper-api.alpaca.markets/v2" if self.is_paper else "https://api.alpaca.markets/v2"

    def _api_request(self, endpoint: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint}"
        data = json.dumps(payload).encode('utf-8') if payload else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                'APCA-API-KEY-ID': self.api_key,
                'APCA-API-SECRET-KEY': self.secret_key,
                'Content-Type': 'application/json'
            },
            method=method
        )
        try:
            with urllib.request.urlopen(req) as resp:
                content = resp.read().decode()
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode()
            logger.error(f"Alpaca HTTP Error {e.code}: {err_msg}")
            return {"error": f"HTTP {e.code}: {err_msg}"}
        except Exception as e:
            logger.error(f"Alpaca API Request Error: {e}")
            return {"error": str(e)}

    def get_account_summary(self) -> Dict[str, Any]:
        acc = self._api_request("account")
        clock = self._api_request("clock")
        positions = self._api_request("positions")
        recent_closed = self.get_recent_closed_trades(limit_days=3)
        
        return {
            "account": acc,
            "clock": clock,
            "positions": positions if isinstance(positions, list) else [],
            "recent_closed_trades": recent_closed
        }

    def get_recent_closed_trades(self, limit_days: int = 3) -> List[Dict[str, Any]]:
        """
        Recupera e calcola con logica FIFO i round-trip completati nelle ultime sessioni
        (default 3 giorni, coprendo weekend e sessione precedente),
        restituendo per ciascuno il profitto/perdita realizzato, la data e l'orario di chiusura.
        """
        try:
            import datetime
            from zoneinfo import ZoneInfo
            from collections import defaultdict

            all_acts = []
            page_token = None
            while True:
                endpoint = "account/activities/FILL?direction=asc&page_size=100"
                if page_token:
                    endpoint += f"&page_token={page_token}"
                data = self._api_request(endpoint)
                if not data or not isinstance(data, list):
                    break
                all_acts.extend(data)
                if len(data) < 100:
                    break
                page_token = data[-1].get('id')

            rome_tz = ZoneInfo("Europe/Rome")
            now_rome = datetime.datetime.now(rome_tz)
            cutoff_date = (now_rome - datetime.timedelta(days=limit_days)).strftime("%Y-%m-%d")

            sym_fills = defaultdict(list)
            for a in all_acts:
                sym_fills[a.get('symbol')].append({
                    'side': a.get('side'),
                    'qty': float(a.get('qty', 0)),
                    'price': float(a.get('price', 0)),
                    'time': a.get('transaction_time', '')
                })

            closed_trades = []
            for sym, fills in sym_fills.items():
                long_queue = []
                short_queue = []
                for f in fills:
                    side = f['side']
                    qty = f['qty']
                    price = f['price']
                    t = f['time']
                    try:
                        dt_utc = datetime.datetime.fromisoformat(t.replace('Z', '+00:00'))
                        dt_rome = dt_utc.astimezone(rome_tz)
                        trade_date_str = dt_rome.strftime("%Y-%m-%d")
                        trade_time_str = dt_rome.strftime("%H:%M")
                        is_in_range = trade_date_str >= cutoff_date
                    except Exception:
                        is_in_range = False
                        trade_date_str = ""
                        trade_time_str = ""

                    if side in ['buy']:
                        while qty > 1e-6 and short_queue:
                            sqty, sprice, stime = short_queue[0]
                            m_qty = min(qty, sqty)
                            pnl = (sprice - price) * m_qty
                            if is_in_range:
                                closed_trades.append({
                                    'symbol': sym,
                                    'side': 'SHORT',
                                    'qty': m_qty,
                                    'entry_price': sprice,
                                    'exit_price': price,
                                    'pnl': pnl,
                                    'pnl_pct': ((sprice - price) / sprice) * 100 if sprice else 0.0,
                                    'date': trade_date_str,
                                    'time': trade_time_str,
                                    'raw_time': t
                                })
                            qty -= m_qty
                            if sqty - m_qty > 1e-6:
                                short_queue[0] = (sqty - m_qty, sprice, stime)
                            else:
                                short_queue.pop(0)
                        if qty > 1e-6:
                            long_queue.append((qty, price, t))

                    elif side in ['sell', 'sell_short']:
                        while qty > 1e-6 and long_queue:
                            bqty, bprice, btime = long_queue[0]
                            m_qty = min(qty, bqty)
                            pnl = (price - bprice) * m_qty
                            if is_in_range:
                                closed_trades.append({
                                    'symbol': sym,
                                    'side': 'LONG',
                                    'qty': m_qty,
                                    'entry_price': bprice,
                                    'exit_price': price,
                                    'pnl': pnl,
                                    'pnl_pct': ((price - bprice) / bprice) * 100 if bprice else 0.0,
                                    'date': trade_date_str,
                                    'time': trade_time_str,
                                    'raw_time': t
                                })
                            qty -= m_qty
                            if bqty - m_qty > 1e-6:
                                long_queue[0] = (bqty - m_qty, bprice, btime)
                            else:
                                long_queue.pop(0)
                        if qty > 1e-6:
                            short_queue.append((qty, price, t))

            # Ordina dal più recente al più vecchio
            closed_trades.sort(key=lambda x: x.get('raw_time', ''), reverse=True)
            return closed_trades
        except Exception as e:
            logger.error(f"Errore calcolo get_recent_closed_trades: {e}")
            return []

    def place_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: str = "buy",
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "qty": qty,
            "side": side.lower(),
            "type": "market",
            "time_in_force": "day",
            "order_class": "bracket"
        }
        if take_profit_price:
            payload["take_profit"] = {"limit_price": round(take_profit_price, 2)}
        if stop_loss_price:
            payload["stop_loss"] = {"stop_price": round(stop_loss_price, 2)}

        return self._api_request("orders", method="POST", payload=payload)

    def place_crypto_order(
        self,
        symbol: str,
        qty: Optional[float] = None,
        notional: Optional[float] = None,
        side: str = "buy"
    ) -> Dict[str, Any]:
        """
        Piazza un ordine crypto su Alpaca (mercato attivo 24/7).
        Su Alpaca il simbolo va espresso come BTC/USD o ETH/USD.
        Si può specificare o la quantità in coin (qty) o il controvalore in dollari (notional, es. 250$).
        """
        sym = symbol.upper()
        if "/" not in sym and not sym.endswith("USD"):
            sym = f"{sym}/USD"
        elif not "/" in sym and sym.endswith("USD"):
            sym = f"{sym[:-3]}/USD"

        payload: Dict[str, Any] = {
            "symbol": sym,
            "side": side.lower(),
            "type": "market",
            "time_in_force": "gtc"
        }
        if qty is not None:
            payload["qty"] = str(round(qty, 6))
        elif notional is not None:
            payload["notional"] = str(round(notional, 2))
        else:
            payload["notional"] = "100.0"

        return self._api_request("orders", method="POST", payload=payload)

    def get_crypto_latest_bars(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """Recupera le quotazioni realtime dal feed ufficiale Alpaca Crypto."""
        symbols = symbols or ["BTC/USD", "ETH/USD", "SOL/USD"]
        sym_param = ",".join(symbols)
        url = f"https://data.alpaca.markets/v1beta3/crypto/us/latest/bars?symbols={sym_param}"
        req = urllib.request.Request(
            url,
            headers={
                'APCA-API-KEY-ID': self.api_key,
                'APCA-API-SECRET-KEY': self.secret_key
            },
            method="GET"
        )
        try:
            with urllib.request.urlopen(req) as resp:
                content = resp.read().decode()
                res = json.loads(content) if content else {}
                return res.get("bars", {})
        except Exception as e:
            logger.error(f"Errore recupero crypto bars Alpaca: {e}")
            return {}

    def close_all_positions(self) -> Dict[str, Any]:
        return self._api_request("positions", method="DELETE")

    def close_position(self, symbol: str) -> Dict[str, Any]:
        """
        Chiude a mercato qualsiasi posizione aperta su un titolo Alpaca.
        Passa cancel_orders=true per cancellare automaticamente gli ordini bracket pendenti
        (Stop Loss e Take Profit) che altrimenti bloccherebbero la chiusura (errore 403: held_for_orders).
        """
        return self._api_request(f"positions/{symbol.upper()}?cancel_orders=true", method="DELETE")

    def update_stop_loss(self, symbol: str, new_stop_price: float) -> Dict[str, Any]:
        """
        Aggiorna il prezzo di Stop Loss di una posizione aperta Alpaca.
        Trova l'ordine stop pendente associato al simbolo e ne fa il replace/patch.
        """
        clean_sym = symbol.upper().strip()
        open_orders = self._api_request("orders?status=open")
        if not isinstance(open_orders, list):
            return {"error": "Impossibile recuperare ordini aperti Alpaca"}

        stop_order = next((o for o in open_orders if o.get("symbol") == clean_sym and o.get("type") == "stop"), None)
        if not stop_order:
            return {"error": f"Nessun ordine stop pendente trovato per {clean_sym}"}

        order_id = stop_order.get("id")
        payload = {"stop_price": str(round(new_stop_price, 2))}
        res = self._api_request(f"orders/{order_id}", method="PATCH", payload=payload)
        return res
