import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.hurst_migliorino_cycles import HurstMigliorinoCycleService as H
from services.indicators_safe import wilder_rsi, drop_forming_bar


def _df(prices):
    return pd.DataFrame({"Close": np.asarray(prices, dtype=float)})


def test_vincolo_triggers_on_break_and_free_on_rise():
    prices = list(np.linspace(100, 120, 99)) + [50.0]
    assert "RIBASSISTA" in H.calculate_cycle_metrics(_df(prices))["vincolo_migliorino"].upper()
    rising = np.linspace(100, 200, 120)
    assert H.calculate_cycle_metrics(_df(rising))["vincolo_migliorino"].startswith("LIBERO")


def test_vincolo_not_always_libero_on_random_walks():
    rng = np.random.default_rng(42)
    hits = 0
    for _ in range(2000):
        p = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 120)))
        if "RIBASSISTA" in H.calculate_cycle_metrics(_df(p))["vincolo_migliorino"].upper():
            hits += 1
    assert hits > 0


def test_fld_keeps_significant_digits():
    rng = np.random.default_rng(1)
    p = 0.1734 * np.exp(np.cumsum(rng.normal(0, 0.003, 100)))
    r = H.calculate_cycle_metrics(_df(p))
    fld = r["hurst_fld_value"]
    raw = float(p[-10])
    assert abs(fld - raw) / raw < 1e-6
    assert len(f"{fld:.10f}".rstrip("0").lstrip("0.").replace(".", "")) >= 6


def test_wilder_rsi_matches_reference():
    rng = np.random.default_rng(7)
    c = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    n = 14
    d = c.diff().values
    ag = al = 0.0
    ref = []
    for i in range(len(c)):
        if i == 0:
            ref.append(np.nan)
            continue
        g, l = max(d[i], 0.0), max(-d[i], 0.0)
        if i == 1:
            ag, al = g, l
        else:
            ag = ag * (1 - 1 / n) + g / n
            al = al * (1 - 1 / n) + l / n
        ref.append(100 - 100 / (1 + ag / (al + 1e-12)))
    got = wilder_rsi(c, n).values
    assert np.allclose(got[1:], np.array(ref[1:]), atol=1e-6)


def test_drop_forming_bar():
    idx = pd.date_range("2025-01-01 10:00", periods=4, freq="15min", tz="UTC")
    df = pd.DataFrame({"Close": [1, 2, 3, 4]}, index=idx)
    now = datetime(2025, 1, 1, 10, 50, tzinfo=timezone.utc)  # last bar opens 10:45 -> forming
    assert len(drop_forming_bar(df, 15, now=now)) == 3
    now2 = datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc)  # closed exactly
    assert len(drop_forming_bar(df, 15, now=now2)) == 4
    naive = df.copy()
    naive.index = naive.index.tz_localize(None)
    assert len(drop_forming_bar(naive, 15, now=now)) == 3
