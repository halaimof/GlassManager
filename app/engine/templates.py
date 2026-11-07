"""Шаблоны конструкций и применение комплектов фурнитуры.

Шаблон конструкции — только геометрическая схема (стекла, правила ширины,
типы кромок). Комплект — фурнитура, профили, зазоры и правила установки.
Один шаблон работает с любым комплектом.
"""
from __future__ import annotations

import copy

from ..db import new_id
from .library import Library
from .model import default_edges, new_panel, normalize, remap_ids
from .resolve import DOOR_TYPES, _resolve_side_kinds


def _p(ptype, name, plane="front", width=None, left="auto", right="auto", x_formula="", bottom="floor"):
    p = new_panel(ptype, name)
    p["plane"] = plane
    if width:
        p["width"] = width
    p["edges"] = default_edges(left=left, right=right, bottom=bottom)
    p["x_formula"] = x_formula
    return p


def builtin_templates() -> list[dict]:
    door_w = {"mode": "value", "value": 600, "formula": ""}
    return [
        {"name": "Дверь + глухарь", "kind": "shower", "builtin_key": "door_fixed",
         "description": "Распашная дверь слева, глухарь справа. Петли стекло–стекло.",
         "panels": [_p("door", "Дверь", width=door_w), _p("fixed", "Глухарь")]},
        {"name": "Глухарь + дверь", "kind": "shower", "builtin_key": "fixed_door",
         "description": "Глухарь слева, распашная дверь справа.",
         "panels": [_p("fixed", "Глухарь"), _p("door", "Дверь", width=door_w)]},
        {"name": "Глухарь + дверь + глухарь", "kind": "shower", "builtin_key": "fixed_door_fixed",
         "description": "Дверь между двумя глухарями.",
         "panels": [_p("fixed", "Глухарь левый"), _p("door", "Дверь", width=door_w), _p("fixed", "Глухарь правый")]},
        {"name": "Раздвижная: стационар + дверь", "kind": "shower", "builtin_key": "sliding",
         "description": "Стационар у левой стены, раздвижная дверь с перехлёстом. Формулы можно менять.",
         "panels": [
             _p("stationary", "Стационар", width={"mode": "formula", "value": None, "formula": "A / 2"},
                left="wall", right="free"),
             _p("sliding_door", "Раздвижная дверь", width={"mode": "formula", "value": None, "formula": "A / 2 + 30"},
                left="free", right="wall", x_formula="L - dr - w"),
         ]},
        {"name": "Угловая: дверь + глухарь + боковое стекло", "kind": "shower", "builtin_key": "corner",
         "description": "Фронт: дверь и глухарь; боковая сторона — глухарь (ширина = глубина замера).",
         "panels": [_p("door", "Дверь", width=door_w), _p("fixed", "Глухарь фронт", right="free"),
                    _p("fixed", "Глухарь боковой", plane="side", left="free")]},
        {"name": "Одно стекло (walk-in)", "kind": "shower", "builtin_key": "walkin",
         "description": "Неподвижное стекло от стены, свободный край.",
         "panels": [_p("fixed", "Стекло", width={"mode": "value", "value": 900, "formula": ""}, right="free")]},
        {"name": "Зеркало / произвольное стекло", "kind": "mirror", "builtin_key": "single",
         "description": "Отдельное стекло, размеры вручную.",
         "panels": [_p("mirror", "Зеркало", width={"mode": "value", "value": 800, "formula": ""},
                       left="free", right="free", bottom="free")]},
    ]


def template_from_product(data: dict) -> dict:
    """Сохранить изделие как шаблон: структура, правила, обработка — без замера."""
    d = normalize(data)
    keep = {k: copy.deepcopy(d[k]) for k in ("panels", "axes", "hardware", "operations", "extra_items", "gaps", "settings")}
    return keep


def apply_template(data: dict, tmpl: dict) -> dict:
    data = normalize(data)
    t = remap_ids({k: copy.deepcopy(tmpl.get(k) or []) for k in ("panels", "axes", "hardware", "operations", "extra_items")})
    for k in ("panels", "axes", "hardware", "operations", "extra_items"):
        data[k] = t[k]
    if tmpl.get("gaps"):
        data["gaps"].update(tmpl["gaps"])
    if tmpl.get("settings"):
        meas_independent = {k: v for k, v in tmpl["settings"].items()}
        data["settings"].update(meas_independent)
    data["template_id"] = tmpl.get("id")
    return normalize(data)


# ------------------------------------------------------------------ комплекты
def _neighbors(data: dict):
    """Соседи в потоке для каждого стекла: {id: {"left": panel|None, "right": panel|None}}."""
    out = {}
    planes = {}
    for p in data["panels"]:
        planes.setdefault(p.get("plane", "front"), []).append(p)
    for plist in planes.values():
        _resolve_side_kinds(plist)
        flow = [p for p in plist if not (p.get("x_formula") or "").strip()]
        for i, p in enumerate(flow):
            out[p["id"]] = {"left": flow[i - 1] if i > 0 else None, "right": flow[i + 1] if i < len(flow) - 1 else None}
        for p in plist:
            out.setdefault(p["id"], {"left": None, "right": None})
    return out


def _hinge_side(door: dict, nb: dict) -> tuple[str, dict | None]:
    """Кромка двери, на которой петли, и соседнее стекло (или None — стена)."""
    for side in ("left", "right"):
        n = nb[side]
        if n is not None and n["type"] not in DOOR_TYPES:
            return side, n
    for side in ("left", "right"):
        if door.get("_kind_" + side) == "wall":
            return side, None
    return "left", None


OPP = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}


def apply_kit(data: dict, kit: dict, lib: Library) -> dict:
    data = normalize(data)
    kid = kit.get("id")
    data["kit_id"] = kid
    data["hardware"] = [h for h in data["hardware"] if not h.get("from_kit")]
    data["extra_items"] = [h for h in data["extra_items"] if not h.get("from_kit")]
    if kit.get("gaps"):
        data["gaps"].update({k: v for k, v in kit["gaps"].items() if v not in (None, "")})
    if kit.get("color"):
        data["settings"]["hardware_color"] = kit["color"]
    nbs = _neighbors(data)

    # Профили на кромки
    for rule in kit.get("profiles") or []:
        pid = rule.get("profile_id")
        target = rule.get("target")
        for p in data["panels"]:
            is_door = p["type"] in DOOR_TYPES
            if target == "wall":
                for side in ("left", "right"):
                    if p.get("_kind_" + side) == "wall" and not is_door:
                        p["edges"][side]["profile_id"] = pid
            elif target == "floor_fixed" and not is_door and p["edges"]["bottom"].get("kind") == "floor":
                p["edges"]["bottom"]["profile_id"] = pid
            elif target == "top":
                p["edges"]["top"]["profile_id"] = pid

    def add_inst(model_id, targets, pos, item):
        data["hardware"].append({
            "id": new_id(), "model_id": model_id, "targets": targets,
            "pos": {"ref": pos.get("ref", "top"), "offset": float(pos.get("offset") or 0), "axis_id": None},
            "flip": bool(item.get("flip")), "qty": int(item.get("qty") or 1), "from_kit": kid,
        })

    for item in kit.get("items") or []:
        model = lib.get("hardware", item.get("model_id"))
        placement = item.get("placement", "none")
        positions = item.get("positions") or [{"ref": "center", "offset": 0}]
        if placement == "none" or not model:
            data["extra_items"].append({
                "id": new_id(), "model_id": item.get("model_id"), "profile_id": item.get("profile_id"),
                "name": item.get("name") or "", "qty": item.get("qty") or 1,
                "length_formula": item.get("length_formula") or "", "note": item.get("note") or "",
                "from_kit": kid,
            })
            continue
        nsides = len(model.get("sides") or [])
        for p in data["panels"]:
            is_door = p["type"] in DOOR_TYPES
            nb = nbs[p["id"]]
            if placement == "hinge" and p["type"] == "door":
                side, other = _hinge_side(p, nb)
                if other is not None and nsides >= 2:
                    targets = {"A": {"panel_id": other["id"], "edge": OPP[side]}, "B": {"panel_id": p["id"], "edge": side}}
                else:
                    targets = {"A": {"panel_id": p["id"], "edge": side}}
                for pos in positions:
                    add_inst(model["id"], targets, pos, item)
            elif placement == "handle" and is_door:
                side, _ = _hinge_side(p, nb) if p["type"] == "door" else ("left", None)
                edge = OPP[side] if p["type"] == "door" else ("left" if p.get("_kind_right") == "wall" else "right")
                for pos in positions:
                    add_inst(model["id"], {"A": {"panel_id": p["id"], "edge": edge}}, pos, item)
            elif placement == "wall_connector" and not is_door:
                for side in ("left", "right"):
                    if p.get("_kind_" + side) == "wall":
                        for pos in positions:
                            add_inst(model["id"], {"A": {"panel_id": p["id"], "edge": side}}, pos, item)
            elif placement == "floor" and not is_door and p["edges"]["bottom"].get("kind") == "floor":
                for pos in positions:
                    add_inst(model["id"], {"A": {"panel_id": p["id"], "edge": "bottom"}}, pos, item)
            elif placement == "door_edge" and is_door:
                for pos in positions:
                    add_inst(model["id"], {"A": {"panel_id": p["id"], "edge": item.get("edge", "bottom")}}, pos, item)
    for p in data["panels"]:
        for k in [k for k in p if k.startswith("_")]:
            p.pop(k)
    return data
