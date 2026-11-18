"""Fetch a layer's OSM half from Overpass, and say honestly how old it is.

Every rule here was paid for by one of the layers:

* One POST was once the entire effort, and two 504s a week apart left a gap
  page comparing against a fortnight-old OSM without failing anything. So
  every mirror is tried and the whole list is retried.
* HTTP 200 is not proof of an answer. A regional instance replies to an
  out-of-region bbox with a valid, empty element list, and taking that at
  face value would report every City feature as missing from OSM. So a reply
  under the layer's element floor is ignored.
* Nor is a full reply proof of a current one. overpass.kumi.systems and
  overpass.private.coffee have both answered in full from data months old,
  which looks exactly like success. So a reply older than the layer's limit
  is ignored, and the date shown is the one the reply declares about itself
  (``osm3s.timestamp_osm_base``), not the day it was fetched.

The functions take what they need as arguments and keep no state: a layer's
compare.py wraps them with its own config, read at call time.

``requests``, ``time`` and ``net`` are called through their modules on purpose.
The layers' tests patch ``requests.post``, ``time.sleep`` and
``net.wait_for_link``, and a ``from x import y`` here would step around that.
"""

import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests
from addressvault import net


class OsmUnavailable(Exception):
    """Every mirror refused, on a machine that has a working link."""


def load_osm(query, *, what, urls, rounds, round_wait, cache_path, fetch_path,
             try_one, undated="unknown"):
    """Return (data, osm_date, from_cache) for one Overpass query.

    ``try_one(url, query)`` is one attempt at one mirror, returning the reply
    or None -- normally the layer's own wrapper around ``try_overpass``.

    Falling back to the cache still beats no gap page, but it is reported
    rather than shrugged off: ``from_cache`` reaches the published page, and an
    online machine that could not reach any mirror and has no cache raises
    ``OsmUnavailable`` so the run can exit non-zero and be retried.
    """
    print(f"Querying Overpass for OSM {what} ...")
    for attempt in range(rounds):
        if attempt:
            print(f"  no mirror answered; retrying the list in {round_wait}s "
                  f"({attempt + 1} of {rounds})")
            time.sleep(round_wait)
        for url in urls:
            data = try_one(url, query)
            if data is None:
                continue
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            base = osm_base(data, undated)
            save_fetch(fetch_path, date.today().isoformat(), url, base, data)
            return data, base, False

    # Nothing answered. Ask why before deciding what it means: no link is not a
    # failed build -- the run may as well not have happened -- while a healthy
    # link and no mirror is a real outage worth retrying.
    cached = load_cache(cache_path, fetch_path)
    try:
        net.wait_for_link(wait=False)
    except net.LinkUnavailable as e:
        print(f"Warning: no usable link ({e}); Overpass was never reachable.")
        if cached:
            return (*cached, True)
        raise

    if cached:
        print(f"Warning: no Overpass mirror answered in {rounds} rounds; "
              f"falling back to OSM data from {cached[1]}.")
        return (*cached, True)
    raise OsmUnavailable(
        f"no Overpass mirror answered in {rounds} rounds "
        f"and there is no cached OSM data"
    )


def try_overpass(url, query, *, user_agent, timeout, min_elements, max_age_days,
                 allow_undated=False, check=None):
    """One attempt at one mirror; None if it failed or answered implausibly.

    ``allow_undated`` accepts a reply that carries no usable
    ``timestamp_osm_base``. The default refuses it: a reply that does not say
    how old it is cannot be shown to be fresh, and the page would date it
    today.

    ``check(data)`` is the layer's own plausibility test, run after the
    element floor: it returns a reason to ignore the reply, or None.
    """
    host = urlsplit(url).netloc
    started = time.time()
    try:
        resp = requests.post(
            url,
            data={"data": query},
            headers={"User-Agent": user_agent},
            timeout=timeout,
        )
        resp.raise_for_status()
        # Overpass sends a runtime error as an HTML page, which lands here as
        # a ValueError.
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  {host}: {type(e).__name__}: {str(e).splitlines()[0][:120]}")
        return None

    count = len(data.get("elements", []))
    if count < min_elements:
        print(f"  {host}: {count:,} elements, under the "
              f"{min_elements:,} floor -- ignoring this reply")
        return None
    reason = check(data) if check else None
    if reason:
        print(f"  {host}: {reason} -- ignoring this reply")
        return None
    base = osm_base_time(data)
    if base is None and not allow_undated:
        print(f"  {host}: no timestamp_osm_base in the reply -- ignoring it")
        return None
    if base and datetime.now(timezone.utc) - base > timedelta(days=max_age_days):
        print(f"  {host}: OSM data from {osm_base(data)}, older than "
              f"{max_age_days} days -- ignoring this reply")
        return None
    print(f"  {host}: {count:,} elements in {time.time() - started:.0f}s, "
          f"OSM base {osm_base(data)}")
    return data


def osm_base(data, undated="unknown"):
    """How current the OSM half of the diff actually is, for display.

    The reply's own ``osm3s.timestamp_osm_base`` -- the last minutely diff the
    answering mirror had applied -- trimmed to the minute. ``undated`` is what
    a reply without one is called; None means today's date.
    """
    stamp = ((data.get("osm3s") or {}).get("timestamp_osm_base") or "").strip()
    if len(stamp) >= 16:
        return f"{stamp[:10]} {stamp[11:16]}Z"
    return date.today().isoformat() if undated is None else undated


def osm_base_time(data):
    """The same timestamp as an aware datetime, or None if absent or garbled."""
    stamp = ((data.get("osm3s") or {}).get("timestamp_osm_base") or "").strip()
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    # A stamp with no zone cannot be aged against UTC; treat it as garbled.
    return when if when.tzinfo else None


def load_cache(cache_path, fetch_path):
    """(data, osm_date) for the cached Overpass reply, or None."""
    if not os.path.isfile(cache_path):
        return None
    with open(cache_path, encoding="utf-8") as f:
        data = json.load(f)
    return data, cache_date(cache_path, fetch_path)


def cache_date(cache_path, fetch_path):
    """How current the cached reply is: the sidecar, else the file's mtime."""
    if os.path.isfile(fetch_path):
        with open(fetch_path, encoding="utf-8") as f:
            sidecar = json.load(f)
        for key in ("osm_base", "fetched"):
            if sidecar.get(key):
                return sidecar[key]
    stamp = os.path.getmtime(cache_path)
    return date.fromtimestamp(stamp).isoformat()


def save_fetch(fetch_path, fetched, url, base, data):
    """Write the sidecar: when the cache was fetched, from where, how current."""
    with open(fetch_path, "w", encoding="utf-8") as f:
        json.dump({
            "fetched": fetched,
            "mirror": urlsplit(url).netloc,
            "osm_base": base,
            "timestamp_osm_base":
                (data.get("osm3s") or {}).get("timestamp_osm_base"),
        }, f, indent=2)
