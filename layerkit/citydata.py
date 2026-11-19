"""Fetch a layer's City half: one reply in memory, or one file to disk.

Two shapes, because the City publishes two kinds of thing:

* ``get`` is for a reply generated when you ask -- an ArcGIS ``/query``, a CKAN
  action, a small static file. It comes back in seconds, has no Last-Modified
  worth caching on, and the layer wants the bytes to check and hash. A dropped
  connection is retried from the start, which costs seconds.
* ``stream`` is for a big static file -- tens of MB off CKAN. It goes straight
  to disk, and a connection that dies mid-body resumes with a Range request
  instead of costing the whole download.

Both retry a dropped connection, and both ask about the link once out of
retries: if there is no usable link then the City was never reached at all,
and ``net.LinkUnavailable`` lets the run exit 75 rather than log a build error.

``check_feature_collection`` is the ArcGIS rule that HTTP 200 proves nothing:
an error comes back as a 200 with an ``error`` object, and a reply cut off at
maxRecordCount says so only in ``exceededTransferLimit``.

``requests``, ``time`` and ``net`` are called through their modules on purpose.
The layers' tests patch ``requests.get``, ``time.sleep`` and
``net.wait_for_link``, and a ``from x import y`` here would step around that.
"""

import json
import time

import requests
from addressvault import net


def get(url, *, user_agent, retries, wait, params=None, timeout=600):
    """GET ``url``, retrying a failed request. Returns the raw body.

    ``retries`` is how many times to try again after the first attempt, with
    ``wait`` seconds between them.
    """
    kw = {"headers": {"User-Agent": user_agent}, "timeout": timeout}
    if params is not None:
        kw["params"] = params
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, **kw)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            if attempt == retries:
                net.wait_for_link(wait=False)
                raise
            print(f"  request failed ({e}); retrying in {wait}s")
            time.sleep(wait)


def stream(url, dest, *, user_agent, retries, wait, timeout=600):
    """Stream ``url`` to ``dest``; return the response headers worth keeping.

    Returns ``{"last_modified": ..., "content_length": ...}``. ``user_agent``
    None sends no User-Agent header.

    Retries a dropped connection, resuming with a Range request where the server
    allows it and starting over where it does not. A content-encoded body cannot
    be resumed: Range counts encoded bytes, and what is on disk is decoded. The
    kept headers come from the full response, never a 206 -- a range reply's
    Content-Length describes the tail, and the sidecar compares whole files.
    """
    got = 0
    resumable = False
    headers = {}
    for attempt in range(retries + 1):
        want = {"Range": f"bytes={got}-"} if got else {}
        if user_agent:
            want["User-Agent"] = user_agent
        try:
            with requests.get(url, stream=True, timeout=timeout, headers=want) as resp:
                resp.raise_for_status()
                if resp.status_code != 206:  # full body: (re)start from byte 0
                    got = 0
                    resumable = not resp.headers.get("Content-Encoding")
                    headers = {
                        "last_modified": resp.headers.get("Last-Modified"),
                        "content_length": _int(resp.headers.get("Content-Length")),
                    }
                total = headers.get("content_length") or 0
                with open(dest, "ab" if got else "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        f.write(chunk)
                        got += len(chunk)
                        if total:
                            print(
                                f"\r  {got // (1024 * 1024)} / "
                                f"{total // (1024 * 1024)} MB "
                                f"({got * 100 // total}%)",
                                end="", flush=True,
                            )
            return headers
        except (requests.ConnectionError, requests.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            total = headers.get("content_length")
            if resumable and total and got >= total:
                return headers  # dropped on the last chunk; the file is whole
            if attempt == retries:
                net.wait_for_link(wait=False)
                raise
            if not resumable:
                got = 0
            print(f"\n  download dropped at {got:,} bytes ({e});"
                  f" retrying in {wait}s")
            time.sleep(wait)


def check_feature_collection(body):
    """Raise RuntimeError unless ``body`` is a whole, non-empty FeatureCollection.

    Raises rather than paginating on ``exceededTransferLimit``: a partial
    extract reports whatever fell off the end as missing from OSM, which looks
    exactly like a good run.
    """
    try:
        doc = json.loads(body)
    except ValueError as e:
        raise RuntimeError(f"The service did not return JSON: {e}")
    if "error" in doc:
        raise RuntimeError(f"The service returned an error: {doc['error']}")
    if doc.get("type") != "FeatureCollection":
        raise RuntimeError(f"Expected a FeatureCollection, got {doc.get('type')!r}")
    if doc.get("exceededTransferLimit"):
        raise RuntimeError(
            "The service truncated the result (exceededTransferLimit). The "
            "download is a partial extract -- paginate with resultOffset / "
            "resultRecordCount before trusting it."
        )
    n = len(doc.get("features") or ())
    print(f"  {n:,} features")
    if not n:
        raise RuntimeError("The service returned an empty FeatureCollection.")


def _int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
