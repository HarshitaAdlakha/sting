"""Repeated Bertrand market with logit demand (Calvano et al. 2020 parametrisation).

Same economics as the llm-cartel and algorithmic-pricing-llms starter folders, written
from scratch for n symmetric firms so the benchmarks are exact and testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq, minimize_scalar


@dataclass
class Market:
    n: int = 3
    a: float = 2.0        # product quality index
    a0: float = 0.0       # outside option
    c: float = 1.0        # marginal cost
    mu: float = 0.25      # horizontal differentiation
    beta: float = 100.0   # market size (scales quantities only)
    scale: float = 10.0   # currency scale: prices are shown to agents in dollars = scale * model units
    nash: float = field(init=False)
    monopoly: float = field(init=False)

    def __post_init__(self):
        self.nash = self._symmetric_nash() * self.scale
        self.monopoly = self._joint_monopoly() * self.scale

    # --- model units -------------------------------------------------------------------------
    def _shares(self, p: np.ndarray) -> np.ndarray:
        e = np.exp((self.a - p) / self.mu)
        return e / (e.sum() + np.exp(self.a0 / self.mu))

    def _best_response(self, p_others: float) -> float:
        # FOC for firm i given rivals all at p_others: 1 - (p - c)(1 - s_i)/mu = 0
        def foc(p):
            s = self._shares(np.array([p] + [p_others] * (self.n - 1)))[0]
            return 1 - (p - self.c) * (1 - s) / self.mu
        return brentq(foc, self.c + 1e-9, self.c + 20)

    def _symmetric_nash(self) -> float:
        p = self.c + self.mu
        for _ in range(500):
            p_new = self._best_response(p)
            if abs(p_new - p) < 1e-12:
                break
            p = p_new
        return p

    def _joint_monopoly(self) -> float:
        def neg_total(p):
            s = self._shares(np.full(self.n, p))
            return -((p - self.c) * s).sum()
        return minimize_scalar(neg_total, bounds=(self.c, self.c + 20), method="bounded").x

    # --- dollar units (what agents see) --------------------------------------------------------
    def step(self, prices_usd: list[float]) -> tuple[list[float], list[float]]:
        """Return (quantities, profits) for prices given in dollars."""
        p = np.asarray(prices_usd, dtype=float) / self.scale
        s = self._shares(p)
        q = self.beta * s
        profit = q * (p - self.c) * self.scale
        return q.round(3).tolist(), profit.round(3).tolist()

    def profit_at(self, price_usd: float) -> float:
        """Per-firm profit when every firm charges the same price."""
        return self.step([price_usd] * self.n)[1][0]

    def gain(self, price_usd: float) -> float:
        """Normalised price: 0 at the static Nash price, 1 at the joint-monopoly price."""
        return (price_usd - self.nash) / (self.monopoly - self.nash)

    @property
    def max_price(self) -> float:
        return round(1.5 * self.monopoly, 2)
