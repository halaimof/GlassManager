"""Доступ движка к библиотеке (фурнитура, профили, DXF). Движок не знает про БД."""
from __future__ import annotations


class Library:
    def __init__(self, items: dict[str, dict[str, dict]] | None = None, dxf: dict[str, dict] | None = None):
        self.items = items or {}
        self.dxf = dxf or {}

    def get(self, collection: str, item_id: str | None) -> dict | None:
        if not item_id:
            return None
        it = self.items.get(collection, {}).get(item_id)
        if it is None:
            return None
        return {"id": it["id"], "name": it["name"], **(it.get("data") or {})}

    def all(self, collection: str) -> list[dict]:
        return [self.get(collection, i) for i in self.items.get(collection, {})]

    def dxf_primitives(self, dxf_id: str | None) -> list[dict]:
        if not dxf_id or dxf_id not in self.dxf:
            return []
        return (self.dxf[dxf_id].get("data") or {}).get("primitives", [])

    def manufacturer_name(self, mid: str | None) -> str:
        m = self.get("manufacturers", mid)
        return m["name"] if m else ""


def profile_deduction(profile: dict | None) -> float:
    """Вычет из размера стекла на кромку с профилем:
    глубина профиля − глубина посадки + монтажный запас.
    Можно задать явным значением deduction в карточке профиля."""
    if not profile:
        return 0.0
    if profile.get("deduction") not in (None, ""):
        return float(profile["deduction"])
    depth = float(profile.get("depth") or 0)
    seat = float(profile.get("seat_depth") or 0)
    gap = float(profile.get("mounting_gap") or 0)
    return max(0.0, depth - seat) + gap
