"""Серверная генерация PDF (reportlab, векторная графика).

Режимы: client — коммерческий документ; production — спецификации и лист
на каждое стекло; full — оба. Геометрия берётся из того же результата
resolve(), что и DXF.
"""
from __future__ import annotations

import io
import math
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

from ..config import FONT_DIRS
from .dimlayout import dims_extent, layout_dims

INK = colors.HexColor("#1d2329")
MUTED = colors.HexColor("#6b7680")
LINE = colors.HexColor("#c9d1d8")
ACCENT = colors.HexColor("#1f6f8b")
GLASS_FILL = colors.HexColor("#e8f3f7")
CUT = colors.HexColor("#c0392b")
DIMC = colors.HexColor("#2c3e50")
ZEBRA = colors.HexColor("#f5f7f9")

_FONTS_OK = None


def _fonts() -> tuple[str, str]:
    global _FONTS_OK
    if _FONTS_OK:
        return _FONTS_OK
    for d in FONT_DIRS:
        reg, bold = Path(d) / "DejaVuSans.ttf", Path(d) / "DejaVuSans-Bold.ttf"
        if reg.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont("GC", str(reg)))
            pdfmetrics.registerFont(TTFont("GC-Bold", str(bold)))
            _FONTS_OK = ("GC", "GC-Bold")
            return _FONTS_OK
    _FONTS_OK = ("Helvetica", "Helvetica-Bold")  # без кириллицы — установите fonts-dejavu-core
    return _FONTS_OK


def n(v) -> str:
    if v is None or v == "":
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(f - round(f)) < 0.05:
        return str(int(round(f)))
    return f"{f:.1f}".replace(".", ",")


def fmt_date(s: str | None) -> str:
    if not s:
        return date.today().strftime("%d.%m.%Y")
    try:
        y, m, d = s[:10].split("-")
        return f"{d}.{m}.{y}"
    except ValueError:
        return s


class Doc:
    """Список страниц-функций → нумерация «Лист N из M» без второго прохода по данным."""

    def __init__(self, order: dict, company: dict):
        self.order = order
        self.company = company
        self.pages: list[tuple[tuple[float, float], callable]] = []
        self.F, self.FB = _fonts()

    def add(self, size, fn):
        self.pages.append((size, fn))

    def render(self) -> bytes:
        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=A4)
        c.setTitle(f"Заказ {self.order.get('number') or ''}")
        c.setAuthor(self.company.get("name") or "GlassCAD")
        c.setCreator("GlassCAD")
        total = len(self.pages)
        for i, (size, fn) in enumerate(self.pages, 1):
            c.setPageSize(size)
            fn(c, size)
            self.footer(c, size, i, total)
            c.showPage()
        c.save()
        return buf.getvalue()

    # ---------------------------------------------------------------- оформление
    def footer(self, c, size, i, total):
        W, _H = size
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(15 * mm, 13 * mm, W - 15 * mm, 13 * mm)
        c.setFont(self.F, 7.5)
        c.setFillColor(MUTED)
        left = f"Заказ №{self.order.get('number') or '—'}   ·   Лист {i} из {total}"
        c.drawString(15 * mm, 9 * mm, left)
        contacts = "   ·   ".join(x for x in (self.company.get("phone"), self.company.get("email"),
                                              self.company.get("address")) if x)
        c.drawCentredString(W / 2, 9 * mm, contacts)
        c.drawRightString(W - 15 * mm, 9 * mm, f"GlassCAD   ·   {fmt_date(self.order.get('date'))}")

    def header(self, c, size, title: str, subtitle: str = ""):
        W, H = size
        top = H - 15 * mm
        logo = self.company.get("logo_path")
        x = 15 * mm
        if logo and Path(logo).exists():
            try:
                c.drawImage(logo, x, top - 12 * mm, width=30 * mm, height=12 * mm, preserveAspectRatio=True,
                            anchor="sw", mask="auto")
                x += 34 * mm
            except Exception:  # noqa: BLE001
                pass
        c.setFillColor(ACCENT)
        c.setFont(self.FB, 13)
        c.drawString(x, top - 5 * mm, self.company.get("name") or "GlassCAD")
        c.setFillColor(MUTED)
        c.setFont(self.F, 7.5)
        c.drawString(x, top - 9.5 * mm, self.company.get("tagline") or "Стеклянные конструкции")
        c.setFillColor(INK)
        c.setFont(self.FB, 15)
        c.drawRightString(W - 15 * mm, top - 5 * mm, title)
        if subtitle:
            c.setFont(self.F, 9)
            c.setFillColor(MUTED)
            c.drawRightString(W - 15 * mm, top - 10 * mm, subtitle)
        c.setStrokeColor(INK)
        c.setLineWidth(1.2)
        c.line(15 * mm, top - 14 * mm, W - 15 * mm, top - 14 * mm)
        return top - 20 * mm

    def info_grid(self, c, x, y, items: list[tuple[str, str]], col_w: float, cols: int = 3, row_h=11 * mm):
        for i, (label, value) in enumerate(items):
            cx = x + (i % cols) * col_w
            cy = y - (i // cols) * row_h
            c.setFont(self.F, 7)
            c.setFillColor(MUTED)
            c.drawString(cx, cy, label.upper())
            c.setFont(self.FB, 10)
            c.setFillColor(INK)
            c.drawString(cx, cy - 4.8 * mm, _clip(c, value or "—", self.FB, 10, col_w - 4 * mm))
        rows = math.ceil(len(items) / cols)
        return y - rows * row_h

    def table(self, c, x, y, columns: list[tuple[str, float, str]], rows: list[list[str]], max_y: float,
              row_h=7.2 * mm) -> tuple[float, int]:
        """columns: (заголовок, ширина, выравнивание l|r|c). Возвращает (y, сколько строк влезло)."""
        total_w = sum(w for _, w, _ in columns)
        c.setFillColor(INK)
        c.rect(x, y - row_h, total_w, row_h, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(self.FB, 7.5)
        cx = x
        for title, w, al in columns:
            self._cell(c, title, cx, y - row_h + 2.5 * mm, w, al, self.FB, 7.5)
            cx += w
        y -= row_h
        drawn = 0
        for ri, row in enumerate(rows):
            if y - row_h < max_y:
                break
            if ri % 2:
                c.setFillColor(ZEBRA)
                c.rect(x, y - row_h, total_w, row_h, stroke=0, fill=1)
            c.setFillColor(INK)
            cx = x
            for (title, w, al), val in zip(columns, row):
                self._cell(c, str(val), cx, y - row_h + 2.5 * mm, w, al, self.F, 8)
                cx += w
            c.setStrokeColor(LINE)
            c.setLineWidth(0.3)
            c.line(x, y - row_h, x + total_w, y - row_h)
            y -= row_h
            drawn += 1
        return y, drawn

    def _cell(self, c, text, x, y, w, al, font, size):
        c.setFont(font, size)
        text = _clip(c, text, font, size, w - 3 * mm)
        if al == "r":
            c.drawRightString(x + w - 1.5 * mm, y, text)
        elif al == "c":
            c.drawCentredString(x + w / 2, y, text)
        else:
            c.drawString(x + 1.5 * mm, y, text)


def _clip(c, text: str, font: str, size: float, width: float) -> str:
    text = str(text)
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


# ------------------------------------------------------------------ чертежи
class View:
    """Преобразование мм модели → точки листа."""

    def __init__(self, extent, box):
        minx, miny, maxx, maxy = extent
        bx, by, bw, bh = box
        self.s = min(bw / max(maxx - minx, 1e-6), bh / max(maxy - miny, 1e-6))
        self.ox = bx + (bw - (maxx - minx) * self.s) / 2 - minx * self.s
        self.oy = by + (bh - (maxy - miny) * self.s) / 2 - miny * self.s

    def p(self, x, y):
        return self.ox + x * self.s, self.oy + y * self.s


def _draw_contour(c, v: View, contour, dx=0.0, dy=0.0, fill=True, lw=0.9):
    path = c.beginPath()
    nn = len(contour)
    for i in range(nn):
        x1, y1, b = contour[i]
        x2, y2, _ = contour[(i + 1) % nn]
        p1 = v.p(x1 + dx, y1 + dy)
        if i == 0:
            path.moveTo(*p1)
        if abs(b) < 1e-9:
            path.lineTo(*v.p(x2 + dx, y2 + dy))
        else:
            for px, py in _bulge_pts((x1, y1), (x2, y2), b)[1:]:
                path.lineTo(*v.p(px + dx, py + dy))
    path.close()
    c.setLineWidth(lw)
    c.setStrokeColor(INK)
    c.setFillColor(GLASS_FILL)
    c.drawPath(path, stroke=1, fill=1 if fill else 0)


def _bulge_pts(p1, p2, b, steps=None):
    theta = 4 * math.atan(b)
    chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    r = chord / (2 * math.sin(abs(theta) / 2))
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    h = r * math.cos(abs(theta) / 2)
    dx, dy = (p2[0] - p1[0]) / chord, (p2[1] - p1[1]) / chord
    sg = 1 if b > 0 else -1
    cx, cy = mx - sg * dy * h, my + sg * dx * h
    a0 = math.atan2(p1[1] - cy, p1[0] - cx)
    steps = steps or max(8, int(abs(theta) / math.radians(3)))
    return [(cx + r * math.cos(a0 + theta * i / steps), cy + r * math.sin(a0 + theta * i / steps)) for i in range(steps + 1)]


def _draw_seg(c, v: View, s, dx=0.0, dy=0.0):
    if s["t"] == "line":
        c.line(*v.p(s["p1"][0] + dx, s["p1"][1] + dy), *v.p(s["p2"][0] + dx, s["p2"][1] + dy))
    elif s["t"] == "circle":
        x, y = v.p(s["c"][0] + dx, s["c"][1] + dy)
        c.circle(x, y, s["r"] * v.s, stroke=1, fill=0)
    else:
        sw = (s["a1"] - s["a0"]) % 360 or 360
        steps = max(8, int(sw / 3))
        pts = [v.p(s["c"][0] + dx + s["r"] * math.cos(math.radians(s["a0"] + sw * i / steps)),
                   s["c"][1] + dy + s["r"] * math.sin(math.radians(s["a0"] + sw * i / steps))) for i in range(steps + 1)]
        for a, b in zip(pts, pts[1:]):
            c.line(*a, *b)


def draw_glass_details(c, v: View, g, dx=0.0, dy=0.0, lw=0.6):
    c.setStrokeColor(CUT)
    c.setLineWidth(lw)
    c.setFillColor(colors.white)
    for h in g.get("holes", []):
        x, y = v.p(h["c"][0] + dx, h["c"][1] + dy)
        c.circle(x, y, max(h["r"] * v.s, 0.6), stroke=1, fill=1)
    for chain in g.get("inner", []) + g.get("open", []):
        for s in chain:
            _draw_seg(c, v, s, dx, dy)


def draw_dims(c, v: View, ops, font, size=7.5):
    c.setStrokeColor(DIMC)
    c.setFillColor(DIMC)
    c.setLineWidth(0.35)
    for op in ops:
        if op[0] == "line":
            c.line(*v.p(*op[1]), *v.p(*op[2]))
        elif op[0] == "arrow":
            (tx, ty), (ux, uy) = op[1], op[2]
            px, py = v.p(tx, ty)
            al, aw = 2.4 * mm, 0.55 * mm
            bx, by = px - ux * al, py - uy * al
            path = c.beginPath()
            path.moveTo(px, py)
            path.lineTo(bx - uy * aw, by + ux * aw)
            path.lineTo(bx + uy * aw, by - ux * aw)
            path.close()
            c.drawPath(path, stroke=0, fill=1)
        elif op[0] == "text":
            _, (x, y), text, ang, _h, align = op
            px, py = v.p(x, y)
            c.saveState()
            c.translate(px, py)
            c.rotate(ang)
            c.setFont(font, size)
            if align == "center":
                c.drawCentredString(0, 0, text)
            else:
                c.drawString(0, 0, text)
            c.restoreState()


# ------------------------------------------------------------------ страницы
def _hw_rows(bom):
    rows = []
    for i, r in enumerate(bom["hardware"], 1):
        rows.append([str(i), r["manufacturer"] or "—", r["article"] or "—", r["name"], r["color"] or "—",
                     n(r["qty"]), n(r["length"]) if r.get("length") else "—", r["note"] or ""])
    return rows


HW_COLS = [("№", 8 * mm, "c"), ("Производитель", 34 * mm, "l"), ("Артикул", 22 * mm, "l"),
           ("Наименование", 72 * mm, "l"), ("Цвет / покрытие", 26 * mm, "l"), ("Кол.", 11 * mm, "r"),
           ("Длина", 17 * mm, "r"), ("Примечание", 77 * mm, "l")]

GLASS_COLS = [("Поз.", 11 * mm, "c"), ("Наименование", 42 * mm, "l"), ("Тип", 26 * mm, "l"),
              ("Ширина", 18 * mm, "r"), ("Высота", 18 * mm, "r"), ("Толщ.", 13 * mm, "r"),
              ("Цвет", 28 * mm, "l"), ("Тип стекла", 30 * mm, "l"), ("Обработка кромки", 45 * mm, "l"),
              ("Отв./выр.", 18 * mm, "c"), ("Кол.", 12 * mm, "r"), ]


def _glass_rows(bom, prefix=""):
    rows = []
    for r in bom["glass"]:
        name = r["name"] + (" (фигурное)" if r["shape"] != "прямоугольное" else "")
        rows.append([f"{prefix}{r['pos']}", name, r["type"], n(r["w"]), n(r["h"]), n(r["thickness"]),
                     r["color"] or "—", (r["glass_type"] or "—") + (", закалка" if r["tempered"] and "кал" not in (r["glass_type"] or "") else ""),
                     r["edge_work"] or "—", f"{r['holes']} / {r['cutouts']}", str(r["qty"])])
    return rows


def _paged_table(doc: Doc, title, subtitle, columns, rows, empty_text):
    size = landscape(A4)
    chunks = []
    per_first, per = 19, 21
    if not rows:
        chunks = [[]]
    else:
        i = 0
        first = True
        while i < len(rows):
            k = per_first if first else per
            chunks.append(rows[i:i + k])
            i += k
            first = False
    for ci, chunk in enumerate(chunks):
        def page(c, sz, chunk=chunk, ci=ci):
            y = doc.header(c, sz, title + (f" (продолжение)" if ci else ""), subtitle)
            if not chunk:
                c.setFont(doc.F, 10)
                c.setFillColor(MUTED)
                c.drawString(15 * mm, y - 10 * mm, empty_text)
                return
            doc.table(c, 15 * mm, y - 2 * mm, columns, chunk, 18 * mm)
        doc.add(size, page)


def overview_page(doc: Doc, product: dict, res: dict):
    size = landscape(A4)
    data = product.get("data") or {}
    s = data.get("settings") or {}

    def page(c, sz):
        W, H = sz
        y = doc.header(c, sz, product.get("name") or "Изделие", "Общий вид · согласование")
        o = doc.order
        glasses = res["glasses"]
        gtype = ", ".join(sorted({g["glass_type"] or "" for g in glasses} - {""})) or "—"
        gcolor = ", ".join(sorted({g["color"] or "" for g in glasses} - {""})) or "—"
        thick = ", ".join(sorted({n(g["thickness"]) + " мм" for g in glasses})) or "—"
        tmpl = product.get("template_name") or "—"
        meas = res.get("opening") or {}
        items = [
            ("Заказ", f"№{o.get('number') or '—'}"), ("Клиент", o.get("client") or "—"),
            ("Дата", fmt_date(o.get("date"))), ("Конструкция", tmpl),
            ("Проём (Ш × В)", f"{n(meas.get('W'))} × {n(meas.get('H'))} мм" if meas.get("W") else "—"),
            ("Цвет фурнитуры", s.get("hardware_color") or "—"),
            ("Стекло", f"{gcolor}, {thick}"), ("Тип стекла", gtype),
            ("Комплект", product.get("kit_name") or "—"),
        ]
        panel_w = 78 * mm
        bottom = doc.info_grid(c, W - 15 * mm - panel_w, y - 4 * mm, items, panel_w, cols=1, row_h=12.5 * mm)
        # Главные размеры стекол
        c.setFont(doc.FB, 8)
        c.setFillColor(INK)
        yy = bottom - 2 * mm
        c.drawString(W - 15 * mm - panel_w, yy, "СТЕКЛА")
        yy -= 5 * mm
        c.setFont(doc.F, 8.5)
        for g in glasses[:10]:
            c.setFillColor(INK)
            c.drawString(W - 15 * mm - panel_w, yy, _clip(c, f"{g['pos']}. {g['name']}", doc.F, 8.5, 45 * mm))
            c.drawRightString(W - 15 * mm, yy, f"{n(g['w'])} × {n(g['h'])} × {n(g['thickness'])}")
            yy -= 4.6 * mm
        # Чертёж
        box = (15 * mm, 20 * mm, W - 30 * mm - panel_w - 10 * mm, y - 24 * mm)
        _draw_product(c, doc, res, box)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(W - 15 * mm - panel_w - 6 * mm, 20 * mm, W - 15 * mm - panel_w - 6 * mm, y - 2 * mm)

    doc.add(size, page)


def _draw_product(c, doc: Doc, res: dict, box):
    planes = {p["key"]: p for p in res.get("planes", [])}
    glasses = res["glasses"]
    if not glasses:
        return
    maxx = max(pl["dx"] + pl["L"] for pl in planes.values()) if planes else max(g["x"] + g["w"] for g in glasses)
    maxx = max(maxx, max(g["x"] + planes[g["plane"]]["dx"] + g["w"] for g in glasses))
    maxy = max([g["y"] + g["h"] for g in glasses] + [res["opening"].get("H") or 0])
    bbox = (0, 0, maxx, maxy)
    # подбор масштаба с учётом размеров: S в мм модели ≈ 9 мм листа
    tmp = View(bbox, box)
    for _ in range(3):
        S = 9 * mm / tmp.s
        tmp = View(dims_extent(bbox, res.get("dims", []), S), box)
    v = tmp
    S = 9 * mm / v.s
    th = 2.6 * mm / v.s
    # проём
    for pl in planes.values():
        outline = res["opening"].get("outline") if pl["key"] == "front" else None
        if outline:
            c.setStrokeColor(MUTED)
            c.setDash(3, 2)
            c.setLineWidth(0.6)
            pts = [v.p(x + pl["dx"], y) for x, y in outline]
            for a, b in zip(pts, pts[1:] + pts[:1]):
                c.line(*a, *b)
            c.setDash()
        c.setStrokeColor(INK)
        c.setLineWidth(1.4)
        c.line(*v.p(pl["dx"] - 80, 0), *v.p(pl["dx"] + pl["L"] + 80, 0))
        if len(planes) > 1:
            c.setFont(doc.FB, 8)
            c.setFillColor(MUTED)
            x, y = v.p(pl["dx"] + pl["L"] / 2, maxy)
            c.drawCentredString(x, y + 4 * mm, pl["name"].upper())
    for g in glasses:
        dx = g["x"] + planes[g["plane"]]["dx"]
        _draw_contour(c, v, g["contour"], dx, g["y"], lw=1.0)
        draw_glass_details(c, v, g, dx, g["y"], lw=0.5)
        cx, cy = v.p(dx + g["w"] / 2, g["y"] + g["h"] * 0.62)
        c.setFillColor(ACCENT)
        c.setFont(doc.FB, 9)
        c.drawCentredString(cx, cy, g["name"])
    draw_dims(c, v, layout_dims(res.get("dims", []), bbox, S, th), doc.F, 7.5)


def glass_sheet(doc: Doc, product: dict, res: dict, g: dict, part_no: str):
    size = landscape(A4)

    def page(c, sz):
        W, H = sz
        y = doc.header(c, sz, f"Деталь {part_no} — {g['name']}", f"{product.get('name') or ''} · производственный чертёж")
        tb_w = 82 * mm
        box = (15 * mm, 22 * mm, W - 30 * mm - tb_w - 8 * mm, y - 26 * mm)
        bbox = (0, 0, g["w"], g["h"])
        v = View(bbox, box)
        for _ in range(3):
            S = 9 * mm / v.s
            v = View(dims_extent(bbox, g.get("dims", []), S), box)
        S = 9 * mm / v.s
        th = 2.6 * mm / v.s
        _draw_contour(c, v, g["contour"], lw=1.1)
        draw_glass_details(c, v, g, lw=0.7)
        # оси
        c.setStrokeColor(colors.HexColor("#3a8fb7"))
        c.setDash([6, 2, 1, 2])
        c.setLineWidth(0.35)
        for a in res.get("axes", []):
            ly = a["y"] - g["y"]
            if -1 < ly < g["h"] + 1:
                c.line(*v.p(-S * 0.3, ly), *v.p(g["w"] + S * 0.3, ly))
        c.setDash()
        draw_dims(c, v, layout_dims(g.get("dims", []), bbox, S, th), doc.F, 8)
        # Штамп
        x0 = W - 15 * mm - tb_w
        c.setStrokeColor(INK)
        c.setLineWidth(0.8)
        c.rect(x0, 22 * mm, tb_w, y - 26 * mm, stroke=1, fill=0)
        rows = [
            ("Заказ", f"№{doc.order.get('number') or '—'}"), ("Деталь", part_no),
            ("Наименование", g["name"]), ("Тип", g["type_name"]),
            ("Размер, мм", f"{n(g['w'])} × {n(g['h'])}"), ("Толщина", f"{n(g['thickness'])} мм"),
            ("Цвет", g["color"] or "—"), ("Тип стекла", g["glass_type"] or "—"),
            ("Закалка", "да" if g["tempered"] else "нет"), ("Кромка", g["edge_work"] or "—"),
            ("Отверстия", str(len(g.get("holes", [])))), ("Вырезы", str(len(g.get("cut_boxes", [])) + len(g.get("inner", [])))),
            ("Форма", "фигурная" if g.get("shape_type") not in (None, "rect") else "прямоугольник"),
            ("Количество", f"{g['qty']} шт"), ("Масштаб", f"1:{max(1, round(1 / (v.s / mm))):d}"),
        ]
        yy = y - 8 * mm
        for label, val in rows:
            c.setFont(doc.F, 6.8)
            c.setFillColor(MUTED)
            c.drawString(x0 + 4 * mm, yy, label.upper())
            c.setFont(doc.FB, 9.5)
            c.setFillColor(INK)
            c.drawString(x0 + 4 * mm, yy - 4.2 * mm, _clip(c, val, doc.FB, 9.5, tb_w - 8 * mm))
            yy -= 9.6 * mm
            if yy < 30 * mm:
                break
        # отверстия: сводка диаметров
        diam: dict[str, int] = {}
        for h in g.get("holes", []):
            k = "Ø" + n(h["r"] * 2)
            diam[k] = diam.get(k, 0) + 1
        if diam:
            c.setFont(doc.F, 7.5)
            c.setFillColor(INK)
            c.drawString(15 * mm, 18 * mm, "Отверстия: " + ", ".join(f"{k} — {v_} шт" for k, v_ in sorted(diam.items())))

    doc.add(size, page)


def build_pdf(order: dict, products: list[dict], resolved: dict[str, dict], company: dict, mode: str = "full") -> bytes:
    doc = Doc(order, company)
    client = mode in ("client", "full")
    prod = mode in ("production", "full")
    multi = len(products) > 1
    if client:
        for pi, p in enumerate(products, 1):
            res = resolved[p["id"]]
            overview_page(doc, p, res)
            pre = f"{pi}." if multi else ""
            _paged_table(doc, "Спецификация стекол", p.get("name") or "", GLASS_COLS, _glass_rows(res["bom"], pre),
                         "Стекла не заданы")
            _paged_table(doc, "Фурнитура и комплектующие", p.get("name") or "", HW_COLS, _hw_rows(res["bom"]),
                         "Фурнитура не добавлена")
    if prod:
        all_glass = []
        all_hw = []
        for pi, p in enumerate(products, 1):
            res = resolved[p["id"]]
            pre = f"{pi}." if multi else ""
            all_glass += _glass_rows(res["bom"], pre)
            all_hw += _hw_rows(res["bom"])
        _paged_table(doc, "Производство: стекла", f"Заказ №{order.get('number') or '—'}", GLASS_COLS, all_glass,
                     "Стекла не заданы")
        _paged_table(doc, "Производство: фурнитура", f"Заказ №{order.get('number') or '—'}", HW_COLS, all_hw,
                     "Фурнитура не добавлена")
        for pi, p in enumerate(products, 1):
            res = resolved[p["id"]]
            for g in res["glasses"]:
                part = f"{order.get('number') or '0'}-{pi}-{g['pos']}"
                glass_sheet(doc, p, res, g, part)
    return doc.render()
