from __future__ import annotations

import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / ".cache"))

import geopandas as gpd
import matplotlib.pyplot as plt

BG = "#101827"
LAND = "#18263a"
ROAD_MINOR = "#52647c"
ROAD_MAJOR = "#f0b35b"
TEXT = "#f6f1e8"
GRID = "#2b3b52"


def roads(path: Path) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path)
    return frame[frame.geometry.notna() & ~frame.geometry.is_empty]


def setup(title: str):
    figure, axis = plt.subplots(figsize=(16, 9), dpi=150)
    figure.patch.set_facecolor(BG)
    axis.set_facecolor(LAND)
    axis.set_title(title, loc="left", color=TEXT, fontsize=23, fontweight="bold", pad=18)
    axis.set_axis_off()
    return figure, axis


def draw_roads(axis, frame: gpd.GeoDataFrame, linewidth: float = 0.22, bounds=None):
    if bounds is not None:
        frame = frame.cx[bounds[0]:bounds[2], bounds[1]:bounds[3]]
    minor = frame[frame["roadClass"] != "major"]
    major = frame[frame["roadClass"] == "major"]
    minor.plot(ax=axis, color=ROAD_MINOR, linewidth=linewidth, alpha=0.48)
    major.plot(ax=axis, color=ROAD_MAJOR, linewidth=linewidth * 2.2, alpha=0.88)


def finish(figure, axis, path: Path, bounds=None):
    if bounds is not None:
        axis.set_xlim(bounds[0], bounds[2])
        axis.set_ylim(bounds[1], bounds[3])
    axis.grid(color=GRID, linewidth=0.35, alpha=0.35)
    figure.text(0.015, 0.025, "AMBA · Buenos Aires Metropolitan Area · OSM + INDEC Census 2022", color="#a8b5c7", fontsize=9)
    figure.savefig(path, facecolor=figure.get_facecolor(), bbox_inches="tight", pad_inches=0.2)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roads", type=Path, required=True)
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "output/gallery")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    road_frame = roads(args.roads)
    parties = gpd.read_file(args.regions / "partidos.geojson")
    comunas = gpd.read_file(args.regions / "comunas.geojson")
    radios = gpd.read_file(args.regions / "radios-censales.geojson")

    figure, axis = setup("AMBA · Metropolitan overview")
    parties.plot(ax=axis, color="#243b55", edgecolor="#7791ae", linewidth=0.7, alpha=0.86)
    draw_roads(axis, road_frame, 0.18)
    for _, region in parties.iterrows():
        point = region.geometry.representative_point()
        axis.text(point.x, point.y, region["name"], color=TEXT, fontsize=5.5, ha="center", alpha=0.83)
    finish(figure, axis, args.output / "01-amba-overview.png", parties.total_bounds)

    figure, axis = setup("AMBA · Partidos")
    parties.plot(ax=axis, column="population", cmap="magma", edgecolor="#f1d18a", linewidth=0.85, alpha=0.82, legend=True, legend_kwds={"label": "Population", "shrink": 0.65})
    draw_roads(axis, road_frame, 0.16)
    finish(figure, axis, args.output / "02-partidos-population.png", parties.total_bounds)

    caba_bounds = (-58.56, -34.72, -58.32, -34.48)
    figure, axis = setup("Buenos Aires · CABA comunas")
    comunas.plot(ax=axis, column="population", cmap="viridis", edgecolor="#f6f1e8", linewidth=1.0, alpha=0.74, legend=True, legend_kwds={"label": "Population", "shrink": 0.7})
    draw_roads(axis, road_frame, 0.26, caba_bounds)
    for _, region in comunas.iterrows():
        point = region.geometry.representative_point()
        axis.text(point.x, point.y, region["name"], color=TEXT, fontsize=8, ha="center", va="center", fontweight="bold")
    finish(figure, axis, args.output / "03-caba-comunas.png", caba_bounds)

    figure, axis = setup("Buenos Aires · Census radio detail")
    detail = radios.cx[-58.58:-58.30, -34.75:-34.45]
    detail.plot(ax=axis, column="population", cmap="plasma", edgecolor="#d8c8b0", linewidth=0.16, alpha=0.68)
    draw_roads(axis, road_frame, 0.3, caba_bounds)
    finish(figure, axis, args.output / "04-census-radio-detail.png", caba_bounds)

    (args.output / "README.txt").write_text(
        "AMBA gallery images for Railyard. Recommended upload order: 01, 02, 03, 04.\n",
        encoding="utf-8",
    )
    print(f"Exported gallery to {args.output}")


if __name__ == "__main__":
    main()
