"""Lot geometry: street sides, Pivotal width, whole-lot sampling. Synthetic shapes in feet."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_app"))

import lot_geometry as geo  # noqa: E402


def rect(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x0, y1), (x1, y1), (x1, y0), (x0, y0)]  # clockwise, closed, like ArcGIS


def measure(lot, neighbours):
    sides = geo.lot_sides(lot, neighbours)
    short, _, short_dir = geo.min_rectangle(lot)
    return sides, geo.lot_width(sides, short_dir, short)


def test_classify_gap_thresholds():
    assert geo.classify_gap(0.0) == "neighbour"
    assert geo.classify_gap(16.0) == "alley"
    assert geo.classify_gap(60.0) == "street"
    assert geo.classify_gap(None) == "open"


def test_interior_lot_width_is_the_street_end():
    lot = rect(0, 0, 50, 100)
    neighbours = [rect(50, 0, 100, 100), rect(-50, 0, 0, 100), rect(0, 100, 50, 200), rect(-50, -160, 100, -60)]
    sides, width = measure(lot, neighbours)
    assert sorted(s.kind for s in sides) == ["neighbour", "neighbour", "neighbour", "street"]
    assert width["width_ft"] == pytest.approx(50.0)
    assert width["corner_lot"] is False
    assert width["needs_check"] is False


def test_corner_lot_uses_narrower_end():
    # trapezoid: west end 64 ft, east end 52 ft; streets south and west, alley east, neighbour north
    lot = [(0, 0), (0, 64), (100, 64), (100, 12), (0, 0)]
    neighbours = [rect(0, 64, 100, 164), rect(-200, -200, -60, 300), rect(-200, -200, 300, -66), rect(116, -100, 300, 300)]
    sides, width = measure(lot, neighbours)
    kinds = {s.kind for s in sides}
    assert {"street", "alley", "neighbour"} <= kinds
    assert width["corner_lot"] is True
    assert width["width_ft"] == pytest.approx(52.0, abs=0.5)


def test_gap_point_is_the_middle_of_the_strip_across():
    # 16 ft strip east of the lot, neighbour beyond it
    lot = rect(0, 0, 50, 100)
    sides = geo.lot_sides(lot, [rect(66, -50, 200, 150)])
    east = next(s for s in sides if s.kind == "alley")
    assert east.gap_ft == pytest.approx(16.0, abs=0.2)
    assert east.gap_point == pytest.approx((58.0, 50.0), abs=0.5)
    assert all(s.gap_point is None for s in sides if s.kind == "open")


def test_street_on_long_side_is_flagged():
    lot = rect(0, 0, 50, 100)
    neighbours = [rect(0, 100, 50, 200), rect(0, -100, 50, 0), rect(50, 0, 100, 100), rect(-160, -100, -60, 200)]
    _, width = measure(lot, neighbours)
    assert width["needs_check"] is True
    assert width["width_ft"] == pytest.approx(50.0)


def test_nothing_across_is_open():
    sides, _ = measure(rect(0, 0, 50, 100), [])
    assert {s.kind for s in sides} == {"open"}


def test_collinear_edges_merge_into_one_side():
    lot = [(0, 0), (0, 100), (50, 100), (50, 40), (50, 0), (0, 0)]  # east side split in two
    sides = geo.lot_sides(lot, [])
    assert len(sides) == 4
    assert max(s.length_ft for s in sides) == pytest.approx(100.0)


def test_min_rectangle_of_rotated_lot():
    import math
    a = math.radians(30)
    pts = [(x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)) for x, y in rect(0, 0, 40, 90)]
    short, long_, _ = geo.min_rectangle(pts)
    assert short == pytest.approx(40, abs=0.01)
    assert long_ == pytest.approx(90, abs=0.01)


def test_grid_points_cover_lot_and_stay_off_edges():
    lot = rect(0, 0, 50, 100)
    grid = geo.grid_points(lot, inset_ft=2.0)
    assert 50 <= len(grid) <= geo.MAX_GRID_POINTS
    assert all(2 <= x <= 48 and 2 <= y <= 98 for x, y in grid)
    assert min(x for x, _ in grid) < 10 and max(x for x, _ in grid) > 40  # spread across, not just the centre


def test_point_in_rings_respects_holes():
    outer, hole = rect(0, 0, 100, 100), rect(40, 40, 60, 60)
    assert geo.point_in_rings((10, 10), [outer, hole])
    assert not geo.point_in_rings((50, 50), [outer, hole])
    assert not geo.point_in_rings((150, 50), [outer, hole])


def test_distance_to_lot():
    lot = rect(0, 0, 50, 100)
    assert geo.distance_to_lot([(25, 50)], lot) == 0.0
    assert geo.distance_to_lot([(80, 50), (60, 50)], lot) == pytest.approx(10.0)
    assert geo.distance_to_lot([], lot) == float("inf")


def test_pie_lot_on_a_cul_de_sac_uses_the_street_frontage():
    # wedge: 40 ft frontage on the bulb (nothing across within 150 ft), 128 ft rear, ~100 ft sides
    lot = [(44, 0), (84, 0), (128, 90), (0, 90), (44, 0)]
    neighbours = [rect(-20, 90, 150, 200), [(84, 0), (200, -10), (200, 120), (128, 90), (84, 0)],
                  [(44, 0), (0, 90), (-80, 120), (-80, -10), (44, 0)]]
    sides, width = measure(lot, neighbours)
    assert width["width_ft"] == pytest.approx(40.0)
    assert width["needs_check"] is True and "frontage" in width["basis"]
