// CAD-холст конструктора: SVG в мм, пан/зум, выбор, перетаскивание обработки.
import { s, contourPath, segPath, layoutDims, renderDimOps } from './draw.js';
import { h, fmt } from './ui.js';

export class CadCanvas {
  constructor(container, { onSelect, onDragEnd }) {
    this.container = container;
    this.onSelect = onSelect;
    this.onDragEnd = onDragEnd;
    this.svg = s('svg', { class: 'cad-svg' });
    this.coords = h('div.coords');
    container.append(this.svg, this.coords);
    this.view = null; // {x, y, w, h} в экранных координатах модели (y инвертирован)
    this.res = null;
    this.sel = null;
    this.showDims = 'detail'; // detail | overview | none
    this.drag = null;
    this._bind();
    this.ro = new ResizeObserver(() => this.render());
    this.ro.observe(container);
  }

  destroy() {
    this.ro.disconnect();
    window.removeEventListener('mousemove', this._mm);
    window.removeEventListener('mouseup', this._mu);
  }

  setData(res, sel) {
    const first = !this.res;
    this.res = res;
    this.sel = sel;
    if (first || !this.view) this.fit();
    this.render();
  }

  setSelection(sel) { this.sel = sel; this.render(); }

  extents() {
    const r = this.res;
    if (!r || !r.glasses.length) return [0, 0, 1000, 2000];
    const planes = Object.fromEntries(r.planes.map((p) => [p.key, p]));
    let minx = 0, miny = 0, maxx = -Infinity, maxy = -Infinity;
    for (const g of r.glasses) {
      const dx = planes[g.plane].dx;
      maxx = Math.max(maxx, g.x + dx + g.w); maxy = Math.max(maxy, g.y + g.h);
      minx = Math.min(minx, g.x + dx); miny = Math.min(miny, g.y);
    }
    for (const p of r.planes) maxx = Math.max(maxx, p.dx + p.L);
    if (r.opening && r.opening.H) maxy = Math.max(maxy, r.opening.H);
    return [minx, miny, maxx, maxy];
  }

  fit() {
    const [minx, miny, maxx, maxy] = this.extents();
    const W = this.container.clientWidth || 800, H = this.container.clientHeight || 600;
    const pad = Math.max(maxx - minx, maxy - miny) * 0.16 + 150;
    let vw = maxx - minx + 2 * pad, vh = maxy - miny + 2 * pad;
    if (vw / vh > W / H) vh = vw * H / W; else vw = vh * W / H;
    this.view = { x: (minx + maxx) / 2 - vw / 2, y: -(miny + maxy) / 2 - vh / 2, w: vw, h: vh };
    this.render();
  }

  k() { return this.view.w / (this.container.clientWidth || 800); } // мм на пиксель

  toModel(ev) {
    const r = this.svg.getBoundingClientRect();
    const x = this.view.x + (ev.clientX - r.left) * this.view.w / r.width;
    const y = this.view.y + (ev.clientY - r.top) * this.view.h / r.height;
    return [x, -y];
  }

  _bind() {
    let pan = null;
    this.svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      if (!this.view) return;
      const [mx, my] = this.toModel(e);
      const f = Math.exp(e.deltaY * 0.0012);
      const v = this.view;
      const sx = -my;
      v.x = mx - (mx - v.x) * f; v.y = sx - (sx - v.y) * f; v.w *= f; v.h *= f;
      this.render();
    }, { passive: false });
    this.svg.addEventListener('mousedown', (e) => {
      if (e.button === 1 || e.button === 2 || (e.button === 0 && e.target === this.svg) || (e.button === 0 && e.shiftKey)) {
        pan = { x: e.clientX, y: e.clientY, v: { ...this.view }, moved: false, bg: e.target === this.svg };
        e.preventDefault();
      }
    });
    this.svg.addEventListener('contextmenu', (e) => e.preventDefault());
    window.addEventListener('mousemove', this._mm = (e) => {
      if (this.view && e.target && this.svg.contains(e.target)) {
        const [x, y] = this.toModel(e);
        this.coords.textContent = `X ${fmt(x, 0)}  Y ${fmt(y, 0)} мм`;
      }
      if (pan) {
        const r = this.svg.getBoundingClientRect();
        const kx = this.view.w / r.width;
        if (Math.abs(e.clientX - pan.x) + Math.abs(e.clientY - pan.y) > 3) pan.moved = true;
        this.view.x = pan.v.x - (e.clientX - pan.x) * kx;
        this.view.y = pan.v.y - (e.clientY - pan.y) * kx;
        this._applyView();
      } else if (this.drag) {
        const [x, y] = this.toModel(e);
        this.drag.dx = x - this.drag.x0; this.drag.dy = y - this.drag.y0;
        if (e.altKey) { this.drag.dx = 0; }
        if (e.ctrlKey) { this.drag.dy = 0; }
        this.drag.el.setAttribute('transform', `translate(${this.drag.dx},${-this.drag.dy})`);
      }
    });
    window.addEventListener('mouseup', this._mu = () => {
      if (pan) {
        if (!pan.moved && pan.bg) this.onSelect(null);
        pan = null;
      }
      if (this.drag) {
        const d = this.drag; this.drag = null;
        const dx = Math.round(d.dx), dy = Math.round(d.dy);
        if (dx || dy) this.onDragEnd(d.src, dx, dy); else this.render();
      }
    });
  }

  _applyView() {
    const v = this.view;
    this.svg.setAttribute('viewBox', `${v.x} ${v.y} ${v.w} ${v.h}`);
  }

  render() {
    if (!this.res || !this.view) return;
    const r = this.res, k = this.k();
    const svg = this.svg;
    while (svg.firstChild) svg.firstChild.remove();
    this._applyView();
    const planes = Object.fromEntries(r.planes.map((p) => [p.key, p]));
    const sw = { 'vector-effect': 'non-scaling-stroke' };
    const root = s('g');
    svg.appendChild(root);
    const fs = 12 * k;

    // проём и пол
    for (const p of r.planes) {
      if (p.key === 'front' && r.opening.outline && r.opening.outline.length)
        root.appendChild(s('polygon', { class: 'opening', points: r.opening.outline.map(([x, y]) => `${x + p.dx},${-y}`).join(' '), ...sw, 'stroke-width': 1 }));
      else if (p.L && r.opening.H)
        root.appendChild(s('rect', { class: 'opening', x: p.dx, y: -r.opening.H, width: p.L, height: r.opening.H, ...sw, 'stroke-width': 1 }));
      root.appendChild(s('line', { class: 'floor', x1: p.dx - 120, y1: 0, x2: p.dx + p.L + 120, y2: 0, ...sw, 'stroke-width': 2 }));
      if (r.planes.length > 1) root.appendChild(s('text', { class: 'plane-label', x: p.dx + p.L / 2, y: -(r.opening.H || 2000) - 24 * k, 'font-size': fs, 'text-anchor': 'middle' }, p.name.toUpperCase()));
    }
    // оси
    const [, , maxx] = this.extents();
    for (const a of r.axes) {
      const selA = this.sel && this.sel.type === 'axis' && this.sel.id === a.id;
      root.appendChild(s('line', { class: 'axis', x1: -150, y1: -a.y, x2: maxx + 150, y2: -a.y, ...sw, 'stroke-width': selA ? 2 : 1,
        onmousedown: (e) => { e.stopPropagation(); this.onSelect({ type: 'axis', id: a.id }); } }));
      root.appendChild(s('text', { class: 'axis-label', x: maxx + 160, y: -a.y + 4 * k, 'font-size': fs * 0.9 }, a.name));
    }
    // стекла
    for (const g of r.glasses) {
      const dx = g.x + planes[g.plane].dx, dy = g.y;
      const isSel = this.sel && this.sel.type === 'glass' && this.sel.id === g.id;
      const gg = s('g');
      gg.appendChild(s('path', { class: 'glass' + (isSel ? ' sel' : ''), d: contourPath(g.contour, dx, dy), ...sw, 'stroke-width': isSel ? 2 : 1.3,
        onmousedown: (e) => { if (e.button === 0 && !e.shiftKey) { e.stopPropagation(); this.onSelect({ type: 'glass', id: g.id }); } } }));
      for (const ho of g.holes) gg.appendChild(s('circle', { class: 'hole', cx: ho.c[0] + dx, cy: -(ho.c[1] + dy), r: ho.r, ...sw, 'stroke-width': 1, 'pointer-events': 'none' }));
      for (const ch of [...g.inner, ...g.open]) for (const sg of ch) gg.appendChild(s('path', { class: 'cutline', d: segPath(sg, dx, dy), ...sw, 'stroke-width': 1, 'pointer-events': 'none' }));
      // подписи
      const cx = dx + g.w / 2, cy = -(dy + g.h * 0.55);
      gg.appendChild(s('text', { class: 'glabel', x: cx, y: cy, 'font-size': fs * 1.15, 'text-anchor': 'middle', 'pointer-events': 'none' }, `${g.pos}. ${g.name}`));
      gg.appendChild(s('text', { class: 'gsize', x: cx, y: cy + fs * 1.5, 'font-size': fs, 'text-anchor': 'middle', 'pointer-events': 'none' }, `${fmt(g.w)} × ${fmt(g.h)}`));
      // профили на кромках
      for (const pe of g.profile_edges || []) {
        const [a, b] = pe;
        gg.appendChild(s('line', { class: 'edge-prof', x1: a[0] + dx, y1: -(a[1] + dy), x2: b[0] + dx, y2: -(b[1] + dy), ...sw, 'stroke-width': 5, 'stroke-opacity': 0.55, 'pointer-events': 'none' }));
      }
      // зоны выбора обработки/фурнитуры
      for (const m of g.marks || []) {
        const [x0, y0, x1, y1] = m.bbox;
        const pad = 6 * k;
        const sel = this.sel && this.sel.id === m.src;
        const rect = s('rect', { class: 'mark' + (sel ? ' sel' : ''), x: x0 + dx - pad, y: -(y1 + dy) - pad, width: x1 - x0 + 2 * pad, height: y1 - y0 + 2 * pad, ...sw, 'stroke-width': 1 });
        const mg = s('g', {}, rect);
        rect.addEventListener('mousedown', (e) => {
          if (e.button !== 0 || e.shiftKey) return;
          e.stopPropagation();
          this.onSelect({ type: 'src', id: m.src, glass: g.id });
          const [mx, my] = this.toModel(e);
          this.drag = { src: m.src, glass: g.id, x0: mx, y0: my, dx: 0, dy: 0, el: mg };
        });
        gg.appendChild(mg);
      }
      root.appendChild(gg);
      // размеры детали
      if (this.showDims === 'detail' && isSel) {
        const ops = layoutDims(g.dims, [0, 0, g.w, g.h], 34 * k, fs);
        root.appendChild(renderDimOps(ops, k, dx, dy));
      }
    }
    if (this.showDims === 'overview' || (this.showDims === 'detail' && !(this.sel && this.sel.type === 'glass'))) {
      const [minx, miny, mx, my] = this.extents();
      const topY = Math.max(...r.glasses.map((g) => g.y + g.h), 0);
      const ops = layoutDims(r.dims, [minx, miny, mx, topY || my], 34 * k, fs);
      root.appendChild(renderDimOps(ops, k));
    }
  }
}
