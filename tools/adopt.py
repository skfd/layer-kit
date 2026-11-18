"""Point one layer repo's shared plumbing at layerkit. One-off migration.

usage: adopt.py REPO_DIR [--skip compare] [--skip history] ...

Replaces whole top-level functions by name with thin wrappers that call the
kit with the layer's config. Everything else in a file -- docstring, imports,
the layer's own functions -- is left byte for byte. A function that is not
there is skipped and reported. Line endings are preserved per file.
"""
import ast
import os
import re
import sys

repo = os.path.abspath(sys.argv[1])
skip = {sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--skip"}
name = os.path.basename(repo)
report = []


def read(rel):
    with open(os.path.join(repo, rel), encoding="utf-8", newline="") as f:
        raw = f.read()
    return raw.replace("\r\n", "\n"), ("\r\n" if "\r\n" in raw else "\n")


def write(rel, text, eol):
    with open(os.path.join(repo, rel), "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", eol))


def nodes(text):
    return {n.name: n for n in ast.parse(text).body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def body_of(text, fn):
    n = nodes(text).get(fn)
    return ast.get_source_segment(text, n) if n else None


def replace(text, fn, new):
    """Swap top-level ``fn`` for ``new`` (None deletes it and one blank run)."""
    n = nodes(text).get(fn)
    if n is None:
        report.append(f"    (no {fn})")
        return text
    lines = text.split("\n")
    start, end = n.lineno - 1, n.end_lineno
    if new is None:
        while end < len(lines) and not lines[end].strip():
            end += 1
        lines[start:end] = []
    else:
        lines[start:end] = new.strip("\n").split("\n")
    return "\n".join(lines)


def _repo_python():
    out = []
    for sub in ("src", "tests", "."):
        d = os.path.join(repo, sub)
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".py"):
                    with open(os.path.join(d, f), encoding="utf-8") as fh:
                        out.append(fh.read())
    return "\n".join(out)


def prune_imports(text, modname):
    """Drop imports the replacements left unused.

    A name some other file reaches through this module (``compare.requests``,
    which the tests patch) is kept even though this file no longer uses it.
    """
    tree = ast.parse(text)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    everything = _repo_python()
    lines = text.split("\n")
    dropped = []
    for node in reversed([n for n in tree.body
                          if isinstance(n, (ast.Import, ast.ImportFrom))]):
        if node.lineno != node.end_lineno or "noqa" in lines[node.lineno - 1]:
            continue
        keep = []
        for a in node.names:
            local = (a.asname or a.name).split(".")[0]
            reached = re.search(rf"\b{modname}\.{re.escape(local)}\b", everything)
            if local in used or reached:
                keep.append(a)
            else:
                dropped.append(local)
        if len(keep) == len(node.names):
            continue
        if not keep:
            del lines[node.lineno - 1]
            continue
        names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in keep)
        if isinstance(node, ast.ImportFrom):
            lines[node.lineno - 1] = f"from {node.module} import {names}"
        else:
            lines[node.lineno - 1] = f"import {names}"
    if dropped:
        report.append(f"    dropped unused imports: {', '.join(sorted(dropped))}")
    return "\n".join(lines)


def add_import(text, after_pattern, line):
    if line in text:
        return text
    m = re.search(after_pattern, text, re.M)
    if not m:
        raise SystemExit(f"{name}: no anchor {after_pattern!r} for {line!r}")
    return text[:m.end()] + "\n" + line + text[m.end():]


# --- tilemath ---------------------------------------------------------------
if "tilemath" not in skip:
    _, eol = read("src/tilemath.py")
    write("src/tilemath.py", '''"""Web Mercator (XYZ slippy-map) coordinate helpers. Tile size is 256 px.

They are layerkit's; this module keeps the name the rest of the layer imports.
"""

from layerkit.tilemath import (  # noqa: F401
    TILE_SIZE,
    lonlat_to_pixel,
    lonlat_to_tile,
    pixel_in_tile,
    tile_bounds,
)
''', eol)
    report.append("  tilemath: shim")

# --- publish ----------------------------------------------------------------
if "publish" not in skip:
    text, eol = read("src/publish.py")
    for fn in ("publish", "_push", "_git"):
        if fn not in nodes(text):
            raise SystemExit(f"{name}: publish.py has no {fn}")
    write("src/publish.py", '''"""Publish build/site/ to the orphan gh-pages branch (single commit, force-push).

The staging, the orphan commit and the push retry are layerkit.publish; this
module binds them to this layer's paths. ``_git``, ``_push`` and ``PUSH_WAIT``
stay here because the tests stand in for them.
"""

from layerkit import publish as _kit

from src import config

PUSH_RETRIES = _kit.PUSH_RETRIES
PUSH_WAIT = _kit.PUSH_WAIT


def publish():
    """Commit build/site/ as a single orphan commit on gh-pages and force-push."""
    _kit.publish(config.PROJECT_DIR, config.SITE_DIR, config.BUILD_DIR,
                 git=_git, push_fn=_push)


def _push(env):
    """Force-push gh-pages, retrying a network failure."""
    _kit.push(env, git=_git, retries=PUSH_RETRIES, wait=PUSH_WAIT)


def _git(args, env):
    return _kit.run_git(config.PROJECT_DIR, args, env)
''', eol)
    report.append("  publish: shim")

# --- vector -----------------------------------------------------------------
if "vector" not in skip:
    text, eol = read("src/vector.py")
    text = replace(text, "win_to_wsl", '''
def win_to_wsl(path):
    """Convert a Windows path to its /mnt/<drive> WSL equivalent."""
    return wsl.win_to_wsl(path)
''')
    text = replace(text, "_wsl", '''
def _wsl(command):
    """Run a bash command inside WSL. Returns stderr; raises on failure."""
    return wsl.run(command, config.WSL_DISTRO)
''')
    text = add_import(text, r"^from src import config$", "@@")
    text = text.replace("from src import config\n@@",
                        "from layerkit import wsl\n\nfrom src import config")
    text = prune_imports(text, "vector")
    write("src/vector.py", text, eol)
    report.append("  vector: win_to_wsl, _wsl")

# --- history ----------------------------------------------------------------
if "history" not in skip:
    text, eol = read("src/history.py")
    sparse = "if k in summary" in (body_of(text, "record") or "")
    text = replace(text, "record", f'''
def record(summary, day=None):
    """Append the run's row (replacing an earlier row from the same day)."""
    return _kit.record(summary, FIELDS, path=config.HISTORY_PATH, seed=seed,
                       day=day{", sparse=True" if sparse else ""})
''')
    text = replace(text, "load", '''
def load():
    """All rows, oldest first. An absent file is an empty history."""
    return _kit.load(config.HISTORY_PATH)
''')
    text = replace(text, "seed", '''
def seed():
    """Start a checkout that has no history from the published copy."""
    return _kit.seed(config.HISTORY_PATH, config.HISTORY_URL, config.USER_AGENT)
''')
    if "dates" in nodes(text):
        text = replace(text, "dates", '''
def dates(since, until, step_days):
    """``since``, then every ``step_days``, while before ``until``."""
    return _kit.dates(since, until, step_days)
''')
    text = replace(text, "_write", '''
def _write(rows):
    _kit.write(config.HISTORY_PATH, rows)
''')
    text = add_import(text, r"^from src import config$",
                      "from layerkit import history as _kit")
    # keep third-party before first-party: move the kit import above src's
    text = text.replace("from src import config\nfrom layerkit import history as _kit",
                        "from layerkit import history as _kit\n\nfrom src import config")
    text = prune_imports(text, "history")
    text = text.replace("from addressvault import net\n\nfrom layerkit",
                        "from addressvault import net\nfrom layerkit")
    write("src/history.py", text, eol)
    report.append(f"  history: record{' (sparse)' if sparse else ''}, load, seed, _write")

# --- compare ----------------------------------------------------------------
if "compare" not in skip:
    text, eol = read("src/compare.py")
    old_load = body_of(text, "_load_osm")
    old_try = body_of(text, "_try_overpass")
    old_base = body_of(text, "_osm_base")
    m = re.search(r'print\("Querying Overpass for OSM (.+?) \.\.\."\)', old_load)
    if not m and "what=\"park areas\"" not in old_load:
        raise SystemExit(f"{name}: cannot read the label out of _load_osm")
    what = m.group(1) if m else None
    # Two layers carry more than the common shape, and are named here:
    #   parks -- a second (amenity) query with its own cache and floor, so the
    #            plumbing takes paths and a floor as arguments;
    #   bike  -- a floor on route relations as well as on elements.
    parks = "_load_osm(query=None, cache_path=None" in old_load
    bike = "OSM_MIN_ROUTES" in old_try
    if parks:
        what = "park areas"
    elif "_load_osm():" not in old_load or "_try_overpass(url, query):" not in old_try:
        raise SystemExit(f"{name}: _load_osm/_try_overpass take arguments; do by hand")
    lenient = "if base and datetime.now" in old_try
    strict = "base is None" in old_try
    if lenient == strict:
        raise SystemExit(f"{name}: cannot tell whether undated replies are accepted")
    today = "return date.today().isoformat()" in old_base
    unknown = 'return "unknown"' in old_base
    if today == unknown:
        raise SystemExit(f"{name}: cannot read _osm_base's fallback")
    undated = "None" if today else '"unknown"'

    allow = (''',
        # This layer still accepts a reply that carries no timestamp_osm_base,
        # as it always has. The sidewalks, bike, gardens and water layers
        # refuse one; dropping this line makes this layer do the same.
        allow_undated=True''' if lenient else "")
    text = replace(text, "OsmUnavailable", None)
    if parks:
        text = replace(text, "_load_osm", f'''
def _load_osm(query=None, cache_path=None, fetch_path=None, min_elements=None,
              what="park areas"):
    """Return (data, osm_date, from_cache) for OSM park areas.

    The arguments default to the park-area query and its cache; the amenity
    query passes its own (see _load_amenity_osm), so the two caches never mix.

    The fetch -- every mirror, the list retried, then the cache -- is
    layerkit.overpass.load_osm; the reasons for each rule are written there.
    """
    return overpass.load_osm(
        query or _overpass_query(), what=what,
        urls=config.OVERPASS_URLS, rounds=config.OVERPASS_ROUNDS,
        round_wait=config.OVERPASS_ROUND_WAIT,
        cache_path=cache_path or config.OSM_CACHE_PATH,
        fetch_path=fetch_path or config.OSM_FETCH_PATH,
        try_one=lambda url, q: _try_overpass(url, q, min_elements),
        undated={undated})
''')
        text = replace(text, "_try_overpass", f'''
def _try_overpass(url, query, min_elements=None):
    """One attempt at one mirror; None if it failed or answered implausibly."""
    if min_elements is None:
        min_elements = config.OSM_MIN_ELEMENTS
    return overpass.try_overpass(
        url, query, user_agent=config.USER_AGENT,
        timeout=config.OVERPASS_TIMEOUT,
        min_elements=min_elements,
        max_age_days=config.OSM_MAX_AGE_DAYS{allow})
''')
        text = replace(text, "_load_cache", '''
def _load_cache(cache_path=None, fetch_path=None):
    """(data, osm_date) for the cached Overpass reply, or None."""
    return overpass.load_cache(cache_path or config.OSM_CACHE_PATH,
                               fetch_path or config.OSM_FETCH_PATH)
''')
        text = replace(text, "_cache_date", '''
def _cache_date(cache_path=None, fetch_path=None):
    """How current the cached reply is: the sidecar, else the file's mtime."""
    return overpass.cache_date(cache_path or config.OSM_CACHE_PATH,
                               fetch_path or config.OSM_FETCH_PATH)
''')
        text = replace(text, "_save_fetch", '''
def _save_fetch(fetched, url, osm_base, data, fetch_path):
    overpass.save_fetch(fetch_path, fetched, url, osm_base, data)
''')
    elif bike:
        text = replace(text, "_try_overpass", f'''
def _try_overpass(url, query):
    """One attempt at one mirror; None if it failed or answered implausibly."""
    return overpass.try_overpass(
        url, query, user_agent=config.USER_AGENT,
        timeout=config.OVERPASS_TIMEOUT,
        min_elements=config.OSM_MIN_ELEMENTS,
        max_age_days=config.OSM_MAX_AGE_DAYS,
        check=_too_few_routes{allow})


def _too_few_routes(data):
    """Why a reply with too few route relations is ignored, or None.

    The relation half of the query timing out leaves the ways intact, and
    every signed route would then read as unsigned.
    """
    routes = sum(1 for el in data.get("elements", [])
                 if el.get("type") == "relation")
    if routes < config.OSM_MIN_ROUTES:
        return (f"{{routes:,}} bicycle routes, under the "
                f"{{config.OSM_MIN_ROUTES:,}} floor")
    return None
''')
    if not parks:
        text = replace(text, "_load_osm", f'''
def _load_osm():
    """Return (data, osm_date, from_cache) for OSM {what}.

    The fetch -- every mirror, the list retried, then the cache -- is
    layerkit.overpass.load_osm; the reasons for each rule are written there.
    """
    return overpass.load_osm(
        _overpass_query(), what="{what}",
        urls=config.OVERPASS_URLS, rounds=config.OVERPASS_ROUNDS,
        round_wait=config.OVERPASS_ROUND_WAIT,
        cache_path=config.OSM_CACHE_PATH, fetch_path=config.OSM_FETCH_PATH,
        try_one=_try_overpass, undated={undated})
''')
    tail = (''',
        # This layer still accepts a reply that carries no timestamp_osm_base,
        # as it always has. The sidewalks, bike, gardens and water layers
        # refuse one; dropping this line makes this layer do the same.
        allow_undated=True)''' if lenient else ")")
    text = text if (parks or bike) else replace(text, "_try_overpass", f'''
def _try_overpass(url, query):
    """One attempt at one mirror; None if it failed or answered implausibly."""
    return overpass.try_overpass(
        url, query, user_agent=config.USER_AGENT,
        timeout=config.OVERPASS_TIMEOUT,
        min_elements=config.OSM_MIN_ELEMENTS,
        max_age_days=config.OSM_MAX_AGE_DAYS{tail}
''')
    text = text if parks else replace(text, "_load_cache", '''
def _load_cache():
    """(data, osm_date) for the cached Overpass reply, or None."""
    return overpass.load_cache(config.OSM_CACHE_PATH, config.OSM_FETCH_PATH)
''')
    text = replace(text, "_osm_base", f'''
def _osm_base(data):
    """How current the OSM half of the diff is: the reply's own
    osm3s.timestamp_osm_base, trimmed to the minute for display."""
    return overpass.osm_base(data, undated={undated})
''')
    text = replace(text, "_osm_base_time", '''
def _osm_base_time(data):
    """The same timestamp as an aware datetime, or None if absent or garbled."""
    return overpass.osm_base_time(data)
''')
    text = text if parks else replace(text, "_cache_date", '''
def _cache_date():
    """How current the cached reply is: the sidecar, else the file's mtime."""
    return overpass.cache_date(config.OSM_CACHE_PATH, config.OSM_FETCH_PATH)
''')
    text = text if parks else replace(text, "_save_fetch", '''
def _save_fetch(fetched, url, osm_base, data):
    overpass.save_fetch(config.OSM_FETCH_PATH, fetched, url, osm_base, data)
''')
    text = add_import(
        text, r"^from addressvault import net$",
        "from layerkit import overpass\n"
        "# Raised by overpass.load_osm; callers and tests name it as compare's.\n"
        "from layerkit.overpass import OsmUnavailable  # noqa: F401")
    text = prune_imports(text, "compare")
    write("src/compare.py", text, eol)
    report.append(f"  compare: what={what!r}, undated replies "
                  f"{'ACCEPTED' if lenient else 'refused'}, fallback date {undated}")

# --- requirements -----------------------------------------------------------
text, eol = read("requirements.txt")
if "layerkit" not in text.split("\n"):
    if "addressvault\n" not in text:
        raise SystemExit(f"{name}: requirements.txt has no addressvault line")
    text = text.replace("addressvault\n", "addressvault\nlayerkit\n", 1)
    write("requirements.txt", text, eol)

print(name)
print("\n".join(report))
