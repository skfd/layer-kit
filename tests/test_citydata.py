"""The City fetch: retries, resume, the link question, and what a reply must be."""

import json

import pytest
import requests
from addressvault import net

from layerkit import citydata

BODY = b"x" * (1024 * 768)  # three 256 KB chunks
CHUNK = 1024 * 256
LAST_MODIFIED = "Tue, 05 May 2026 21:59:31 GMT"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr(net, "wait_for_link", lambda **k: None)


def dead_link(monkeypatch):
    monkeypatch.setattr(net, "wait_for_link",
                        lambda **k: (_ for _ in ()).throw(net.Offline("offline")))


class Reply:
    def __init__(self, body=b"", status=200, headers=None, drop_after=None):
        self.content, self.status_code = body, status
        self.headers = headers or {}
        self.drop_after = drop_after

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")

    def iter_content(self, chunk_size=1):
        sent = 0
        for i in range(0, len(self.content), chunk_size):
            if self.drop_after is not None and sent >= self.drop_after:
                raise requests.ConnectionError("connection dropped")
            chunk = self.content[i:i + chunk_size]
            sent += len(chunk)
            yield chunk


def args(**kw):
    return {"user_agent": "test", "retries": 2, "wait": 0, **kw}


# -- get ----------------------------------------------------------------------

def test_get_returns_the_body_and_sends_the_user_agent(monkeypatch):
    seen = []
    monkeypatch.setattr(requests, "get",
                        lambda url, **k: seen.append((url, k)) or Reply(b"ok"))

    assert citydata.get("http://x/q", **args()) == b"ok"
    assert seen == [("http://x/q", {"headers": {"User-Agent": "test"}, "timeout": 600})]


def test_get_passes_params_only_when_given(monkeypatch):
    seen = []
    monkeypatch.setattr(requests, "get", lambda url, **k: seen.append(k) or Reply(b"ok"))

    citydata.get("http://x/q", **args(params={"f": "json"}))
    assert seen[0]["params"] == {"f": "json"}


def test_get_retries_a_failure_then_succeeds(monkeypatch):
    replies = [Reply(status=503), Reply(b"ok")]
    monkeypatch.setattr(requests, "get", lambda *a, **k: replies.pop(0))

    assert citydata.get("http://x/q", **args()) == b"ok"


def test_get_out_of_retries_on_a_dead_link_raises_link_unavailable(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise requests.ConnectionError("getaddrinfo failed")
    monkeypatch.setattr(requests, "get", boom)
    dead_link(monkeypatch)

    with pytest.raises(net.Offline):
        citydata.get("http://x/q", **args(retries=1))
    assert len(calls) == 2  # the first attempt plus one retry


def test_get_out_of_retries_on_a_good_link_raises_the_failure(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: Reply(status=500))

    with pytest.raises(requests.HTTPError):
        citydata.get("http://x/q", **args(retries=1))


# -- stream -------------------------------------------------------------------

def fake_get(state, drops=0, honor_range=True):
    def get(url, stream=False, timeout=None, headers=None):
        state["headers"].append(dict(headers or {}))
        rng = (headers or {}).get("Range")
        if rng and honor_range:
            start = int(rng.split("=")[1].split("-")[0])
            resp = Reply(BODY[start:], status=206,
                         headers={"Content-Length": str(len(BODY) - start)})
        else:
            resp = Reply(BODY, headers={"Last-Modified": LAST_MODIFIED,
                                        "Content-Length": str(len(BODY))})
        if len(state["headers"]) <= drops:
            resp.drop_after = CHUNK
        return resp
    return get


def test_stream_resumes_after_a_dropped_connection(tmp_path, monkeypatch):
    state = {"headers": []}
    monkeypatch.setattr(requests, "get", fake_get(state, drops=1))
    dest = tmp_path / "out"

    headers = citydata.stream("http://x/f", str(dest), **args(user_agent=None))

    assert dest.read_bytes() == BODY
    assert headers == {"last_modified": LAST_MODIFIED, "content_length": len(BODY)}
    assert [h.get("Range") for h in state["headers"]] == [None, f"bytes={CHUNK}-"]


def test_stream_restarts_when_the_server_ignores_range(tmp_path, monkeypatch):
    state = {"headers": []}
    monkeypatch.setattr(requests, "get", fake_get(state, drops=1, honor_range=False))
    dest = tmp_path / "out"

    citydata.stream("http://x/f", str(dest), **args(user_agent=None))

    assert dest.read_bytes() == BODY  # restarted, not appended onto the partial


def test_stream_does_not_resume_an_encoded_body(tmp_path, monkeypatch):
    state = {"headers": []}

    def get(url, stream=False, timeout=None, headers=None):
        state["headers"].append(dict(headers or {}))
        resp = Reply(BODY, headers={"Content-Length": str(len(BODY)),
                                    "Content-Encoding": "gzip"})
        if len(state["headers"]) == 1:
            resp.drop_after = CHUNK
        return resp
    monkeypatch.setattr(requests, "get", get)

    citydata.stream("http://x/f", str(tmp_path / "out"), **args(user_agent=None))

    assert [h.get("Range") for h in state["headers"]] == [None, None]


def test_stream_sends_a_user_agent_only_when_given(tmp_path, monkeypatch):
    state = {"headers": []}
    monkeypatch.setattr(requests, "get", fake_get(state))

    citydata.stream("http://x/f", str(tmp_path / "a"), **args(user_agent=None))
    citydata.stream("http://x/f", str(tmp_path / "b"), **args(user_agent="ua"))

    assert state["headers"] == [{}, {"User-Agent": "ua"}]


def test_stream_out_of_retries_on_a_dead_link_raises_link_unavailable(tmp_path, monkeypatch):
    state = {"headers": []}
    monkeypatch.setattr(requests, "get", fake_get(state, drops=99))
    dead_link(monkeypatch)

    with pytest.raises(net.Offline):
        citydata.stream("http://x/f", str(tmp_path / "out"), **args(retries=1))
    assert len(state["headers"]) == 2


# -- check_feature_collection -------------------------------------------------

def fc(n, **extra):
    return json.dumps({"type": "FeatureCollection",
                       "features": [{"type": "Feature"}] * n, **extra}).encode()


def test_a_whole_collection_passes():
    citydata.check_feature_collection(fc(3))


@pytest.mark.parametrize("body, says", [
    (b"<html>", "did not return JSON"),
    (json.dumps({"error": {"code": 400}}).encode(), "returned an error"),
    (json.dumps({"type": "Feature"}).encode(), "Expected a FeatureCollection"),
    (fc(3, exceededTransferLimit=True), "truncated"),
    (fc(0), "empty"),
])
def test_a_200_that_is_not_a_whole_collection_is_refused(body, says):
    with pytest.raises(RuntimeError, match=says):
        citydata.check_feature_collection(body)


def _row(gid, width=1.5):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"OBJECTID": 1, "WIDTH": width, "GlobalID": gid}}


def test_digest_with_nothing_ignored_is_the_hash_of_the_compact_body():
    import hashlib
    rows = [_row("{A}")]
    body = json.dumps({"type": "FeatureCollection", "features": rows},
                      separators=(",", ":")).encode("utf-8")
    assert citydata.digest(rows) == hashlib.sha256(body).hexdigest()


def test_digest_does_not_see_an_ignored_field_change():
    assert (citydata.digest([_row("{A}")], ignore=("GlobalID",))
            == citydata.digest([_row("{B}")], ignore=("GlobalID",)))
    assert citydata.digest([_row("{A}")]) != citydata.digest([_row("{B}")])


def test_digest_still_sees_a_real_change():
    assert (citydata.digest([_row("{A}")], ignore=("GlobalID",))
            != citydata.digest([_row("{A}", width=2.0)], ignore=("GlobalID",)))


def test_digest_leaves_the_rows_it_was_given_alone():
    rows = [_row("{A}")]
    citydata.digest(rows, ignore=("GlobalID",))
    assert rows[0]["properties"]["GlobalID"] == "{A}"
