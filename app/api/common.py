from __future__ import annotations

from .. import repo
from ..config import UPLOADS_DIR
from ..engine.library import Library


def company_info() -> dict:
    s = repo.settings_get()
    comp = dict(s.get("company") or {})
    logo = comp.get("logo")
    comp["logo_path"] = str(UPLOADS_DIR / logo) if logo else None
    return comp


def product_summary(p: dict, lib: Library) -> dict:
    data = p.get("data") or {}
    tmpl = lib.get("construction_templates", data.get("template_id"))
    kit = lib.get("kits", data.get("kit_id"))
    m = data.get("measurement") or {}
    widths = [m.get(k) for k in ("width_top", "width_mid", "width_bottom") if m.get(k)]
    heights = [m.get(k) for k in ("height_left", "height_right") if m.get(k)]
    return {
        "id": p["id"], "name": p["name"], "kind": p["kind"], "position": p["position"],
        "updated_at": p["updated_at"],
        "template_name": tmpl["name"] if tmpl else None,
        "kit_name": kit["name"] if kit else None,
        "panels": len(data.get("panels") or []),
        "opening": f"{min(widths):g} × {min(heights):g}" if widths and heights else None,
        "mode": data.get("mode"),
    }
