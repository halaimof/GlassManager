"""Чертежи узлов крупным планом: фрагмент каждого стекла вокруг установленной фурнитуры
с размерами от кромки, между элементами, радиусами и диаметрами.

Одинаковые узлы (та же модель на тех же стеклах и кромках — например, верхняя и нижняя
петля) объединяются в один узел со списком положений.
"""
from __future__ import annotations

import math

from .dims import fmt

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
    far_side = {"right": "left", "left": "right", "top": "bottom", "bottom": "top"}[edge]

    def P(v):   # координата поперёк кромки
        return v[0] if vertical else v[1]

    def A(v):   # координата вдоль кромки
        return v[1] if vertical else v[0]

    def lin_perp(a, b, side, level):
        if vertical:
            return {"t": "lin", "dir": "h", "p1": [a, win[3]], "p2": [b, win[3]], "side": side, "level": level, "text": fmt(abs(b - a))}
        return {"t": "lin", "dir": "v", "p1": [win[2], a], "p2": [win[2], b], "side": side, "level": level, "text": fmt(abs(b - a))}

    def lin_along(a, b, side, level):
        if vertical:
            return {"t": "lin", "dir": "v", "p1": [e, a], "p2": [e, b], "side": side, "level": level, "text": fmt(abs(b - a))}
        return {"t": "lin", "dir": "h", "p1": [a, e], "p2": [b, e], "side": side, "level": level, "text": fmt(abs(b - a))}

    perp_side = "top" if vertical else "right"
    dims: list[dict] = []
    # 1) отверстия и внутренние контуры — цепочками от кромки
    perp, along = [], []
    for hl in holes:
        perp.append(P(hl["c"]))
        along.append(A(hl["c"]))
    for chain in g.get("inner", []):
        pts = [pt for s_ in chain for pt in ((s_["p1"], s_["p2"]) if s_["t"] == "line" else (s_["c"],))]
        if pts and inside(*pts[0]):
            perp += [P(pt) for pt in pts]
            along += [A(pt) for pt in pts]
    ps = _uniq([e] + [v for v in perp if abs(v - e) > 0.05])
    for a, b in zip(ps, ps[1:]):
        dims.append(lin_perp(a, b, perp_side, 1))
    al = _uniq(along)
    for a, b in zip(al, al[1:]):
        dims.append(lin_along(a, b, edge, 1))
    lv_perp = 2 if len(ps) > 1 else 1
    lv_edge = 2 if len(al) > 1 else 1
    lv_far = 1

    # 2) вырезы на кромке — чертёж самого выреза: проём, глубины от кромки, прямые стенки, радиусы
    cont = g["contour"]
    for cf in g.get("cut_feats", []):
        if not cf.get("open"):
            continue
        x0, y0, x1, y1 = cf["bbox"]
        if not (x1 >= win[0] and x0 <= win[2] and y1 >= win[1] and y0 <= win[3]):
            continue
        (oa, ob) = cf["open"]
        dims.append(lin_along(A(oa), A(ob), edge, lv_edge))           # проём на кромке
        lv_edge += 1

        def in_box(v, t=0.05):
            return x0 - t <= v[0] <= x1 + t and y0 - t <= v[1] <= y1 + t
        depths, walls = [], []
        for i, (vx, vy, b) in enumerate(cont):
            nx_, ny_, _ = cont[(i + 1) % len(cont)]
            pa, pb = (vx, vy), (nx_, ny_)
            if not (in_box(pa) and in_box(pb)):
                continue
            if abs(P(pa) - e) < 0.05 and abs(P(pb) - e) < 0.05:
                continue  # участок самой кромки
            depths += [P(pa), P(pb)]
            if abs(b) > 1e-9:
                c, _r = _arc_center(pa, pb, b)
                if c is not None:
                    depths.append(P(c))
            elif abs(P(pa) - P(pb)) < 0.05 and abs(A(pa) - A(pb)) > 0.05:
                walls.append((A(pa), A(pb), P(pa)))                      # прямая стенка вдоль кромки
        for d_ in sorted(_uniq([v for v in depths if abs(v - e) > 0.05]), key=lambda v: abs(v - e)):
            dims.append(lin_perp(e, d_, perp_side, lv_perp))           # глубины — каждая от кромки
            lv_perp += 1
        for a, b, _pp in walls:
            dims.append(lin_along(a, b, far_side, lv_far))
            lv_far += 1
    seen = set()
    for hl in holes:
        key = (round(hl["c"][0], 2), round(hl["c"][1], 2))
        if key not in seen:
            seen.add(key)
            dims.append({"t": "dia", "c": hl["c"], "r": hl["r"], "text": "Ø" + fmt(hl["r"] * 2)})
    # радиусы выреза: подпись в центре вогнутой дуги (контур стекла обходится против часовой,
    # дуга по часовой — bulge < 0 — вогнута, её центр лежит в вырезе, вне стекла)
    radii = set()
    cont = g["contour"]
    for i, (px, py, b) in enumerate(cont):
        if abs(b) < 1e-9:
            continue
        qx, qy, _ = cont[(i + 1) % len(cont)]
        c, r = _arc_center((px, py), (qx, qy), b)
        if c is None or b > 0 or not inside(*c):
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
