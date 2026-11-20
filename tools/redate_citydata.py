"""Point a layer's download sidecar at the day the City data last really changed.

usage: redate_citydata.py SIDECAR PREFIX FIELD [FIELD ...] [--write]

A layer whose hash kept a field the service reissues on every request (the
GlobalID of Guelph's paged /query services) saved a new dated file on every
run, and its sidecar names the latest one, so the page dated the City data to
the last build. Once the layer hashes with ``citydata.digest(..., ignore=...)``
its next run would see the old sidecar hash as a change and save yet another
file. This rehashes the dated ``PREFIX*.geojson`` files beside SIDECAR the new
way, finds the first file of the newest run of identical ones, and records that
file and its new hash in SIDECAR.

Prints what it would write; ``--write`` writes it. The dated files are left as
they are: the newest still holds the current data, and nothing reads the
in-between ones.
"""
import json
import os
import re
import sys

from layerkit import citydata

args = [a for a in sys.argv[1:] if a != "--write"]
write = "--write" in sys.argv[1:]
sidecar, prefix, fields = os.path.abspath(args[0]), args[1], tuple(args[2:])
data = os.path.dirname(sidecar)
dated = re.compile(re.escape(prefix) + r"\d{4}-\d{2}-\d{2}\.geojson$")

names = sorted(n for n in os.listdir(data) if dated.match(n))
if not names:
    sys.exit(f"No {prefix}YYYY-MM-DD.geojson beside {sidecar}.")


def digest(name):
    with open(os.path.join(data, name), encoding="utf-8") as f:
        return citydata.digest(json.load(f)["features"], ignore=fields)


newest = digest(names[-1])
first = names[-1]
for name in reversed(names[:-1]):
    if digest(name) != newest:
        break
    first = name

with open(sidecar, encoding="utf-8") as f:
    old = json.load(f)
new = {"sha256": newest, "bytes": os.path.getsize(os.path.join(data, first)),
       "filename": first}
print(f"{sidecar}\n  was {old.get('filename')}  {old.get('sha256', '')[:12]}"
      f"\n  now {first}  {newest[:12]}")
if write:
    with open(sidecar, "w", encoding="utf-8", newline="\n") as f:
        json.dump(new, f, indent=2)
    print("  written")
