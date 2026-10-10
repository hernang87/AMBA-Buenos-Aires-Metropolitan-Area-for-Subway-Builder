from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
from shapely.geometry import Point, shape

from .common import integerize, representative_point


def load_anchors(path: Path) -> dict[str, tuple[float, float]]:
    anchors = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            area_id = row["area_id"]
            location = (float(row["longitude"]), float(row["latitude"]))
            if area_id in anchors or not all(math.isfinite(value) for value in location):
                raise ValueError(f"Invalid or duplicate census anchor: {area_id}")
            anchors[area_id] = location
    if not anchors:
        raise ValueError("No CABA census anchors found")
    return anchors


def load_census_radios(
    path: Path, solver_zone_degrees: float, anchors: dict[str, tuple[float, float]] | None = None
) -> list[dict[str, object]]:
    radios: list[dict[str, object]] = []
    anchors = anchors or {}
    used_anchors = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            geometry = json.loads(row["geometry"])
            location = representative_point(geometry)
            display_location = anchors.get(row["area_id"], location)
            if row["area_id"] in anchors:
                if not shape(geometry).covers(Point(display_location)):
                    raise ValueError(f"Census anchor is outside its radio: {row['area_id']}")
                used_anchors.add(row["area_id"])
            radios.append(
                {
                    "id": row["area_id"],
                    "location": location,
                    "display_location": display_location,
                    "employed_residents": int(round(float(row["jobs"]))),
                    "zone_key": (
                        math.floor(location[0] / solver_zone_degrees),
                        math.floor(location[1] / solver_zone_degrees),
                    ),
                }
            )
    if not radios:
        raise ValueError("No prepared census areas found")
    if used_anchors != anchors.keys():
        raise ValueError("Census anchors contain unknown radio identifiers")
    return radios


def load_workplaces(path: Path) -> list[dict[str, object]]:
    workplaces: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            workplaces.append(
                {
                    "id": row["workplace_id"],
                    "cell_id": row["cell_id"],
                    "location": (float(row["longitude"]), float(row["latitude"])),
                    "employment_weight": float(row["employment_weight"]),
                }
            )
    if not workplaces:
        raise ValueError("No prepared workplace establishments found")
    capacities = integerize(np.array([float(workplace["employment_weight"]) for workplace in workplaces]))
    for workplace, capacity in zip(workplaces, capacities):
        workplace["capacity"] = int(capacity)
    return workplaces
