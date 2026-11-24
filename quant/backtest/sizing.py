from __future__ import annotations


def fractional_kelly(p: float, payoff_b: float, lam: float = 0.25, cap: float = 0.25) -> float:
    if payoff_b <= 0:
        return 0.0
    edge = p - (1 - p) / payoff_b
    if edge <= 0:
        return 0.0
    return float(min(lam * edge, cap))


def breakeven_probability(avg_win: float, avg_loss: float, cost: float) -> float:
    return (avg_loss + cost) / (avg_win + avg_loss)


def vol_target_fraction(sigma_annual: float, target_annual: float = 0.20, cap: float = 1.0) -> float:
    if not sigma_annual or sigma_annual <= 0:
        return cap
    return float(min(target_annual / sigma_annual, cap))
