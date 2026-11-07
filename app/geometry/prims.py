"""Геометрические примитивы (мм, Y вверх).

Сегменты:
  {"t": "line",   "p1": [x, y], "p2": [x, y]}
  {"t": "arc",    "c": [x, y], "r": r, "a0": deg, "a1": deg}   # против часовой от a0 к a1
  {"t": "circle", "c": [x, y], "r": r}
"""
from __future__ import annotations

import math
from typing import Callable, Iterable

Point = tuple[float, float]
EPS = 1e-6
SAGITTA = 0.002  # мм: максимальное отклонение хорды при дискретизации дуг


def norm_angle(a: float) -> float:
    a = a % 360.0
    return a + 360.0 if a < 0 else a


def arc_sweep(a0: float, a1: float) -> float:
    s = norm_angle(a1 - a0)
    return 360.0 if s < EPS else s


def arc_point(c, r, ang_deg) -> Point:
    a = math.radians(ang_deg)
    return (c[0] + r * math.cos(a), c[1] + r * math.sin(a))


def seg_start(s: dict) -> Point:
    if s["t"] == "line":
        return tuple(s["p1"])
    if s["t"] == "arc":
        return arc_point(s["c"], s["r"], s["a0"])
    return arc_point(s["c"], s["r"], 0)


def seg_end(s: dict) -> Point:
    if s["t"] == "line":
        return tuple(s["p2"])
    if s["t"] == "arc":
        return arc_point(s["c"], s["r"], s["a1"])
    return arc_point(s["c"], s["r"], 0)


def reverse_seg(s: dict) -> dict:
    """Сегмент в обратном направлении обхода. Дуга хранится всегда CCW,
    поэтому для неё добавляется флаг rev (используется только при обходе цепочек)."""
    if s["t"] == "line":
        return {**s, "p1": s["p2"], "p2": s["p1"]}
    if s["t"] == "arc":
        return {**s, "rev": not s.get("rev", False)}
    return s


def walk_start(s: dict) -> Point:
    return seg_end({**s}) if s.get("rev") and s["t"] == "arc" else seg_start(s)


def walk_end(s: dict) -> Point:
    return seg_start(s) if s.get("rev") and s["t"] == "arc" else seg_end(s)


def arc_steps(r: float, sweep_deg: float, sagitta: float = SAGITTA) -> int:
    if r <= sagitta:
        return 4
    step = 2 * math.acos(max(-1.0, 1 - sagitta / r))
    return max(4, int(math.ceil(math.radians(sweep_deg) / step)))


def discretize(s: dict, sagitta: float = SAGITTA) -> list[Point]:
    """Точки сегмента в направлении обхода (с учётом rev)."""
    if s["t"] == "line":
        return [tuple(s["p1"]), tuple(s["p2"])]
    if s["t"] == "circle":
        n = arc_steps(s["r"], 360, sagitta)
        return [arc_point(s["c"], s["r"], 360.0 * i / n) for i in range(n)] + [arc_point(s["c"], s["r"], 0)]
    sw = arc_sweep(s["a0"], s["a1"])
    n = arc_steps(s["r"], sw, sagitta)
    pts = [arc_point(s["c"], s["r"], s["a0"] + sw * i / n) for i in range(n + 1)]
    return list(reversed(pts)) if s.get("rev") else pts


def transform_seg(s: dict, fn: Callable[[Point], Point], mirrored: bool) -> dict:
    """Применяет аффинное преобразование без масштаба (поворот/перенос/отражение)."""
    if s["t"] == "line":
        return {**s, "p1": list(fn(s["p1"])), "p2": list(fn(s["p2"]))}
    c = fn(s["c"])
    if s["t"] == "circle":
        return {**s, "c": list(c)}
    p0 = fn(seg_start(s))
    p1 = fn(seg_end(s))
    a0 = math.degrees(math.atan2(p0[1] - c[1], p0[0] - c[0]))
    a1 = math.degrees(math.atan2(p1[1] - c[1], p1[0] - c[0]))
    if mirrored:  # отражение меняет направление обхода
        a0, a1 = a1, a0
    return {**s, "c": list(c), "a0": norm_angle(a0), "a1": norm_angle(a1)}


def seg_bbox(s: dict) -> tuple[float, float, float, float]:
    pts = discretize(s, 0.05)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_of(segs: Iterable[dict]):
    boxes = [seg_bbox(s) for s in segs]
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def snap_points(s: dict) -> list[dict]:
    """Объектные привязки примитива."""
    out = []
    if s["t"] == "line":
        p1, p2 = s["p1"], s["p2"]
        out += [
            {"kind": "end", "label": "Конечная точка", "p": list(p1)},
            {"kind": "end", "label": "Конечная точка", "p": list(p2)},
            {"kind": "mid", "label": "Середина", "p": [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2]},
        ]
    elif s["t"] == "circle":
        c, r = s["c"], s["r"]
        out += [
            {"kind": "center", "label": "Центр", "p": list(c)},
            {"kind": "quad", "label": "Верхняя точка", "p": [c[0], c[1] + r]},
            {"kind": "quad", "label": "Нижняя точка", "p": [c[0], c[1] - r]},
            {"kind": "quad", "label": "Левая точка", "p": [c[0] - r, c[1]]},
            {"kind": "quad", "label": "Правая точка", "p": [c[0] + r, c[1]]},
        ]
    elif s["t"] == "arc":
        sw = arc_sweep(s["a0"], s["a1"])
        out += [
            {"kind": "end", "label": "Начало дуги", "p": list(seg_start(s))},
            {"kind": "end", "label": "Конец дуги", "p": list(seg_end(s))},
            {"kind": "center", "label": "Центр", "p": list(s["c"])},
            {"kind": "mid", "label": "Середина дуги", "p": list(arc_point(s["c"], s["r"], s["a0"] + sw / 2))},
        ]
    return out


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def chain_segments(segs: list[dict], tol: float = 0.01) -> list[list[dict]]:
    """Объединяет сегменты (кроме окружностей) в цепочки по совпадающим концам."""
    rest = [s for s in segs if s["t"] != "circle"]
    chains: list[list[dict]] = []
    while rest:
        chain = [rest.pop(0)]
        grown = True
        while grown:
            grown = False
            head, tail = walk_start(chain[0]), walk_end(chain[-1])
            if dist(head, tail) < tol and len(chain) > 1:
                break
            for i, s in enumerate(rest):
                a, b = walk_start(s), walk_end(s)
                if dist(tail, a) < tol:
                    chain.append(rest.pop(i))
                elif dist(tail, b) < tol:
                    chain.append(reverse_seg(rest.pop(i)))
                elif dist(head, b) < tol:
                    chain.insert(0, rest.pop(i))
                elif dist(head, a) < tol:
                    chain.insert(0, reverse_seg(rest.pop(i)))
                else:
                    continue
                grown = True
                break
        chains.append(chain)
    return chains


def chain_points(chain: list[dict], sagitta: float = SAGITTA) -> list[Point]:
    pts: list[Point] = []
    for s in chain:
        sp = discretize(s, sagitta)
        if pts and dist(pts[-1], sp[0]) < 0.05:
            sp = sp[1:]
        pts.extend(sp)
    return pts


def chain_closed(chain: list[dict], tol: float = 0.01) -> bool:
    if len(chain) == 1 and chain[0]["t"] == "arc" and arc_sweep(chain[0]["a0"], chain[0]["a1"]) >= 359.999:
        return True
    return len(chain) > 0 and dist(walk_start(chain[0]), walk_end(chain[-1])) < tol


def bulge_arc(p1: Point, p2: Point, bulge: float) -> dict | None:
    """Дуга сегмента полилинии с выпуклостью bulge (DXF). Возвращает сегмент arc с rev."""
    if abs(bulge) < 1e-12:
        return None
    theta = 4 * math.atan(bulge)  # подписанный угол
    chord = dist(p1, p2)
    if chord < 1e-12:
        return None
    r = chord / (2 * math.sin(abs(theta) / 2))
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    # расстояние от середины хорды до центра
    h = r * math.cos(abs(theta) / 2)
    dx, dy = (p2[0] - p1[0]) / chord, (p2[1] - p1[1]) / chord
    # для CCW (bulge>0) центр слева от направления p1->p2, если |theta|<180
    # (для дуг > 180° cos отрицателен — центр автоматически по другую сторону)
    sign = 1 if bulge > 0 else -1
    cx, cy = mx - sign * dy * h, my + sign * dx * h
    a1 = math.degrees(math.atan2(p1[1] - cy, p1[0] - cx))
    a2 = math.degrees(math.atan2(p2[1] - cy, p2[0] - cx))
    if bulge > 0:
        return {"t": "arc", "c": [cx, cy], "r": r, "a0": norm_angle(a1), "a1": norm_angle(a2)}
    return {"t": "arc", "c": [cx, cy], "r": r, "a0": norm_angle(a2), "a1": norm_angle(a1), "rev": True}
