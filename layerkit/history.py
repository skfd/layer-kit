"""Keep the gap counts of every compare run: one JSON line per day.

Each layer owns its record -- its own ``data/history.jsonl``, its own fields,
its own published copy. This module is only the reading and writing of it; the
path, the URL and the field list are the layer's, passed in on every call.

The record is deliberately tiny and reconstructible. A run that fell back to
cached OSM observed nothing new and is not recorded, so a chart never shows a
false plateau. How a layer rebuilds its past from Overpass attic data is its
own business (it has to re-run its own matcher), so ``backfill`` stays with
the layer; ``dates`` is the part of it that is the same everywhere.

``requests`` is called through its module on purpose: the layers' tests patch
``requests.get``.
"""

import json
import os
from datetime import date, timedelta

import requests


def record(summary, fields, *, path, seed, day=None, sparse=False):
    """Append the run's row (replacing an earlier row from the same day).

    ``seed()`` is called first so a checkout with no history starts from the
    published copy; it is the layer's own function, passed in so a test that
    stubs it out stubs out the fetch.

    ``sparse`` leaves out a count the run did not take, where the default
    writes it as 0 -- for a layer whose later fields start partway through its
    record.
    """
    if summary.get("osm_stale"):
        print("History: not recorded (compared against cached OSM).")
        return None
    day = day or date.today().isoformat()
    if sparse:
        counts = {k: summary[k] for k in fields if k in summary}
    else:
        counts = {k: summary.get(k, 0) for k in fields}
    row = {"date": day, "osm_date": summary.get("osm_date") or day,
           "source": "live", **counts}
    seed()
    rows = [r for r in load(path) if r["date"] != day] + [row]
    write(path, rows)
    print(f"History: recorded {day} ({len(rows):,} runs on record).")
    return row


def load(path):
    """All rows, oldest first. An absent file is an empty history."""
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return sorted(rows, key=lambda r: r["date"])


def write(path, rows):
    """Replace the file with ``rows``, oldest first."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = sorted(rows, key=lambda r: r["date"])
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def seed(path, url, user_agent):
    """Start a checkout that has no history from the published copy.

    data/ is not in git, so a fresh clone (or a wiped data dir) would otherwise
    begin the record again from this week. Best-effort: before the first
    publish there is nothing to fetch, and that is fine.
    """
    if os.path.isfile(path):
        return False
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=30)
    except requests.RequestException as e:
        print(f"History: could not fetch the published copy ({e}).")
        return False
    if resp.status_code != 200 or not resp.text.strip():
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(resp.text if resp.text.endswith("\n") else resp.text + "\n")
    print(f"History: seeded from {url}.")
    return True


def dates(since, until, step_days):
    """``since``, then every ``step_days``, while before ``until``."""
    d = since
    while d < until:
        yield d
        d += timedelta(days=step_days)
