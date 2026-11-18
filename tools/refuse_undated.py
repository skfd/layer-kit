"""Make a layer refuse an Overpass reply that carries no timestamp_osm_base.

usage: refuse_undated.py REPO_DIR

Drops the ``allow_undated=True`` argument adopt.py left at the layer's
_try_overpass call, and replaces the one test that asserted the old rule with
the water layer's test of the new one. Line endings are preserved.
"""
import os
import sys

repo = os.path.abspath(sys.argv[1])

OLD_ARG = ''',
        # This layer still accepts a reply that carries no timestamp_osm_base,
        # as it always has. The sidewalks, bike, gardens and water layers
        # refuse one; dropping this line makes this layer do the same.
        allow_undated=True)'''

OLD_TEST = '''def test_a_mirror_without_an_osm3s_block_still_dates_the_page(paths, monkeypatch):
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://terse.example/api",))
    terse = {"elements": GOOD["elements"]}
    monkeypatch.setattr(compare.requests, "post",
                        _post({"terse.example": FakeResponse(terse)}))
    _data, osm_date, _from_cache = compare._load_osm()
    assert osm_date.startswith("20")
'''

NEW_TEST = '''def test_a_reply_that_does_not_say_how_old_it_is_is_not_accepted(paths, monkeypatch):
    # With no timestamp_osm_base there is nothing to show the data is fresh,
    # and the page would date it today -- the failure the age check exists for.
    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://terse.example/api", "https://good.example/api"))
    terse = {"elements": GOOD["elements"]}
    post = _post({"terse.example": FakeResponse(terse),
                  "good.example": FakeResponse(GOOD)})
    monkeypatch.setattr(compare.requests, "post", post)
    _data, osm_date, from_cache = compare._load_osm()
    assert from_cache is False
    assert osm_date.startswith(OSM_BASE[:10])
    assert [u.split("/")[2] for u in post.calls] == ["terse.example", "good.example"]
'''


def swap(rel, old, new):
    path = os.path.join(repo, rel)
    with open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    eol = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    if text.count(old) != 1:
        raise SystemExit(f"{os.path.basename(repo)}: {rel}: expected the old text once, "
                         f"found it {text.count(old)} times")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace(old, new).replace("\n", eol))


swap("src/compare.py", OLD_ARG, ")")
swap("tests/test_compare.py", OLD_TEST, NEW_TEST)
print(os.path.basename(repo), "refuses undated replies")
