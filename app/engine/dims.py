"""Автоматические производственные размеры.

Размер — семантический объект; конкретное смещение размерной линии
вычисляет отрисовщик (холст, PDF, DXF), поэтому все три вывода совпадают.

  {"t": "lin", "dir": "h"|"v", "p1": [x, y], "p2": [x, y], "side": "top"|"bottom"|"left"|"right",
   "level": 1.., "text": "250"}
  {"t": "dia", "c": [x, y], "r": r, "text": "Ø16"}
  {"t": "aligned", "p1": .., "p2": .., "text": .., "side": "out"}

Правила:
  * габарит ширины — снизу, локальные размеры по X — сверху (цепочка);
  * цепочка по Y — со стороны основной фурнитуры;
  * габарит высоты — с противоположной стороны (auto) либо слева/справа принудительно.
"""
from __future__ import annotations

import math


def fmt(v: float) -> str:
    r = round(v, 1)
    if abs(r - round(r)) < 1e-9:
        return str(int(round(r)))
    return f"{r:.1f}".replace(".", ",")


def _uniq(values: list[float], tol: float = 0.05) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or abs(v - out[-1]) > tol:
            out.append(v)
    return out


def glass_features(g: dict) -> list[tuple[float, float]]:
    """Характерные точки обработки (центры отверстий, границы вырезов)."""
    pts: list[tuple[float, float]] = []
    for h in g.get("holes", []):
        pts.append((h["c"][0], h["c"][1]))
    w, hh = g["w"], g["h"]
    for x0, y0, x1, y1 in g.get("cut_boxes", []):
        for x in (x0, x1):
            for y in (y0, y1):
                pts.append((min(max(x, 0), w), min(max(y, 0), hh)))
    for chain in g.get("inner", []):
        xs, ys = [], []
        for s in chain:
            if s["t"] == "line":
                xs += [s["p1"][0], s["p2"][0]]
                ys += [s["p1"][1], s["p2"][1]]
            else:
                xs += [s["c"][0] - s["r"], s["c"][0] + s["r"]]
                ys += [s["c"][1] - s["r"], s["c"][1] + s["r"]]
        if xs:
            pts += [(min(xs), min(ys)), (max(xs), max(ys))]
    return pts


def hardware_side(g: dict) -> str | None:
    feats = glass_features(g)
    if not feats:
        return None
    w = g["w"]
    right = sum(1 for x, _ in feats if x > w / 2)
    left = sum(1 for x, _ in feats if x < w / 2)
    return "right" if right >= left else "left"


def glass_dims(g: dict, dim_side: str = "auto") -> list[dict]:
    w, h = g["w"], g["h"]
    dims: list[dict] = []
    feats = glass_features(g)
    hw = hardware_side(g)
    if dim_side in ("left", "right"):
        overall_side = dim_side
    else:
        overall_side = "left" if hw == "right" else ("right" if hw == "left" else "left")

    # Цепочка по X сверху (от левого края)
    inner_x = [x for x, _ in feats if 0.05 < x < w - 0.05]
    if inner_x:
        xs = _uniq([0.0] + inner_x + [w])
        # точка выноски: сама особенность (самая верхняя с таким X), края — верхние углы
        def top_y_at(x):
            ys = [fy for fx, fy in feats if abs(fx - x) <= 0.05]
            return max(ys) if ys else h
        for a, b in zip(xs, xs[1:]):
            dims.append({"t": "lin", "dir": "h", "p1": [a, top_y_at(a) if 0 < a < w else h],
                         "p2": [b, top_y_at(b) if 0 < b < w else h], "side": "top", "level": 1, "text": fmt(b - a)})
    # Цепочки по Y — отдельно для особенностей у левой и у правой кромки
    side_feats = {
        "left": [(x, y) for x, y in feats if x <= w / 2 and 0.05 < y < h - 0.05],
        "right": [(x, y) for x, y in feats if x > w / 2 and 0.05 < y < h - 0.05],
    }
    for side, sf in side_feats.items():
        if not sf:
            continue
        ys = _uniq([0.0] + [y for _, y in sf] + [h])
        edge_x = w if side == "right" else 0.0

        def x_at(y, sf=sf, side=side, edge_x=edge_x):
            xs_ = [fx for fx, fy in sf if abs(fy - y) <= 0.05]
            if not xs_:
                return edge_x
            return max(xs_) if side == "right" else min(xs_)
        for a, b in zip(ys, ys[1:]):
            dims.append({"t": "lin", "dir": "v", "p1": [x_at(a) if 0 < a < h else edge_x, a],
                         "p2": [x_at(b) if 0 < b < h else edge_x, b], "side": side, "level": 1,
                         "text": fmt(b - a)})
    # Габариты
    dims.append({"t": "lin", "dir": "h", "p1": [0, 0], "p2": [w, 0], "side": "bottom", "level": 1,
                 "text": fmt(w), "overall": True})
    lvl = 2 if side_feats[overall_side] else 1
    ox = 0.0 if overall_side == "left" else w
    dims.append({"t": "lin", "dir": "v", "p1": [ox, 0], "p2": [ox, h], "side": overall_side, "level": lvl,
                 "text": fmt(h), "overall": True})
    # Диаметры
    seen = set()
    for hole in g.get("holes", []):
        key = (round(hole["c"][0], 2), round(hole["c"][1], 2), round(hole["r"], 3))
        if key in seen:
            continue
        seen.add(key)
        dims.append({"t": "dia", "c": hole["c"], "r": hole["r"], "text": "Ø" + fmt(hole["r"] * 2)})
    # Непрямоугольная форма — длины сторон
    if g.get("shape_type") not in (None, "rect"):
        pts = g["outline"]
        for i in range(len(pts)):
            p, q = pts[i], pts[(i + 1) % len(pts)]
            ln = math.hypot(q[0] - p[0], q[1] - p[1])
            if ln > 1:
                dims.append({"t": "aligned", "p1": list(p), "p2": list(q), "text": fmt(ln), "side": "out"})
    return dims


def product_dims(glasses: list[dict], planes: list[dict]) -> list[dict]:
    """Размеры общего вида (мировые координаты плоскости, со сдвигом dx)."""
    dims = []
    for pl in planes:
        gs = sorted([g for g in glasses if g["plane"] == pl["key"]], key=lambda g: g["x"])
        dx = pl["dx"]
        if not gs:
            continue
        for g in gs:
            dims.append({"t": "lin", "dir": "h", "p1": [g["x"] + dx, g["y"]], "p2": [g["x"] + g["w"] + dx, g["y"]],
                         "side": "bottom", "level": 1, "text": fmt(g["w"])})
            dims.append({"t": "lin", "dir": "v", "p1": [g["x"] + dx + g["w"] / 2, g["y"]],
                         "p2": [g["x"] + dx + g["w"] / 2, g["y"] + g["h"]], "side": "inside", "level": 0,
                         "text": fmt(g["h"])})
        dims.append({"t": "lin", "dir": "h", "p1": [dx, 0], "p2": [pl["L"] + dx, 0], "side": "bottom", "level": 2,
                     "text": fmt(pl["L"]), "overall": True})
        top = max(g["y"] + g["h"] for g in gs)
        dims.append({"t": "lin", "dir": "v", "p1": [dx, 0], "p2": [dx, top], "side": "left", "level": 1,
                     "text": fmt(top), "overall": True})
    return dims
