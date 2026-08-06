from __future__ import annotations

import math
import random
import secrets
from collections.abc import Sequence


DEFAULT_ORDERS = [1.0 + value / 10.0 for value in range(1, 100)] + list(range(11, 64))


def l2_norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) * float(value) for value in values))


def clip_update(values: Sequence[float], max_norm: float) -> list[float]:
    norm = l2_norm(values)
    if norm <= max_norm:
        return [float(value) for value in values]
    scale = max_norm / norm
    return [float(value) * scale for value in values]


def add_gaussian_noise(
    values: Sequence[float],
    sigma: float,
    max_norm: float,
    *,
    rng: random.Random | None = None,
) -> list[float]:
    """Gaussian mechanism adapted from Veritas; default RNG is CSPRNG-seeded."""
    if rng is None:
        rng = random.Random(secrets.randbits(128))
    return [float(value) + rng.gauss(0.0, sigma * max_norm) for value in values]


def privatize(
    values: Sequence[float],
    max_norm: float,
    sigma: float,
    *,
    rng: random.Random | None = None,
) -> list[float]:
    return add_gaussian_noise(clip_update(values, max_norm), sigma, max_norm, rng=rng)


def gaussian_rdp(alpha: float, noise_multiplier: float) -> float:
    if noise_multiplier <= 0.0:
        return math.inf
    if alpha <= 1.0:
        raise ValueError("RDP order alpha must be > 1")
    return alpha / (2.0 * noise_multiplier * noise_multiplier)


def rdp_to_epsilon(rdp_by_order: Sequence[tuple[float, float]], delta: float) -> tuple[float, float]:
    if not 0.0 < delta < 1.0:
        raise ValueError("delta must be in (0, 1)")

    best_epsilon = math.inf
    best_alpha = math.nan
    for alpha, rdp in rdp_by_order:
        epsilon = (
            rdp
            + math.log((alpha - 1.0) / alpha)
            - (math.log(delta) + math.log(alpha)) / (alpha - 1.0)
        )
        epsilon = max(epsilon, 0.0)
        if epsilon < best_epsilon:
            best_epsilon = epsilon
            best_alpha = alpha
    return best_epsilon, best_alpha


class RDPAccountant:
    """Small RDP accountant adapted from Veritas for TraceLayer federation demos."""

    def __init__(self, orders: Sequence[float] | None = None) -> None:
        self.orders = list(orders or DEFAULT_ORDERS)
        self._rdp = [0.0 for _ in self.orders]
        self.steps = 0

    def step(self, noise_multiplier: float, sample_rate: float = 1.0) -> "RDPAccountant":
        amplification = sample_rate * sample_rate if sample_rate < 1.0 else 1.0
        for index, alpha in enumerate(self.orders):
            self._rdp[index] += gaussian_rdp(alpha, noise_multiplier) * amplification
        self.steps += 1
        return self

    def get_epsilon_and_order(self, delta: float) -> tuple[float, float]:
        return rdp_to_epsilon(list(zip(self.orders, self._rdp)), delta)

    def summary(self, delta: float, noise_multiplier: float, sample_rate: float) -> dict:
        epsilon, best_order = self.get_epsilon_and_order(delta)
        return {
            "epsilon": round(epsilon, 4),
            "delta": delta,
            "best_order": best_order,
            "noise_multiplier": noise_multiplier,
            "sample_rate": sample_rate,
            "rounds": self.steps,
        }
