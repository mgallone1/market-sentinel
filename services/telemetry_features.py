"""Telemetry v2: orthogonal state variables logged with executed trades and shadow signals.

TELEMETRY ONLY. Nothing in this module is read by an entry/exit rule, the Time Machine gate, the
risk manager or the allocator. Every function is pure (or, for the Bybit public REST fetcher,
non-blocking with a short timeout) and returns None / NaN-free dictionaries on any failure, so a
telemetry error can never block or slow down the trading loop.

Blocks
1. Rogers-Satchell OHLC variance (drift-independent, captures intrabar excursions).
2. Empirical-Bayes drift shrinkage (removes the Jensen inflation of P(TP) from a noisy drift).
3. Idiosyncratic decomposition vs SPY (beta, orthogonal residual, its z-score, cross-sectional rank).
4. Orthogonal state variables: Bybit funding and open-interest deltas (public REST v5),
   Bulk Volume Classification order-flow imbalance, volatility risk premium (VIX - RV SPY 5d).
"""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

import numpy as np
import pandas as pd

# Columns added to trade_journal and signal_shadows (all REAL, NULL when unavailable).
TELEMETRY_V2_COLUMNS: Tuple[str, ...] = (
    "fp_s_rs", "fp_p_tp_rs", "fp_p_sl_rs", "fp_p_tp_rs_zero_drift", "fp_p_sl_rs_zero_drift",
    "fp_nu_bayes", "fp_p_tp_bayes", "fp_p_sl_bayes", "fp_ev_r_bayes",
    "spy_beta", "idio_ret_window", "idio_z_drift", "idio_cs_rank",
    "bybit_funding_rate", "bybit_oi_delta_1h", "bybit_oi_delta_4h",
    "ofi_bvc_short", "ofi_bvc_med",
    "vrp_spread",
)

ALPACA_UNIVERSE: Tuple[str, ...] = ("NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "META", "GOOGL", "AMD")


def _finite(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _col(df: pd.DataFrame, name: str) -> Optional[pd.Series]:
    for c in (name, name.lower(), name.upper()):
        if c in df.columns:
            return pd.to_numeric(df[c], errors="coerce")
    return None


# ---------------------------------------------------------------------------
# 1. Rogers-Satchell variance
# ---------------------------------------------------------------------------

def rogers_satchell_variance(
    open_: Iterable[float], high: Iterable[float], low: Iterable[float], close: Iterable[float],
) -> Tuple[Optional[float], int]:
    """Per-bar Rogers-Satchell variance  mean[ ln(H/C)ln(H/O) + ln(L/C)ln(L/O) ].

    Unbiased for a Brownian motion with ANY constant drift (the drift terms cancel), and it uses the
    intrabar high/low, so it measures the excursions a stop can be hit on. Bars with non-positive or
    inconsistent prices (H < max(O,C), L > min(O,C)) are discarded. Returns (variance, n_valid);
    variance is None when no valid bar is left or the estimate is <= 0 (flat bars).
    """
    o, h, l, c = (np.asarray(list(x) if not isinstance(x, (np.ndarray, pd.Series)) else x, dtype=float)
                  for x in (open_, high, low, close))
    ok = (
        np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
        & (o > 0) & (h > 0) & (l > 0) & (c > 0)
        & (h >= np.maximum(o, c)) & (l <= np.minimum(o, c))
    )
    n = int(ok.sum())
    if n == 0:
        return None, 0
    o, h, l, c = o[ok], h[ok], l[ok], c[ok]
    terms = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
    v = float(np.mean(terms))
    if not math.isfinite(v) or v <= 0.0:
        return None, n
    return v, n


# ---------------------------------------------------------------------------
# 2. Empirical-Bayes drift shrinkage
# ---------------------------------------------------------------------------

def bars_per_year(interval_minutes: Optional[float], asset_class: str = "crypto") -> Optional[float]:
    """Bars per year: 24/7 for crypto, 252 x 390 regular-session minutes for US equities."""
    m = _finite(interval_minutes)
    if m is None or m <= 0:
        return None
    if str(asset_class).lower() in ("equity", "equities", "stock", "us_equity"):
        return 252.0 * 390.0 / m
    return 365.0 * 24.0 * 60.0 / m


def bayes_shrunk_drift(
    nu_hat: float,
    s_hat: float,
    n: int,
    n_bars_per_year: float,
    sr0: float = 0.4,
) -> Tuple[Optional[float], Optional[float]]:
    """Posterior mean of the per-bar drift under a N(0, tau0^2) prior.

    tau0 = SR0 / sqrt(N_bars/year) * s_hat (an annual Sharpe SR0 rescaled to one bar),
    SE(nu_hat) = s_hat / sqrt(n), weight w = tau0^2 / (tau0^2 + SE^2) = SR0^2 n / (SR0^2 n + N).
    Returns (nu_bayes, w). w -> 1 as n -> inf, w -> 0 as n -> 0 or SR0 -> 0.
    """
    nu, s, nby = _finite(nu_hat), _finite(s_hat), _finite(n_bars_per_year)
    if nu is None or s is None or nby is None or s <= 0.0 or nby <= 0.0 or n is None or int(n) <= 0:
        return None, None
    tau0_sq = (float(sr0) ** 2 / nby) * s * s
    se_sq = s * s / float(n)
    w = tau0_sq / (tau0_sq + se_sq) if (tau0_sq + se_sq) > 0.0 else 0.0
    return w * nu, w


# ---------------------------------------------------------------------------
# 3. Idiosyncratic decomposition vs SPY
# ---------------------------------------------------------------------------

def idio_decomposition(
    stock_close: pd.Series,
    spy_close: pd.Series,
    window: int = 140,
    min_obs: int = 30,
) -> Dict[str, Optional[float]]:
    """Beta to SPY and the orthogonal residual on the last `window` time-aligned log returns.

    beta = Cov(r, r_spy) / Var(r_spy) (sample moments), eps_t = r_t - beta * r_spy_t, so that the
    sample Cov(eps, r_spy) is exactly 0. Reports spy_beta, idio_ret_window = sum(eps) over the
    window and idio_z_drift = mean(eps) / (sd(eps)/sqrt(n)).
    """
    out: Dict[str, Optional[float]] = {"spy_beta": None, "idio_ret_window": None, "idio_z_drift": None}
    try:
        a = pd.Series(stock_close).astype(float)
        b = pd.Series(spy_close).astype(float)
        a = a[~a.index.duplicated(keep="last")]
        b = b[~b.index.duplicated(keep="last")]
        j = pd.concat([a.rename("s"), b.rename("m")], axis=1, join="inner").dropna()
        j = j[(j["s"] > 0) & (j["m"] > 0)]
        r = np.log(j).diff().dropna().tail(int(window))
        if len(r) < int(min_obs):
            return out
        rs, rm = r["s"].to_numpy(), r["m"].to_numpy()
        var_m = float(np.var(rm, ddof=1))
        if not (var_m > 0.0):
            return out
        beta = float(np.cov(rs, rm, ddof=1)[0, 1] / var_m)
        eps = rs - beta * rm
        sd = float(np.std(eps, ddof=1))
        out["spy_beta"] = _finite(beta)
        out["idio_ret_window"] = _finite(eps.sum())
        out["idio_z_drift"] = _finite(eps.mean() / (sd / math.sqrt(len(eps)))) if sd > 0.0 else None
    except Exception:
        pass
    return out


def cross_sectional_rank(values: Dict[str, Optional[float]], symbol: str) -> Optional[float]:
    """Fraction of the OTHER symbols whose value is below `symbol`'s (ties count 1/2), in [0, 1]."""
    me = _finite(values.get(symbol))
    others = [v for k, v in values.items() if k != symbol and _finite(v) is not None]
    if me is None or not others:
        return None
    below = sum(1.0 for v in others if v < me) + 0.5 * sum(1.0 for v in others if v == me)
    return below / len(others)


def idio_universe(
    closes: Dict[str, pd.Series],
    spy_close: pd.Series,
    window: int = 140,
) -> Dict[str, Dict[str, Optional[float]]]:
    """idio_decomposition for every symbol plus idio_cs_rank against the rest of the universe."""
    res = {sym: idio_decomposition(c, spy_close, window) for sym, c in (closes or {}).items()}
    rets = {sym: d.get("idio_ret_window") for sym, d in res.items()}
    for sym, d in res.items():
        d["idio_cs_rank"] = cross_sectional_rank(rets, sym)
    return res


# ---------------------------------------------------------------------------
# 4a. Bulk Volume Classification order-flow imbalance
# ---------------------------------------------------------------------------

def ofi_bvc(
    df: pd.DataFrame,
    short: int = 15,
    med: int = 60,
    sigma_window: int = 60,
) -> Dict[str, Optional[float]]:
    """OFI_t = 2 Phi((C_t - O_t) / sigma_dP) - 1 = erf(z / sqrt 2), in [-1, 1].

    sigma_dP is the rolling standard deviation of (C - O) over the previous `sigma_window` bars
    (shifted by one bar, so bar t is classified with information up to t-1). Returns the
    volume-weighted mean over the last `short` and `med` bars (plain mean if volume is missing).
    """
    out: Dict[str, Optional[float]] = {"ofi_bvc_short": None, "ofi_bvc_med": None}
    try:
        o, c = _col(df, "Open"), _col(df, "Close")
        if o is None or c is None:
            return out
        v = _col(df, "Volume")
        dp = (c - o)
        sig = dp.rolling(int(sigma_window), min_periods=max(10, int(sigma_window) // 3)).std().shift(1)
        z = (dp / sig.where(sig > 0)).to_numpy(dtype=float)
        ofi = np.array([math.erf(x / math.sqrt(2.0)) if math.isfinite(x) else np.nan for x in z])
        vol = v.to_numpy(dtype=float) if v is not None else np.full(len(ofi), np.nan)
        for key, k in (("ofi_bvc_short", short), ("ofi_bvc_med", med)):
            f, w = ofi[-int(k):], vol[-int(k):]
            m = np.isfinite(f)
            if m.sum() < max(3, int(k) // 3):
                continue
            wm = np.isfinite(w) & (w > 0) & m
            val = float(np.sum(f[wm] * w[wm]) / np.sum(w[wm])) if wm.sum() >= max(3, int(k) // 3) else float(np.mean(f[m]))
            out[key] = _finite(max(-1.0, min(1.0, val)))
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# 4b. Volatility risk premium (equities)
# ---------------------------------------------------------------------------

def realized_vol_5d_annualized(spy_df: pd.DataFrame, sessions: int = 5) -> Optional[float]:
    """Annualised realised vol of SPY over the last `sessions` NY sessions from intraday bars.

    Sum of squared log returns (including the overnight return carried by the first bar of each
    session) over the sessions, annualised with 252 / sessions.
    """
    try:
        c = _col(spy_df, "Close")
        if c is None:
            return None
        c = c.dropna()
        c = c[c > 0]
        idx = pd.DatetimeIndex(c.index)
        idx_ny = (idx.tz_localize("UTC") if idx.tz is None else idx).tz_convert("America/New_York")
        r = pd.Series(np.log(c.to_numpy()), index=idx_ny).diff().dropna()
        days = sorted(set(r.index.date))[-int(sessions):]
        if len(days) < int(sessions):
            return None
        rr = r[np.isin(np.array(r.index.date), days)]
        rv = math.sqrt(float(np.sum(rr.to_numpy() ** 2)) * 252.0 / float(sessions))
        return _finite(rv)
    except Exception:
        return None


def vrp_spread(vix_level: Optional[float], spy_df: Optional[pd.DataFrame]) -> Optional[float]:
    """IV(VIX)/100 - RV(SPY, 5 sessions), both annualised decimal volatilities."""
    iv = _finite(vix_level)
    if iv is None or iv <= 0.0 or spy_df is None:
        return None
    rv = realized_vol_5d_annualized(spy_df)
    return _finite(iv / 100.0 - rv) if rv is not None else None


# ---------------------------------------------------------------------------
# 4c. Bybit public REST state (funding, open interest) — non-blocking, cached
# ---------------------------------------------------------------------------

class BybitPublicState:
    """Funding rate and open-interest deltas from Bybit public REST v5, never blocking the caller.

    `get(symbol)` only reads an in-memory cache; if the entry is missing or older than `ttl` it
    schedules a background refresh and returns whatever is cached (or all-None). `fetch(symbol)` is
    the synchronous fetch used by the worker (strict timeouts, any error -> None fields). After a
    failure the host is skipped for `cooldown` seconds.
    """

    BASE_URL = "https://api.bybit.com"
    EMPTY = {"bybit_funding_rate": None, "bybit_oi_delta_1h": None, "bybit_oi_delta_4h": None}

    def __init__(
        self,
        http_get: Optional[Callable[..., Any]] = None,
        base_url: Optional[str] = None,
        ttl: float = 90.0,
        cooldown: float = 300.0,
        timeout: Tuple[float, float] = (1.0, 1.5),
        background: bool = True,
    ):
        if http_get is None:
            import requests

            http_get = requests.get
        self._get = http_get
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.ttl, self.cooldown, self.timeout = float(ttl), float(cooldown), timeout
        self._cache: Dict[str, Tuple[float, Dict[str, Optional[float]]]] = {}
        self._pending: set = set()
        self._down_until = 0.0
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bybit-telemetry") if background else None

    def _json(self, path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        resp = self._get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        if getattr(resp, "status_code", 200) != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict) or int(data.get("retCode", -1)) != 0:
            return None
        return data.get("result") or {}

    def fetch(self, symbol: str) -> Dict[str, Optional[float]]:
        out = dict(self.EMPTY)
        if time.monotonic() < self._down_until:
            return out
        try:
            fr = self._json("/v5/market/funding/history", {"category": "linear", "symbol": symbol, "limit": 1})
            lst = (fr or {}).get("list") or []
            if lst:
                out["bybit_funding_rate"] = _finite(lst[0].get("fundingRate"))
            oi = self._json("/v5/market/open-interest",
                            {"category": "linear", "symbol": symbol, "intervalTime": "1h", "limit": 5})
            rows = sorted(((oi or {}).get("list") or []), key=lambda r: int(r.get("timestamp", 0)), reverse=True)
            vals = [_finite(r.get("openInterest")) for r in rows]
            if len(vals) >= 2 and vals[0] is not None and vals[1]:
                out["bybit_oi_delta_1h"] = _finite(vals[0] / vals[1] - 1.0)
            if len(vals) >= 5 and vals[0] is not None and vals[4]:
                out["bybit_oi_delta_4h"] = _finite(vals[0] / vals[4] - 1.0)
        except Exception:
            self._down_until = time.monotonic() + self.cooldown
            return dict(self.EMPTY)
        return out

    def _refresh(self, symbol: str) -> None:
        try:
            vals = self.fetch(symbol)
            with self._lock:
                self._cache[symbol] = (time.monotonic(), vals)
        finally:
            with self._lock:
                self._pending.discard(symbol)

    def get(self, symbol: str) -> Dict[str, Optional[float]]:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(symbol)
            fresh = hit is not None and (now - hit[0]) < self.ttl
            schedule = not fresh and symbol not in self._pending and now >= self._down_until
            if schedule:
                self._pending.add(symbol)
        if schedule:
            if self._pool is not None:
                try:
                    self._pool.submit(self._refresh, symbol)
                except Exception:
                    with self._lock:
                        self._pending.discard(symbol)
            else:
                self._refresh(symbol)
                with self._lock:
                    hit = self._cache.get(symbol)
        return dict(hit[1]) if hit is not None else dict(self.EMPTY)


def safe_telemetry(fn: Callable[..., Dict[str, Any]], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Run a telemetry builder; any exception -> {} (telemetry must never break the caller)."""
    try:
        res = fn(*args, **kwargs)
        return dict(res) if isinstance(res, dict) else {}
    except Exception:
        return {}
