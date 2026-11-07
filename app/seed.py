"""Начальное наполнение БД: категории, встроенные шаблоны конструкций и
небольшой демо-набор (помечен «Демо», его можно удалить или изменить).
Выполняется один раз; повторный запуск ничего не перезаписывает."""
from __future__ import annotations

import tempfile
from pathlib import Path

import ezdxf

from . import repo
from .db import new_id
from .engine.templates import builtin_templates

CATEGORIES = [
    "Петли", "Коннекторы", "Ручки", "Уплотнители", "П-образные профили", "Алюминиевые профили", "Штанги",
    "Стабилизационные штанги", "Крепления", "Стеклодержатели", "Раздвижные системы", "Треки", "Замки", "Комплекты",
]


def _demo_hinge_dxfs(tmpdir: Path) -> tuple[Path, Path]:
    """Сторона A (глухарь): два отверстия Ø16. Сторона B (дверь): фигурный вырез на кромке.
    Вертикальная линия на слое AUX — край стекла, точка (0, 0) — ось петли."""
    a = ezdxf.new("R2010")
    a.header["$INSUNITS"] = 4
    m = a.modelspace()
    a.layers.add("AUX", color=8)
    m.add_line((0, -80), (0, 80), dxfattribs={"layer": "AUX"})
    m.add_circle((-25, 22), 8)
    m.add_circle((-25, -22), 8)
    pa = tmpdir / "demo_hinge_A.dxf"
    a.saveas(pa)

    b = ezdxf.new("R2010")
    b.header["$INSUNITS"] = 4
    m = b.modelspace()
    b.layers.add("AUX", color=8)
    m.add_line((0, -80), (0, 80), dxfattribs={"layer": "AUX"})
    # вырез 20 × 65 с радиусами R10, открытая полилиния от кромки к кромке
    m.add_lwpolyline([(0, -32.5, 0), (10, -32.5, 0.41421356), (20, -22.5, 0), (20, 22.5, 0.41421356), (10, 32.5, 0),
                      (0, 32.5, 0)], format="xyb")
    pb = tmpdir / "demo_hinge_B.dxf"
    b.saveas(pb)
    return pa, pb


def seed() -> None:
    s = repo.settings_get()
    if s.get("seeded"):
        return
    from .api.library import store_dxf  # локальный импорт: избегаем цикла

    cats = {name: repo.lib_create("categories", name, {})["id"] for name in CATEGORIES}
    for t in builtin_templates():
        name = t.pop("name")
        repo.lib_create("construction_templates", name, t)

    man = repo.lib_create("manufacturers", "Демо-производитель", {"country": "", "site": "", "note": "Пример — можно удалить"})
    mid = man["id"]

    prof = repo.lib_create("profiles", "Демо П-профиль 20×15", {
        "manufacturer_id": mid, "article": "U-2015", "kind": "u", "color": "Хром",
        "thickness_min": 6, "thickness_max": 10, "depth": 20, "seat_depth": 15, "mounting_gap": 3,
        "adjust_range": 3, "length": 3000, "deduction": None,
    })

    with tempfile.TemporaryDirectory() as td:
        pa, pb = _demo_hinge_dxfs(Path(td))
        da = store_dxf(pa, "Демо петля 90° — сторона A", "demo_hinge_A.dxf")
        db_ = store_dxf(pb, "Демо петля 90° — сторона B", "demo_hinge_B.dxf")

    def aux_line(d):
        return next(p["id"] for p in d["data"]["primitives"] if p["layer"] == "AUX")

    def roles(d):
        return {p["id"]: ("aux" if p["layer"] == "AUX" else "op") for p in d["data"]["primitives"]}

    hinge = repo.lib_create("hardware", "Демо петля стекло–стекло 180°", {
        "manufacturer_id": mid, "category_id": cats["Петли"], "article": "DH-180", "color": "Хром",
        "connection": "glass-glass", "joint_gap": 4, "note": "",
        "sides": [
            {"key": "A", "label": "Неподвижное стекло", "dxf_id": da["id"], "roles": roles(da), "edge_pid": aux_line(da),
             "glass_side": "left", "anchor": [0, 0], "holes": []},
            {"key": "B", "label": "Дверь", "dxf_id": db_["id"], "roles": roles(db_), "edge_pid": aux_line(db_),
             "glass_side": "right", "anchor": [0, 0], "holes": []},
        ],
    })
    handle = repo.lib_create("hardware", "Демо ручка-скоба 300", {
        "manufacturer_id": mid, "category_id": cats["Ручки"], "article": "HD-300", "color": "Хром",
        "connection": "single", "joint_gap": None, "note": "Межосевое 300",
        "sides": [{"key": "A", "label": "Дверь", "dxf_id": None, "roles": {}, "edge_pid": None, "glass_side": "left",
                   "anchor": [0, 0], "holes": [{"u": 150, "v": 60, "d": 12}, {"u": -150, "v": 60, "d": 12}]}],
    })
    seal = repo.lib_create("hardware", "Демо уплотнитель магнитный 180°", {
        "manufacturer_id": mid, "category_id": cats["Уплотнители"], "article": "SM-180", "color": "Прозрачный",
        "connection": "single", "sides": [], "note": "Отрезается по высоте двери",
    })
    seal2 = repo.lib_create("hardware", "Демо уплотнитель нижний с капельником", {
        "manufacturer_id": mid, "category_id": cats["Уплотнители"], "article": "SB-01", "color": "Прозрачный",
        "connection": "single", "sides": [], "note": "",
    })
    repo.lib_create("kits", "Демо — душевая в проём (петли стекло–стекло)", {
        "manufacturer_id": mid, "color": "Хром",
        "description": "Петли между дверью и глухарём, глухарь в П-профиле у стены и на полу.",
        "gaps": {"glass_glass": 4, "door_floor": 12},
        "profiles": [{"target": "wall", "profile_id": prof["id"]}, {"target": "floor_fixed", "profile_id": prof["id"]}],
        "items": [
            {"id": new_id(), "model_id": hinge["id"], "placement": "hinge",
             "positions": [{"ref": "top", "offset": 250}, {"ref": "bottom", "offset": 246}]},
            {"id": new_id(), "model_id": handle["id"], "placement": "handle", "positions": [{"ref": "bottom", "offset": 1000}]},
            {"id": new_id(), "model_id": seal["id"], "placement": "none", "qty": 1, "length_formula": "H_door",
             "note": "Вертикальный, по двери"},
            {"id": new_id(), "model_id": seal2["id"], "placement": "none", "qty": 1, "length_formula": "W_door",
             "note": "Низ двери"},
        ],
    })
    repo.lib_create("op_templates", "РД-001 — раздвижная дверь", {
        "description": "Ø16 и Ø10 у левого края, зеркально справа",
        "items": [{
            "type": "group", "name": "Ролики", "mirror": "x", "repeat": {"count": 1, "step": 0, "dir": "v"},
            "items": [{"d": 16, "x": {"ref": "left", "value": 80}, "y": {"ref": "top", "value": 30}},
                      {"d": 10, "x": {"ref": "left", "value": 80}, "y": {"ref": "top", "value": 60}}],
        }],
    })
    repo.settings_set({"seeded": True, "company": {"name": "GlassCAD", "tagline": "Душевые кабины и стеклянные конструкции",
                                                   "phone": "", "email": "", "address": ""}})
