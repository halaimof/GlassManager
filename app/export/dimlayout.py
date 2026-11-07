"""Раскладка размеров в примитивы рисования (общая для PDF и DXF).

Входные размеры — семантические (engine/dims.py). Здесь выбирается
положение размерных линий: смещение S и высота текста th задаются
в единицах модели (мм), поэтому PDF и DXF совпадают по смыслу.

Выход: список операций
  ("line", (x1, y1), (x2, y2))
  ("arrow", (tip_x, tip_y), (dir_x, dir_y))
  ("text", (x, y), text, angle_deg, height, align)   align: "center"|"left"
"""
from __future__ import annotations

import math


def layout_dims(dims: list[dict], bbox: tuple[float, float, float, float], S: float, th: float) -> list[tuple]:
    minx, miny, maxx, maxy = bbox
    ops: list[tuple] = []
    gap = S * 0.12
    over = S * 0.2
    small_run: dict[tuple, int] = {}
    for d in dims:
        t = d["t"]
        if t == "lin":
            key = (d["dir"], d.get("side"), d.get("level", 1))
            (x1, y1), (x2, y2) = d["p1"], d["p2"]
            side, lvl = d.get("side", "bottom"), d.get("level", 1)
            if d["dir"] == "h":
                if side == "top":
                    yl = maxy + lvl * S
                    sgn = 1
                elif side == "inside":
                    yl = y1
                    sgn = 0
                else:
                    yl = miny - lvl * S
                    sgn = -1
                if abs(x2 - x1) < 1e-6:
                    continue
                if sgn:
                    ops.append(("line", (x1, y1 + sgn * gap), (x1, yl + sgn * over)))
                    ops.append(("line", (x2, y2 + sgn * gap), (x2, yl + sgn * over)))
                ops.append(("line", (x1, yl), (x2, yl)))
                dirx = 1 if x2 > x1 else -1
                ops.append(("arrow", (x1, yl), (-dirx, 0)))
                ops.append(("arrow", (x2, yl), (dirx, 0)))
                tw = len(d["text"]) * th * 0.62
                mx, ty = (x1 + x2) / 2, yl + th * 0.35
                if abs(x2 - x1) < tw + th:
                    # мелкий размер: текст поочерёдно с другой стороны линии / вынесен за конец
                    n = small_run.get(key, 0)
                    small_run[key] = n + 1
                    if n % 2 == 0:
                        ty = yl - th * 1.25
                    else:
                        mx = max(x1, x2) + tw / 2 + th * 0.4
                else:
                    small_run[key] = 0
                ops.append(("text", (mx, ty), d["text"], 0, th, "center"))
            else:
                if side == "right":
                    xl = maxx + lvl * S
                    sgn = 1
                elif side == "inside":
                    xl = x1
                    sgn = 0
                else:
                    xl = minx - lvl * S
                    sgn = -1
                if abs(y2 - y1) < 1e-6:
                    continue
                if sgn:
                    ops.append(("line", (x1 + sgn * gap, y1), (xl + sgn * over, y1)))
                    ops.append(("line", (x2 + sgn * gap, y2), (xl + sgn * over, y2)))
                ops.append(("line", (xl, y1), (xl, y2)))
                diry = 1 if y2 > y1 else -1
                ops.append(("arrow", (xl, y1), (0, -diry)))
                ops.append(("arrow", (xl, y2), (0, diry)))
                tw = len(d["text"]) * th * 0.62
                my, tx = (y1 + y2) / 2, xl - th * 0.35
                if abs(y2 - y1) < tw + th:
                    n = small_run.get(key, 0)
                    small_run[key] = n + 1
                    if n % 2 == 0:
                        tx = xl + th * 1.25
                    else:
                        my = max(y1, y2) + tw / 2 + th * 0.4
                else:
                    small_run[key] = 0
                ops.append(("text", (tx, my), d["text"], 90, th, "center"))
        elif t == "dia":
            (cx, cy), r = d["c"], d["r"]
            a = math.radians(45)
            p0 = (cx + r * math.cos(a), cy + r * math.sin(a))
            p1 = (cx + (r + S * 0.45) * math.cos(a), cy + (r + S * 0.45) * math.sin(a))
            tw = len(d["text"]) * th * 0.62
            p2 = (p1[0] + tw + th * 0.3, p1[1])
            ops.append(("line", p0, p1))
            ops.append(("line", p1, p2))
            ops.append(("arrow", p0, (-math.cos(a), -math.sin(a))))
            ops.append(("text", (p1[0] + th * 0.15, p1[1] + th * 0.3), d["text"], 0, th, "left"))
        elif t == "aligned":
            (x1, y1), (x2, y2) = d["p1"], d["p2"]
            ln = math.hypot(x2 - x1, y2 - y1)
            if ln < 1e-6:
                continue
            ux, uy = (x2 - x1) / ln, (y2 - y1) / ln
            nx, ny = uy, -ux  # наружу для CCW-контура
            ang = math.degrees(math.atan2(uy, ux))
            if ang > 90 or ang < -90:
                ang += 180
            mx, my = (x1 + x2) / 2 + nx * th * 1.4, (y1 + y2) / 2 + ny * th * 1.4
            ops.append(("text", (mx, my), d["text"], ang, th * 0.9, "center"))
    return ops


def dims_extent(bbox, dims, S) -> tuple[float, float, float, float]:
    """Габарит рисунка с учётом размерных линий (для масштаба листа)."""
    minx, miny, maxx, maxy = bbox
    lv = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    for d in dims:
        if d["t"] == "lin" and d.get("side") in lv:
            lv[d["side"]] = max(lv[d["side"]], d.get("level", 1))
    return (minx - (lv["left"] + 0.8) * S, miny - (lv["bottom"] + 0.8) * S,
            maxx + (lv["right"] + 0.8) * S, maxy + (lv["top"] + 0.8) * S)
