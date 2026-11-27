// Общие функции отрисовки геометрии (мм, ось Y вверх) в SVG.
// На экране Y инвертируется: sy = -y.

export const SVGNS = 'http://www.w3.org/2000/svg';

export function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c) el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  return el;
}

const f = (v) => (Math.round(v * 1000) / 1000).toString();

// Контур с bulge → SVG path
export function contourPath(contour, dx = 0, dy = 0) {
  const n = contour.length;
  if (!n) return '';
  let d = `M${f(contour[0][0] + dx)},${f(-(contour[0][1] + dy))}`;
  for (let i = 0; i < n; i++) {
    const [x1, y1, b] = contour[i];
    const [x2, y2] = contour[(i + 1) % n];
    if (Math.abs(b) < 1e-9) d += `L${f(x2 + dx)},${f(-(y2 + dy))}`;
    else {
      const theta = 4 * Math.atan(b);
      const chord = Math.hypot(x2 - x1, y2 - y1);
      const r = chord / (2 * Math.sin(Math.abs(theta) / 2));
      const large = Math.abs(theta) > Math.PI ? 1 : 0;
      const sweep = b > 0 ? 0 : 1; // экран: Y вниз → CCW модели = против часовой на экране (sweep 0)
      d += `A${f(r)},${f(r)} 0 ${large} ${sweep} ${f(x2 + dx)},${f(-(y2 + dy))}`;
    }
  }
  return d + 'Z';
}

export function segPath(seg, dx = 0, dy = 0) {
  if (seg.t === 'line') return `M${f(seg.p1[0] + dx)},${f(-(seg.p1[1] + dy))}L${f(seg.p2[0] + dx)},${f(-(seg.p2[1] + dy))}`;
  if (seg.t === 'circle') {
    const [cx, cy] = seg.c; const r = seg.r;
    return `M${f(cx + r + dx)},${f(-(cy + dy))}A${f(r)},${f(r)} 0 1 0 ${f(cx - r + dx)},${f(-(cy + dy))}A${f(r)},${f(r)} 0 1 0 ${f(cx + r + dx)},${f(-(cy + dy))}`;
  }
  const a0 = seg.a0 * Math.PI / 180;
  let sw = ((seg.a1 - seg.a0) % 360 + 360) % 360; if (sw < 1e-9) sw = 360;
  if (sw >= 359.999) return segPath({ t: 'circle', c: seg.c, r: seg.r }, dx, dy);
  const a1 = a0 + sw * Math.PI / 180;
  const x0 = seg.c[0] + seg.r * Math.cos(a0), y0 = seg.c[1] + seg.r * Math.sin(a0);
  const x1 = seg.c[0] + seg.r * Math.cos(a1), y1 = seg.c[1] + seg.r * Math.sin(a1);
  return `M${f(x0 + dx)},${f(-(y0 + dy))}A${f(seg.r)},${f(seg.r)} 0 ${sw > 180 ? 1 : 0} 0 ${f(x1 + dx)},${f(-(y1 + dy))}`;
}

const SIDES = ['top', 'bottom', 'left', 'right'];
export const textW = (t, th) => t.length * th * 0.62;
const axisOf = (d) => { const a = d.dir === 'h' ? d.p1[0] : d.p1[1], b = d.dir === 'h' ? d.p2[0] : d.p2[1]; return a <= b ? [a, b] : [b, a]; };

// Порт export/dimlayout.py: размеры снаружи изделия, без наложений
export function layoutDims(dims, bbox, S, th, al) {
  const [minx, miny, maxx, maxy] = bbox;
  al = al || th * 0.8;
  const gap = th * 0.35, extGap = th * 0.4, over = th * 0.6, rowH = th * 1.35;
  const ops = [];
  const lins = dims.filter((d) => d.t === 'lin' && SIDES.includes(d.side) && Math.abs(axisOf(d)[1] - axisOf(d)[0]) > 1e-6);
  const dias = dims.filter((d) => d.t === 'dia');
  const pad = { top: 0, bottom: 0, left: 0, right: 0 };
  const midx = (minx + maxx) / 2;
  const diaSide = { left: [], right: [] };
  for (const d of dias) {
    const side = d.c[0] < midx ? 'left' : 'right';
    diaSide[side].push(d);
    pad[side] = Math.max(pad[side], th * 0.9 + textW(d.text, th) + th * 0.6);
  }
  const groups = new Map();
  for (const d of lins) { const k = `${d.side}|${d.level ?? 1}`; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(d); }
  const rowOf = new Map(), rows = {};
  for (const [key, ds] of groups) {
    const placed = [];
    for (const d of [...ds].sort((x, y) => (axisOf(x)[0] + axisOf(x)[1]) - (axisOf(y)[0] + axisOf(y)[1]))) {
      const [a, b] = axisOf(d), c = (a + b) / 2, w = textW(d.text, th);
      const iv = [c - w / 2 - th * 0.25, c + w / 2 + th * 0.25];
      let r = 0;
      for (;;) {
        if (r === placed.length) placed.push([]);
        if (placed[r].every(([x0, x1]) => iv[1] <= x0 || iv[0] >= x1)) { placed[r].push(iv); break; }
        r++;
      }
      rowOf.set(d, r);
    }
    rows[key] = placed.length;
  }
  const dist = {};
  for (const side of SIDES) {
    let cur = pad[side] + S;
    const levels = Object.keys(rows).filter((k) => k.startsWith(side + '|')).map((k) => +k.split('|')[1]).sort((a, b) => a - b);
    for (const lv of levels) { dist[`${side}|${lv}`] = cur; cur += rows[`${side}|${lv}`] * rowH + S * 0.55; }
  }
  for (const d of lins) {
    const side = d.side, lv = d.level ?? 1;
    const [a, b] = axisOf(d), r = rowOf.get(d), far = dist[`${side}|${lv}`];
    const short = (b - a) < al * 2.6;
    if (d.dir === 'h') {
      let yl, e0, sg, ty;
      if (side === 'top') { yl = maxy + far; e0 = maxy + extGap; sg = 1; ty = yl + gap + r * rowH; } else { yl = miny - far; e0 = miny - extGap; sg = -1; ty = yl - gap - th * 0.75 - r * rowH; }
      for (const x of [a, b]) ops.push(['line', [x, e0], [x, yl + sg * over]]);
      if (short) { ops.push(['line', [a - al * 1.6, yl], [b + al * 1.6, yl]], ['arrow', [a, yl], [1, 0]], ['arrow', [b, yl], [-1, 0]]); } else { ops.push(['line', [a, yl], [b, yl]], ['arrow', [a, yl], [-1, 0]], ['arrow', [b, yl], [1, 0]]); }
      ops.push(['text', [(a + b) / 2, ty], d.text, 0, th, 'center', d.overall]);
    } else {
      let xl, e0, sg, tx;
      if (side === 'left') { xl = minx - far; e0 = minx - extGap; sg = -1; tx = xl - gap - r * rowH; } else { xl = maxx + far; e0 = maxx + extGap; sg = 1; tx = xl + gap + th * 0.75 + r * rowH; }
      for (const y of [a, b]) ops.push(['line', [e0, y], [xl + sg * over, y]]);
      if (short) { ops.push(['line', [xl, a - al * 1.6], [xl, b + al * 1.6]], ['arrow', [xl, a], [0, 1]], ['arrow', [xl, b], [0, -1]]); } else { ops.push(['line', [xl, a], [xl, b]], ['arrow', [xl, a], [0, -1]], ['arrow', [xl, b], [0, 1]]); }
      ops.push(['text', [tx, (a + b) / 2], d.text, 90, th, 'center', d.overall]);
    }
  }
  for (const side of ['left', 'right']) {
    let last = Infinity;
    const edge = side === 'right' ? maxx : minx, sg = side === 'right' ? 1 : -1;
    for (const d of [...diaSide[side]].sort((x, y) => y.c[1] - x.c[1])) {
      const [cx, cy] = d.c, rr = d.r;
      const ly = Math.min(cy, last - rowH); last = ly;
      const pHole = [cx + sg * rr, cy], knee = [edge + sg * th * 0.5, cy], sh0 = [edge + sg * th * 0.9, ly];
      const sh1 = [sh0[0] + sg * (textW(d.text, th) + th * 0.3), ly];
      ops.push(['line', pHole, knee], ['line', knee, sh0], ['line', sh0, sh1], ['arrow', pHole, [-sg, 0]]);
      ops.push(['text', [sh0[0] + sg * th * 0.15, ly + th * 0.2], d.text, 0, th, side === 'right' ? 'left' : 'right']);
    }
  }
  for (const d of dims) if (d.t === 'note') ops.push(['text', [d.p[0], d.p[1] - th * 0.35], d.text, 0, th, 'center']);
  for (const d of dims) {
    if (d.t !== 'aligned') continue;
    const [x1, y1] = d.p1, [x2, y2] = d.p2;
    const ln = Math.hypot(x2 - x1, y2 - y1);
    if (ln < 1e-6) continue;
    const ux = (x2 - x1) / ln, uy = (y2 - y1) / ln;
    let ang = Math.atan2(uy, ux) * 180 / Math.PI;
    if (ang > 90 || ang < -90) ang += 180;
    ops.push(['text', [(x1 + x2) / 2 + uy * th * 1.4, (y1 + y2) / 2 - ux * th * 1.4], d.text, ang, th * 0.9, 'center']);
  }
  return ops;
}

export function renderDimOps(ops, k, dx = 0, dy = 0) {
  // k — мм на пиксель экрана; стрелки и линии постоянной экранной толщины
  const g = s('g');
  for (const op of ops) {
    if (op[0] === 'line') {
      g.appendChild(s('line', { class: 'dim', x1: op[1][0] + dx, y1: -(op[1][1] + dy), x2: op[2][0] + dx, y2: -(op[2][1] + dy), 'vector-effect': 'non-scaling-stroke', 'stroke-width': 0.8 }));
    } else if (op[0] === 'arrow') {
      const [tx, ty] = op[1], [ux, uy] = op[2];
      const al = 8 * k, aw = 2.2 * k;
      const bx = tx - ux * al, by = ty - uy * al;
      const pts = [[tx, ty], [bx - uy * aw, by + ux * aw], [bx + uy * aw, by - ux * aw]];
      g.appendChild(s('polygon', { class: 'dim-arrow', points: pts.map(([x, y]) => `${x + dx},${-(y + dy)}`).join(' ') }));
    } else if (op[0] === 'text') {
      const [, [x, y], text, ang, hh, align, bold] = op;
      const t = s('text', {
        class: 'dim-text', x: x + dx, y: -(y + dy), 'font-size': hh, 'stroke-width': hh * 0.22, 'text-anchor': align === 'center' ? 'middle' : align === 'right' ? 'end' : 'start',
        transform: ang ? `rotate(${-ang} ${x + dx} ${-(y + dy)})` : null, 'font-weight': bold ? 700 : null,
      }, text);
      g.appendChild(t);
    }
  }
  return g;
}

// Миниатюра изделия (карточки заказа, шаблоны)
export function thumbSvg(items) {
  const svg = s('svg', { viewBox: '0 0 100 100', preserveAspectRatio: 'xMidYMid meet' });
  if (!items || !items.length) return svg;
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for (const it of items) for (const [x, y] of it.contour) {
    minx = Math.min(minx, x + it.x); maxx = Math.max(maxx, x + it.x);
    miny = Math.min(miny, y + it.y); maxy = Math.max(maxy, y + it.y);
  }
  const w = maxx - minx, hh = maxy - miny, pad = Math.max(w, hh) * 0.06;
  svg.setAttribute('viewBox', `${minx - pad} ${-maxy - pad} ${w + 2 * pad} ${hh + 2 * pad}`);
  for (const it of items) {
    svg.appendChild(s('path', { d: contourPath(it.contour, it.x, it.y), fill: '#dff0f6', stroke: '#24323c', 'stroke-width': 1.2, 'vector-effect': 'non-scaling-stroke' }));
    for (const ho of it.holes || []) svg.appendChild(s('circle', { cx: ho.c[0] + it.x, cy: -(ho.c[1] + it.y), r: ho.r, fill: '#fff', stroke: '#c0392b', 'stroke-width': 0.8, 'vector-effect': 'non-scaling-stroke' }));
  }
  return svg;
}
