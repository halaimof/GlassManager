"""Ручная параметрическая обработка: отверстия, группы отверстий, вырезы.

Привязки хранятся семантически (от левого/правого края, от верха/низа,
от центра, от оси), координаты пересчитываются при каждом изменении стекла.
"""
from __future__ import annotations

import copy

X_REFS = {"left": "от левого края", "right": "от правого края", "center": "от центра", "abs": "вручную"}
Y_REFS = {"top": "от верха", "bottom": "от низа", "center": "от центра", "axis": "от оси", "abs": "вручную"}


def resolve_x(spec: dict, w: float) -> float:
    ref = spec.get("ref", "left")
    v = float(spec.get("value") or 0)
    if ref == "right":
        return w - v
    if ref == "center":
        return w / 2 + v
    return v


def resolve_y(spec: dict, h: float, glass_y: float, axes: dict[str, float]) -> float:
    ref = spec.get("ref", "top")
    v = float(spec.get("value") or 0)
    if ref == "top":
        return h - v
    if ref == "bottom":
        return v
    if ref == "center":
        return h / 2 + v
    if ref == "axis":
        ay = axes.get(spec.get("axis_id") or "")
        if ay is None:
            raise ValueError("Ось не найдена")
        return ay - glass_y + v
    return v


def expand_group(op: dict) -> list[dict]:
    """Группа → список отверстий-спецификаций (с учётом количества и шага).
    Зеркалирование выполняется позже численно (зависит от размеров стекла)."""
    items = op.get("items") or []
    rep = op.get("repeat") or {}
    count = max(1, int(rep.get("count") or 1))
    step = float(rep.get("step") or 0)
    direction = rep.get("dir", "v")
    out = []
    for it in items:
        for i in range(count):
            h = copy.deepcopy(it)
            if i and step:
                if direction == "v":
                    y = dict(h.get("y") or {})
                    # «вдоль от базы»: от верха/низа — увеличиваем отступ, иначе — вниз
                    if y.get("ref") in ("top", "bottom"):
                        y["value"] = float(y.get("value") or 0) + i * step
                    else:
                        y["value"] = float(y.get("value") or 0) - i * step
                    h["y"] = y
                else:
                    x = dict(h.get("x") or {})
                    x["value"] = float(x.get("value") or 0) + i * step
                    h["x"] = x
            out.append(h)
    return out


def cutout_center(op: dict, w: float, h: float, gy: float, axes: dict[str, float]) -> tuple[float, float]:
    """Центр выреза по привязке.

    anchor «edge» (по умолчанию для новых вырезов): отступ задаётся до КРАЯ выреза со стороны
    базы — «от верха 300» = верхний край выреза в 300 мм от верха стекла, «от правого края 0» —
    вырез вплотную к правой кромке. anchor «center» — до центра выреза (так хранились вырезы
    в версиях до 0.2.3, поэтому без поля anchor сохраняется прежнее поведение).
    """
    cw, ch = float(op.get("w") or 0), float(op.get("h") or 0)
    xs, ys = op.get("x") or {}, op.get("y") or {}
    anchor = op.get("anchor") or {}
    cx = resolve_x(xs, w)
    cy = resolve_y(ys, h, gy, axes)
    if anchor.get("x") == "edge":
        ref = xs.get("ref", "left")
        if ref in ("left", "abs"):
            cx += cw / 2
        elif ref == "right":
            cx -= cw / 2
    if anchor.get("y") == "edge":
        ref = ys.get("ref", "top")
        if ref == "top":
            cy -= ch / 2
        elif ref in ("bottom", "abs"):
            cy += ch / 2
    return cx, cy


def rect_cut_segments(cx: float, cy: float, w: float, h: float, r: float) -> list[dict]:
    """Прямоугольный вырез/паз со скруглением углов. Центр (cx, cy)."""
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    r = max(0.0, min(r, w / 2 - 1e-9, h / 2 - 1e-9))
    if r <= 1e-9:
        return [
            {"t": "line", "p1": [x0, y0], "p2": [x1, y0]},
            {"t": "line", "p1": [x1, y0], "p2": [x1, y1]},
            {"t": "line", "p1": [x1, y1], "p2": [x0, y1]},
            {"t": "line", "p1": [x0, y1], "p2": [x0, y0]},
        ]
    segs = []
    segs.append({"t": "line", "p1": [x0 + r, y0], "p2": [x1 - r, y0]})
    segs.append({"t": "arc", "c": [x1 - r, y0 + r], "r": r, "a0": 270, "a1": 360})
    segs.append({"t": "line", "p1": [x1, y0 + r], "p2": [x1, y1 - r]})
    segs.append({"t": "arc", "c": [x1 - r, y1 - r], "r": r, "a0": 0, "a1": 90})
    segs.append({"t": "line", "p1": [x1 - r, y1], "p2": [x0 + r, y1]})
    segs.append({"t": "arc", "c": [x0 + r, y1 - r], "r": r, "a0": 90, "a1": 180})
    segs.append({"t": "line", "p1": [x0, y1 - r], "p2": [x0, y0 + r]})
    segs.append({"t": "arc", "c": [x0 + r, y0 + r], "r": r, "a0": 180, "a1": 270})
    return segs


def resolve_operations(glass: dict, ops: list[dict], axes: dict[str, float], warnings: list[str]) -> list[dict]:
    """Возвращает сегменты обработки в локальных координатах стекла.
    Каждый сегмент получает поле src (id операции) для выделения на холсте."""
    w, h, gy = glass["w"], glass["h"], glass["y"]
    segs: list[dict] = []
    for op in ops:
        if op.get("panel_id") != glass["id"] or op.get("disabled"):
            continue
        try:
            t = op.get("type", "hole")
            if t == "hole":
                d = float(op.get("d") or 0)
                if d <= 0:
                    continue
                x = resolve_x(op.get("x") or {}, w)
                y = resolve_y(op.get("y") or {}, h, gy, axes)
                segs.append({"t": "circle", "c": [x, y], "r": d / 2, "src": op["id"]})
            elif t == "group":
                mirror = op.get("mirror", "none")
                for it in expand_group(op):
                    d = float(it.get("d") or 0)
                    if d <= 0:
                        continue
                    x = resolve_x(it.get("x") or {}, w)
                    y = resolve_y(it.get("y") or {}, h, gy, axes)
                    pts = [(x, y)]
                    if mirror in ("x", "xy"):
                        pts.append((w - x, y))
                    if mirror in ("y", "xy"):
                        pts.append((x, h - y))
                    if mirror == "xy":
                        pts.append((w - x, h - y))
                    for px, py in pts:
                        segs.append({"t": "circle", "c": [px, py], "r": d / 2, "src": op["id"]})
            elif t == "cutout":
                cw, ch = float(op.get("w") or 0), float(op.get("h") or 0)
                if cw <= 0 or ch <= 0:
                    continue
                cx, cy = cutout_center(op, w, h, gy, axes)
                rad = float(op.get("r") or 0)
                # вырез у кромки продлеваем за кромку: скругляются только внутренние углы,
                # без «рожек» стекла на кромке
                x0, x1, y0, y1 = cx - cw / 2, cx + cw / 2, cy - ch / 2, cy + ch / 2
                ext = rad + 2.0
                if x0 <= 1e-6:
                    x0 -= ext
                if x1 >= w - 1e-6:
                    x1 += ext
                if y0 <= 1e-6:
                    y0 -= ext
                if y1 >= h - 1e-6:
                    y1 += ext
                cx, cy, cw, ch = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
                for s in rect_cut_segments(cx, cy, cw, ch, rad):
                    s["src"] = op["id"]
                    segs.append(s)
        except ValueError as e:
            warnings.append(f"{glass['name']}: обработка «{op.get('name') or op.get('type')}» — {e}")
    return segs
