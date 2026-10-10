# Pipeline for the BUE (AMBA) Subway Builder map.
#
# Stamps and slices: each config section is written to output/.config/<name>.json
# by scripts/config_slice.py, which only rewrites a file when its content changes.
# Stages depend on the slice they use, so editing one config section rebuilds
# only the stages whose slice changed. Build outputs that are not files of their
# own (the build step) are tracked with the stamp output/BUE/.build.stamp.
# Use `make mark-built` to adopt existing prepared inputs, map build and demand
# artifacts as up to date (only packaging then reruns).

PYTHON ?= .venv/bin/python
CONFIG := config/bue.json
RAW := data/raw
PROCESSED := data/processed
MAP := output/BUE
SLICES := output/.config
OSM_PBF_FILES := $(wildcard argentina-latest.osm.pbf $(RAW)/argentina-latest.osm.pbf)
DEMAND_SOURCES := scripts/generate_demand.py $(wildcard scripts/demand/*.py)

.DEFAULT_GOAL := all
.PHONY: all download verify prepare build demand validate package regions gallery test lint check mark-built

all: output/amba.zip

download: $(RAW)/rmba_areas.geojson $(RAW)/caba_parcels.geojson $(RAW)/caba_land_use.csv $(RAW)/rmba_stats.csv $(RAW)/workplaces.csv

verify:
	$(PYTHON) scripts/checksums.py verify

prepare: $(PROCESSED)/areas.csv $(PROCESSED)/workplaces.csv $(PROCESSED)/caba_anchors.csv

build: $(MAP)/.build.stamp

demand: $(MAP)/demand_data.json

validate:
	$(PYTHON) scripts/validate_map.py

package: output/amba.zip

regions:
	$(PYTHON) scripts/prepare_regions.py

gallery:
	$(PYTHON) scripts/export_gallery.py --roads $(MAP)/roads.geojson --regions output/BUE-regions

test:
	$(PYTHON) -m unittest discover -s tests

lint:
	$(PYTHON) -m ruff check scripts tests

check: test lint

mark-built: $(SLICES)/build.json $(SLICES)/workplaces.json $(SLICES)/demand.json
	touch $(PROCESSED)/areas.csv $(PROCESSED)/workplaces.csv $(PROCESSED)/caba_anchors.csv
	touch $(MAP)/.build.stamp
	touch $(MAP)/demand_data.json

$(SLICES)/%.json: $(CONFIG) scripts/config_slice.py
	$(PYTHON) scripts/config_slice.py $* $@

$(RAW)/rmba_areas.geojson $(RAW)/caba_parcels.geojson $(RAW)/caba_land_use.csv:
	$(PYTHON) scripts/download_sources.py $@

$(RAW)/rmba_stats.csv:
	$(PYTHON) scripts/fetch_redatam_stats.py --output $@

$(RAW)/workplaces.csv:
	$(PYTHON) scripts/fetch_workplace_data.py --output $@

$(PROCESSED)/areas.csv: $(RAW)/rmba_areas.geojson $(RAW)/rmba_stats.csv scripts/prepare_census.py
	$(PYTHON) scripts/prepare_census.py --areas $(RAW)/rmba_areas.geojson --stats $(RAW)/rmba_stats.csv --output $@

$(PROCESSED)/workplaces.csv: $(RAW)/workplaces.csv $(SLICES)/workplaces.json scripts/prepare_workplaces.py
	$(PYTHON) scripts/prepare_workplaces.py

$(PROCESSED)/caba_anchors.csv: $(PROCESSED)/areas.csv $(RAW)/caba_parcels.geojson $(RAW)/caba_land_use.csv scripts/prepare_caba_anchors.py
	$(PYTHON) scripts/prepare_caba_anchors.py

$(MAP)/.build.stamp: $(SLICES)/build.json scripts/build_map.py $(OSM_PBF_FILES)
	$(PYTHON) scripts/build_map.py
	touch $@

$(MAP)/demand_data.json: $(MAP)/.build.stamp $(PROCESSED)/areas.csv $(PROCESSED)/workplaces.csv $(PROCESSED)/caba_anchors.csv $(SLICES)/demand.json $(DEMAND_SOURCES)
	$(PYTHON) scripts/generate_demand.py --output $@

output/amba.zip: $(MAP)/demand_data.json $(MAP)/.build.stamp $(CONFIG) scripts/package_map.py scripts/validate_map.py
	$(PYTHON) scripts/package_map.py
