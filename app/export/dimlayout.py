"""Раскладка размеров в примитивы рисования (общая логика для PDF, DXF и холста — см. static/js/draw.js).

Правила:
  * все размеры — снаружи изделия: выносные линии начинаются от габарита стекла;
  * размеры не накладываются: тексты одной цепочки, которые не помещаются, разносятся
    по рядам, а следующий уровень размеров отодвигается на высоту этих рядов;
  * на коротких размерах стрелки выносятся наружу;
  * диаметры отверстий — выноской за ближайший край стекла, подписи не перекрываются.

Входные размеры — семантические (engine/dims.py). Все величины в единицах модели (мм):
  S  — расстояние от изделия до первой размерной линии,
  th — высота текста, al — длина стрелки.

Выход: список операций
  ("line", (x1, y1), (x2, y2))
  ("arrow", (tip_x, tip_y), (dir_x, dir_y))         стрелка смотрит в сторону dir
  ("text", (x, y), text, angle_deg, height, align)   align: center | left | right; (x, y) — базовая линия
"""
from __future__ import annotations

import math
from collections import defaultdict

SIDES = ("top", "bottom", "left", "right")


def text_w(text: str, th: float) -> float:
    return len(text) * th * 0.62


def _axis(d: dict) -> tuple[float, float]:
    """Координаты концов размера вдоль его оси."""
    if d["dir"] == "h":
        a, b = d["p1"][0], d["p2"][0]
    else:
        a, b = d["p1"][1], d["p2"][1]
    return (a, b) if a <= b else (b, a)


def layout_dims(dims: list[dict], bbox: tuple[float, float, float, float], S: float, th: float,
                al: float | None = None) -> list[tuple]:
    minx, miny, maxx, maxy = bbox
    al = al or th * 0.8
    gap = th * 0.35          # от размерной линии до текста
    ext_gap = th * 0.4       # от изделия до начала выносной линии
    over = th * 0.6          # выносная линия за размерную
    row_h = th * 1.35        # шаг рядов текста
    ops: list[tuple] = []

    lins = [d for d in dims if d["t"] == "lin" and d.get("side") in SIDES and abs(_axis(d)[1] - _axis(d)[0]) > 1e-6]
    dias = [d for d in dims if d["t"] == "dia"]

    # --- выноски диаметров: сторона и место под подписи
    pad = {s: 0.0 for s in SIDES}
    midx = (minx + maxx) / 2
    dia_side: dict[str, list[dict]] = {"left": [], "right": []}
    for d in dias:
        side = "left" if d["c"][0] < midx else "right"
        dia_side[side].append(d)
        pad[side] = max(pad[side], th * 0.9 + text_w(d["text"], th) + th * 0.6)

    # --- ряды текста в каждой цепочке (сторона + уровень)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for d in lins:
        groups[(d["side"], d.get("level", 1))].append(d)
    row_of: dict[int, int] = {}
    rows: dict[tuple, int] = {}
    for key, ds in groups.items():
        placed: list[list[tuple[float, float]]] = []
        for d in sorted(ds, key=lambda x: sum(_axis(x)) / 2):
            a, b = _axis(d)
            c, w = (a + b) / 2, text_w(d["text"], th)
            iv = (c - w / 2 - th * 0.25, c + w / 2 + th * 0.25)
            r = 0
            while True:
                if r == len(placed):
                    placed.append([])
                if all(iv[1] <= x0 or iv[0] >= x1 for x0, x1 in placed[r]):
                    placed[r].append(iv)
                    break
                r += 1
            row_of[id(d)] = r
        rows[key] = len(placed)

    # --- расстояние от изделия до каждого уровня
    dist: dict[tuple, float] = {}
    for side in SIDES:
        cur = pad[side] + S
        for lv in sorted(lv for (sd, lv) in rows if sd == side):
            dist[(side, lv)] = cur
            cur += rows[(side, lv)] * row_h + S * 0.55

    # --- линейные размеры
    for d in lins:
        side, lv = d["side"], d.get("level", 1)
        a, b = _axis(d)
        r = row_of[id(d)]
        far = dist[(side, lv)]
        short = (b - a) < al * 2.6
        txt = d["text"]
        if d["dir"] == "h":
            if side == "top":
                yl, e0, sg = maxy + far, maxy + ext_gap, 1
                ty = yl + gap + r * row_h
            else:
                yl, e0, sg = miny - far, miny - ext_gap, -1
                ty = yl - gap - th * 0.75 - r * row_h
            for x in (a, b):
                ops.append(("line", (x, e0), (x, yl + sg * over)))
            if short:
                ops.append(("line", (a - al * 1.6, yl), (b + al * 1.6, yl)))
                ops.append(("arrow", (a, yl), (1, 0)))
                ops.append(("arrow", (b, yl), (-1, 0)))
            else:
                ops.append(("line", (a, yl), (b, yl)))
                ops.append(("arrow", (a, yl), (-1, 0)))
                ops.append(("arrow", (b, yl), (1, 0)))
            ops.append(("text", ((a + b) / 2, ty), txt, 0, th, "center"))
        else:
            if side == "left":
                xl, e0, sg = minx - far, minx - ext_gap, -1
                tx = xl - gap - r * row_h
            else:
                xl, e0, sg = maxx + far, maxx + ext_gap, 1
                tx = xl + gap + th * 0.75 + r * row_h
            for y in (a, b):
                ops.append(("line", (e0, y), (xl + sg * over, y)))
            if short:
                ops.append(("line", (xl, a - al * 1.6), (xl, b + al * 1.6)))
                ops.append(("arrow", (xl, a), (0, 1)))
                ops.append(("arrow", (xl, b), (0, -1)))
            else:
                ops.append(("line", (xl, a), (xl, b)))
                ops.append(("arrow", (xl, a), (0, -1)))
                ops.append(("arrow", (xl, b), (0, 1)))
            ops.append(("text", (tx, (a + b) / 2), txt, 90, th, "center"))

    # --- выноски диаметров (за край стекла, подписи не перекрываются)
    for side, ds in dia_side.items():
        last = math.inf
        edge = maxx if side == "right" else minx
        sg = 1 if side == "right" else -1
        for d in sorted(ds, key=lambda x: -x["c"][1]):
            (cx, cy), rr = d["c"], d["r"]
            ly = min(cy, last - row_h)
            last = ly
            p_hole = (cx + sg * rr, cy)
            knee = (edge + sg * th * 0.5, cy)
            shelf0 = (edge + sg * th * 0.9, ly)
            w = text_w(d["text"], th)
            shelf1 = (shelf0[0] + sg * (w + th * 0.3), ly)
            ops.append(("line", p_hole, knee))
            ops.append(("line", knee, shelf0))
            ops.append(("line", shelf0, shelf1))
            ops.append(("arrow", p_hole, (-sg, 0)))
            ops.append(("text", (shelf0[0] + sg * th * 0.15, ly + th * 0.2), d["text"], 0, th,
                        "left" if side == "right" else "right"))

    # --- подписи (радиусы выреза и т.п.) — как есть, в указанной точке
    for d in dims:
        if d["t"] == "note":
            ops.append(("text", (d["p"][0], d["p"][1] - th * 0.35), d["text"], 0, th, "center"))

    # --- длины сторон фигурного стекла (снаружи, вдоль стороны)
    for d in dims:
        if d["t"] != "aligned":
            continue
        (x1, y1), (x2, y2) = d["p1"], d["p2"]
        ln = math.hypot(x2 - x1, y2 - y1)
        if ln < 1e-6:
            continue
        ux, uy = (x2 - x1) / ln, (y2 - y1) / ln
        nx, ny = uy, -ux  # наружу для контура против часовой
        ang = math.degrees(math.atan2(uy, ux))
        if ang > 90 or ang < -90:
            ang += 180
        mx, my = (x1 + x2) / 2 + nx * th * 1.4, (y1 + y2) / 2 + ny * th * 1.4
        ops.append(("text", (mx, my), d["text"], ang, th * 0.9, "center"))
    return ops


def ops_extent(ops: list[tuple], th: float) -> tuple[float, float, float, float] | None:
    xs, ys = [], []
    for op in ops:
        if op[0] == "line":
            xs += [op[1][0], op[2][0]]
            ys += [op[1][1], op[2][1]]
        elif op[0] == "text":
            (x, y), text, ang = op[1], op[2], op[3]
            w = text_w(text, op[4])
            if ang == 90:
                xs += [x - th, x]
                ys += [y - w / 2, y + w / 2]
            else:
                if op[5] == "left":
                    xs += [x, x + w]
                elif op[5] == "right":
                    xs += [x - w, x]
                else:
                    xs += [x - w / 2, x + w / 2]
                ys += [y, y + th]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def dims_extent(bbox, dims, S, th=None, al=None) -> tuple[float, float, float, float]:
    """Габарит рисунка вместе с размерами (для подбора масштаба листа)."""
    th = th or S / 3.2
    ext = ops_extent(layout_dims(dims, bbox, S, th, al), th)
    if not ext:
        return bbox
    return (min(ext[0], bbox[0]) - th, min(ext[1], bbox[1]) - th, max(ext[2], bbox[2]) + th, max(ext[3], bbox[3]) + th)
