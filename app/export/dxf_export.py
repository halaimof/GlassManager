"""Экспорт DXF 1:1 в мм. Слои: GLASS, CUT, HOLES, AXIS, DIM, TEXT, AUX.

Вспомогательная геометрия из DXF фурнитуры сюда не попадает: движок
передаёт только примитивы с ролью «обработка».
"""
from __future__ import annotations

import io

import ezdxf
from ezdxf.enums import TextEntityAlignment

from .dimlayout import layout_dims

LAYERS = {
    "GLASS": 7,   # белый/чёрный
    "CUT": 1,     # красный
    "HOLES": 5,   # синий
    "AXIS": 4,    # голубой
    "DIM": 3,     # зелёный
    "TEXT": 2,    # жёлтый
    "AUX": 8,     # серый
}


def _new_doc():
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # мм
    doc.header["$MEASUREMENT"] = 1
    for name, color in LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    doc.layers.get("AXIS").dxf.linetype = "CENTER" if "CENTER" in doc.linetypes else "Continuous"
    if "GlassCAD" not in doc.styles:
        doc.styles.add("GlassCAD", font="DejaVuSans.ttf")
    return doc


def _seg_to_dxf(msp, s: dict, dx: float, dy: float, layer: str):
    if s["t"] == "line":
        msp.add_line((s["p1"][0] + dx, s["p1"][1] + dy), (s["p2"][0] + dx, s["p2"][1] + dy), dxfattribs={"layer": layer})
    elif s["t"] == "arc":
        msp.add_arc((s["c"][0] + dx, s["c"][1] + dy), s["r"], s["a0"], s["a1"], dxfattribs={"layer": layer})
    elif s["t"] == "circle":
        msp.add_circle((s["c"][0] + dx, s["c"][1] + dy), s["r"], dxfattribs={"layer": layer})


def draw_glass(msp, g: dict, dx: float = 0.0, dy: float = 0.0, with_dims: bool = True, axes: list | None = None,
               label: str | None = None):
    pts = [(x + dx, y + dy, 0, 0, b) for x, y, b in g["contour"]]
    msp.add_lwpolyline(pts, format="xyseb", close=True, dxfattribs={"layer": "GLASS"})
    for h in g.get("holes", []):
        msp.add_circle((h["c"][0] + dx, h["c"][1] + dy), h["r"], dxfattribs={"layer": "HOLES"})
    for chain in g.get("inner", []) + g.get("open", []):
        for s in chain:
            _seg_to_dxf(msp, s, dx, dy, "CUT")
    for ring in g.get("rings", []):
        msp.add_lwpolyline([(x + dx, y + dy) for x, y in ring], close=True, dxfattribs={"layer": "CUT"})
    w, h = g["w"], g["h"]
    th = max(12.0, min(40.0, max(w, h) * 0.018))
    S = th * 3.2
    for a in axes or []:
        ly = a["y"] - g["y"]
        if -1 < ly < h + 1:
            msp.add_line((dx - S * 0.4, ly + dy), (w + dx + S * 0.4, ly + dy), dxfattribs={"layer": "AXIS"})
    if with_dims:
        for op in layout_dims(g.get("dims", []), (0, 0, w, h), S, th):
            if op[0] == "line":
                msp.add_line((op[1][0] + dx, op[1][1] + dy), (op[2][0] + dx, op[2][1] + dy), dxfattribs={"layer": "DIM"})
            elif op[0] == "arrow":
                (tx, ty), (ux, uy) = op[1], op[2]
                al, aw = th * 0.7, th * 0.18
                bx, by = tx - ux * al, ty - uy * al
                px, py = -uy * aw, ux * aw
                msp.add_solid([(tx + dx, ty + dy), (bx + px + dx, by + py + dy), (bx - px + dx, by - py + dy)],
                              dxfattribs={"layer": "DIM"})
            elif op[0] == "text":
                _, (x, y), text, ang, hh, align = op
                t = msp.add_text(text, height=hh, rotation=ang, dxfattribs={"layer": "DIM", "style": "GlassCAD"})
                t.set_placement((x + dx, y + dy), align=TextEntityAlignment.BOTTOM_CENTER if align == "center"
                                else TextEntityAlignment.BOTTOM_LEFT)
    if label:
        t = msp.add_text(label, height=th, dxfattribs={"layer": "TEXT", "style": "GlassCAD"})
        t.set_placement((dx, dy - S * 3.2), align=TextEntityAlignment.BOTTOM_LEFT)


def glass_label(g: dict, order_no: str = "", part_no: str = "") -> str:
    parts = [f"Заказ {order_no}" if order_no else "", f"Деталь {part_no}" if part_no else "",
             g["name"], f"{_n(g['w'])}x{_n(g['h'])}x{_n(g['thickness'])}", g.get("color") or ""]
    return "  ".join(p for p in parts if p)


def _n(v):
    return str(int(round(v))) if abs(v - round(v)) < 0.05 else f"{v:.1f}"


def glass_dxf(g: dict, *, axes=None, with_dims=True, order_no="", part_no="") -> bytes:
    doc = _new_doc()
    draw_glass(doc.modelspace(), g, axes=axes, with_dims=with_dims, label=glass_label(g, order_no, part_no))
    return _to_bytes(doc)


def product_dxf(resolved: dict, *, with_dims=True, order_no="") -> bytes:
    doc = _new_doc()
    msp = doc.modelspace()
    planes = {p["key"]: p for p in resolved.get("planes", [])}
    for g in resolved["glasses"]:
        dx = g["x"] + planes.get(g["plane"], {"dx": 0})["dx"]
        draw_glass(msp, g, dx=dx, dy=g["y"], with_dims=False, label=None)
    for pl in planes.values():
        outline = resolved["opening"].get("outline") if pl["key"] == "front" else None
        if outline:
            msp.add_lwpolyline([(x + pl["dx"], y) for x, y in outline], close=True, dxfattribs={"layer": "AUX"})
    if with_dims:
        allx = [g["x"] + planes[g["plane"]]["dx"] for g in resolved["glasses"]]
        if allx:
            maxx = max(g["x"] + planes[g["plane"]]["dx"] + g["w"] for g in resolved["glasses"])
            maxy = max(g["y"] + g["h"] for g in resolved["glasses"])
            th = max(15.0, maxx * 0.012)
            for op in layout_dims(resolved.get("dims", []), (0, 0, maxx, maxy), th * 3.2, th):
                if op[0] == "line":
                    msp.add_line(op[1], op[2], dxfattribs={"layer": "DIM"})
                elif op[0] == "text":
                    _, (x, y), text, ang, hh, align = op
                    t = msp.add_text(text, height=hh, rotation=ang, dxfattribs={"layer": "DIM", "style": "GlassCAD"})
                    t.set_placement((x, y), align=TextEntityAlignment.BOTTOM_CENTER)
    return _to_bytes(doc)


def _to_bytes(doc) -> bytes:
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")

