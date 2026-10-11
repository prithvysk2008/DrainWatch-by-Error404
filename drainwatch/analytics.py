"""Small pure helpers for the analytics page."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime

import numpy as np

from drainwatch import config


def response_lag_minutes(rain: Sequence[float], fill: Sequence[float], max_lag_steps: int = 6) -> int | None:
    """Delay between rainfall and the average drain level, from the best-matching shift.

    Returns None until there is enough storm to measure.
    """
    r = np.asarray(rain, dtype=float)
    f = np.asarray(fill, dtype=float)
    if len(r) < max_lag_steps + 4 or r.std() < 1e-6 or f.std() < 1e-6:
        return None
    best_lag, best_corr = 0, -np.inf
    for lag in range(0, max_lag_steps + 1):
        a = r[: len(r) - lag]
        b = f[lag:]
        if a.std() < 1e-6 or b.std() < 1e-6:
            continue
        corr = float(np.corrcoef(a, b)[0, 1])
        if corr > best_corr:
            best_lag, best_corr = lag, corr
    return best_lag * config.STEP_MINUTES


def counts(values: Iterable[str]) -> list[tuple[str, int]]:
    return sorted(Counter(values).items(), key=lambda kv: (-kv[1], kv[0]))


def mean_minutes_by(pairs: Iterable[tuple[str, datetime, datetime]]) -> list[tuple[str, float]]:
    """Mean minutes from start to end, grouped by key. pairs are (key, start, end)."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for key, start, end in pairs:
        buckets[key].append((end - start).total_seconds() / 60.0)
    return sorted(((k, round(sum(v) / len(v), 1)) for k, v in buckets.items()), key=lambda kv: kv[0])
