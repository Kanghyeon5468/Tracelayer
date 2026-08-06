from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable, Sequence

MASK_SCALE = 1.0e6
SEED_BYTES = 32
SeedKey = tuple[str, str]


def canonical_pair(a: str, b: str) -> SeedKey:
    return (a, b) if a < b else (b, a)


def prg_floats(seed: bytes, n: int) -> list[float]:
    """HMAC-SHA256 counter-mode PRG adapted from Veritas secure aggregation."""
    if n < 0:
        raise ValueError("n must be non-negative")
    if len(seed) != SEED_BYTES:
        seed = hashlib.sha256(seed).digest()

    out: list[float] = []
    counter = 0
    inv = float(2**64)
    while len(out) < n:
        block = hmac.new(seed, counter.to_bytes(8, "big"), hashlib.sha256).digest()
        for index in range(4):
            if len(out) >= n:
                break
            value = int.from_bytes(block[index * 8 : (index + 1) * 8], "little")
            out.append(value / inv)
        counter += 1
    return out


def derive_pairwise_mask(seed: bytes, dim: int) -> list[float]:
    if dim <= 0:
        raise ValueError("dim must be positive")
    uniforms = prg_floats(seed, dim)
    return [(value * 2.0 - 1.0) * MASK_SCALE for value in uniforms]


def establish_pairwise_seeds(client_ids: Sequence[str]) -> dict[SeedKey, bytes]:
    ids = list(client_ids)
    if len(set(ids)) != len(ids):
        raise ValueError("client_ids must be unique")

    seeds: dict[SeedKey, bytes] = {}
    for left_index, left_id in enumerate(ids):
        for right_id in ids[left_index + 1 :]:
            seeds[canonical_pair(left_id, right_id)] = secrets.token_bytes(SEED_BYTES)
    return seeds


def deterministic_pairwise_seeds(client_ids: Sequence[str], session_id: str) -> dict[SeedKey, bytes]:
    """Deterministic dealer for reproducible local demos; not for production privacy."""
    ids = list(client_ids)
    if len(set(ids)) != len(ids):
        raise ValueError("client_ids must be unique")

    seeds: dict[SeedKey, bytes] = {}
    for left_index, left_id in enumerate(ids):
        for right_id in ids[left_index + 1 :]:
            pair = canonical_pair(left_id, right_id)
            material = f"tracelayer/veritas-demo/{session_id}/{pair[0]}/{pair[1]}".encode()
            seeds[pair] = hashlib.sha256(material).digest()
    return seeds


def mask_update(
    update: Sequence[float],
    client_id: str,
    peer_ids: Iterable[str],
    shared_seeds: dict[SeedKey, bytes],
) -> list[float]:
    masked = [float(value) for value in update]
    for peer_id in peer_ids:
        if peer_id == client_id:
            continue
        seed = shared_seeds[canonical_pair(client_id, peer_id)]
        mask = derive_pairwise_mask(seed, len(masked))
        sign = 1.0 if client_id < peer_id else -1.0
        masked = [value + sign * mask_value for value, mask_value in zip(masked, mask)]
    return masked


def secure_sum(masked_updates: Sequence[Sequence[float]]) -> list[float]:
    if not masked_updates:
        raise ValueError("no masked updates to sum")
    dim = len(masked_updates[0])
    total = [0.0] * dim
    for update in masked_updates:
        if len(update) != dim:
            raise ValueError("all updates must have the same dimension")
        total = [left + float(right) for left, right in zip(total, update)]
    return total


def secure_aggregate(
    updates: dict[str, Sequence[float]],
    *,
    session_id: str,
    deterministic: bool = True,
) -> tuple[list[float], dict]:
    """Aggregate node updates while exposing only pairwise-masked messages."""
    client_ids = sorted(updates)
    seeds = (
        deterministic_pairwise_seeds(client_ids, session_id)
        if deterministic
        else establish_pairwise_seeds(client_ids)
    )
    masked_messages = [
        mask_update(updates[client_id], client_id, client_ids, seeds) for client_id in client_ids
    ]
    aggregate_sum = secure_sum(masked_messages)
    return aggregate_sum, {
        "protocol": "bonawitz_pairwise_masking_reference",
        "client_count": len(client_ids),
        "dimension": len(aggregate_sum),
        "server_observes": "masked_node_updates_and_aggregate_only",
        "deterministic_demo_dealer": deterministic,
    }
