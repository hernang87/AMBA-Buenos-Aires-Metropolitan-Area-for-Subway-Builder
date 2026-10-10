from __future__ import annotations

import math

import numpy as np
from shapely.geometry import shape

EARTH_KM_PER_DEGREE = 111.2


def representative_point(geometry: dict) -> tuple[float, float]:
    point = shape(geometry).representative_point()
    return point.x, point.y


def distance_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(value))


def integerize(values: np.ndarray, total: int | None = None) -> np.ndarray:
    floors = np.floor(values).astype(np.int64)
    target = int(round(float(values.sum()))) if total is None else total
    extra = target - int(floors.sum())
    if extra < 0 or extra > len(values):
        raise ValueError("Cannot integerize values with the requested total")
    if extra:
        fractions = values - floors
        indices = np.argpartition(fractions, -extra)[-extra:]
        floors[indices] += 1
    return floors


def weighted_percentile(values: np.ndarray, weights: np.ndarray, percentile: float) -> float:
    if not len(values) or int(weights.sum()) == 0:
        return 0.0
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    position = np.searchsorted(cumulative, weights.sum() * percentile, side="left")
    return float(values[order[min(position, len(order) - 1)]])
