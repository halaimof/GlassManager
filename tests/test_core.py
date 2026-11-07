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
