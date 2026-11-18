"""The Overpass fetch: which replies are believed, and what happens when none is."""

import json
from datetime import datetime, timedelta, timezone

import pytest
import requests
from addressvault import net

from layerkit import overpass

NOW = datetime.now(timezone.utc)
FRESH = (NOW - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
OLD = (NOW - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Reply:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} Server Error")

    def json(self):
        if self.payload is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self.payload


def reply(n=10, stamp=FRESH):
    data = {"elements": [{"type": "node", "id": i} for i in range(n)]}
    if stamp is not None:
        data["osm3s"] = {"timestamp_osm_base": stamp}
    return data


def attempt(monkeypatch, payload, status=200, **kw):
    monkeypatch.setattr(requests, "post", lambda *a, **k: Reply(payload, status))
    args = {"user_agent": "test", "timeout": 5, "min_elements": 5,
            "max_age_days": 3, **kw}
    return overpass.try_overpass("https://a.example/api", "q", **args)


def test_a_fresh_full_reply_is_believed(monkeypatch):
    assert attempt(monkeypatch, reply()) == reply()


def test_an_http_error_is_not_an_answer(monkeypatch):
    assert attempt(monkeypatch, reply(), status=504) is None


def test_an_html_error_page_is_not_an_answer(monkeypatch):
    assert attempt(monkeypatch, None) is None


def test_a_reply_under_the_floor_is_ignored(monkeypatch):
    assert attempt(monkeypatch, reply(n=4)) is None


def test_a_stale_reply_is_ignored(monkeypatch):
    assert attempt(monkeypatch, reply(stamp=OLD)) is None


def test_an_undated_reply_is_ignored_unless_the_layer_allows_it(monkeypatch):
    assert attempt(monkeypatch, reply(stamp=None)) is None
    assert attempt(monkeypatch, reply(stamp=None), allow_undated=True) is not None


def test_a_stamp_with_no_zone_counts_as_undated(monkeypatch):
    naive = FRESH.rstrip("Z")
    assert overpass.osm_base_time(reply(stamp=naive)) is None
    assert attempt(monkeypatch, reply(stamp=naive)) is None


def test_a_stale_reply_is_ignored_even_where_undated_is_allowed(monkeypatch):
    assert attempt(monkeypatch, reply(stamp=OLD), allow_undated=True) is None


def test_the_layers_own_check_can_refuse_a_reply(monkeypatch):
    assert attempt(monkeypatch, reply(), check=lambda d: "0 routes") is None
    assert attempt(monkeypatch, reply(), check=lambda d: None) is not None


def test_osm_base_is_the_replys_own_stamp_to_the_minute():
    data = reply(stamp="2026-10-09T14:23:51Z")
    assert overpass.osm_base(data) == "2026-10-09 14:23Z"
    assert overpass.osm_base(reply(stamp=None)) == "unknown"
    assert overpass.osm_base(reply(stamp=None), undated=None) == NOW.astimezone().date().isoformat()


# --- load_osm ----------------------------------------------------------------

@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(overpass.time, "sleep", lambda _s: None)
    return {"cache_path": str(tmp_path / "osm.json"),
            "fetch_path": str(tmp_path / ".osm-fetch.json")}


def load(try_one, paths, urls=("https://a.example/api", "https://b.example/api"),
         rounds=2):
    return overpass.load_osm("q", what="things", urls=urls, rounds=rounds,
                             round_wait=60, try_one=try_one, **paths)


def test_the_first_mirror_that_answers_wins_and_is_cached(paths):
    seen = []

    def try_one(url, query):
        seen.append(url)
        return reply() if "b.example" in url else None

    data, osm_date, from_cache = load(try_one, paths)
    assert (data, from_cache) == (reply(), False)
    assert osm_date == overpass.osm_base(reply())
    assert seen == ["https://a.example/api", "https://b.example/api"]
    with open(paths["fetch_path"], encoding="utf-8") as f:
        sidecar = json.load(f)
    assert sidecar["mirror"] == "b.example"
    assert sidecar["timestamp_osm_base"] == FRESH
    with open(paths["cache_path"], encoding="utf-8") as f:
        assert json.load(f) == reply()


def test_the_whole_list_is_retried(paths):
    calls = []

    def try_one(url, query):
        calls.append(url)
        return reply() if len(calls) == 4 else None

    assert load(try_one, paths)[2] is False
    assert len(calls) == 4


def test_no_mirror_falls_back_to_the_cache_and_says_so(paths, monkeypatch):
    load(lambda url, query: reply(), paths)
    monkeypatch.setattr(net, "wait_for_link", lambda wait=True: None)
    data, osm_date, from_cache = load(lambda url, query: None, paths)
    assert from_cache is True
    assert data == reply()
    assert osm_date == overpass.osm_base(reply())


def test_no_mirror_and_no_cache_on_a_working_link_raises(paths, monkeypatch):
    monkeypatch.setattr(net, "wait_for_link", lambda wait=True: None)
    with pytest.raises(overpass.OsmUnavailable):
        load(lambda url, query: None, paths)


def test_no_link_and_no_cache_raises_link_unavailable(paths, monkeypatch):
    def no_link(wait=True):
        raise net.Offline("no usable link")
    monkeypatch.setattr(net, "wait_for_link", no_link)
    with pytest.raises(net.LinkUnavailable):
        load(lambda url, query: None, paths)
