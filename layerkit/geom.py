"""Small geometry helpers the matchers share. No GIS dependency.

Only what was byte-identical across the layers lives here. How a layer pairs
City features with OSM ones is its own business and stays in its compare.py.
"""

import math


def dist(a, b):
    """Metres between two {lat, lon}; equirectangular, fine at city scale."""
    lat0 = math.radians((a["lat"] + b["lat"]) / 2)
    dx = math.radians(b["lon"] - a["lon"]) * math.cos(lat0)
    dy = math.radians(b["lat"] - a["lat"])
    return 6371008.8 * math.hypot(dx, dy)


def bbox_overlap(a, b):
    """Whether two (minx, miny, maxx, maxy) boxes touch or overlap."""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def point_in_ring(pt, pts):
    """Ray-casting point-in-polygon test."""
    x, y = pt
    n = len(pts)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            xint = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside


def relation_outer_loops(rel):
    """Stitch a multipolygon relation's outer member ways into closed loops.

    OSM splits a long outer boundary across several ways; only joined
    end-to-end do they form the ring(s). Without this, each open segment looks
    like a degenerate sliver. Returns a list of point lists (Overpass geometry
    dicts, {lat, lon}), one per assembled loop.
    """
    segs = [m["geometry"] for m in rel.get("members", [])
            if m.get("type") == "way" and m.get("role") in ("outer", "")
            and m.get("geometry")]
    loops = []
    used = [False] * len(segs)
    for i in range(len(segs)):
        if used[i]:
            continue
        used[i] = True
        loop = list(segs[i])
        grew = True
        while grew and _pt(loop[0]) != _pt(loop[-1]):
            grew = False
            for j, other in enumerate(segs):
                if used[j]:
                    continue
                if _pt(other[0]) == _pt(loop[-1]):
                    loop.extend(other[1:])
                elif _pt(other[-1]) == _pt(loop[-1]):
                    loop.extend(reversed(other[:-1]))
                elif _pt(other[-1]) == _pt(loop[0]):
                    loop[:0] = other[:-1]
                elif _pt(other[0]) == _pt(loop[0]):
                    loop[:0] = list(reversed(other[1:]))
                else:
                    continue
                used[j] = grew = True
        loops.append(loop)
    return loops


def _pt(p):
    return (p["lat"], p["lon"])
