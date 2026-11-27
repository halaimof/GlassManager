"""Тесты ядра: геометрия, расчёт душевой, обработка, фурнитура, экспорт."""
import io
import math
import os
import tempfile

os.environ.setdefault("GLASSCAD_DATA", tempfile.mkdtemp(prefix="glasscad-test-"))

import ezdxf  # noqa: E402
import pytest  # noqa: E402

from app.engine import Library, resolve  # noqa: E402
from app.engine.model import new_panel  # noqa: E402
from app.engine.templates import apply_kit, apply_template, builtin_templates  # noqa: E402
from app.export.dxf_export import glass_dxf  # noqa: E402
from app.geometry.contour import build_contour  # noqa: E402
from app.geometry.formula import FormulaError, eval_formula  # noqa: E402
from app.geometry.quad import GeometryError, solve_quad  # noqa: E402


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ------------------------------------------------------------------ геометрия
def test_quad_sides_and_right_angle():
    bl, br, tr, tl = solve_quad(710, 970, 760, 950, "tl")
    assert dist(tl, tr) == pytest.approx(710)
    assert dist(tr, br) == pytest.approx(970)
    assert dist(br, bl) == pytest.approx(760)
    assert dist(bl, tl) == pytest.approx(950)
    v1 = (tr[0] - tl[0], tr[1] - tl[1])
    v2 = (bl[0] - tl[0], bl[1] - tl[1])
    assert v1[0] * v2[0] + v1[1] * v2[1] == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize("corner", ["tr", "bl", "br"])
def test_quad_other_corners(corner):
    pts = solve_quad(700, 1000, 740, 980, corner)
    names = ["bl", "br", "tr", "tl"]
    i = names.index(corner)
    p, a, b = pts[i], pts[(i + 1) % 4], pts[(i - 1) % 4]
    dot = (a[0] - p[0]) * (b[0] - p[0]) + (a[1] - p[1]) * (b[1] - p[1])
    assert dot == pytest.approx(0, abs=1e-6)


def test_quad_impossible():
    with pytest.raises(GeometryError):
        solve_quad(100, 100, 1000, 100, "tl")


def test_formula():
    assert eval_formula("L / 2 + 30", {"L": 1200}) == 630
    assert eval_formula("min(A, 900)", {"A": 1000}) == 900
    with pytest.raises(FormulaError):
        eval_formula("__import__('os')", {})
    with pytest.raises(FormulaError):
        eval_formula("X + 1", {})


def test_edge_cutout_changes_contour_and_keeps_arcs():
    segs = [{"t": "line", "p1": [500, 400], "p2": [480, 400]},
            {"t": "arc", "c": [480, 430], "r": 30, "a0": 90, "a1": 270},
            {"t": "line", "p1": [480, 460], "p2": [500, 460]},
            {"t": "circle", "c": [100, 100], "r": 8}]
    r = build_contour([(0, 0), (500, 0), (500, 1000), (0, 1000)], segs)
    xs = {round(v[0], 3) for v in r["contour"]}
    assert 480.0 in xs                                  # вырез вошёл в контур
    assert any(abs(v[2]) > 0.9 for v in r["contour"])   # полуокружность сохранена как дуга (bulge≈−1)
    assert len(r["holes"]) == 1                          # внутреннее отверстие не меняет контур
    assert r["area"] == pytest.approx(500 * 1000 - (20 * 60 + math.pi * 30 ** 2 / 2), rel=1e-4)


# ------------------------------------------------------------------ расчёт душевой
def tmpl(key):
    t = next(t for t in builtin_templates() if t["builtin_key"] == key)
    return apply_template({"measurement": {"width_top": 1200, "width_bottom": 1203, "height_left": 2200}}, t)


def test_door_fixed_common_top_and_gaps():
    data = tmpl("door_fixed")
    res = resolve(data, Library())
    door, fixed = res["glasses"]
    assert door["w"] == 600
    assert fixed["w"] == pytest.approx(1200 - 600 - 4)
    assert door["y"] + door["h"] == fixed["y"] + fixed["h"] == 2000  # общий верх
    assert door["h"] == 1988                                          # перепад снизу (12 мм)
    assert not res["errors"]


def test_profile_deduction_reduces_glass():
    lib = Library({"profiles": {"p": {"id": "p", "name": "U", "data": {"depth": 20, "seat_depth": 15, "mounting_gap": 3}}}})
    data = tmpl("door_fixed")
    data["panels"][1]["edges"]["right"]["profile_id"] = "p"
    data["panels"][1]["edges"]["bottom"]["profile_id"] = "p"
    res = resolve(data, lib)
    fixed = res["glasses"][1]
    assert fixed["w"] == pytest.approx(1200 - 600 - 4 - 8)
    assert fixed["h"] == pytest.approx(2000 - 8)
    assert res["bom"]["hardware"][0]["kind"] == "profile"


def test_manual_override_wins():
    data = tmpl("door_fixed")
    data["panels"][1]["width_override"] = 555.5
    res = resolve(data, Library())
    assert res["glasses"][1]["w"] == 555.5


def test_sliding_formulas():
    data = tmpl("sliding")
    res = resolve(data, Library())
    st, door = res["glasses"]
    assert st["w"] == 600 and door["w"] == 630
    assert door["x"] + door["w"] == pytest.approx(1200)


def test_corner_two_planes():
    data = tmpl("corner")
    data["measurement"]["depth"] = 900
    res = resolve(data, Library())
    side = [g for g in res["glasses"] if g["plane"] == "side"][0]
    assert side["w"] == 900
    assert len(res["planes"]) == 2


# ------------------------------------------------------------------ обработка
def test_hole_keeps_offset_from_right_edge_after_resize():
    data = tmpl("door_fixed")
    door = data["panels"][0]
    data["operations"] = [{"id": "h1", "panel_id": door["id"], "type": "hole", "d": 12,
                           "x": {"ref": "right", "value": 60}, "y": {"ref": "top", "value": 100}}]
    for w in (600, 720):
        door["width"]["value"] = w
        g = resolve(data, Library())["glasses"][0]
        assert g["holes"][0]["c"] == pytest.approx([w - 60, g["h"] - 100])


def test_group_mirror_and_repeat():
    data = tmpl("sliding")
    sd = data["panels"][1]
    data["operations"] = [{"id": "g", "panel_id": sd["id"], "type": "group", "mirror": "x",
                           "repeat": {"count": 2, "step": 50, "dir": "v"},
                           "items": [{"d": 16, "x": {"ref": "left", "value": 80}, "y": {"ref": "top", "value": 30}}]}]
    g = resolve(data, Library())["glasses"][1]
    cs = sorted((round(h["c"][0], 3), round(h["c"][1], 3)) for h in g["holes"])
    w, hh = g["w"], g["h"]
    assert cs == sorted([(80, hh - 30), (80, hh - 80), (w - 80, hh - 30), (w - 80, hh - 80)])


def test_axis_binding():
    data = tmpl("door_fixed")
    data["axes"] = [{"id": "ax", "name": "Ось петли", "ref": "top", "offset": 250}]
    data["operations"] = [{"id": "h", "panel_id": data["panels"][0]["id"], "type": "hole", "d": 10,
                           "x": {"ref": "left", "value": 50}, "y": {"ref": "axis", "value": 0, "axis_id": "ax"}}]
    res = resolve(data, Library())
    door = res["glasses"][0]
    assert door["holes"][0]["c"][1] + door["y"] == pytest.approx(2000 - 250)


# ------------------------------------------------------------------ фурнитура
def _hinge_lib():
    prims_a = [{"id": "e", "segs": [{"t": "line", "p1": [0, -80], "p2": [0, 80]}], "snaps": []},
               {"id": "c1", "segs": [{"t": "circle", "c": [-25, 22], "r": 8}], "snaps": []}]
    prims_b = [{"id": "e", "segs": [{"t": "line", "p1": [0, -80], "p2": [0, 80]}], "snaps": []},
               {"id": "n", "segs": [{"t": "line", "p1": [0, -30], "p2": [20, -30]}, {"t": "line", "p1": [20, -30], "p2": [20, 30]},
                                    {"t": "line", "p1": [20, 30], "p2": [0, 30]}], "snaps": []}]
    hinge = {"id": "hg", "name": "Петля", "data": {"connection": "glass-glass", "joint_gap": 5, "sides": [
        {"key": "A", "dxf_id": "da", "roles": {"e": "aux"}, "edge_pid": "e", "glass_side": "left", "anchor": [0, 0]},
        {"key": "B", "dxf_id": "db", "roles": {"e": "aux"}, "edge_pid": "e", "glass_side": "right", "anchor": [0, 0]}]}}
    kit = {"id": "k", "items": [{"model_id": "hg", "placement": "hinge", "positions": [{"ref": "top", "offset": 250}]}]}
    return Library({"hardware": {"hg": hinge}}, {"da": {"data": {"primitives": prims_a}}, "db": {"data": {"primitives": prims_b}}}), kit


def test_hinge_applies_both_sides_and_gap():
    lib, kit = _hinge_lib()
    data = apply_kit(tmpl("fixed_door"), kit, lib)
    res = resolve(data, lib)
    fixed, door = res["glasses"]
    assert door["x"] - (fixed["x"] + fixed["w"]) == pytest.approx(5)  # зазор петли из базы
    assert len(fixed["holes"]) == 1                                   # сторона A — отверстие на глухаре
    hx, hy = fixed["holes"][0]["c"]
    assert hx == pytest.approx(fixed["w"] - 25)
    assert hy + fixed["y"] == pytest.approx(2000 - 250 + 22)
    xs = [v[0] for v in door["contour"]]
    assert min(xs) == pytest.approx(0) and any(abs(x - 20) < 1e-6 for x in xs)  # вырез на левой кромке двери
    assert door["cut_boxes"]


def test_dxf_export_layers_and_scale():
    lib, kit = _hinge_lib()
    res = resolve(apply_kit(tmpl("fixed_door"), kit, lib), lib)
    g = res["glasses"][1]
    raw = glass_dxf(g, axes=res["axes"])
    doc = ezdxf.read(io.StringIO(raw.decode("utf-8")))
    msp = doc.modelspace()
    layers = {e.dxf.layer for e in msp}
    assert {"GLASS", "DIM", "TEXT"} <= layers
    assert "AUX" not in layers
    poly = next(e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "GLASS")
    xs = [p[0] for p in poly.get_points("xy")]
    ys = [p[1] for p in poly.get_points("xy")]
    assert max(xs) - min(xs) == pytest.approx(g["w"])
    assert max(ys) - min(ys) == pytest.approx(g["h"])


def test_dxf_import_roundtrip(tmp_path):
    from app.hardware_dxf import parse_dxf
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    m = doc.modelspace()
    m.add_line((0, 0), (0, 100), dxfattribs={"layer": "AUX"})
    m.add_lwpolyline([(0, 0, 0), (10, 0, 1), (10, 20, 0), (0, 20, 0)], format="xyb")
    m.add_circle((5, 50), 8)
    f = tmp_path / "x.dxf"
    doc.saveas(f)
    r = parse_dxf(f)
    kinds = sorted(p["etype"] for p in r["primitives"])
    assert kinds == ["CIRCLE", "LINE", "LWPOLYLINE"]
    poly = next(p for p in r["primitives"] if p["etype"] == "LWPOLYLINE")
    arc = next(s for s in poly["segs"] if s["t"] == "arc")
    assert arc["r"] == pytest.approx(10) and arc["c"] == pytest.approx([10, 10])
    labels = {s["label"] for p in r["primitives"] for s in p["snaps"]}
    assert {"Центр", "Середина", "Конечная точка"} <= labels


def test_new_panel_has_stable_id():
    p = new_panel("door")
    assert len(p["id"]) == 32 and p["name"] == "Дверь"


def test_cutout_anchor_edge_and_flush_notch():
    data = tmpl("door_fixed")
    door = data["panels"][0]
    # новый вырез: правый край вплотную к кромке, верх выреза в 300 мм от верха
    data["operations"] = [{"id": "c", "panel_id": door["id"], "type": "cutout", "w": 20, "h": 63, "r": 5,
                           "anchor": {"x": "edge", "y": "edge"},
                           "x": {"ref": "right", "value": 0}, "y": {"ref": "top", "value": 300}}]
    g = resolve(data, Library())["glasses"][0]
    x0, y0, x1, y1 = g["cut_boxes"][0]
    assert (x0, x1) == pytest.approx((g["w"] - 20, g["w"]))
    assert (y0, y1) == pytest.approx((g["h"] - 363, g["h"] - 300))
    # на кромке нет «рожек»: точки контура на правой кромке только вне выреза
    on_edge = [v[1] for v in g["contour"] if abs(v[0] - g["w"]) < 1e-6]
    assert all(y <= y0 + 1e-6 or y >= y1 - 1e-6 for y in on_edge)
    # размерная цепочка по Y справа идёт до краёв выреза: 300 и 63
    texts = [d["text"] for d in g["dims"] if d["t"] == "lin" and d["side"] == "right" and d["level"] == 1]
    assert "300" in texts and "63" in texts


def test_cutout_without_anchor_keeps_old_center_behaviour():
    data = tmpl("door_fixed")
    door = data["panels"][0]
    data["operations"] = [{"id": "c", "panel_id": door["id"], "type": "cutout", "w": 40, "h": 60, "r": 0,
                           "x": {"ref": "right", "value": 0}, "y": {"ref": "top", "value": 300}}]
    g = resolve(data, Library())["glasses"][0]
    x0, y0, x1, y1 = g["cut_boxes"][0]
    assert x0 == pytest.approx(g["w"] - 20) and (y1 - y0) == pytest.approx(60)


def test_edge_line_marked_as_processing_does_not_inflate_cut_size():
    segs = [{"t": "line", "p1": [500, 400], "p2": [480, 400]}, {"t": "line", "p1": [480, 400], "p2": [480, 463]},
            {"t": "line", "p1": [480, 463], "p2": [500, 463]}, {"t": "line", "p1": [500, 392.5], "p2": [500, 470.5]}]
    r = build_contour([(0, 0), (500, 0), (500, 1000), (0, 1000)], segs)
    assert [b[3] - b[1] for b in r["cut_boxes"]] == [pytest.approx(63)]


def test_dimension_layout_outside_and_without_overlaps():
    from app.export.dimlayout import layout_dims, ops_extent, text_w

    lib, kit = _hinge_lib()
    data = apply_kit(tmpl("fixed_door"), kit, lib)
    data["operations"] = [{"id": "g", "panel_id": data["panels"][1]["id"], "type": "group", "mirror": "x",
                           "repeat": {"count": 3, "step": 8, "dir": "v"},
                           "items": [{"d": 10, "x": {"ref": "left", "value": 40}, "y": {"ref": "top", "value": 30}}]}]
    res = resolve(data, lib)
    for g in res["glasses"]:
        th = 12.0
        ops = layout_dims(g["dims"], (0, 0, g["w"], g["h"]), th * 3, th, th * 0.8)
        boxes = []
        for op in ops:
            if op[0] != "text":
                continue
            (x, y), text, ang, al_ = op[1], op[2], op[3], op[5]
            w = text_w(text, op[4])
            if ang == 90:
                box = (x - th * 0.75, y - w / 2, x, y + w / 2)
            elif al_ == "left":
                box = (x, y, x + w, y + th * 0.75)
            elif al_ == "right":
                box = (x - w, y, x, y + th * 0.75)
            else:
                box = (x - w / 2, y, x + w / 2, y + th * 0.75)
            if op[3] in (0, 90):
                # текст размеров — снаружи стекла
                assert box[2] <= 0 + 1e-6 or box[0] >= g["w"] - 1e-6 or box[3] <= 0 + 1e-6 or box[1] >= g["h"] - 1e-6, (text, box)
            boxes.append((box, text))
        for i, (a, ta) in enumerate(boxes):
            for b, tb in boxes[i + 1:]:
                overlap = min(a[2], b[2]) - max(a[0], b[0]) > 0.5 and min(a[3], b[3]) - max(a[1], b[1]) > 0.5
                assert not overlap, (ta, a, tb, b)
        assert ops_extent(ops, th)


def _corner_lib():
    con = {"id": "con", "name": "21-062", "data": {"connection": "glass-glass", "sides": [
        {"key": "A", "label": "Стекло 1", "cutouts": [{"u": 0, "depth": 24, "h": 20, "r": 10}]},
        {"key": "B", "label": "Стекло 2", "edge_deduction": 12}]}}
    kit = {"id": "k", "items": [{"model_id": "con", "placement": "corner",
                                 "positions": [{"ref": "top", "offset": 150}, {"ref": "bottom", "offset": 150}]}]}
    return Library({"hardware": {"con": con}}), kit


def test_corner_connector_parametric_cutout_and_deduction():
    lib, kit = _corner_lib()
    data = tmpl("corner")
    data["measurement"]["depth"] = 900
    data = apply_kit(data, kit, lib)
    assert len(data["hardware"]) == 2
    data["settings"]["node_details"] = True
    res = resolve(data, lib)
    front = [g for g in res["glasses"] if g["plane"] == "front"][-1]
    side = [g for g in res["glasses"] if g["plane"] == "side"][0]
    assert side["w"] == pytest.approx(900 - 12)               # вычет стороны B на угловой кромке
    assert len(front["cut_boxes"]) == 2
    x0, y0, x1, y1 = front["cut_boxes"][0]
    assert (x1 - x0, y1 - y0) == (pytest.approx(24), pytest.approx(20))
    assert (y0 + y1) / 2 == pytest.approx(150)                 # центр выреза — на оси узла
    # полукруг R10 сохранён дугами (не ломаной): суммарно 180° на каждый вырез
    import math as _m
    sweep = sum(4 * _m.degrees(_m.atan(abs(v[2]))) for v in front["contour"] if abs(v[2]) > 1e-9)
    assert sweep == pytest.approx(360, abs=0.01)
    nodes = res["nodes"]
    assert len(nodes) == 1 and nodes[0]["qty"] == 2 and len(nodes[0]["positions"]) == 2
    texts = {d.get("text") for d in nodes[0]["views"][0]["dims"]}
    assert {"24", "20", "R10"} <= texts


def test_node_details_off_by_default():
    lib, kit = _corner_lib()
    data = apply_kit(tmpl("corner"), kit, lib)
    assert resolve(data, lib)["nodes"] == []
