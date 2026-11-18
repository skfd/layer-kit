"""The geometry helpers the matchers share."""

from layerkit import geom


def p(lat, lon):
    return {"lat": lat, "lon": lon}


def way(*pts, role="outer"):
    return {"type": "way", "role": role, "geometry": [p(*x) for x in pts]}


def test_dist_is_metres():
    # One thousandth of a degree of latitude is about 111 m anywhere.
    assert abs(geom.dist(p(43.5, -80.2), p(43.501, -80.2)) - 111.2) < 0.5
    assert geom.dist(p(43.5, -80.2), p(43.5, -80.2)) == 0


def test_bbox_overlap():
    assert geom.bbox_overlap((0, 0, 2, 2), (1, 1, 3, 3))
    assert geom.bbox_overlap((0, 0, 1, 1), (1, 1, 2, 2))  # touching counts
    assert not geom.bbox_overlap((0, 0, 1, 1), (2, 2, 3, 3))


def test_point_in_ring():
    square = [(0, 0), (4, 0), (4, 4), (0, 4)]
    assert geom.point_in_ring((2, 2), square)
    assert not geom.point_in_ring((5, 2), square)


def test_outer_ways_are_stitched_end_to_end_in_either_direction():
    rel = {"members": [
        way((0, 0), (0, 1), (1, 1)),
        way((0, 0), (1, 0), (1, 1)),          # runs the other way round
        way((9, 9), (9, 8), role="inner"),    # not an outer: ignored
    ]}
    loops = geom.relation_outer_loops(rel)
    assert len(loops) == 1
    assert loops[0][0] == loops[0][-1]
    assert len(loops[0]) == 5


def test_two_separate_outers_are_two_loops():
    rel = {"members": [
        way((0, 0), (0, 1), (1, 1), (0, 0)),
        way((5, 5), (5, 6), (6, 6), (5, 5)),
    ]}
    assert len(geom.relation_outer_loops(rel)) == 2


def test_an_unclosed_outer_is_returned_as_it_stands():
    rel = {"members": [way((0, 0), (0, 1))]}
    assert geom.relation_outer_loops(rel) == [[p(0, 0), p(0, 1)]]
