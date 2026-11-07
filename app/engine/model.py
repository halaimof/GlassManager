"""Структура данных изделия и значения по умолчанию.

Все размеры — в мм. Система координат изделия: начало — левый нижний угол
проёма (пол у левой стены), ось Y вверх. Каждое стекло имеет свои локальные
координаты: начало в левом нижнем углу его габарита.
"""
from __future__ import annotations

import copy
from typing import Any

from ..db import new_id

PANEL_TYPES = {
    "door": "Дверь",
    "fixed": "Глухарь",
    "stationary": "Стационар",
    "sliding_door": "Раздвижная дверь",
    "mirror": "Зеркало",
    "other": "Другое",
}

DEFAULT_GAPS = {
    "glass_glass": 4.0,   # стекло ↔ стекло
    "door_floor": 12.0,   # дверь ↔ пол
    "fixed_floor": 0.0,   # глухарь ↔ пол (без профиля)
    "wall": 0.0,          # стекло ↔ стена (без профиля/фурнитуры)
    "top": 0.0,           # верх стекла ↔ верх проёма
}

DEFAULT_SETTINGS = {
    "common_top": True,
    "top_mode": "fixed",        # fixed — высота стекол задаётся; opening — по высоте проёма
    "top_height": 2000.0,
    "thickness": 8.0,
    "color": "Прозрачное",
    "glass_type": "Закалённое",
    "tempered": True,
    "edge_work": "Шлифовка + полировка",
    "hardware_color": "Хром",
    "dim_side": "auto",         # auto | left | right
}

DEFAULT_MEASUREMENT = {
    "width_top": None,
    "width_mid": None,
    "width_bottom": None,
    "height_left": None,
    "height_right": None,
    "depth": None,  # для угловой: ширина боковой стороны
}


def default_edges(left="auto", right="auto", top="free", bottom="floor") -> dict:
    return {
        "left": {"kind": left, "profile_id": None, "override": None},
        "right": {"kind": right, "profile_id": None, "override": None},
        "top": {"kind": top, "profile_id": None, "override": None},
        "bottom": {"kind": bottom, "profile_id": None, "override": None},
    }


def new_panel(ptype: str = "fixed", name: str | None = None, **kw) -> dict:
    p = {
        "id": new_id(),
        "name": name or PANEL_TYPES.get(ptype, "Стекло"),
        "type": ptype,
        "plane": "front",
        "width": {"mode": "auto", "value": None, "formula": ""},
        "width_override": None,
        "height_override": None,
        "x_formula": "",
        "y_override": None,
        "align_top_with": None,
        "edges": default_edges(),
        "shape": {"type": "rect"},
        "thickness": None,
        "color": None,
        "glass_type": None,
        "tempered": None,
        "edge_work": None,
        "qty": 1,
        "note": "",
    }
    for k, v in kw.items():
        p[k] = v
    return p


def empty_product_data() -> dict:
    return {
        "mode": "quick",
        "measurement": dict(DEFAULT_MEASUREMENT),
        "settings": dict(DEFAULT_SETTINGS),
        "gaps": dict(DEFAULT_GAPS),
        "template_id": None,
        "kit_id": None,
        "panels": [],
        "axes": [],
        "hardware": [],
        "operations": [],
        "extra_items": [],
    }


def normalize(data: dict | None) -> dict:
    """Дополняет данные изделия значениями по умолчанию (обратная совместимость)."""
    base = empty_product_data()
    data = copy.deepcopy(data or {})
    for k, v in base.items():
        if k not in data or data[k] is None:
            data[k] = v
        elif isinstance(v, dict):
            merged = dict(v)
            merged.update({kk: vv for kk, vv in data[k].items()})
            data[k] = merged
    for p in data["panels"]:
        tmpl = new_panel(p.get("type", "fixed"))
        for k, v in tmpl.items():
            if k not in p:
                p[k] = v
        edges = p.get("edges") or {}
        for side, e in default_edges().items():
            cur = edges.get(side) or {}
            merged = dict(e)
            merged.update(cur)
            edges[side] = merged
        p["edges"] = edges
        if not isinstance(p.get("width"), dict):
            p["width"] = {"mode": "auto", "value": None, "formula": ""}
    return data


def remap_ids(data: dict) -> dict:
    """Создаёт новые внутренние ID для стекол/осей/фурнитуры/операций,
    сохраняя все ссылки (для шаблонов и дублирования)."""
    data = copy.deepcopy(data)
    mapping: dict[str, str] = {}
    for coll in ("panels", "axes", "hardware", "operations", "extra_items"):
        for obj in data.get(coll, []):
            old = obj.get("id") or new_id()
            mapping[old] = new_id()
            obj["id"] = mapping[old]

    def fix(obj: Any) -> Any:
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k in ("panel_id", "axis_id", "align_top_with") and isinstance(v, str):
                    out[k] = mapping.get(v, v)
                else:
                    out[k] = fix(v)
            return out
        if isinstance(obj, list):
            return [fix(x) for x in obj]
        return obj

    for coll in ("panels", "axes", "hardware", "operations", "extra_items"):
        data[coll] = [fix(o) for o in data.get(coll, [])]
    return data
