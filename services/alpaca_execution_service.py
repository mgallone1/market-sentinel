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
        self.api_key = os.environ.get("ALPACA_API_KEY", "")
        self.secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
        self.is_paper = os.environ.get("ALPACA_PAPER_TRADE", "true").lower() == "true"
        self._load_credentials()

    def _load_credentials(self):
        # Fallback to local ~/.alpaca_paper.env if not in environment
        env_path = os.path.expanduser("~/.alpaca_paper.env")
        if (not self.api_key or not self.secret_key) and os.path.exists(env_path):
            try:
                with open(env_path) as f:
                    env = dict(line.strip().split('=', 1) for line in f if '=' in line)
                    self.api_key = env.get('ALPACA_API_KEY', '')
                    self.secret_key = env.get('ALPACA_SECRET_KEY', '')
                    self.is_paper = env.get('ALPACA_PAPER_TRADE', 'true').lower() == 'true'
            except Exception as e:
                logger.error(f"Error reading local alpaca env: {e}")

        # Hardcoded fallback for paper demo
        if not self.api_key:
            self.api_key = "PKWXW7ZOPAE4UPWCHT6DEJVJO6"
            self.secret_key = "2eEjHoVUYdmKM2YcQL1M2JhP3mtMMc2pLgN3wSgd5rsL"
            self.is_paper = True

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
        today_trades = self.get_today_closed_trades()
        
        return {
            "account": acc,
            "clock": clock,
            "positions": positions if isinstance(positions, list) else [],
            "today_closed_trades": today_trades
        }

    def get_today_closed_trades(self) -> List[Dict[str, Any]]:
        """
        Recupera e calcola con logica FIFO i round-trip completati nella giornata odierna,
        restituendo per ciascuno il profitto/perdita realizzato e l'orario di chiusura.
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

            today_rome_str = datetime.datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d")
            sym_fills = defaultdict(list)
            for a in all_acts:
                sym_fills[a.get('symbol')].append({
                    'side': a.get('side'),
                    'qty': float(a.get('qty', 0)),
                    'price': float(a.get('price', 0)),
                    'time': a.get('transaction_time', '')
                })

            closed_today = []
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
                        dt_rome = dt_utc.astimezone(ZoneInfo("Europe/Rome"))
                        is_today = dt_rome.strftime("%Y-%m-%d") == today_rome_str
                        close_time_str = dt_rome.strftime("%H:%M")
                    except Exception:
                        is_today = False
                        close_time_str = ""

                    if side in ['buy']:
                        while qty > 1e-6 and short_queue:
                            sqty, sprice, stime = short_queue[0]
                            m_qty = min(qty, sqty)
                            pnl = (sprice - price) * m_qty
                            if is_today:
                                closed_today.append({
                                    'symbol': sym,
                                    'side': 'SHORT',
                                    'qty': m_qty,
                                    'entry_price': sprice,
                                    'exit_price': price,
                                    'pnl': pnl,
                                    'pnl_pct': ((sprice - price) / sprice) * 100 if sprice else 0.0,
                                    'close_time': close_time_str
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
                            if is_today:
                                closed_today.append({
                                    'symbol': sym,
                                    'side': 'LONG',
                                    'qty': m_qty,
                                    'entry_price': bprice,
                                    'exit_price': price,
                                    'pnl': pnl,
                                    'pnl_pct': ((price - bprice) / bprice) * 100 if bprice else 0.0,
                                    'close_time': close_time_str
                                })
                            qty -= m_qty
                            if bqty - m_qty > 1e-6:
                                long_queue[0] = (bqty - m_qty, bprice, btime)
                            else:
                                long_queue.pop(0)
                        if qty > 1e-6:
                            short_queue.append((qty, price, t))

            # Raggruppa per simbolo e direzione se eseguiti allo stesso orario
            consolidated = []
            for ct in closed_today:
                consolidated.append(ct)
            return consolidated
        except Exception as e:
            logger.error(f"Errore calcolo today_closed_trades: {e}")
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
        return self._api_request(f"positions/{symbol.upper()}", method="DELETE")
