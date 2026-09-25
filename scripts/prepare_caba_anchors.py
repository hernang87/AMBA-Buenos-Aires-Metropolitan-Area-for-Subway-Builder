from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, shape


ROOT = Path(__file__).resolve().parents[1]


def parcel_key(value: str) -> str:
    return "".join(value.split()).upper()


def prepare_anchors(areas_path: Path, parcels_path: Path, uses_path: Path) -> list[dict[str, object]]:
    areas = pd.read_csv(areas_path, dtype={"area_id": str})
    areas = areas[areas["area_id"].str.startswith("02")].copy()
    if areas.empty or areas["area_id"].duplicated().any():
        raise ValueError("CABA census radios are missing or duplicated")
    radios = gpd.GeoDataFrame(
        areas[["area_id"]],
        geometry=areas["geometry"].map(lambda value: shape(json.loads(value))),
        crs=4326,
    ).set_index("area_id")

    uses = pd.read_csv(uses_path, dtype=str, encoding="utf-8-sig", usecols=["SMP", "TIPO1", "ESTADO", "PISOS"])
    uses = uses[(uses["TIPO1"] == "RESIDENCIAL") & (uses["ESTADO"] == "ACTIVO")].copy()
    if uses.empty:
        raise ValueError("No active residential land uses found")
    uses["key"] = uses["SMP"].map(parcel_key)
    uses["floors"] = pd.to_numeric(
        uses["PISOS"].replace({">25": "26"}), errors="coerce"
    ).fillna(1).clip(1, 26)
    floors_by_parcel = uses.groupby("key")["floors"].max()

    parcels = gpd.read_file(parcels_path, columns=["smp", "geometry"])
    if parcels.crs is None or parcels["smp"].isna().any():
        raise ValueError("Parcel GeoJSON needs a CRS and parcel identifiers")
    parcels = parcels.to_crs(4326)
    parcels["key"] = parcels["smp"].map(parcel_key)
    if parcels["key"].duplicated().any() or not parcels.geometry.is_valid.all():
        raise ValueError("Parcel identifiers or geometries are invalid")
    parcels = parcels[parcels["key"].isin(floors_by_parcel.index)].copy()
    if len(parcels) < 0.95 * len(floors_by_parcel):
        raise ValueError("Fewer than 95% of residential uses match parcel geometry")
    parcels["weight"] = parcels["key"].map(floors_by_parcel)
    points = gpd.GeoDataFrame(
        parcels[["weight"]], geometry=parcels.geometry.representative_point(), crs=4326
    )
    joined = gpd.sjoin(points, radios.reset_index(), predicate="within", how="inner")
    if joined.index.duplicated().any():
        raise ValueError("A residential parcel belongs to multiple census radios")
    if joined["area_id"].nunique() < 0.9 * len(radios):
        raise ValueError("Residential parcels cover fewer than 90% of CABA radios")

    joined["weighted_lon"] = joined.geometry.x * joined["weight"]
    joined["weighted_lat"] = joined.geometry.y * joined["weight"]
    totals = joined.groupby("area_id")[["weight", "weighted_lon", "weighted_lat"]].sum()
    anchors = []
    for area_id, row in totals.iterrows():
        point = Point(row["weighted_lon"] / row["weight"], row["weighted_lat"] / row["weight"])
        if not radios.loc[area_id].geometry.covers(point):
            point = joined.loc[joined[joined["area_id"] == area_id]["weight"].idxmax()].geometry
        anchors.append({"area_id": area_id, "longitude": point.x, "latitude": point.y})
    return anchors


def main() -> None:
    parser = argparse.ArgumentParser(description="Locate CABA census demand within surveyed residential parcels.")
    parser.add_argument("--areas", type=Path, default=ROOT / "data/processed/areas.csv")
    parser.add_argument("--parcels", type=Path, default=ROOT / "data/raw/caba_parcels.geojson")
    parser.add_argument("--uses", type=Path, default=ROOT / "data/raw/caba_land_use.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/caba_anchors.csv")
    args = parser.parse_args()
    anchors = prepare_anchors(args.areas, args.parcels, args.uses)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["area_id", "longitude", "latitude"])
        writer.writeheader()
        writer.writerows(anchors)
    print(f"Prepared {len(anchors)} parcel-informed CABA radio anchors in {args.output}")


if __name__ == "__main__":
    main()
