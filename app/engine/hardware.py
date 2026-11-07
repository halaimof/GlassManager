"""Фурнитура как инженерный узел.

Модель фурнитуры содержит стороны (A, B, C …). Каждая сторона — набор
операций для одного стекла: DXF-примитивы с ролью «обработка» и/или
параметрические отверстия (u — вдоль кромки, v — внутрь стекла).

Локальная система стороны строится из DXF:
  * «край стекла» — вспомогательная линия, задающая направление кромки d;
  * glass_side — с какой стороны от линии находится стекло (нормаль n внутрь);
  * anchor — точка привязки (по магниту), её проекция на кромку = начало (u=0, v=0).

При установке на стекло кромка стекла даёт базис (D, N) и точку P;
точка DXF p переносится как  P + ((p−O)·d)·D + ((p−O)·n)·N.
"""
from __future__ import annotations

import math

from ..geometry.prims import transform_seg
from .library import Library

EDGE_NAMES = {"left": "левая кромка", "right": "правая кромка", "top": "верх", "bottom": "низ"}

CONNECTION_TYPES = {
    "glass-glass": "Стекло ↔ стекло",
    "glass-wall": "Стекло ↔ стена",
    "glass-profile": "Стекло ↔ профиль",
    "glass-floor": "Стекло ↔ пол",
    "glass-glass-glass": "Стекло ↔ стекло ↔ стекло",
    "single": "Одиночная обработка",
}


def _norm(v):
    l = math.hypot(v[0], v[1])
    return (v[0] / l, v[1] / l) if l > 1e-12 else (0.0, 1.0)


def side_frame(side: dict, prims_by_id: dict[str, dict]):
    """(O, d, n) локальной системы стороны фурнитуры в координатах DXF."""
    edge = prims_by_id.get(side.get("edge_pid") or "")
    seg = None
    if edge:
        seg = next((s for s in edge["segs"] if s["t"] == "line"), None)
    if seg:
        p1, p2 = seg["p1"], seg["p2"]
        d = _norm((p2[0] - p1[0], p2[1] - p1[1]))
        if abs(d[1]) >= abs(d[0]):
            if d[1] < 0:
                d = (-d[0], -d[1])
        elif d[0] < 0:
            d = (-d[0], -d[1])
        base = p1
    else:
        d = (0.0, 1.0)
        base = side.get("anchor") or [0.0, 0.0]
    left = (-d[1], d[0])
    n = left if side.get("glass_side", "left") in ("left", "above") else (-left[0], -left[1])
    anchor = side.get("anchor") or base
    t = (anchor[0] - base[0]) * d[0] + (anchor[1] - base[1]) * d[1]
    origin = (base[0] + d[0] * t, base[1] + d[1] * t)
    return origin, d, n


def glass_edge_frame(glass: dict, edge: str):
    """Кромка стекла: (E0, D, N) — начальная точка, направление (вверх/вправо),
    нормаль внутрь стекла. Для четырёхугольников — по реальной стороне."""
    pts = glass["outline"]
    if len(pts) == 4:
        bl, br, tr, tl = pts
    else:
        w, h = glass["w"], glass["h"]
        bl, br, tr, tl = (0, 0), (w, 0), (w, h), (0, h)
    if edge == "right":
        e0, e1 = br, tr
    elif edge == "left":
        e0, e1 = bl, tl
    elif edge == "top":
        e0, e1 = tl, tr
    else:
        e0, e1 = bl, br
    D = _norm((e1[0] - e0[0], e1[1] - e0[1]))
    left = (-D[1], D[0])
    N = left if edge in ("right", "bottom") else (-left[0], -left[1])
    return e0, D, N


def point_on_edge(glass: dict, edge: str, coord: float):
    """Точка на кромке: для вертикальных кромок coord — локальный Y, для горизонтальных — X."""
    e0, D, N = glass_edge_frame(glass, edge)
    if edge in ("left", "right"):
        t = (coord - e0[1]) / D[1] if abs(D[1]) > 1e-12 else 0.0
    else:
        t = (coord - e0[0]) / D[0] if abs(D[0]) > 1e-12 else 0.0
    return (e0[0] + D[0] * t, e0[1] + D[1] * t), D, N


def placement_coord(inst: dict, glass: dict, ref_glass: dict, edge: str, axes: dict[str, float]) -> float:
    """Координата точки привязки вдоль кромки в локальных координатах стекла.
    Положение задаётся относительно стекла-основания (сторона A) или оси,
    затем переводится через мировые координаты — поэтому на соседнем стекле
    с другим низом (дверь выше на 12 мм) узел остаётся соосным."""
    pos = inst.get("pos") or {}
    ref = pos.get("ref", "top")
    off = float(pos.get("offset") or 0)
    if edge in ("left", "right"):
        if ref == "top":
            wy = ref_glass["y"] + ref_glass["h"] - off
        elif ref == "bottom":
            wy = ref_glass["y"] + off
        elif ref == "center":
            wy = ref_glass["y"] + ref_glass["h"] / 2 + off
        elif ref == "axis":
            ay = axes.get(pos.get("axis_id") or "")
            if ay is None:
                raise ValueError("ось не найдена")
            wy = ay + off
        else:
            wy = ref_glass["y"] + off
        return wy - glass["y"]
    if ref == "right":
        wx = ref_glass["x"] + ref_glass["w"] - off
    elif ref == "center":
        wx = ref_glass["x"] + ref_glass["w"] / 2 + off
    else:
        wx = ref_glass["x"] + off
    return wx - glass["x"]


def model_sides(model: dict) -> list[dict]:
    return model.get("sides") or []


def side_segments(side: dict, lib: Library) -> list[dict]:
    """Рабочие сегменты стороны (в координатах DXF) — только роль «обработка»."""
    roles = side.get("roles") or {}
    out = []
    for prim in lib.dxf_primitives(side.get("dxf_id")):
        role = roles.get(prim["id"], prim.get("default_role", "op"))
        if role != "op" or prim["id"] == side.get("edge_pid"):
            continue
        out.extend(prim["segs"])
    return out


def apply_hardware(inst: dict, model: dict, glasses: dict[str, dict], lib: Library,
                   axes: dict[str, float], warnings: list[str]) -> dict[str, list[dict]]:
    """Возвращает {glass_id: [сегменты]} для одного установленного узла."""
    result: dict[str, list[dict]] = {}
    targets = inst.get("targets") or {}
    sides = model_sides(model)
    if not sides:
        return result
    ref_target = targets.get(sides[0].get("key", "A")) or next(iter(targets.values()), None)
    if not ref_target or ref_target.get("panel_id") not in glasses:
        warnings.append(f"Фурнитура «{model['name']}»: не указано стекло")
        return result
    ref_glass = glasses[ref_target["panel_id"]]
    for side in sides:
        tgt = targets.get(side.get("key", "A"))
        if not tgt:
            continue
        g = glasses.get(tgt.get("panel_id"))
        if not g:
            warnings.append(f"Фурнитура «{model['name']}», сторона {side.get('key')}: стекло не найдено")
            continue
        edge = tgt.get("edge", "right")
        try:
            coord = placement_coord(inst, g, ref_glass, edge, axes)
        except ValueError as e:
            warnings.append(f"Фурнитура «{model['name']}»: {e}")
            continue
        P, D, N = point_on_edge(g, edge, coord)
        if inst.get("flip"):
            D = (-D[0], -D[1])
        prims = {p["id"]: p for p in lib.dxf_primitives(side.get("dxf_id"))}
        O, d, n = side_frame(side, prims)
        det_src = d[0] * n[1] - d[1] * n[0]
        det_dst = D[0] * N[1] - D[1] * N[0]
        mirrored = (det_src > 0) != (det_dst > 0)

        def fn(p, O=O, d=d, n=n, P=P, D=D, N=N):
            qx, qy = p[0] - O[0], p[1] - O[1]
            u = qx * d[0] + qy * d[1]
            v = qx * n[0] + qy * n[1]
            return (P[0] + u * D[0] + v * N[0], P[1] + u * D[1] + v * N[1])

        segs = [transform_seg(s, fn, mirrored) for s in side_segments(side, lib)]
        for hole in side.get("holes") or []:
            dmt = float(hole.get("d") or 0)
            if dmt <= 0:
                continue
            u, v = float(hole.get("u") or 0), float(hole.get("v") or 0)
            c = (P[0] + u * D[0] + v * N[0], P[1] + u * D[1] + v * N[1])
            segs.append({"t": "circle", "c": [c[0], c[1]], "r": dmt / 2})
        for s in segs:
            s["src"] = inst["id"]
        result.setdefault(g["id"], []).extend(segs)
    return result
