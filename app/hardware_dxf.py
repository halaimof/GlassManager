"""Импорт DXF фурнитуры: разбор в примитивы (мм) для просмотрщика и привязок."""
from __future__ import annotations

import math
from pathlib import Path

import ezdxf
from ezdxf import recover

from .geometry.prims import bbox_of, bulge_arc, norm_angle, snap_points

UNIT_SCALE = {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}


class DxfImportError(ValueError):
    pass


def _entity_segments(e, scale: float) -> list[dict]:
    t = e.dxftype()

    def P(v):
        return [float(v[0]) * scale, float(v[1]) * scale]

    if t == "LINE":
        return [{"t": "line", "p1": P(e.dxf.start), "p2": P(e.dxf.end)}]
    if t == "CIRCLE":
        return [{"t": "circle", "c": P(e.dxf.center), "r": float(e.dxf.radius) * scale}]
    if t == "ARC":
        return [{"t": "arc", "c": P(e.dxf.center), "r": float(e.dxf.radius) * scale,
                 "a0": norm_angle(float(e.dxf.start_angle)), "a1": norm_angle(float(e.dxf.end_angle))}]
    if t in ("LWPOLYLINE", "POLYLINE"):
        if t == "LWPOLYLINE":
            pts = [(float(x) * scale, float(y) * scale, float(b)) for x, y, _s, _e, b in e.get_points("xyseb")]
            closed = e.closed
        else:
            if e.is_3d_polyline or e.is_poly_face_mesh or e.is_polygon_mesh:
                return [{"t": "line", "p1": P(a), "p2": P(b)} for a, b in zip(list(e.points()), list(e.points())[1:])]
            pts = [(float(v.dxf.location[0]) * scale, float(v.dxf.location[1]) * scale, float(v.dxf.bulge or 0))
                   for v in e.vertices]
            closed = e.is_closed
        segs = []
        n = len(pts)
        rng = range(n if closed else n - 1)
        for i in rng:
            x1, y1, b = pts[i]
            x2, y2, _ = pts[(i + 1) % n]
            if abs(x2 - x1) < 1e-9 and abs(y2 - y1) < 1e-9:
                continue
            arc = bulge_arc((x1, y1), (x2, y2), b)
            segs.append(arc if arc else {"t": "line", "p1": [x1, y1], "p2": [x2, y2]})
        return segs
    if t in ("ELLIPSE", "SPLINE"):
        pts = [P(v) for v in e.flattening(0.01 / max(scale, 1e-9))]
        return [{"t": "line", "p1": a, "p2": b} for a, b in zip(pts, pts[1:])]
    return []


def parse_dxf(path: str | Path) -> dict:
    try:
        doc, _auditor = recover.readfile(str(path))
    except (IOError, ezdxf.DXFStructureError) as e:
        raise DxfImportError(f"Не удалось прочитать DXF: {e}") from e
    units = int(doc.header.get("$INSUNITS", 4) or 4)
    scale = UNIT_SCALE.get(units, 1.0)
    prims: list[dict] = []
    skipped: dict[str, int] = {}

    def add(e, pid):
        segs = _entity_segments(e, scale)
        if not segs:
            skipped[e.dxftype()] = skipped.get(e.dxftype(), 0) + 1
            return
        snaps = [s for seg in segs for s in snap_points(seg)]
        # для полилинии — вершины и середины сегментов, без дубликатов
        uniq = []
        for s in snaps:
            if not any(abs(s["p"][0] - u["p"][0]) < 1e-6 and abs(s["p"][1] - u["p"][1]) < 1e-6 and s["kind"] == u["kind"]
                       for u in uniq):
                uniq.append(s)
        prims.append({
            "id": pid,
            "etype": e.dxftype(),
            "layer": e.dxf.get("layer", "0"),
            "segs": segs,
            "snaps": uniq,
            "length": _length(segs),
        })

    for e in doc.modelspace():
        if e.dxftype() == "INSERT":
            for i, ve in enumerate(e.virtual_entities()):
                add(ve, f"{e.dxf.handle}.{i}")
        else:
            add(e, str(e.dxf.handle))
    if not prims:
        raise DxfImportError("В DXF не найдено поддерживаемых примитивов (LINE, ARC, CIRCLE, POLYLINE…)")
    allsegs = [s for p in prims for s in p["segs"]]
    bb = bbox_of(allsegs)
    return {"primitives": prims, "bbox": list(bb), "units": units, "skipped": skipped}


def _length(segs):
    total = 0.0
    for s in segs:
        if s["t"] == "line":
            total += math.hypot(s["p2"][0] - s["p1"][0], s["p2"][1] - s["p1"][1])
        elif s["t"] == "circle":
            total += 2 * math.pi * s["r"]
        else:
            sw = norm_angle(s["a1"] - s["a0"]) or 360
            total += math.radians(sw) * s["r"]
    return round(total, 3)
