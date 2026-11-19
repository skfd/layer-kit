"""Point a layer's City download at layerkit.citydata.

usage: lift_citydata.py REPO_DIR

Replaces, in src/download.py, the copies of:

* ``_fetch(url)``        -> a wrapper around ``citydata.get``
* ``_fetch(url, dest)``  -> a wrapper around ``citydata.stream``
* ``_check_payload(body)`` -> a wrapper around ``citydata.check_feature_collection``

A function is replaced only when it is one of the known copies (compared as
syntax trees, so a docstring or comment may differ). Anything else is left
alone and reported. The layer's docstring on ``_check_payload`` is kept: it
says why that layer's row count is safe from the transfer limit.

``import requests`` stays even where nothing calls it any more: the layers'
tests patch ``src.download.requests.get``.
"""
import ast
import os
import sys

repo = os.path.abspath(sys.argv[1])
path = os.path.join(repo, "src", "download.py")

GET_COPIES = [
    '''
def _fetch(url):
    for attempt in range(RETRIES + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=600)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            if attempt == RETRIES:
                net.wait_for_link(wait=False)
                raise
            print(f"  %s failed ({e}); retrying in {RETRY_WAIT}s")
            time.sleep(RETRY_WAIT)
''' % word for word in ("query", "request")]

STREAM_COPY = '''
def _fetch(url, dest):
    got = 0
    resumable = False
    headers = {}
    for attempt in range(RETRIES + 1):
        want = {"Range": f"bytes={got}-"} if got else {}
        try:
            with requests.get(url, stream=True, timeout=600, headers=want) as resp:
                resp.raise_for_status()
                if resp.status_code != 206:
                    got = 0
                    resumable = not resp.headers.get("Content-Encoding")
                    headers = {"last_modified": resp.headers.get("Last-Modified"),
                               "content_length": _parse_int(resp.headers.get("Content-Length"))}
                total = headers.get("content_length") or 0
                with open(dest, "ab" if got else "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        f.write(chunk)
                        got += len(chunk)
                        if total:
                            print(f"\\r  {got // (1024 * 1024)} / {total // (1024 * 1024)} MB ({got * 100 // total}%)", end="", flush=True)
            return headers
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as e:
            total = headers.get("content_length")
            if resumable and total and got >= total:
                return headers
            if attempt == RETRIES:
                net.wait_for_link(wait=False)
                raise
            if not resumable:
                got = 0
            print(f"\\n  download dropped at {got:,} bytes ({e}); retrying in {RETRY_WAIT}s")
            time.sleep(RETRY_WAIT)
'''

CHECK_COPY = '''
def _check_payload(body):
    try:
        doc = json.loads(body)
    except ValueError as e:
        raise RuntimeError(f"The service did not return JSON: {e}")
    if "error" in doc:
        raise RuntimeError(f"The service returned an error: {doc['error']}")
    if doc.get("type") != "FeatureCollection":
        raise RuntimeError(f"Expected a FeatureCollection, got {doc.get('type')!r}")
    if doc.get("exceededTransferLimit"):
        raise RuntimeError("The service truncated the result (exceededTransferLimit). The download is a partial extract -- paginate with resultOffset / resultRecordCount before trusting it.")
    n = len(doc.get("features") or ())
    print(f"  {n:,} features")
    if not n:
        raise RuntimeError("The service returned an empty FeatureCollection.")
'''

GET_WRAPPER = '''
def _fetch(url):
    """GET ``url``, retrying a failed request. Returns the raw body."""
    return citydata.get(url, user_agent=config.USER_AGENT,
                        retries=RETRIES, wait=RETRY_WAIT)
'''

STREAM_WRAPPER = '''
def _fetch(url, dest):
    """Stream ``url`` to ``dest``, resuming a dropped connection; return the
    Last-Modified and Content-Length of the full response."""
    # user_agent=None: this download has never sent one.
    return citydata.stream(url, dest, user_agent=None,
                           retries=RETRIES, wait=RETRY_WAIT)
'''


def shape(node):
    """The function as a dump with its docstring dropped."""
    node = ast.parse(ast.unparse(node)).body[0]
    if ast.get_docstring(node) is not None:
        node.body = node.body[1:]
    return ast.dump(node)


def known(src):
    return shape(ast.parse(src).body[0])


def funcs(text):
    return {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}


def swap(text, node, new):
    lines = text.split("\n")
    lines[node.lineno - 1:node.end_lineno] = new.strip("\n").split("\n")
    return "\n".join(lines)


with open(path, encoding="utf-8", newline="") as f:
    raw = f.read()
eol = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")
done = []

node = funcs(text).get("_fetch")
if node is not None:
    if shape(node) in {known(s) for s in GET_COPIES}:
        text = swap(text, node, GET_WRAPPER)
        done.append("_fetch -> citydata.get")
    elif shape(node) == known(STREAM_COPY):
        text = swap(text, node, STREAM_WRAPPER)
        done.append("_fetch -> citydata.stream")
    else:
        print("  _fetch: not a known copy, left alone")

node = funcs(text).get("_check_payload")
if node is not None:
    if shape(node) == known(CHECK_COPY):
        doc = ast.get_source_segment(text, node.body[0]) if ast.get_docstring(node) else None
        new = "def _check_payload(body):\n"
        if doc:
            new += "    " + doc + "\n"
        new += "    citydata.check_feature_collection(body)\n"
        text = swap(text, node, new)
        done.append("_check_payload -> citydata.check_feature_collection")
    else:
        print("  _check_payload: not a known copy, left alone")

if done:
    anchor = "from addressvault import net\n"
    if text.count(anchor) != 1:
        raise SystemExit(f"{os.path.basename(repo)}: no single {anchor!r}")
    text = text.replace(anchor, anchor + "from layerkit import citydata\n")

    tree = ast.parse(text)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line == "import time" and "time" not in used:
            lines[i] = None
        elif line == "import requests" and "requests" not in used:
            lines[i] = "import requests  # noqa: F401 -- the tests patch requests.get here"
    text = "\n".join(l for l in lines if l is not None)
    # _parse_int was only the stream's, unless the layer's _head uses it too.
    tree = ast.parse(text)
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    node = funcs(text).get("_parse_int")
    if node is not None and "_parse_int" not in called:
        lines = text.split("\n")
        start, end = node.lineno - 1, node.end_lineno
        while end < len(lines) and not lines[end].strip():
            end += 1
        del lines[start:end]
        text = "\n".join(lines)
        done.append("dropped _parse_int, now unused")

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.rstrip("\n").replace("\n", eol) + eol)
print(os.path.basename(repo), "lifted:", ", ".join(done) or "nothing")
