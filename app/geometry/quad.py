"""Четырёхугольник по длинам сторон и одному известному углу.

Система координат: мм, ось Y вверх, вершины возвращаются против часовой
стрелки: BL, BR, TR, TL; bbox начинается в (0, 0).
"""
from __future__ import annotations

import math

Point = tuple[float, float]


class GeometryError(ValueError):
    pass


def _circle_intersections(c1: Point, r1: float, c2: Point, r2: float) -> list[Point]:
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    d = math.hypot(dx, dy)
    if d < 1e-12:
        return []
    if d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h2 = r1 * r1 - a * a
    h = math.sqrt(max(h2, 0.0))
    mx, my = c1[0] + a * dx / d, c1[1] + a * dy / d
    return [(mx + h * dy / d, my - h * dx / d), (mx - h * dy / d, my + h * dx / d)]


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _is_convex_ccw(pts: list[Point]) -> bool:
    n = len(pts)
    return all(_cross(pts[i], pts[(i + 1) % n], pts[(i + 2) % n]) > 1e-9 for i in range(n))


def _solve_tl(top: float, right: float, bottom: float, left: float, angle_deg: float) -> list[Point]:
    """Известен угол в верхнем левом углу. Возвращает BL, BR, TR, TL."""
    a = math.radians(angle_deg)
    tl = (0.0, 0.0)
    tr = (top, 0.0)
    # левая сторона уходит вниз от TL под углом a к верхней стороне
    bl = (left * math.cos(-a), left * math.sin(-a))
    candidates = _circle_intersections(tr, right, bl, bottom)
    for br in candidates:
        pts = [bl, br, tr, tl]
        if _is_convex_ccw(pts):
            return pts
    raise GeometryError(
        "Такой четырёхугольник построить невозможно: проверьте длины сторон и угол"
    )


def solve_quad(
    top: float,
    right: float,
    bottom: float,
    left: float,
    corner: str = "tl",
    angle: float = 90.0,
) -> list[Point]:
    """corner: tl | tr | bl | br — угол, значение которого известно (по умолчанию 90°)."""
    for name, v in (("верх", top), ("право", right), ("низ", bottom), ("лево", left)):
        if v is None or v <= 0:
            raise GeometryError(f"Сторона «{name}» должна быть больше нуля")
    if not (0 < angle < 180):
        raise GeometryError("Угол должен быть в диапазоне 0…180°")
    mirror_x = corner in ("tr", "br")
    mirror_y = corner in ("bl", "br")
    t, r, b, l = top, right, bottom, left
    if mirror_x:
        l, r = r, l
    if mirror_y:
        t, b = b, t
    bl, br, tr, tl = _solve_tl(t, r, b, l, angle)
    pts = {"bl": bl, "br": br, "tr": tr, "tl": tl}
    if mirror_x:
        pts = {k: (-p[0], p[1]) for k, p in pts.items()}
        pts = {"bl": pts["br"], "br": pts["bl"], "tr": pts["tl"], "tl": pts["tr"]}
    if mirror_y:
        pts = {k: (p[0], -p[1]) for k, p in pts.items()}
        pts = {"bl": pts["tl"], "br": pts["tr"], "tr": pts["br"], "tl": pts["bl"]}
    ordered = [pts["bl"], pts["br"], pts["tr"], pts["tl"]]
    minx = min(p[0] for p in ordered)
    miny = min(p[1] for p in ordered)
    return [(p[0] - minx, p[1] - miny) for p in ordered]


def polygon_area(pts: list[Point]) -> float:
    return 0.5 * sum(
        pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
        for i in range(len(pts))
    )
