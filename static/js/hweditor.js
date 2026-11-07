// Редактор модели фурнитуры: стороны узла, DXF-просмотрщик, роли примитивов, магнитные привязки.
import { api, lib, invalidateLib, meta } from './api.js';
import { h, clear, field, textInput, numInput, selectInput, toast, confirmDlg, modal, fmt, clone } from './ui.js';
import { s, segPath, contourPath } from './draw.js';

const ROLE_RU = { op: 'Обработка', aux: 'Вспомогательная', ignore: 'Не использовать' };
const SNAP_PX = 14;

export async function hardwareEditor(root, id) {
  const [item, m, mans, cats, dxfList] = await Promise.all([api.get('/api/lib/hardware/' + id), meta(), lib('manufacturers', true), lib('categories', true), api.get('/api/dxf')]);
  const st = { name: item.name, d: clone(item.data), side: 0, tool: 'op', dxf: null, dirty: false, view: null, hover: null, snap: null };
  st.d.sides = st.d.sides || [];
  const dxfCache = {};

  const left = h('div.hw-side');
  const view = h('div.hw-view');
  const svg = s('svg', { class: 'dxf', style: 'width:100%;height:100%;display:block' });
  const tip = h('div.snap-tip', { style: { display: 'none' } });
  const legend = h('div.legend', { style: { position: 'absolute', left: '12px', bottom: '10px', background: 'rgba(255,255,255,.9)', padding: '4px 8px', borderRadius: '4px' } },
    h('span', h('span.sw', { style: { width: '14px', height: '3px', background: '#c0392b', display: 'inline-block' } }), 'обработка'),
    h('span', h('span.sw', { style: { width: '14px', height: '3px', background: '#7f8a93', display: 'inline-block' } }), 'вспомогательная'),
    h('span', h('span.sw', { style: { width: '14px', height: '3px', background: '#d0d6db', display: 'inline-block' } }), 'не используется'),
    h('span', h('span.sw', { style: { width: '14px', height: '3px', background: '#1f6fd1', display: 'inline-block' } }), 'край стекла'),
    h('span', '✛ точка привязки'));
  view.append(svg, tip, legend);
  root.appendChild(h('div.hw-editor', left, view));

  const side = () => st.d.sides[st.side];
  const markDirty = () => { st.dirty = true; saveBtn.classList.add('primary'); };
  const saveBtn = h('button.btn', { onclick: () => save() }, 'Сохранить');

  async function save() {
    document.activeElement && document.activeElement.blur();
    await api.put('/api/lib/hardware/' + id, { name: st.name, data: st.d });
    invalidateLib('hardware');
    st.dirty = false; saveBtn.classList.remove('primary');
    toast('Модель сохранена', 'ok', 1500);
  }

  async function loadDxf() {
    const sd = side();
    st.dxf = null;
    if (sd && sd.dxf_id) {
      if (!dxfCache[sd.dxf_id]) {
        try { dxfCache[sd.dxf_id] = await api.get('/api/dxf/' + sd.dxf_id); } catch (_) { dxfCache[sd.dxf_id] = null; }
      }
      st.dxf = dxfCache[sd.dxf_id];
    }
    st.view = null;
    renderView();
  }

  // ---------------------------------------------------------------- левая панель
  function renderLeft() {
    const d = st.d, sd = side();
    const prims = st.dxf ? st.dxf.data.primitives : [];
    const roleOf = (p) => (sd.roles || {})[p.id] || 'op';
    const nOp = prims.filter((p) => roleOf(p) === 'op' && p.id !== sd.edge_pid).length;
    const nAux = prims.filter((p) => roleOf(p) === 'aux').length;
    const edgePrim = prims.find((p) => p.id === sd.edge_pid);
    const vertical = edgePrim ? (() => { const sg = edgePrim.segs[0]; return Math.abs(sg.p2[1] - sg.p1[1]) >= Math.abs(sg.p2[0] - sg.p1[0]); })() : true;
    const steps = [
      ['Модель создана', true], ['Производитель указан', !!d.manufacturer_id], ['DXF загружен (или заданы отверстия)', !!sd.dxf_id || (sd.holes || []).length > 0],
      ['Рабочие линии выбраны', nOp > 0 || (sd.holes || []).length > 0], ['Вспомогательные помечены', nAux > 0 || !sd.dxf_id], ['Край стекла указан', !!sd.edge_pid || !sd.dxf_id],
      ['Точка привязки задана', !!sd.anchor || !sd.dxf_id], ['Сохранено', !st.dirty],
    ];
    const tools = [['op', 'Обработка', '#c0392b'], ['aux', 'Вспомогательная', '#7f8a93'], ['ignore', 'Не использовать', '#d0d6db'], ['edge', 'Край стекла', '#1f6fd1'], ['anchor', 'Точка привязки', '#1f6fd1']];
    clear(left,
      h('div.row', h('a', { href: '#/library/hardware' }, '← Библиотека'), h('div.right.row', h('button.btn.sm', { onclick: () => testPlacement() }, 'Проверить на стекле'), saveBtn)),
      field('Название / модель', textInput(st.name, (v) => { st.name = v; markDirty(); })),
      h('div.grid2',
        field('Производитель', selectInput(mans.map((x) => [x.id, x.name]), d.manufacturer_id, (v) => { d.manufacturer_id = v; markDirty(); renderLeft(); }, { empty: '—' })),
        field('Категория', selectInput(cats.map((x) => [x.id, x.name]), d.category_id, (v) => { d.category_id = v; markDirty(); }, { empty: '—' })),
        field('Артикул', textInput(d.article, (v) => { d.article = v; markDirty(); })),
        field('Цвет / покрытие', textInput(d.color, (v) => { d.color = v; markDirty(); }))),
      field('Тип соединения', selectInput(Object.entries(m.connection_types), d.connection, (v) => { d.connection = v; markDirty(); })),
      field('Зазор узла', numInput(d.joint_gap, (v) => { d.joint_gap = v; markDirty(); }, { unit: 'мм', placeholder: 'не влияет' }), 'Если задан — используется в расчёте стекол на этом стыке'),
      field('Примечание (спецификация)', textInput(d.note, (v) => { d.note = v; markDirty(); })),
      h('div.props-sec',
        h('div.row', h('div.sec-title', 'Стороны узла'), h('button.btn.sm.right', { onclick: () => {
          const key = String.fromCharCode(65 + d.sides.length);
          d.sides.push({ key, label: `Стекло ${key}`, dxf_id: null, roles: {}, edge_pid: null, glass_side: 'left', anchor: null, holes: [] });
          st.side = d.sides.length - 1; markDirty(); loadDxf().then(renderLeft);
        } }, '+ Сторона')),
        d.sides.length ? h('div.segmented', d.sides.map((x, i) => h('button' + (i === st.side ? '.on' : ''), { onclick: () => { st.side = i; loadDxf().then(renderLeft); } }, 'Сторона ' + x.key))) : h('span.hint', 'Без сторон модель попадает только в спецификацию.'),
        sd ? h('div.col',
          h('div.grid2',
            field('Назначение стороны', textInput(sd.label, (v) => { sd.label = v; markDirty(); }), 'напр. «Глухарь» / «Дверь»'),
            h('div.field', h('span.field-label', ' '), h('button.btn.sm.danger', { onclick: async () => { if (await confirmDlg(`Удалить сторону ${sd.key}?`)) { d.sides.splice(st.side, 1); st.side = 0; markDirty(); loadDxf().then(renderLeft); } } }, 'Удалить сторону'))),
          field('DXF обработки', h('div.row',
            selectInput(dxfList.map((x) => [x.id, x.name]), sd.dxf_id, (v) => { sd.dxf_id = v; sd.roles = {}; sd.edge_pid = null; sd.anchor = null; markDirty(); loadDxf().then(renderLeft); }, { empty: '— без DXF —' }),
            h('label.btn.sm', 'Загрузить…', h('input', { type: 'file', accept: '.dxf', style: { display: 'none' }, onchange: async (e) => {
              const fd = new FormData(); fd.append('file', e.target.files[0]); fd.append('name', `${st.name} — сторона ${sd.key}`);
              const r = await api.post('/api/dxf', fd);
              dxfList.push(r); sd.dxf_id = r.id; sd.roles = {}; sd.edge_pid = null; sd.anchor = null;
              // эвристика: примитивы на слоях AUX/ВСП — вспомогательные
              for (const p of r.data.primitives) if (/aux|всп|help|constr/i.test(p.layer)) sd.roles[p.id] = 'aux';
              markDirty(); await loadDxf(); renderLeft();
            } })))),
          sd.dxf_id ? h('div.col',
            h('div.sec-title.small.muted', 'ИНСТРУМЕНТ (клик по чертежу)'),
            h('div.tool-grid', tools.map(([k, label, color]) => h('button.tool' + (st.tool === k ? '.on' : ''), { onclick: () => { st.tool = k; renderLeft(); renderView(); } }, h('span.sw', { style: { background: color } }), label))),
            sd.edge_pid ? field('Где стекло относительно края',
              h('div.segmented', (vertical ? [['left', 'Слева'], ['right', 'Справа']] : [['above', 'Сверху'], ['below', 'Снизу']]).map(([k, l]) =>
                h('button' + (sd.glass_side === k || (!vertical && sd.glass_side === (k === 'above' ? 'left' : 'right')) ? '.on' : ''), { onclick: () => { sd.glass_side = k; markDirty(); renderLeft(); renderView(); } }, l))),
            'Подсвечено голубым') : null,
            h('div.readout', h('span', 'Рабочих примитивов'), h('b', String(nOp)), h('span', 'Вспомогательных'), h('b', String(nAux)),
              h('span', 'Точка привязки'), h('b', sd.anchor ? `${fmt(sd.anchor[0], 2)}; ${fmt(sd.anchor[1], 2)}` : '—'))) : null,
          h('div.sec-title.small.muted', 'ПАРАМЕТРИЧЕСКИЕ ОТВЕРСТИЯ СТОРОНЫ'),
          h('span.hint', 'u — вдоль кромки от точки привязки, v — внутрь стекла от кромки.'),
          ...(sd.holes || []).map((ho, i) => h('div.row', { style: { flexWrap: 'nowrap' } },
            field('u', numInput(ho.u, (v) => { ho.u = v ?? 0; markDirty(); renderView(); })),
            field('v', numInput(ho.v, (v) => { ho.v = v ?? 0; markDirty(); renderView(); })),
            field('Ø', numInput(ho.d, (v) => { ho.d = v ?? 0; markDirty(); renderView(); })),
            h('button.icon-btn', { style: { alignSelf: 'flex-end' }, onclick: () => { sd.holes.splice(i, 1); markDirty(); renderLeft(); renderView(); } }, '×'))),
          h('button.btn.sm', { onclick: () => { (sd.holes = sd.holes || []).push({ u: 0, v: 30, d: 12 }); markDirty(); renderLeft(); renderView(); } }, '+ Отверстие')) : null),
      h('div.props-sec', h('div.sec-title', 'Готовность'), h('ol.steps', steps.map(([t, ok]) => h('li' + (ok ? '.done' : ''), (ok ? '✓ ' : '') + t)))));
  }

  // ---------------------------------------------------------------- просмотр DXF
  function bbox() {
    if (st.dxf) return st.dxf.data.bbox;
    return [-100, -100, 100, 100];
  }
  function fit() {
    const [x0, y0, x1, y1] = bbox();
    const W = view.clientWidth || 800, H = view.clientHeight || 600;
    const pad = Math.max(x1 - x0, y1 - y0) * 0.2 + 5;
    let vw = x1 - x0 + 2 * pad, vh = y1 - y0 + 2 * pad;
    if (vw / vh > W / H) vh = vw * H / W; else vw = vh * W / H;
    st.view = { x: (x0 + x1) / 2 - vw / 2, y: -(y0 + y1) / 2 - vh / 2, w: vw, h: vh };
  }
  const k = () => st.view.w / (view.clientWidth || 800);
  function toModel(e) {
    const r = svg.getBoundingClientRect();
    return [st.view.x + (e.clientX - r.left) * st.view.w / r.width, -(st.view.y + (e.clientY - r.top) * st.view.h / r.height)];
  }
  function sideFrame() {
    const sd = side();
    const prims = st.dxf ? st.dxf.data.primitives : [];
    const edge = prims.find((p) => p.id === sd.edge_pid);
    if (!edge) return null;
    const sg = edge.segs[0];
    let d = [sg.p2[0] - sg.p1[0], sg.p2[1] - sg.p1[1]];
    const l = Math.hypot(...d); d = [d[0] / l, d[1] / l];
    if (Math.abs(d[1]) >= Math.abs(d[0])) { if (d[1] < 0) d = [-d[0], -d[1]]; } else if (d[0] < 0) d = [-d[0], -d[1]];
    const leftN = [-d[1], d[0]];
    const n = ['left', 'above'].includes(sd.glass_side) ? leftN : [-leftN[0], -leftN[1]];
    const a = sd.anchor || sg.p1;
    const t = (a[0] - sg.p1[0]) * d[0] + (a[1] - sg.p1[1]) * d[1];
    return { o: [sg.p1[0] + d[0] * t, sg.p1[1] + d[1] * t], d, n };
  }

  function renderView() {
    if (!st.view) fit();
    while (svg.firstChild) svg.firstChild.remove();
    svg.setAttribute('viewBox', `${st.view.x} ${st.view.y} ${st.view.w} ${st.view.h}`);
    const sd = side();
    if (!sd) return;
    const kk = k();
    const ns = { 'vector-effect': 'non-scaling-stroke' };
    const fr = sideFrame();
    if (fr) { // подсветка стороны стекла
      const L = Math.max(st.view.w, st.view.h) * 3;
      const { o, d, n } = fr;
      const pts = [[o[0] - d[0] * L, o[1] - d[1] * L], [o[0] + d[0] * L, o[1] + d[1] * L], [o[0] + d[0] * L + n[0] * L, o[1] + d[1] * L + n[1] * L], [o[0] - d[0] * L + n[0] * L, o[1] - d[1] * L + n[1] * L]];
      svg.appendChild(s('polygon', { class: 'glass-side', points: pts.map(([x, y]) => `${x},${-y}`).join(' ') }));
    }
    const prims = st.dxf ? st.dxf.data.primitives : [];
    for (const p of prims) {
      const role = (sd.roles || {})[p.id] || 'op';
      const isEdge = p.id === sd.edge_pid;
      const cls = 'prim ' + (isEdge ? 'edge' : role) + (st.hover === p.id ? ' hover' : '');
      const dpath = p.segs.map((sg) => segPath(sg)).join(' ');
      svg.appendChild(s('path', { class: cls, d: dpath, ...ns, 'stroke-width': isEdge ? 2.5 : 1.6 }));
      svg.appendChild(s('path', { class: 'hit', d: dpath, ...ns, 'stroke-width': 12, 'data-pid': p.id,
        onmouseenter: () => { st.hover = p.id; renderView(); }, onmouseleave: () => { if (st.hover === p.id) { st.hover = null; renderView(); } } }));
    }
    // параметрические отверстия (предпросмотр в системе стороны)
    if (fr || !st.dxf) {
      const { o, d, n } = fr || { o: sd.anchor || [0, 0], d: [0, 1], n: [-1, 0] };
      for (const ho of sd.holes || []) {
        const c = [o[0] + ho.u * d[0] + ho.v * n[0], o[1] + ho.u * d[1] + ho.v * n[1]];
        svg.appendChild(s('circle', { cx: c[0], cy: -c[1], r: (ho.d || 0) / 2, fill: 'none', stroke: '#c0392b', 'stroke-dasharray': '3 2', ...ns }));
      }
    }
    if (sd.anchor) {
      const [ax, ay] = sd.anchor, r = 10 * kk;
      svg.appendChild(s('g', { class: 'anchor' },
        s('line', { x1: ax - r * 1.6, y1: -ay, x2: ax + r * 1.6, y2: -ay, ...ns, 'stroke-width': 1.5 }),
        s('line', { x1: ax, y1: -ay - r * 1.6, x2: ax, y2: -ay + r * 1.6, ...ns, 'stroke-width': 1.5 }),
        s('circle', { cx: ax, cy: -ay, r, ...ns, 'stroke-width': 1.5 })));
    }
    if (st.snap && (st.tool === 'anchor')) {
      const [x, y] = st.snap.p, r = 6 * kk;
      const shape = st.snap.kind === 'center' ? s('circle', { cx: x, cy: -y, r }) :
        st.snap.kind === 'mid' ? s('polygon', { points: `${x},${-y - r} ${x + r},${-y + r} ${x - r},${-y + r}` }) :
          st.snap.kind === 'quad' ? s('polygon', { points: `${x},${-y - r} ${x + r},${-y} ${x},${-y + r} ${x - r},${-y}` }) :
            s('rect', { x: x - r, y: -y - r, width: 2 * r, height: 2 * r });
      shape.setAttribute('class', 'snap'); shape.setAttribute('vector-effect', 'non-scaling-stroke'); shape.setAttribute('stroke-width', '2');
      svg.appendChild(shape);
    }
    if (!st.dxf && !(sd.holes || []).length) {
      svg.appendChild(s('text', { x: st.view.x + st.view.w / 2, y: st.view.y + st.view.h / 2, 'text-anchor': 'middle', 'font-size': 14 * kk, fill: '#6b7680' }, 'Загрузите DXF или добавьте отверстия'));
    }
  }

  function findSnap(e) {
    if (!st.dxf) return null;
    const [mx, my] = toModel(e);
    const lim = SNAP_PX * k();
    let best = null, bd = lim;
    for (const p of st.dxf.data.primitives) for (const sn of p.snaps) {
      const dd = Math.hypot(sn.p[0] - mx, sn.p[1] - my);
      if (dd < bd) { bd = dd; best = sn; }
    }
    return best;
  }

  let pan = null;
  svg.addEventListener('wheel', (e) => {
    e.preventDefault();
    const [mx, my] = toModel(e);
    const f = Math.exp(e.deltaY * 0.0012), v = st.view, sy = -my;
    v.x = mx - (mx - v.x) * f; v.y = sy - (sy - v.y) * f; v.w *= f; v.h *= f;
    renderView();
  }, { passive: false });
  svg.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || e.shiftKey) { pan = { x: e.clientX, y: e.clientY, v: { ...st.view } }; e.preventDefault(); return; }
    const sd = side(); if (!sd) return;
    if (st.tool === 'anchor') {
      const sn = findSnap(e);
      if (!sn) { toast('Наведите курсор на объектную привязку (конец, середина, центр…)', 'error', 2000); return; }
      sd.anchor = [sn.p[0], sn.p[1]]; markDirty(); renderLeft(); renderView();
      return;
    }
    const pid = e.target.getAttribute && e.target.getAttribute('data-pid');
    if (!pid) { pan = { x: e.clientX, y: e.clientY, v: { ...st.view } }; return; }
    const prim = st.dxf.data.primitives.find((p) => p.id === pid);
    sd.roles = sd.roles || {};
    if (st.tool === 'edge') {
      if (!(prim.segs.length === 1 && prim.segs[0].t === 'line')) { toast('Край стекла — это отрезок (LINE)', 'error'); return; }
      sd.edge_pid = pid; sd.roles[pid] = 'aux';
      const sg = prim.segs[0];
      const vertical = Math.abs(sg.p2[1] - sg.p1[1]) >= Math.abs(sg.p2[0] - sg.p1[0]);
      if (vertical && !['left', 'right'].includes(sd.glass_side)) sd.glass_side = 'left';
      if (!vertical && !['above', 'below'].includes(sd.glass_side)) sd.glass_side = 'above';
      if (!sd.anchor) sd.anchor = [(sg.p1[0] + sg.p2[0]) / 2, (sg.p1[1] + sg.p2[1]) / 2];
    } else {
      sd.roles[pid] = st.tool;
      if (sd.edge_pid === pid && st.tool !== 'aux') sd.edge_pid = null;
    }
    markDirty(); renderLeft(); renderView();
  });
  const onMove = (e) => {
    if (pan) {
      const r = svg.getBoundingClientRect(), kx = st.view.w / r.width;
      st.view.x = pan.v.x - (e.clientX - pan.x) * kx; st.view.y = pan.v.y - (e.clientY - pan.y) * kx;
      svg.setAttribute('viewBox', `${st.view.x} ${st.view.y} ${st.view.w} ${st.view.h}`);
      return;
    }
    if (!svg.contains(e.target) && e.target !== svg) { tip.style.display = 'none'; return; }
    if (st.tool === 'anchor') {
      const sn = findSnap(e);
      if ((sn && sn.p) !== (st.snap && st.snap.p)) { st.snap = sn; renderView(); }
      if (sn) {
        const r = view.getBoundingClientRect();
        tip.style.display = 'block'; tip.style.left = (e.clientX - r.left + 14) + 'px'; tip.style.top = (e.clientY - r.top + 14) + 'px';
        tip.textContent = `${sn.label}  (${fmt(sn.p[0], 2)}; ${fmt(sn.p[1], 2)})`;
      } else tip.style.display = 'none';
    } else {
      const pid = e.target.getAttribute && e.target.getAttribute('data-pid');
      if (pid && st.dxf) {
        const p = st.dxf.data.primitives.find((x) => x.id === pid);
        const role = pid === side().edge_pid ? 'Край стекла' : ROLE_RU[(side().roles || {})[pid] || 'op'];
        const r = view.getBoundingClientRect();
        tip.style.display = 'block'; tip.style.left = (e.clientX - r.left + 14) + 'px'; tip.style.top = (e.clientY - r.top + 14) + 'px';
        tip.textContent = `${p.etype} · слой ${p.layer} · ${role}`;
      } else tip.style.display = 'none';
    }
  };
  const onUp = () => { pan = null; };
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp);
  const ro = new ResizeObserver(() => { st.view = null; renderView(); });
  ro.observe(view);

  // ---------------------------------------------------------------- проверка на тестовом стекле
  async function testPlacement() {
    if (st.dirty) await save();
    const sides = st.d.sides;
    const panels = (sides.length ? sides : [{ key: 'A' }]).slice(0, 3).map((sd, i) => ({
      id: 'p' + i, name: `${sd.label || 'Стекло'} (${sd.key})`, type: 'fixed', width: { mode: 'value', value: 600 }, height_override: 1000,
      edges: { left: { kind: 'free' }, right: { kind: 'free' }, top: { kind: 'free' }, bottom: { kind: 'free' } },
    }));
    const targets = {};
    sides.slice(0, 3).forEach((sd, i) => { targets[sd.key] = { panel_id: 'p' + i, edge: i === 0 ? 'right' : 'left' }; });
    const res = await api.post('/api/preview', { data: { panels, hardware: [{ id: 'hw', model_id: id, targets, pos: { ref: 'center', offset: 0 }, qty: 1 }], settings: { common_top: false } } });
    const pv = s('svg', { style: 'width:100%;height:440px;background:#fbfcfd;border:1px solid #dde3e8;border-radius:6px' });
    let x = 0;
    const g = s('g');
    for (const gl of res.glasses) {
      g.appendChild(s('path', { d: contourPath(gl.contour, x, 0), fill: '#dff0f6', stroke: '#24323c', 'vector-effect': 'non-scaling-stroke' }));
      for (const ho of gl.holes) g.appendChild(s('circle', { cx: ho.c[0] + x, cy: -ho.c[1], r: ho.r, fill: '#fff', stroke: '#c0392b', 'vector-effect': 'non-scaling-stroke' }));
      for (const ch of [...gl.inner, ...gl.open]) for (const sg of ch) g.appendChild(s('path', { d: segPath(sg, x, 0), fill: 'none', stroke: '#c0392b', 'vector-effect': 'non-scaling-stroke' }));
      g.appendChild(s('text', { x: x + gl.w / 2, y: 40, 'text-anchor': 'middle', 'font-size': 36, fill: '#1f6f8b' }, gl.name));
      x += gl.w + 40;
    }
    pv.appendChild(g);
    pv.setAttribute('viewBox', `-60 -1060 ${x + 80} 1160`);
    modal('Проверка: узел на тестовых стеклах 600 × 1000', h('div.col', pv,
      h('p.muted.small', 'Сторона A — на правой кромке левого стекла, сторона B — на левой кромке правого. Узел по центру высоты. Вырезы на кромке меняют контур.'),
      ...res.warnings.map((w) => h('div.msg.warn', w)), ...res.errors.map((w) => h('div.msg.err', w))), { wide: true });
  }

  await loadDxf();
  renderLeft();
  return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); ro.disconnect(); if (st.dirty) save(); };
}
