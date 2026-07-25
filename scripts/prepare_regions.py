from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare SubwayBuilder Regions datasets for AMBA")
    parser.add_argument("--areas", type=Path, default=Path("data/raw/rmba_areas.geojson"))
    parser.add_argument("--stats", type=Path, default=Path("data/processed/areas.csv"))
    parser.add_argument("--output", type=Path, default=Path("output/BUE-regions"))
    args = parser.parse_args()

    stats = pd.read_csv(args.stats, dtype={"area_id": str})
    stats["area_id"] = stats["area_id"].str.strip()
    stats["population"] = pd.to_numeric(stats["population"], errors="coerce").fillna(0)
    stats["jobs"] = pd.to_numeric(stats["jobs"], errors="coerce").fillna(0)
    wanted = set(stats["area_id"])

    source = gpd.read_file(args.areas)
    source["area_id"] = source["cod_indec"].astype(str).str.strip()
    source = source[source["area_id"].isin(wanted)].copy()
    if source.empty:
        raise RuntimeError("No census geometries matched the prepared AMBA statistics")

    source = source.merge(stats[["area_id", "population", "jobs"]], on="area_id", how="inner")
    source = source[source.geometry.notna() & ~source.geometry.is_empty].copy()
    source["population"] = source["population"].round().astype(int)
    source["jobs"] = source["jobs"].round().astype(int)

    radios = gpd.GeoDataFrame(
        {
            "id": source["area_id"],
            "name": "Radio censal " + source["area_id"],
            "region_type": "radio_censal",
            "area_id": source["area_id"],
            "population": source["population"],
            "jobs": source["jobs"],
            "geometry": source.geometry,
        },
        crs=source.crs,
    ).to_crs(4326)

    source["region_id"] = source["area_id"].str[:5]

    def aggregate_regions(frame: gpd.GeoDataFrame, region_type: str, fallback: str) -> gpd.GeoDataFrame:
        stats = frame.groupby("region_id", as_index=False)[["population", "jobs"]].sum()
        names = frame.groupby("region_id", as_index=False)["dpto"].first()
        dissolved = frame[["region_id", "geometry"]].dissolve(by="region_id", as_index=False)
        dissolved = dissolved.merge(stats, on="region_id", how="left").merge(names, on="region_id", how="left")
        return gpd.GeoDataFrame(
            {
                "id": dissolved["region_id"],
                "name": dissolved["dpto"].fillna(fallback + " " + dissolved["region_id"]),
                "region_type": region_type,
                "area_id": dissolved["region_id"],
                "population": dissolved["population"].round().astype(int),
                "jobs": dissolved["jobs"].round().astype(int),
                "geometry": dissolved.geometry,
            },
            crs=frame.crs,
        ).to_crs(4326)

    parties = aggregate_regions(source[~source["region_id"].str.startswith("02")], "partido", "Partido")
    comunas = aggregate_regions(source[source["region_id"].str.startswith("02")], "comuna", "Comuna")

    args.output.mkdir(parents=True, exist_ok=True)
    files = []
    for filename, frame in (
        ("radios-censales.geojson", radios),
        ("partidos.geojson", parties),
        ("comunas.geojson", comunas),
    ):
        path = args.output / filename
        frame.to_file(path, driver="GeoJSON")
        files.append(path)

    readme = args.output / "README.txt"
    readme.write_text(
        "AMBA datasets for SubwayBuilder Regions.\n\n"
        "Copy the two GeoJSON files into your Subway Builder Regions mod directory:\n"
        "mods/regions/data/BUE/\n\n"
        "The radio layer uses INDEC cod_indec as its stable area_id.\n"
        "The partido layer dissolves those radio geometries by the first five\n"
        "digits of cod_indec and aggregates population and employed people.\n",
        encoding="utf-8",
    )
    files.append(readme)

    archive = args.output.parent / "BUE-regions.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for path in files:
            handle.write(path, path.name)

    print(f"Prepared {len(radios)} radios and {len(parties)} partidos")
    print(f"Wrote {archive}")


if __name__ == "__main__":
    main()
