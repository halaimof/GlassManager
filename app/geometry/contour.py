"""Построение реального контура стекла с учётом вырезов.

Вырез, пересекающий кромку, вычитается из контура (исходная линия кромки в
месте выреза исчезает). Внутренние отверстия и контуры контур не меняют.
После булевой операции дуги восстанавливаются (bulge), чтобы DXF/PDF
сохраняли настоящие радиусы, а не ломаную.
"""
from __future__ import annotations

import math

from shapely.geometry import MultiPolygon, Point as SPoint, Polygon
from shapely.geometry.polygon import orient

from .prims import chain_closed, chain_points, chain_segments, discretize, dist, norm_angle, arc_sweep

ON_ARC_TOL = 0.01
EDGE_TOL = 0.5


def _outward_normal_at(poly: Polygon, p) -> tuple[float, float]:
    coords = list(poly.exterior.coords)
    best, bn = 1e18, (0.0, 0.0)
    for a, b in zip(coords, coords[1:]):
        seg_len = dist(a, b)
        if seg_len < 1e-12:
            continue
        ex, ey = (b[0] - a[0]) / seg_len, (b[1] - a[1]) / seg_len
        t = max(0.0, min(seg_len, (p[0] - a[0]) * ex + (p[1] - a[1]) * ey))
        q = (a[0] + ex * t, a[1] + ey * t)
        d = dist(p, q)
        if d < best:
            best, bn = d, (ey, -ex)  # CCW → наружу справа от направления
    return bn


def _on_arc(p, arc: dict, tol: float = ON_ARC_TOL) -> bool:
    c, r = arc["c"], arc["r"]
    if abs(dist(p, c) - r) > tol:
        return False
    if arc["t"] == "circle":
        return True
    ang = norm_angle(math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])))
    sw = arc_sweep(arc["a0"], arc["a1"])
    rel = norm_angle(ang - arc["a0"])
    tol_deg = math.degrees(tol / max(r, 1e-9)) + 1e-6
    return rel <= sw + tol_deg or rel >= 360 - tol_deg


def _recover_arcs(coords: list, arcs: list[dict]) -> list[list[float]]:
    n = len(coords)
    if not arcs or n < 3:
        return [[x, y, 0.0] for x, y in coords]
    seg_arc: list[int | None] = []
    for i in range(n):
        p, q = coords[i], coords[(i + 1) % n]
        m = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        k_found = None
        for k, a in enumerate(arcs):
            if _on_arc(p, a) and _on_arc(q, a):
                # середина хорды должна лежать почти на дуге (отсекаем длинные прямые хорды)
                if abs(dist(m, a["c"]) - a["r"]) <= ON_ARC_TOL:
                    k_found = k
                    break
        seg_arc.append(k_found)
    start = next((i for i in range(n) if seg_arc[i] != seg_arc[i - 1]), None)
    if start is None:
        return [[x, y, 0.0] for x, y in coords]
    out: list[list[float]] = []
    i = 0
    while i < n:
        idx = (start + i) % n
        k = seg_arc[idx]
        if k is None:
            out.append([coords[idx][0], coords[idx][1], 0.0])
            i += 1
            continue
        c = arcs[k]["c"]
        total = 0.0
        j = i
        while j < n and seg_arc[(start + j) % n] == k:
            p = coords[(start + j) % n]
            q = coords[(start + j + 1) % n]
            v1 = (p[0] - c[0], p[1] - c[1])
            v2 = (q[0] - c[0], q[1] - c[1])
            total += math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1])
            j += 1
        out.append([coords[idx][0], coords[idx][1], math.tan(total / 4)])
        i = j
    return out


def _clean(v: float) -> float:
    r = round(v, 5)
    return 0.0 if r == 0 else r


def build_contour(outline: list[tuple[float, float]], op_segs: list[dict]) -> dict:
    """outline — вершины многоугольника стекла (CCW), op_segs — сегменты обработки
    в локальных координатах стекла. Возвращает контур с bulge, отверстия,
    внутренние контуры, области вырезов и предупреждения."""
    glass = orient(Polygon(outline), 1.0)
    inner_test = glass.buffer(-1e-6)
    edge_test = glass.buffer(-EDGE_TOL)
    holes: list[dict] = []
    inner: list[list[dict]] = []
    cut_polys: list[Polygon] = []
    cut_arcs: list[dict] = []
    open_inner: list[list[dict]] = []
    warnings: list[str] = []

    for c in (s for s in op_segs if s["t"] == "circle"):
        cp = Polygon(discretize(c))
        if inner_test.contains(cp):
            holes.append({"c": [c["c"][0], c["c"][1]], "r": c["r"]})
        elif glass.intersects(cp):
            cut_polys.append(cp)
            cut_arcs.append(c)
        else:
            warnings.append(f"Отверстие Ø{c['r'] * 2:g} находится вне стекла")

    for chain in chain_segments(op_segs):
        pts = chain_points(chain)
        if len(pts) < 2:
            continue
        if chain_closed(chain):
            poly = Polygon(pts).buffer(0)
            if poly.is_empty:
                continue
            if inner_test.contains(poly):
                inner.append(chain)
            elif glass.intersects(poly):
                cut_polys.append(poly)
                cut_arcs += [s for s in chain if s["t"] == "arc"]
            else:
                warnings.append("Контур обработки находится вне стекла")
            continue
        a, b = pts[0], pts[-1]
        a_ok = not edge_test.contains(SPoint(a))
        b_ok = not edge_test.contains(SPoint(b))
        if a_ok and b_ok:
            na = _outward_normal_at(glass, a)
            nb = _outward_normal_at(glass, b)
            ext = 2.0
            ring = pts + [(b[0] + nb[0] * ext, b[1] + nb[1] * ext), (a[0] + na[0] * ext, a[1] + na[1] * ext)]
            poly = Polygon(ring).buffer(0)
            if not poly.is_empty and glass.intersects(poly):
                cut_polys.append(poly)
                cut_arcs += [s for s in chain if s["t"] == "arc"]
                continue
        open_inner.append(chain)
        warnings.append("Незамкнутый контур обработки не касается кромки — выведен как линия")

    result = glass
    for cp in cut_polys:
        result = result.difference(cp)
    if isinstance(result, MultiPolygon):
        parts = sorted(result.geoms, key=lambda g: g.area, reverse=True)
        warnings.append("Вырез разделяет стекло на части — используется наибольшая")
        result = parts[0]
    if result.is_empty:
        raise ValueError("После вырезов от стекла ничего не осталось")
    result = orient(result, 1.0)
    ext = [(x, y) for x, y in list(result.exterior.coords)[:-1]]
    contour = _recover_arcs(ext, cut_arcs)
    contour = [[_clean(x), _clean(y), round(b, 9)] for x, y, b in contour]
    extra_rings = []
    for ring in result.interiors:
        extra_rings.append([[_clean(x), _clean(y)] for x, y in list(ring.coords)[:-1]])

    cut_boxes = []
    for cp in cut_polys:
        inter = cp.intersection(glass)
        if not inter.is_empty:
            cut_boxes.append([round(v, 4) for v in inter.bounds])

    def strip(chain):
        return [{k: v for k, v in s.items() if k != "rev"} for s in chain]

    return {
        "contour": contour,
        "holes": holes,
        "inner": [strip(ch) for ch in inner],
        "open": [strip(ch) for ch in open_inner],
        "rings": extra_rings,
        "cut_boxes": cut_boxes,
        "area": result.area,
        "warnings": warnings,
    }


def contour_length_segments(contour: list[list[float]]):
    """Сегменты контура: прямые и дуги (для отрисовки)."""
    n = len(contour)
    for i in range(n):
        x1, y1, b = contour[i]
        x2, y2, _ = contour[(i + 1) % n]
        yield (x1, y1), (x2, y2), b
