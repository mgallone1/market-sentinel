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
        
        return {
            "account": acc,
            "clock": clock,
            "positions": positions if isinstance(positions, list) else []
        }

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

    def close_all_positions(self) -> Dict[str, Any]:
        return self._api_request("positions", method="DELETE")

    def close_position(self, symbol: str) -> Dict[str, Any]:
        return self._api_request(f"positions/{symbol.upper()}", method="DELETE")
