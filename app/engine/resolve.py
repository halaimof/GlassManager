"""Главный расчёт изделия: замер → раскладка стекол → обработка → контуры → размеры.

Результат resolve() — единая геометрическая модель, из которой строятся
холст, PDF и DXF.
"""
from __future__ import annotations

from ..geometry.contour import build_contour
from ..geometry.prims import seg_bbox
from ..geometry.formula import FormulaError, eval_formula
from ..geometry.quad import GeometryError, solve_quad
from .bom import build_bom
from .dims import glass_dims, product_dims
from .hardware import apply_hardware
from .library import Library, profile_deduction
from .model import PANEL_TYPES, normalize
from .operations import resolve_operations

DOOR_TYPES = ("door", "sliding_door")
PLANE_GAP = 500.0  # расстояние между плоскостями на общем виде (мм)


def effective_measurement(m: dict, warnings: list[str]) -> dict:
    widths = [float(m[k]) for k in ("width_top", "width_mid", "width_bottom") if m.get(k) not in (None, "")]
    heights = [float(m[k]) for k in ("height_left", "height_right") if m.get(k) not in (None, "")]
    W = min(widths) if widths else 0.0
    H = min(heights) if heights else 0.0
    if widths and max(widths) - min(widths) > 5:
        warnings.append(
            f"Ширина проёма отличается на {max(widths) - min(widths):g} мм (верх/центр/низ) — расчёт по минимальной: {W:g}"
        )
    if heights and max(heights) - min(heights) > 5:
        warnings.append(f"Высота слева/справа отличается на {max(heights) - min(heights):g} мм — расчёт по минимальной: {H:g}")
    depth = float(m["depth"]) if m.get("depth") not in (None, "") else None
    wt = float(m.get("width_top") or W or 0)
    wb = float(m.get("width_bottom") or W or 0)
    hl = float(m.get("height_left") or H or 0)
    hr = float(m.get("height_right") or H or 0)
    return {"W": W, "H": H, "depth": depth, "outline": [[0, 0], [wb, 0], [wt, hr], [0, hl]] if W and H else []}


class Ctx:
    def __init__(self, data: dict, lib: Library):
        self.data = data
        self.lib = lib
        self.gaps = {k: float(v or 0) for k, v in data["gaps"].items()}
        self.settings = data["settings"]
        self.warnings: list[str] = []
        self.errors: list[str] = []
        # зазоры/вычеты, задаваемые установленной фурнитурой
        self.hw_joint_gap: dict[tuple[str, str], float] = {}
        for inst in data["hardware"]:
            model = lib.get("hardware", inst.get("model_id"))
            if not model or model.get("joint_gap") in (None, ""):
                continue
            for tgt in (inst.get("targets") or {}).values():
                key = (tgt.get("panel_id"), tgt.get("edge"))
                self.hw_joint_gap[key] = max(self.hw_joint_gap.get(key, 0.0), float(model["joint_gap"]))

    def profile(self, edge: dict):
        return self.lib.get("profiles", edge.get("profile_id"))

    def wall_deduction(self, panel: dict, side: str) -> float:
        e = panel["edges"][side]
        if e.get("override") not in (None, ""):
            return float(e["override"])
        if (panel["id"], side) in self.hw_joint_gap:
            return self.hw_joint_gap[(panel["id"], side)]
        prof = self.profile(e)
        if prof:
            return profile_deduction(prof)
        return self.gaps.get("wall", 0.0)

    def joint_gap(self, left: dict, right: dict) -> float:
        for p, side in ((left, "right"), (right, "left")):
            ov = p["edges"][side].get("override")
            if ov not in (None, ""):
                return float(ov)
        g = max(self.hw_joint_gap.get((left["id"], "right"), -1), self.hw_joint_gap.get((right["id"], "left"), -1))
        return g if g >= 0 else self.gaps.get("glass_glass", 0.0)

    def bottom_deduction(self, panel: dict) -> float:
        e = panel["edges"]["bottom"]
        if e.get("override") not in (None, ""):
            return float(e["override"])
        if e.get("kind") == "floor":
            if panel["type"] in DOOR_TYPES:
                return self.gaps.get("door_floor", 0.0)
            prof = self.profile(e)
            if prof:
                return profile_deduction(prof)
            if (panel["id"], "bottom") in self.hw_joint_gap:
                return self.hw_joint_gap[(panel["id"], "bottom")]
            return self.gaps.get("fixed_floor", 0.0)
        return 0.0

    def top_limit(self, panel: dict, H: float) -> float:
        e = panel["edges"]["top"]
        fixed = self.settings.get("top_mode") == "fixed"
        base = float(self.settings.get("top_height") or 0) if fixed else H
        if e.get("override") not in (None, ""):
            return base - float(e["override"])
        prof = self.profile(e) if e.get("kind") in ("ceiling", "wall") else None
        if prof:
            return base - profile_deduction(prof)
        return base - (0.0 if fixed else self.gaps.get("top", 0.0))


def _resolve_side_kinds(plist: list[dict]) -> None:
    flow = [p for p in plist if not (p.get("x_formula") or "").strip()]
    for p in plist:
        in_flow = p in flow
        idx = flow.index(p) if in_flow else -1
        for side in ("left", "right"):
            kind = p["edges"][side].get("kind", "auto")
            if kind == "auto":
                if in_flow:
                    has_nb = idx > 0 if side == "left" else idx < len(flow) - 1
                    kind = "glass" if has_nb else "wall"
                else:
                    first, last = plist[0] is p, plist[-1] is p
                    kind = "wall" if (side == "left" and first) or (side == "right" and last) else "free"
            p["_kind_" + side] = kind


def layout(data: dict, ctx: Ctx, meas: dict) -> tuple[list[dict], list[dict]]:
    panels = data["panels"]
    H = meas["H"]
    planes = []
    glasses: list[dict] = []
    plane_keys = []
    for p in panels:
        if p.get("plane", "front") not in plane_keys:
            plane_keys.append(p.get("plane", "front"))
    dx = 0.0
    for key in plane_keys:
        plist = [p for p in panels if p.get("plane", "front") == key]
        L = meas["W"] if key == "front" else (meas["depth"] or meas["W"])
        _resolve_side_kinds(plist)
        flow = [p for p in plist if not (p.get("x_formula") or "").strip()]
        first, last = plist[0], plist[-1]
        dl = ctx.wall_deduction(first, "left") if first["_kind_left"] == "wall" else 0.0
        dr = ctx.wall_deduction(last, "right") if last["_kind_right"] == "wall" else 0.0
        gaps = [ctx.joint_gap(a, b) for a, b in zip(flow, flow[1:])]
        A = L - dl - dr - sum(gaps)
        T = float(ctx.settings.get("thickness") or 8)
        variables = {"L": L, "H": H, "A": A, "dl": dl, "dr": dr, "T": T, "n": len(plist)}
        widths: dict[str, float | None] = {}
        for p in plist:
            wspec = p.get("width") or {}
            try:
                if p.get("width_override") not in (None, ""):
                    widths[p["id"]] = float(p["width_override"])
                elif wspec.get("mode") == "value" and wspec.get("value") not in (None, ""):
                    widths[p["id"]] = float(wspec["value"])
                elif wspec.get("mode") == "formula" and (wspec.get("formula") or "").strip():
                    widths[p["id"]] = eval_formula(wspec["formula"], variables)
                else:
                    widths[p["id"]] = None
            except FormulaError as e:
                ctx.errors.append(f"{p['name']}: {e}")
                widths[p["id"]] = None
        auto_flow = [p for p in flow if widths[p["id"]] is None]
        used = sum(widths[p["id"]] or 0 for p in flow if widths[p["id"]] is not None)
        share = (A - used) / len(auto_flow) if auto_flow else 0.0
        for p in plist:
            if widths[p["id"]] is None:
                widths[p["id"]] = share if p in flow else A
        # X
        xs: dict[str, float] = {}
        x = dl
        for i, p in enumerate(flow):
            xs[p["id"]] = x
            x += widths[p["id"]] + (gaps[i] if i < len(gaps) else 0)
        if flow and L and abs(x - (L - dr)) > 0.05 and not auto_flow and last in flow:
            ctx.warnings.append(
                f"Сумма ширин стекол не совпадает с проёмом ({key}): расхождение {x - (L - dr):+.1f} мм"
            )
        for p in plist:
            if p["id"] not in xs:
                try:
                    xs[p["id"]] = eval_formula(p["x_formula"], {**variables, "w": widths[p["id"]]})
                except FormulaError as e:
                    ctx.errors.append(f"{p['name']}: положение — {e}")
                    xs[p["id"]] = 0.0
        planes.append({"key": key, "L": L, "dx": dx, "dl": dl, "dr": dr, "A": A,
                       "name": "Фронт" if key == "front" else "Боковая сторона"})
        for p in plist:
            glasses.append({"id": p["id"], "panel": p, "plane": key, "x": xs[p["id"]], "w": widths[p["id"]]})
        dx += L + PLANE_GAP

    # Высоты: общий верх, перепады снизу
    tops = {g["id"]: ctx.top_limit(g["panel"], H) for g in glasses}
    if ctx.settings.get("common_top", True) and tops:
        common = min(tops.values())
        tops = {k: common for k in tops}
    for g in glasses:
        al = g["panel"].get("align_top_with")
        if al and al in tops and al != g["id"]:
            tops[g["id"]] = tops[al]
    for g in glasses:
        p = g["panel"]
        top = tops[g["id"]]
        bottom = ctx.bottom_deduction(p)
        if p.get("height_override") not in (None, ""):
            bottom = top - float(p["height_override"])
        if p.get("y_override") not in (None, ""):
            h = top - bottom
            bottom = float(p["y_override"])
            top = bottom + h
        g["y"] = bottom
        g["h"] = top - bottom
    return glasses, planes


def _shape_outline(g: dict, ctx: Ctx) -> list[tuple[float, float]]:
    shape = g["panel"].get("shape") or {"type": "rect"}
    t = shape.get("type", "rect")
    if t == "quad":
        pts = solve_quad(
            float(shape.get("top") or 0), float(shape.get("right") or 0),
            float(shape.get("bottom") or 0), float(shape.get("left") or 0),
            shape.get("corner", "tl"), float(shape.get("angle") or 90),
        )
        return pts
    if t == "polygon":
        raw = shape.get("points") or []
        if len(raw) < 3:
            raise GeometryError("Многоугольник должен иметь минимум 3 вершины")
        minx = min(p[0] for p in raw)
        miny = min(p[1] for p in raw)
        pts = [(float(p[0]) - minx, float(p[1]) - miny) for p in raw]
        area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
        return pts if area > 0 else list(reversed(pts))
    w, h = g["w"], g["h"]
    return [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]


def resolve(raw_data: dict, lib: Library) -> dict:
    data = normalize(raw_data)
    ctx = Ctx(data, lib)
    meas = effective_measurement(data["measurement"], ctx.warnings)
    if not data["panels"]:
        return {"opening": meas, "planes": [], "glasses": [], "axes": [], "dims": [], "warnings": ctx.warnings,
                "errors": [], "bom": build_bom(data, [], lib, {})}
    manual_mode = not meas["W"]
    if manual_mode and any((p.get("width") or {}).get("mode") == "auto" and p.get("width_override") in (None, "")
                           for p in data["panels"]):
        ctx.warnings.append("Не задан замер проёма — для стекол с авто-шириной укажите ширину вручную")
    glasses, planes = layout(data, ctx, meas)
    s = data["settings"]

    # Форма и базовые атрибуты
    for g in glasses:
        p = g["panel"]
        try:
            outline = _shape_outline(g, ctx)
        except GeometryError as e:
            ctx.errors.append(f"{p['name']}: {e}")
            outline = [(0.0, 0.0), (g["w"], 0.0), (g["w"], g["h"]), (0.0, g["h"])]
        if (p.get("shape") or {}).get("type", "rect") != "rect":
            top = g["y"] + g["h"]
            g["w"] = max(pt[0] for pt in outline)
            g["h"] = max(pt[1] for pt in outline)
            # у душевых (низ — пол) сохраняется общий верх; у отдельного стекла — низ
            if p["edges"]["bottom"].get("kind") != "free" or p.get("y_override") not in (None, ""):
                g["y"] = top - g["h"]
            elif p.get("height_override") in (None, ""):
                g["y"] = max(g["y"], 0.0)
            else:
                g["y"] = 0.0
        g["outline"] = outline
        bl, br, tr, tl = outline if len(outline) == 4 else [(0, 0), (g["w"], 0), (g["w"], g["h"]), (0, g["h"])]
        ends = {"left": (bl, tl), "right": (br, tr), "top": (tl, tr), "bottom": (bl, br)}
        g["profile_edges"] = [[list(ends[side][0]), list(ends[side][1])] for side, e in p["edges"].items()
                              if e.get("profile_id") and side in ends]
        g["shape_type"] = (p.get("shape") or {}).get("type", "rect")
        g["name"] = p.get("name") or PANEL_TYPES.get(p["type"], "Стекло")
        g["type"] = p["type"]
        g["type_name"] = PANEL_TYPES.get(p["type"], p["type"])
        g["thickness"] = float(p.get("thickness") or s.get("thickness") or 8)
        g["color"] = p.get("color") or s.get("color")
        g["glass_type"] = p.get("glass_type") or s.get("glass_type")
        g["tempered"] = p.get("tempered") if p.get("tempered") is not None else s.get("tempered", True)
        g["edge_work"] = p.get("edge_work") or s.get("edge_work")
        g["qty"] = int(p.get("qty") or 1)
        if g["w"] <= 0 or g["h"] <= 0:
            ctx.errors.append(f"{g['name']}: недопустимый размер {g['w']:.1f} × {g['h']:.1f}")

    # Оси (мировые Y)
    by_id = {g["id"]: g for g in glasses}
    common_top = max((g["y"] + g["h"] for g in glasses), default=0.0)
    axes_out, axes_y = [], {}
    for a in data["axes"]:
        base = by_id.get(a.get("panel_id"))
        off = float(a.get("offset") or 0)
        if a.get("ref", "top") == "top":
            y = (base["y"] + base["h"] if base else common_top) - off
        else:
            y = (base["y"] if base else 0.0) + off
        axes_y[a["id"]] = y
        axes_out.append({"id": a["id"], "name": a.get("name") or "Ось", "y": y})

    # Обработка
    segs_by_glass: dict[str, list[dict]] = {g["id"]: [] for g in glasses}
    for g in glasses:
        segs_by_glass[g["id"]] += resolve_operations(g, data["operations"], axes_y, ctx.warnings)
    hw_out = []
    for inst in data["hardware"]:
        model = lib.get("hardware", inst.get("model_id"))
        if not model:
            ctx.warnings.append("Установлена фурнитура, модель которой удалена из базы")
            hw_out.append({"id": inst["id"], "name": "(удалена)", "missing": True})
            continue
        hw_out.append({"id": inst["id"], "name": model["name"], "model_id": model["id"]})
        for gid, segs in apply_hardware(inst, model, by_id, lib, axes_y, ctx.warnings).items():
            segs_by_glass[gid] += segs

    # Контуры
    for g in glasses:
        try:
            res = build_contour(g["outline"], segs_by_glass[g["id"]])
        except Exception as e:  # noqa: BLE001
            ctx.errors.append(f"{g['name']}: ошибка построения контура — {e}")
            res = {"contour": [[x, y, 0] for x, y in g["outline"]], "holes": [], "inner": [], "open": [],
                   "rings": [], "cut_boxes": [], "warnings": []}
        for w in res.pop("warnings", []):
            ctx.warnings.append(f"{g['name']}: {w}")
        g.update(res)
        marks: dict[str, list[float]] = {}
        for sg in segs_by_glass[g["id"]]:
            src = sg.get("src")
            if not src:
                continue
            bb = seg_bbox(sg)
            m = marks.get(src)
            marks[src] = list(bb) if m is None else [min(m[0], bb[0]), min(m[1], bb[1]), max(m[2], bb[2]), max(m[3], bb[3])]
        g["marks"] = [{"src": k, "bbox": [round(v, 3) for v in bb]} for k, bb in marks.items()]
        # для холста: принадлежность отверстий к объекту
        for hole in g["holes"]:
            src = next((s.get("src") for s in segs_by_glass[g["id"]] if s["t"] == "circle"
                        and abs(s["c"][0] - hole["c"][0]) < 1e-6 and abs(s["c"][1] - hole["c"][1]) < 1e-6), None)
            hole["src"] = src
        g["dims"] = glass_dims(g, s.get("dim_side", "auto"))

    for i, g in enumerate(glasses, 1):
        g["pos"] = i
        g.pop("panel", None)
        for k in [k for k in g if k.startswith("_")]:
            g.pop(k)

    for p in data["panels"]:
        for k in [k for k in p if k.startswith("_")]:
            p.pop(k)

    return {
        "opening": meas,
        "planes": planes,
        "glasses": glasses,
        "axes": axes_out,
        "hardware": hw_out,
        "dims": product_dims(glasses, planes),
        "warnings": ctx.warnings,
        "errors": ctx.errors,
        "bom": build_bom(data, glasses, lib, {g["id"]: g for g in glasses}),
    }
