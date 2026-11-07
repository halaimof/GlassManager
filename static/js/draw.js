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

// Порт export/dimlayout.py — одинаковая логика размещения размеров
export function layoutDims(dims, bbox, S, th) {
  const [minx, miny, maxx, maxy] = bbox;
  const ops = [];
  const gap = S * 0.12, over = S * 0.2;
  const smallRun = {};
  for (const d of dims) {
    if (d.t === 'lin') {
      const key = `${d.dir}|${d.side}|${d.level ?? 1}`;
      const [x1, y1] = d.p1, [x2, y2] = d.p2;
      const side = d.side || 'bottom', lvl = d.level ?? 1;
      const tw = d.text.length * th * 0.62;
      if (d.dir === 'h') {
        if (Math.abs(x2 - x1) < 1e-6) continue;
        let yl, sg;
        if (side === 'top') { yl = maxy + lvl * S; sg = 1; } else if (side === 'inside') { yl = y1; sg = 0; } else { yl = miny - lvl * S; sg = -1; }
        if (sg) { ops.push(['line', [x1, y1 + sg * gap], [x1, yl + sg * over]]); ops.push(['line', [x2, y2 + sg * gap], [x2, yl + sg * over]]); }
        ops.push(['line', [x1, yl], [x2, yl]]);
        const dir = x2 > x1 ? 1 : -1;
        ops.push(['arrow', [x1, yl], [-dir, 0]], ['arrow', [x2, yl], [dir, 0]]);
        let mx = (x1 + x2) / 2, ty = yl + th * 0.35;
        if (Math.abs(x2 - x1) < tw + th) {
          const n = smallRun[key] || 0; smallRun[key] = n + 1;
          if (n % 2 === 0) ty = yl - th * 1.25; else mx = Math.max(x1, x2) + tw / 2 + th * 0.4;
        } else smallRun[key] = 0;
        ops.push(['text', [mx, ty], d.text, 0, th, 'center', d.overall]);
      } else {
        if (Math.abs(y2 - y1) < 1e-6) continue;
        let xl, sg;
        if (side === 'right') { xl = maxx + lvl * S; sg = 1; } else if (side === 'inside') { xl = x1; sg = 0; } else { xl = minx - lvl * S; sg = -1; }
        if (sg) { ops.push(['line', [x1 + sg * gap, y1], [xl + sg * over, y1]]); ops.push(['line', [x2 + sg * gap, y2], [xl + sg * over, y2]]); }
        ops.push(['line', [xl, y1], [xl, y2]]);
        const dir = y2 > y1 ? 1 : -1;
        ops.push(['arrow', [xl, y1], [0, -dir]], ['arrow', [xl, y2], [0, dir]]);
        let my = (y1 + y2) / 2, tx = xl - th * 0.35;
        if (Math.abs(y2 - y1) < tw + th) {
          const n = smallRun[key] || 0; smallRun[key] = n + 1;
          if (n % 2 === 0) tx = xl + th * 1.25; else my = Math.max(y1, y2) + tw / 2 + th * 0.4;
        } else smallRun[key] = 0;
        ops.push(['text', [tx, my], d.text, 90, th, 'center', d.overall]);
      }
    } else if (d.t === 'dia') {
      const [cx, cy] = d.c, r = d.r, a = Math.PI / 4;
      const p0 = [cx + r * Math.cos(a), cy + r * Math.sin(a)];
      const p1 = [cx + (r + S * 0.45) * Math.cos(a), cy + (r + S * 0.45) * Math.sin(a)];
      const tw = d.text.length * th * 0.62;
      ops.push(['line', p0, p1], ['line', p1, [p1[0] + tw + th * 0.3, p1[1]]]);
      ops.push(['arrow', p0, [-Math.cos(a), -Math.sin(a)]]);
      ops.push(['text', [p1[0] + th * 0.15, p1[1] + th * 0.3], d.text, 0, th, 'left']);
    } else if (d.t === 'aligned') {
      const [x1, y1] = d.p1, [x2, y2] = d.p2;
      const ln = Math.hypot(x2 - x1, y2 - y1);
      if (ln < 1e-6) continue;
      const ux = (x2 - x1) / ln, uy = (y2 - y1) / ln;
      let ang = Math.atan2(uy, ux) * 180 / Math.PI;
      if (ang > 90 || ang < -90) ang += 180;
      ops.push(['text', [(x1 + x2) / 2 + uy * th * 1.4, (y1 + y2) / 2 - ux * th * 1.4], d.text, ang, th * 0.9, 'center']);
    }
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
        class: 'dim-text', x: x + dx, y: -(y + dy), 'font-size': hh, 'stroke-width': hh * 0.22, 'text-anchor': align === 'center' ? 'middle' : 'start',
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
