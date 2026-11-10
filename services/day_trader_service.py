"""
Day Trader Service for Market Sentinel.
Integrates the modular Day Trader Skill suite (from Jakeschincariol/day-trader-skill):
- Congressional PTR trades tracker (Pelosi & Congress disclosures)
- Market setup scanner (ORB, 20d High Breakouts, Bull Flags, Oversold Bounce)
- Time Machine Monte Carlo simulation (10,000 intraday replays)
- Breaking news monitor with catalyst tags
"""

import os
import sys
import json
import logging
import subprocess
import tempfile
import importlib.util
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Base directory for day trader modules
DAY_TRADER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "day_trader"))


class DayTraderService:
    def __init__(self):
        self.base_dir = DAY_TRADER_DIR
        self.pelosi_script = os.path.join(self.base_dir, "trader-pelosi", "ptr.py")
        self.scanner_script = os.path.join(self.base_dir, "trader-scanner", "scan.py")
        self.timemachine_script = os.path.join(self.base_dir, "trader-timemachine", "timemachine.py")
        self.news_script = os.path.join(self.base_dir, "trader-news", "news.py")

    def get_congress_trades(self, member: str = "pelosi", max_reports: int = 3) -> List[Dict[str, Any]]:
        """
        Fetches the latest Periodic Transaction Reports (PTRs) filed by a member of Congress
        (default: Nancy Pelosi) and parses the underlying transactions.
        """
        results = []
        try:
            if not os.path.exists(self.pelosi_script):
                logger.error(f"ptr.py script not found at {self.pelosi_script}")
                return results

            # Import ptr module dynamically
            spec = importlib.util.spec_from_file_location("ptr_mod", self.pelosi_script)
            ptr_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ptr_mod)

            import datetime as _dt
            current_year = _dt.date.today().year
            filings = ptr_mod.load_index(current_year)
            selected = ptr_mod.select(filings, members=[member])

            if not selected and current_year > 2025:
                # Fallback to previous year if early in the year
                filings_prev = ptr_mod.load_index(current_year - 1)
                selected = ptr_mod.select(filings_prev, members=[member])

            for filing in selected[:max_reports]:
                doc_id = filing.get("doc_id")
                year = filing.get("year", current_year)
                filed_date = filing.get("filed")
                pdf_url = filing.get("url") or (ptr_mod.PTR_URL % (year, doc_id))

                report_data = {
                    "doc_id": doc_id,
                    "member": filing.get("name"),
                    "district": filing.get("district"),
                    "filed": filed_date,
                    "url": pdf_url,
                    "transactions": []
                }

                # Try to download and parse details
                try:
                    pdf_bytes = ptr_mod.download(pdf_url, timeout=15)
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                        tf.write(pdf_bytes)
                        tf_path = tf.name

                    txt = ptr_mod.pdf_to_text(tf_path)
                    if not txt:
                        # Fallback con pypdf se pdftotext non è installato a livello di OS
                        try:
                            import pypdf
                            reader = pypdf.PdfReader(tf_path)
                            txt_pages = [page.extract_text() or "" for page in reader.pages]
                            txt = "\n".join(txt_pages)
                        except Exception as pex:
                            logger.warning(f"pypdf fallback failed: {pex}")

                    try:
                        os.remove(tf_path)
                    except Exception:
                        pass

                    if txt:
                        parsed = ptr_mod.parse_ptr_text(txt, filed=filed_date)
                        for row in parsed.get("rows", []):
                            report_data["transactions"].append({
                                "ticker": row.get("ticker"),
                                "asset": row.get("asset"),
                                "type": row.get("type_name", row.get("type")),
                                "amount": row.get("amount"),
                                "description": row.get("description"),
                                "trade_date": row.get("date"),
                                "owner": row.get("owner_name", "self")
                            })
                except Exception as ex:
                    logger.warning(f"Could not parse PTR details for {doc_id}: {ex}")

                results.append(report_data)

        except Exception as e:
            logger.error(f"Error fetching congress trades: {e}", exc_info=True)

        return results

    def scan_market_setups(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Runs the daily chart scanner across a universe or custom watchlist.
        Returns matched setups (breakout 20d, bull flag, reclaim MA20, oversold, oversold bounce).
        """
        if not symbols:
            symbols = [
                "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "AMZN", "META", "GOOGL",
                "PLTR", "COIN", "MSTR", "SMCI", "AVGO", "INTC", "ASML", "ARM"
            ]

        sym_str = ",".join(symbols)
        cmd = [sys.executable, self.scanner_script, "daily", "--symbols", sym_str]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            output = res.stdout

            # Check if trader/watchlist.json was written
            watchlist_path = "trader/watchlist.json"
            hits = []
            if os.path.exists(watchlist_path):
                try:
                    with open(watchlist_path, "r") as f:
                        data = json.load(f)
                        hits = data.get("hits", [])
                except Exception:
                    pass

            return {
                "raw_output": output,
                "hits": hits,
                "symbols_scanned": symbols
            }
        except Exception as e:
            logger.error(f"Error running market scanner: {e}", exc_info=True)
            return {"error": str(e), "hits": [], "symbols_scanned": symbols}

    def run_timemachine(
        self,
        symbol: str,
        entry: float,
        stop: float,
        target: float,
        date: Optional[str] = None,
        entry_time: str = "10:15 AM",
        replays: int = 10000
    ) -> Dict[str, Any]:
        """
        Runs the 10,000 session Monte Carlo replay on 5-minute bars.
        """
        if not date:
            import datetime as _dt
            # Default to most recent completed weekday
            d = _dt.date.today() - _dt.timedelta(days=1)
            while d.weekday() >= 5:
                d -= _dt.timedelta(days=1)
            date = d.strftime("%Y-%m-%d")

        cmd = [
            sys.executable, self.timemachine_script, "run",
            "--symbol", symbol,
            "--date", date,
            "--entry", str(entry),
            "--stop", str(stop),
            "--target", str(target),
            "--entry-time", entry_time,
            "--replays", str(replays),
            "--json"
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=40)
            output = res.stdout
            err = res.stderr
            if res.returncode != 0:
                return {"error": err or output}

            # Parse JSON if output is JSON, or return output text
            try:
                data = json.loads(output)
                return {"success": True, "data": data}
            except Exception:
                return {"success": True, "raw_output": output}
        except Exception as e:
            logger.error(f"Error running timemachine: {e}", exc_info=True)
            return {"error": str(e)}

    def get_breaking_news(self, tickers: Optional[List[str]] = None, hours: int = 48) -> str:
        """
        Fetches breaking news and SEC filing alerts for the specified tickers.
        """
        if not tickers:
            tickers = ["NVDA", "TSLA", "AAPL", "BTC-USD", "MSFT"]

        ticker_args = " ".join(tickers)
        cmd = [sys.executable, self.news_script, "--tickers"] + tickers + ["--hours", str(hours)]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=25)
            return res.stdout
        except Exception as e:
            logger.error(f"Error fetching news: {e}", exc_info=True)
            return f"Errore recupero news: {e}"
