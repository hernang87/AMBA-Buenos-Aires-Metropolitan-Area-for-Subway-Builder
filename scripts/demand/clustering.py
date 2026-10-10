from __future__ import annotations

import heapq
import math
from collections import defaultdict

import numpy as np
from scipy.cluster.hierarchy import cut_tree, linkage
from scipy.spatial import cKDTree


def allocate_cluster_counts(
    zone_employment: list[int],
    zone_radio_counts: list[int],
    display_cluster_count: int,
) -> list[int]:
    zone_count = len(zone_employment)
    total_radios = sum(zone_radio_counts)
    if display_cluster_count < zone_count or display_cluster_count > total_radios:
        raise ValueError(
            f"display_cluster_count must be between solver-zone count {zone_count} "
            f"and census-radio count {total_radios}"
        )
    counts = [1] * zone_count
    priorities: list[tuple[float, int]] = []
    for zone_index, (employment, radio_count) in enumerate(zip(zone_employment, zone_radio_counts)):
        if radio_count > 1:
            heapq.heappush(priorities, (-employment / 2, zone_index))
    for _ in range(display_cluster_count - zone_count):
        if not priorities:
            raise ValueError("Could not allocate the requested display clusters")
        _, zone_index = heapq.heappop(priorities)
        counts[zone_index] += 1
        if counts[zone_index] < zone_radio_counts[zone_index]:
            heapq.heappush(
                priorities,
                (-zone_employment[zone_index] / (counts[zone_index] + 1), zone_index),
            )
    return counts


def build_adaptive_clusters(
    radios: list[dict[str, object]],
    display_cluster_count: int,
    bbox: list[float] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    radio_indices_by_zone: dict[tuple[int, int], list[int]] = defaultdict(list)
    for radio_index, radio in enumerate(radios):
        radio_indices_by_zone[tuple(radio["zone_key"])].append(radio_index)
    zone_keys = sorted(radio_indices_by_zone)
    zone_employment = [
        sum(int(radios[index]["employed_residents"]) for index in radio_indices_by_zone[key])
        for key in zone_keys
    ]
    cluster_counts = allocate_cluster_counts(
        zone_employment,
        [len(radio_indices_by_zone[key]) for key in zone_keys],
        display_cluster_count,
    )
    mean_latitude = math.radians(
        sum(float(radio["location"][1]) for radio in radios) / len(radios)
    )
    longitude_scale = math.cos(mean_latitude)
    clusters: list[dict[str, object]] = []
    solver_zones: list[dict[str, object]] = []
    for zone_index, (zone_key, cluster_count) in enumerate(zip(zone_keys, cluster_counts)):
        radio_indices = radio_indices_by_zone[zone_key]
        coordinates = np.array(
            [
                (
                    float(radios[index]["location"][0]) * longitude_scale,
                    float(radios[index]["location"][1]),
                )
                for index in radio_indices
            ],
            dtype=float,
        )
        labels = (
            np.zeros(len(radio_indices), dtype=np.int64)
            if cluster_count == 1
            else cut_tree(linkage(coordinates, method="ward"), n_clusters=[cluster_count]).ravel()
        )
        zone_cluster_indices: list[int] = []
        for label in range(cluster_count):
            member_indices = [
                radio_index
                for radio_index, member_label in zip(radio_indices, labels)
                if int(member_label) == label
            ]
            weights = np.array(
                [max(int(radios[index]["employed_residents"]), 1) for index in member_indices],
                dtype=float,
            )
            member_locations = np.array(
                [radios[index].get("display_location", radios[index]["location"]) for index in member_indices],
                dtype=float,
            )
            model_locations = np.array([radios[index]["location"] for index in member_indices], dtype=float)
            cluster_index = len(clusters)
            longitude, latitude = np.average(member_locations, axis=0, weights=weights)
            model_longitude, model_latitude = np.average(model_locations, axis=0, weights=weights)
            if bbox is not None:
                west, south, east, north = bbox
                longitude = min(max(float(longitude), west), east)
                latitude = min(max(float(latitude), south), north)
                model_longitude = min(max(float(model_longitude), west), east)
                model_latitude = min(max(float(model_latitude), south), north)
            cluster = {
                "id": f"origin_{cluster_index:05d}",
                "location": (float(longitude), float(latitude)),
                "model_location": (float(model_longitude), float(model_latitude)),
                "employed_residents": sum(int(radios[index]["employed_residents"]) for index in member_indices),
                "radio_count": len(member_indices),
                "zone_index": zone_index,
            }
            clusters.append(cluster)
            zone_cluster_indices.append(cluster_index)
            for radio_index in member_indices:
                radios[radio_index]["cluster_index"] = cluster_index
        zone_weights = np.array(
            [max(int(clusters[index]["employed_residents"]), 1) for index in zone_cluster_indices],
            dtype=float,
        )
        zone_locations = np.array([clusters[index]["model_location"] for index in zone_cluster_indices], dtype=float)
        solver_zones.append(
            {
                "id": f"zone_{zone_key[0]}_{zone_key[1]}",
                "location": tuple(np.average(zone_locations, axis=0, weights=zone_weights)),
                "employed_residents": zone_employment[zone_index],
                "cluster_indices": zone_cluster_indices,
            }
        )
    if len(clusters) != display_cluster_count:
        raise ValueError("Adaptive clustering did not produce the requested point count")
    if len({tuple(cluster["location"]) for cluster in clusters}) != len(clusters):
        raise ValueError("Adaptive clustering produced duplicate coordinates")
    return clusters, solver_zones


def aggregate_workplaces_to_clusters(
    workplaces: list[dict[str, object]],
    radios: list[dict[str, object]],
    clusters: list[dict[str, object]],
) -> np.ndarray:
    """Assign rounded workplace capacity through the nearest census radio."""
    if not radios or not clusters:
        raise ValueError("Cannot aggregate workplaces without census radios and display clusters")
    mean_latitude = math.radians(
        sum(float(radio["location"][1]) for radio in radios) / len(radios)
    )
    longitude_scale = math.cos(mean_latitude)
    radio_locations = np.array(
        [
            (float(radio["location"][0]) * longitude_scale, float(radio["location"][1]))
            for radio in radios
        ],
        dtype=float,
    )
    workplace_locations = np.array(
        [
            (float(workplace["location"][0]) * longitude_scale, float(workplace["location"][1]))
            for workplace in workplaces
        ],
        dtype=float,
    )
    _, nearest_radios = cKDTree(radio_locations).query(workplace_locations, k=1)
    nearest_clusters = np.array(
        [int(radios[int(radio_index)]["cluster_index"]) for radio_index in nearest_radios],
        dtype=np.int64,
    )
    return np.bincount(
        nearest_clusters,
        weights=np.array([int(workplace["capacity"]) for workplace in workplaces], dtype=np.int64),
        minlength=len(clusters),
    ).astype(np.int64)


def build_destination_zones(
    solver_zones: list[dict[str, object]],
    cluster_capacities: np.ndarray,
) -> tuple[list[dict[str, object]], dict[int, int]]:
    destinations: list[dict[str, object]] = []
    destination_index_by_zone: dict[int, int] = {}
    for zone_index, zone in enumerate(solver_zones):
        capacity = int(sum(cluster_capacities[index] for index in zone["cluster_indices"]))
        if not capacity:
            continue
        destination_index_by_zone[zone_index] = len(destinations)
        destinations.append(
            {
                "id": f"destination_{zone['id']}",
                "location": tuple(zone["location"]),
                "capacity": capacity,
                "zone_index": zone_index,
            }
        )
    return destinations, destination_index_by_zone
