"""Registro delle strategie del lab. LAB_STRATEGIES (lista separata da virgole di `name`) seleziona un sottoinsieme."""
from __future__ import annotations

import os
from typing import List

from quant.lab.strategies.brent_wti_grid import BrentWtiSpreadGrid
from quant.lab.strategies.crypto_breakout import CryptoBreakout4hMaker
from quant.lab.strategies.funding_carry import FundingCarry
from quant.lab.strategies.in_play_momentum import InPlayMomentum
from quant.lab.strategies.post_liq_reversal import PostLiqReversal
from quant.lab.strategies.tsmom_monthly import TsmomMonthly


def default_strategies() -> List:
    all_ = [TsmomMonthly(), BrentWtiSpreadGrid(), FundingCarry(), CryptoBreakout4hMaker(),
            PostLiqReversal(), InPlayMomentum()]  # last two: candidates (2026-11-26), paper only
    sel = [x.strip() for x in os.getenv("LAB_STRATEGIES", "").split(",") if x.strip()]
    return [s for s in all_ if s.name in sel] if sel else all_


all_strategies = default_strategies
__all__ = ["all_strategies", "default_strategies", "TsmomMonthly", "BrentWtiSpreadGrid", "FundingCarry", "CryptoBreakout4hMaker",
           "PostLiqReversal", "InPlayMomentum"]
