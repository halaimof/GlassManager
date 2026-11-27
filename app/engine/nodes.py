"""Чертежи узлов крупным планом: фрагмент каждого стекла вокруг установленной фурнитуры
с размерами от кромки, между элементами, радиусами и диаметрами.

Одинаковые узлы (та же модель на тех же стеклах и кромках — например, верхняя и нижняя
петля) объединяются в один узел со списком положений.
"""
from __future__ import annotations

import math

from shapely.geometry import Point, Polygon

from .dims import fmt, glass_features

EDGE_RU = {"left": "левая кромка", "right": "правая кромка", "top": "верхняя кромка", "bottom": "нижняя кромка"}
REF_RU = {"top": "от верха", "bottom": "от низа", "center": "от центра", "left": "от левого края", "right": "от правого края"}


def _uniq(vals, tol=0.05):
    out = []
    for v in sorted(vals):
        if not out or abs(v - out[-1]) > tol:
            out.append(v)
    return out


def _arc_center(p1, p2, b):
    theta = 4 * math.atan(b)
    chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if chord < 1e-9:
        return None, 0
    r = chord / (2 * math.sin(abs(theta) / 2))
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    h = r * math.cos(abs(theta) / 2)
    dx, dy = (p2[0] - p1[0]) / chord, (p2[1] - p1[1]) / chord
    sg = 1 if b > 0 else -1
    return (mx - sg * dy * h, my + sg * dx * h), r


def _view(g: dict, mark_bbox, edge: str) -> dict:
    w, hh = g["w"], g["h"]
    x0, y0, x1, y1 = mark_bbox
    m = max(25.0, 0.6 * max(x1 - x0, y1 - y0))
    win = [x0 - m, y0 - m, x1 + m, y1 + m]
    # фрагмент всегда захватывает кромку узла и немного пространства за ней
    if edge == "right":
        win[2] = max(win[2], w + m * 0.6)
    elif edge == "left":
        win[0] = min(win[0], -m * 0.6)
    elif edge == "top":
        win[3] = max(win[3], hh + m * 0.6)
    else:
        win[1] = min(win[1], -m * 0.6)

    def inside(x, y):
        return win[0] <= x <= win[2] and win[1] <= y <= win[3]

    holes = [hl for hl in g.get("holes", []) if inside(*hl["c"])]
    vertical = edge in ("left", "right")
    e = (w if edge == "right" else 0.0) if vertical else (hh if edge == "top" else 0.0)
    perp, along = [], []  # координаты поперёк кромки и вдоль неё
    # те же точки, что и на листе детали: центры отверстий, концы проёма выреза на кромке, глубина выреза
    for x, y, ux, uy in glass_features(g):
        if not inside(x, y):
            continue
        px_, pu = (x, ux) if vertical else (y, uy)
        ax_, au = (y, uy) if vertical else (x, ux)
        if pu and abs(px_ - e) > 0.05:
            perp.append(px_)
        if au:
            along.append(ax_)
    dims: list[dict] = []
    ps = _uniq([e] + perp)
    for a, b in zip(ps, ps[1:]):
        if vertical:
            dims.append({"t": "lin", "dir": "h", "p1": [a, win[3]], "p2": [b, win[3]], "side": "top", "level": 1, "text": fmt(b - a)})
        else:
            dims.append({"t": "lin", "dir": "v", "p1": [win[2], a], "p2": [win[2], b], "side": "right", "level": 1, "text": fmt(b - a)})
    al = _uniq(along)
    for a, b in zip(al, al[1:]):
        if vertical:
            dims.append({"t": "lin", "dir": "v", "p1": [e, a], "p2": [e, b], "side": edge, "level": 1, "text": fmt(b - a)})
        else:
            dims.append({"t": "lin", "dir": "h", "p1": [a, e], "p2": [b, e], "side": edge, "level": 1, "text": fmt(b - a)})
    seen = set()
    for hl in holes:
        key = (round(hl["c"][0], 2), round(hl["c"][1], 2))
        if key not in seen:
            seen.add(key)
            dims.append({"t": "dia", "c": hl["c"], "r": hl["r"], "text": "Ø" + fmt(hl["r"] * 2)})
    # радиусы выреза: подпись в центре дуги, если он вне стекла (вогнутая дуга выреза)
    glass_poly = Polygon([(x, y) for x, y, _b in g["contour"]])
    radii = set()
    cont = g["contour"]
    for i, (px, py, b) in enumerate(cont):
        if abs(b) < 1e-9:
            continue
        qx, qy, _ = cont[(i + 1) % len(cont)]
        c, r = _arc_center((px, py), (qx, qy), b)
        if c is None or not inside(*c) or glass_poly.contains(Point(c)):
            continue
        key = (round(c[0], 1), round(c[1], 1), round(r, 2))
        if key in radii:
            continue
        radii.add(key)
        dims.append({"t": "note", "p": [c[0], c[1]], "text": "R" + fmt(r)})
    return {"window": [round(v, 3) for v in win], "dims": dims, "edge": edge}


def node_details(data: dict, res: dict, lib) -> list[dict]:
    glasses = {g["id"]: g for g in res["glasses"]}
    axes = {a["id"]: a for a in res.get("axes", [])}
    groups: dict[tuple, dict] = {}
    for inst in data.get("hardware", []):
        model = lib.get("hardware", inst.get("model_id"))
        if not model or not model.get("sides"):
            continue
        tkey = tuple(sorted((k, t.get("panel_id"), t.get("edge")) for k, t in (inst.get("targets") or {}).items()))
        grp = groups.setdefault((model["id"], tkey), {"model": model, "instances": []})
        grp["instances"].append(inst)
    nodes = []
    for (_mid, _tk), grp in groups.items():
        model, inst0 = grp["model"], grp["instances"][0]
        views = []
        for side in model["sides"]:
            tgt = (inst0.get("targets") or {}).get(side.get("key"))
            g = glasses.get((tgt or {}).get("panel_id"))
            if not g:
                continue
            mark = next((mk for mk in g.get("marks", []) if mk["src"] == inst0["id"]), None)
            if not mark:
                continue
            v = _view(g, mark["bbox"], tgt.get("edge", "right"))
            v.update({"glass_id": g["id"], "glass_name": g["name"], "glass_pos": g["pos"], "side": side.get("key"),
                      "side_label": side.get("label") or "", "edge_name": EDGE_RU.get(tgt.get("edge"), "")})
            views.append(v)
        if not views:
            continue
        positions = []
        for inst in grp["instances"]:
            pos = inst.get("pos") or {}
            ref, off = pos.get("ref", "top"), float(pos.get("offset") or 0)
            if ref == "axis":
                ax = axes.get(pos.get("axis_id") or "")
                positions.append(f"по оси «{ax['name'] if ax else '?'}»" + (f" {off:+g} мм" if off else ""))
            else:
                positions.append(f"{fmt(off)} мм {REF_RU.get(ref, ref)} до оси узла")
        nodes.append({"model_id": model["id"], "name": model["name"], "article": model.get("article") or "",
                      "joint_gap": model.get("joint_gap"), "qty": sum(int(i.get("qty") or 1) for i in grp["instances"]),
                      "positions": positions, "views": views})
    return nodes
