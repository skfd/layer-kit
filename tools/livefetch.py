"""Fetch a layer's OSM half from live Overpass without touching its data.

usage (from a layer checkout): python livefetch.py

Points the layer's Overpass cache and sidecar at a temp folder, then calls
its own compare._load_osm() (and _load_amenity_osm(), where there is one).
Nothing under data/ is written and no history row is recorded.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())
from src import compare, config  # noqa: E402

tmp = tempfile.mkdtemp(prefix="livefetch-")
for name in dir(config):
    if name.startswith("OSM_") and name.endswith(("_CACHE_PATH", "_FETCH_PATH")):
        setattr(config, name, os.path.join(tmp, os.path.basename(getattr(config, name))))

loaders = [compare._load_osm]
if hasattr(compare, "_load_amenity_osm"):
    loaders.append(compare._load_amenity_osm)
for load in loaders:
    data, osm_date, from_cache = load()
    print(f"{load.__name__}: {len(data.get('elements', [])):,} elements, "
          f"dated {osm_date!r}, from_cache={from_cache}")
for f in sorted(os.listdir(tmp)):
    if f.endswith("fetch.json"):
        with open(os.path.join(tmp, f), encoding="utf-8") as fh:
            print(f, json.load(fh))
