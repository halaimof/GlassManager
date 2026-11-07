"""Спецификации: стекла, фурнитура, профили, дополнительные позиции комплекта."""
from __future__ import annotations

import math

from ..geometry.formula import FormulaError, eval_formula
from .library import Library

EDGE_RU = {"left": "левая", "right": "правая", "top": "верх", "bottom": "низ"}


def formula_vars(data: dict, glasses: list[dict]) -> dict[str, float]:
    m = data.get("measurement") or {}
    widths = [float(m[k]) for k in ("width_top", "width_mid", "width_bottom") if m.get(k) not in (None, "")]
    heights = [float(m[k]) for k in ("height_left", "height_right") if m.get(k) not in (None, "")]
    doors = [g for g in glasses if g["type"] in ("door", "sliding_door")]
    fixed = [g for g in glasses if g["type"] not in ("door", "sliding_door")]
    return {
        "W": min(widths) if widths else 0.0,
        "H": min(heights) if heights else 0.0,
        "W_door": doors[0]["w"] if doors else 0.0,
        "H_door": doors[0]["h"] if doors else 0.0,
        "W_fixed": fixed[0]["w"] if fixed else 0.0,
        "H_fixed": fixed[0]["h"] if fixed else 0.0,
        "H_max": max((g["h"] for g in glasses), default=0.0),
        "W_total": sum(g["w"] for g in glasses),
        "n_doors": float(len(doors)),
        "n_glass": float(len(glasses)),
    }


def _edge_length(g: dict, edge: str) -> float:
    pts = g["outline"]
    if len(pts) == 4:
        bl, br, tr, tl = pts
        a, b = {"left": (bl, tl), "right": (br, tr), "top": (tl, tr), "bottom": (bl, br)}[edge]
        return math.hypot(b[0] - a[0], b[1] - a[1])
    return g["h"] if edge in ("left", "right") else g["w"]


def build_bom(data: dict, glasses: list[dict], lib: Library, by_id: dict[str, dict]) -> dict:
    settings = data.get("settings") or {}
    hw_color = settings.get("hardware_color") or ""
    glass_rows = []
    for g in glasses:
        glass_rows.append({
            "pos": g["pos"], "id": g["id"], "name": g["name"], "type": g["type_name"],
            "w": round(g["w"], 1), "h": round(g["h"], 1), "thickness": g["thickness"],
            "color": g["color"], "glass_type": g["glass_type"], "tempered": g["tempered"],
            "edge_work": g["edge_work"], "qty": g["qty"],
            "shape": "фигурное" if g.get("shape_type") not in (None, "rect") else "прямоугольное",
            "holes": len(g.get("holes", [])), "cutouts": len(g.get("cut_boxes", [])),
            "area": round(g["w"] * g["h"] / 1e6, 3),
        })

    hw: dict[str, dict] = {}
    for inst in data.get("hardware", []):
        model = lib.get("hardware", inst.get("model_id"))
        if not model:
            continue
        row = hw.setdefault(model["id"], {
            "kind": "hardware",
            "manufacturer": lib.manufacturer_name(model.get("manufacturer_id")),
            "article": model.get("article") or "",
            "name": model["name"],
            "category": (lib.get("categories", model.get("category_id")) or {}).get("name", ""),
            "color": model.get("color") or hw_color,
            "qty": 0, "length": None, "unit": "шт", "note": model.get("note") or "",
        })
        row["qty"] += int(inst.get("qty") or 1)

    prof: dict[tuple, dict] = {}
    panels = {p["id"]: p for p in data.get("panels", [])}
    for g in glasses:
        p = panels.get(g["id"])
        if not p:
            continue
        for edge, e in (p.get("edges") or {}).items():
            pr = lib.get("profiles", e.get("profile_id"))
            if not pr:
                continue
            length = round(_edge_length(g, edge) * (g.get("qty") or 1))
            key = (pr["id"], length)
            row = prof.setdefault(key, {
                "kind": "profile",
                "manufacturer": lib.manufacturer_name(pr.get("manufacturer_id")),
                "article": pr.get("article") or "",
                "name": pr["name"],
                "category": "Профиль",
                "color": pr.get("color") or hw_color,
                "qty": 0, "length": length, "unit": "шт",
                "note": f"{g['name']}: {EDGE_RU.get(edge, edge)} кромка",
            })
            if row["qty"]:
                row["note"] += f"; {g['name']}: {EDGE_RU.get(edge, edge)}"
            row["qty"] += 1

    extra = []
    variables = formula_vars(data, glasses)
    for it in data.get("extra_items", []):
        src = lib.get("hardware", it.get("model_id")) or lib.get("profiles", it.get("profile_id"))
        length = None
        lf = (it.get("length_formula") or "").strip()
        note = it.get("note") or ""
        if lf:
            try:
                length = round(eval_formula(lf, variables))
            except FormulaError as e:
                note = f"{note} [ошибка длины: {e}]".strip()
        extra.append({
            "kind": "extra",
            "manufacturer": lib.manufacturer_name((src or {}).get("manufacturer_id")),
            "article": (src or {}).get("article") or "",
            "name": (src or {}).get("name") or it.get("name") or "Позиция",
            "category": (lib.get("categories", (src or {}).get("category_id")) or {}).get("name", "") if src else "",
            "color": (src or {}).get("color") or hw_color,
            "qty": it.get("qty") or 1, "length": length, "unit": it.get("unit") or "шт", "note": note,
        })
    return {"glass": glass_rows, "hardware": list(hw.values()) + list(prof.values()) + extra}
