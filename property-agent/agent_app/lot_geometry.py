"""Pure geometry for a lot outline in feet (WA State Plane). No network, no AI.

- which sides of the lot face a street, an alley or a neighbour
- the lot width Pivotal uses (narrow end; on a corner lot, the narrower end)
- a grid of points covering the lot, for whole-lot map checks
"""

import math
from typing import NamedTuple

Point = tuple[float, float]
Ring = list[Point]

NEIGHBOUR_MAX_GAP_FT = 2.0   # shared boundary with the next parcel
ALLEY_MAX_GAP_FT = 30.0      # alleys are ~14-20 ft wide; streets are 40-66+
RAY_MAX_FT = 150.0           # nothing across within this distance: open land/water
SAME_SIDE_DEG = 20.0         # consecutive edges this close in direction are one side
END_AXIS_DEG = 35.0          # a side within this angle of the short axis is an "end"
OFFSET_FT = 1.5              # step outside the lot before looking across
MAX_GRID_POINTS = 200


class Side(NamedTuple):
    direction_deg: float   # 0-180, direction of the side line
    length_ft: float
    gap_ft: float | None   # distance to the parcel across; None = nothing within RAY_MAX_FT
    kind: str              # neighbour | alley | street | open
    gap_point: Point | None = None  # middle of the gap across this side (to look up what's in it)


# ---------- basic shapes ----------

def polygon_area(ring: Ring) -> float:
    pts = _open(ring)
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2


def point_in_ring(pt: Point, ring: Ring) -> bool:
    x, y = pt
    inside = False
    pts = _open(ring)
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def point_in_rings(pt: Point, rings: list[Ring]) -> bool:
    """Even-odd across all rings, so holes in a map feature are respected."""
    return sum(point_in_ring(pt, r) for r in rings) % 2 == 1


def convex_hull(points: list[Point]) -> list[Point]:
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def half(seq: list[Point]) -> list[Point]:
        out: list[Point] = []
        for p in seq:
            while len(out) >= 2 and cross(out[-2], out[-1], p) <= 0:
                out = out[:-1]
            out = [*out, p]
        return out

    return half(pts)[:-1] + half(list(reversed(pts)))[:-1]


def min_rectangle(points: list[Point]) -> tuple[float, float, float]:
    """Smallest rotated rectangle -> (short side ft, long side ft, short-side direction 0-180°)."""
    hull = convex_hull(points)
    best = (math.inf, 0.0, 0.0, 0.0)
    for i, a in enumerate(hull):
        b = hull[(i + 1) % len(hull)]
        angle = math.atan2(b[1] - a[1], b[0] - a[0])
        c, s = math.cos(-angle), math.sin(-angle)
        xs = [x * c - y * s for x, y in hull]
        ys = [x * s + y * c for x, y in hull]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if w * h < best[0]:
            best = (w * h, w, h, math.degrees(angle))
    _, w, h, angle = best
    short_dir = angle if w <= h else angle + 90
    return min(w, h), max(w, h), short_dir % 180


# ---------- sides of the lot ----------

def _open(ring: Ring) -> Ring:
    return ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else list(ring)


def _ray_distance(origin: Point, direction: Point, a: Point, b: Point) -> float | None:
    (ox, oy), (dx, dy) = origin, direction
    ex, ey = b[0] - a[0], b[1] - a[1]
    den = dx * ey - dy * ex
    if abs(den) < 1e-9:
        return None
    t = ((a[0] - ox) * ey - (a[1] - oy) * ex) / den
    u = ((a[0] - ox) * dy - (a[1] - oy) * dx) / den
    return t if t >= 0 and 0 <= u <= 1 else None


def classify_gap(gap_ft: float | None) -> str:
    if gap_ft is None:
        return "open"
    if gap_ft <= NEIGHBOUR_MAX_GAP_FT:
        return "neighbour"
    if gap_ft <= ALLEY_MAX_GAP_FT:
        return "alley"
    return "street"


def _outward_normal(a: Point, b: Point, lot: Ring) -> Point:
    length = math.dist(a, b)
    nx, ny = (b[1] - a[1]) / length, -(b[0] - a[0]) / length
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return (-nx, -ny) if point_in_ring((mid[0] + nx, mid[1] + ny), lot) else (nx, ny)


def _gap_point(a: Point, b: Point, lot: Ring, gap_ft: float | None) -> Point | None:
    if gap_ft is None:
        return None
    nx, ny = _outward_normal(a, b, lot)
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return (round(mid[0] + nx * gap_ft / 2, 1), round(mid[1] + ny * gap_ft / 2, 1))


def _gap_across(a: Point, b: Point, lot: Ring, neighbours: list[Ring]) -> float | None:
    nx, ny = _outward_normal(a, b, lot)
    gaps: list[float] = []
    for frac in (0.25, 0.5, 0.75):
        p = (a[0] + (b[0] - a[0]) * frac + nx * OFFSET_FT, a[1] + (b[1] - a[1]) * frac + ny * OFFSET_FT)
        if any(point_in_ring(p, r) for r in neighbours):
            gaps = [*gaps, 0.0]
            continue
        hits = [
            t for r in neighbours for s, e in zip(_open(r), _open(r)[1:] + _open(r)[:1])
            if (t := _ray_distance(p, (nx, ny), s, e)) is not None and t <= RAY_MAX_FT
        ]
        if hits:
            gaps = [*gaps, min(hits) + OFFSET_FT]
    if not gaps:
        return None
    return round(sorted(gaps)[len(gaps) // 2], 1)  # median of the samples


def _direction(a: Point, b: Point) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180


def _angle_diff(d1: float, d2: float) -> float:
    d = abs(d1 - d2) % 180
    return min(d, 180 - d)


def lot_sides(lot: Ring, neighbours: list[Ring]) -> list[Side]:
    """Merge the lot's edges into straight sides and say what lies across each one."""
    pts = _open(lot)
    edges = [(a, b) for a, b in zip(pts, pts[1:] + pts[:1]) if math.dist(a, b) >= 1.0]
    groups: list[list[tuple[Point, Point]]] = []
    for edge in edges:
        if groups and _angle_diff(_direction(*groups[-1][-1]), _direction(*edge)) < SAME_SIDE_DEG:
            groups = [*groups[:-1], [*groups[-1], edge]]
        else:
            groups = [*groups, [edge]]
    if len(groups) > 1 and _angle_diff(_direction(*groups[-1][-1]), _direction(*groups[0][0])) < SAME_SIDE_DEG:
        groups = [groups[-1] + groups[0], *groups[1:-1]]
    sides = []
    for group in groups:
        length = sum(math.dist(a, b) for a, b in group)
        longest = max(group, key=lambda e: math.dist(*e))
        gap = _gap_across(*longest, lot, neighbours)
        sides = [*sides, Side(round(_direction(group[0][0], group[-1][1]), 1), round(length, 1), gap,
                              classify_gap(gap), _gap_point(*longest, lot, gap))]
    return sides


# ---------- width ----------

def lot_width(sides: list[Side], short_dir_deg: float, short_side_ft: float) -> dict:
    """Pivotal's width: the lot's narrow end. Corner lot: the narrower end (front doesn't matter)."""
    ends = [s for s in sides if _angle_diff(s.direction_deg, short_dir_deg) <= END_AXIS_DEG]
    street_sides = [s for s in sides if s.kind == "street"]
    corner = len(street_sides) >= 2
    street_ends = [s for s in ends if s.kind == "street"]
    # Sides facing the street. With no street seen, "open" sides count (e.g. a cul-de-sac bulb,
    # where nothing lies across within RAY_MAX_FT).
    frontage = street_sides or [s for s in sides if s.kind == "open"]
    if not corner and not street_ends and len(frontage) == 1 and \
            frontage[0].length_ft < min((s.length_ft for s in ends), default=math.inf):
        return {"width_ft": frontage[0].length_ft, "basis": "irregular lot: the street frontage, which is "
                "narrower than either end (e.g. a pie lot on a curve or cul-de-sac)", "needs_check": True,
                "corner_lot": False}
    if len(ends) < 2:
        return {"width_ft": round(short_side_ft, 1), "basis": "irregular shape: no clear ends, used the "
                "narrow side of the bounding rectangle", "needs_check": True, "corner_lot": corner}
    if corner:
        narrow = min(ends, key=lambda s: s.length_ft)
        return {"width_ft": narrow.length_ft, "basis": "corner lot: the narrower end of the lot",
                "needs_check": False, "corner_lot": True}
    if street_ends:
        front = street_ends[0]
        return {"width_ft": front.length_ft, "basis": "the end of the lot that faces the street",
                "needs_check": False, "corner_lot": False}
    narrow = min(ends, key=lambda s: s.length_ft)
    return {"width_ft": narrow.length_ft, "basis": "no street on either end (street on a long side, "
            "or a flag/landlocked lot): used the narrower end", "needs_check": True, "corner_lot": False}


# ---------- whole-lot sampling ----------

def grid_points(lot: Ring, inset_ft: float = 2.0) -> list[Point]:
    """Evenly spaced points inside the lot (kept off the boundary) for whole-lot map checks."""
    pts = _open(lot)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    spacing = max(5.0, math.sqrt(polygon_area(lot) / MAX_GRID_POINTS))
    edges = list(zip(pts, pts[1:] + pts[:1]))
    out: list[Point] = []
    y = min(ys) + spacing / 2
    while y < max(ys):
        x = min(xs) + spacing / 2
        while x < max(xs):
            if point_in_ring((x, y), lot) and min(_seg_dist((x, y), a, b) for a, b in edges) >= inset_ft:
                out = [*out, (round(x, 1), round(y, 1))]
            x += spacing
        y += spacing
    if not out:
        out = [(sum(xs) / len(xs), sum(ys) / len(ys))]
    return out[:MAX_GRID_POINTS]


def _seg_dist(p: Point, a: Point, b: Point) -> float:
    ax, ay = b[0] - a[0], b[1] - a[1]
    length2 = ax * ax + ay * ay
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / length2))
    return math.dist(p, (a[0] + t * ax, a[1] + t * ay))


def distance_to_lot(points: list[Point], lot: Ring) -> float:
    """Shortest distance from any of `points` to the lot (0 if a point is inside)."""
    pts = _open(lot)
    edges = list(zip(pts, pts[1:] + pts[:1]))
    if not points:
        return math.inf
    return min(0.0 if point_in_ring(p, lot) else min(_seg_dist(p, a, b) for a, b in edges) for p in points)
