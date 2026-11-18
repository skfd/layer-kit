# layerkit

The plumbing that the OSM reference-layer repos share (`guelph-*-layer`,
`toronto-*-layer`): the code that was the same in every clone, or was meant to
be and had drifted.

Each layer was cloned from a sibling, so a fix made in one had to be copied by
hand to the others, and mostly was not. Measured on 2026-11-18 across 13
layers: the Overpass fetch existed in 11 copies, all different; a rule added to
four of them (refuse a reply that does not say how old it is) never reached the
other seven. This package is where that code lives now, once.

## What is here

| Module | What it does |
|---|---|
| `overpass` | Fetch a layer's OSM half: every mirror, retried; refuse empty, stale and undated replies; fall back to the cache and say so. |
| `history` | Read and write a layer's gap history (`data/history.jsonl`, one row per day). |
| `publish` | Push a built site to the orphan `gh-pages` branch, retrying a network failure. |
| `wsl` | Run tippecanoe's commands inside WSL, or directly off Windows. |
| `tilemath` | Web Mercator tile and pixel math. |

## What is not

- **A layer's data.** Each layer keeps its own gap history, cache and config.
  Every function here takes paths and settings as arguments and keeps no state.
- **The matcher.** How City features are paired with OSM ones differs by
  geometry and by layer, and stays in each layer's `compare.py`. So do
  `download`, `slim`, `raster` and `site`, which every layer has its own
  version of.
- **A runner.** Each layer still has its own `run.py` and scheduled task.

## How a layer uses it

A layer's module keeps its name and its functions, and those call the kit with
the layer's config, read at call time:

```python
# src/compare.py in a layer
from layerkit import overpass
from layerkit.overpass import OsmUnavailable  # noqa: F401

def _try_overpass(url, query):
    return overpass.try_overpass(
        url, query, user_agent=config.USER_AGENT, timeout=config.OVERPASS_TIMEOUT,
        min_elements=config.OSM_MIN_ELEMENTS, max_age_days=config.OSM_MAX_AGE_DAYS)
```

The wrappers are there so a layer's tests, which patch `config`,
`compare._try_overpass`, `history.seed` and `publish._git`, keep working
unchanged. For the same reason the kit calls `requests.post`, `time.sleep` and
`net.wait_for_link` through their modules.

## Install

It is installed editable into the Python the layers' scheduled tasks use, the
same way `addressvault` is:

```sh
python -m pip install -e .
python -m pytest -q
```

A change here reaches every layer on its next run. Run every layer's tests
before committing one: `python -m pytest -q` in each `*-layer` checkout.
