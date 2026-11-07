// Конструктор изделия: дерево слева, CAD-холст в центре, свойства справа.
import { api, lib, meta, download, invalidateLib } from './api.js';
import { h, clear, uid, clone, fmt, modal, field, selectInput, numInput, promptDlg, confirmDlg, menuButton, toast } from './ui.js';
import { CadCanvas } from './canvas.js';
import { renderProps, EDGE_RU } from './props.js';
import { templateIcon } from './orders.js';

export async function constructorPage(root, pid) {
  const first = await api.get('/api/products/' + pid);
  const lists = {};
  const reloadLists = async () => {
    const [m, hw, pr, tp, kits, opt, cats] = await Promise.all([meta(), lib('hardware'), lib('profiles'), lib('construction_templates'), lib('kits'), lib('op_templates'), lib('categories')]);
    Object.assign(lists, { meta: m, hardware: hw, profiles: pr, templates: tp, kits, opTemplates: opt, categories: cats });
  };
  await reloadLists();

  const st = {
    product: first.product, data: first.product.data, res: first.resolved, summary: first.summary,
    sel: null, undo: [], redo: [], version: 0, saveTimer: null, inflight: false,
  };
  const order = await api.get('/api/orders/' + st.product.order_id);
  const saveState = document.getElementById('save-state');

  // ---------------------------------------------------------------- разметка
  const left = h('div.cad-left');
  const center = h('div.cad-center');
  const right = h('div.cad-right');
  const titleEl = h('span.title', { title: 'Переименовать' }, st.product.name);
  titleEl.addEventListener('click', async () => {
    const n = await promptDlg('Название изделия', st.product.name);
    if (n) { const r = await api.put('/api/products/' + pid, { name: n }); st.product.name = r.product.name; titleEl.textContent = n; }
  });
  const undoBtn = h('button.btn.sm', { title: 'Отменить (Ctrl+Z)', onclick: () => undo() }, '↶');
  const redoBtn = h('button.btn.sm', { title: 'Повторить (Ctrl+Y)', onclick: () => redo() }, '↷');
  const toolbar = h('div.cad-toolbar',
    h('a', { href: '#/order/' + order.id }, `← Заказ №${order.number}`), titleEl, undoBtn, redoBtn,
    h('span.muted.small', '|'),
    h('button.btn.sm', { onclick: () => addGlass() }, '+ Стекло'),
    h('button.btn.sm', { onclick: () => addOp('hole') }, '+ Отверстие'),
    h('button.btn.sm', { onclick: () => addOp('group') }, '+ Группа'),
    h('button.btn.sm', { onclick: () => addOp('cutout') }, '+ Вырез'),
    h('button.btn.sm', { onclick: () => installHardwareDlg() }, '+ Фурнитура'),
    h('button.btn.sm', { onclick: () => addAxis() }, '+ Ось'),
    h('div.right.row',
      menuButton('Шаблоны', [
        { label: 'Сменить конструкцию…', onClick: () => applyTemplateDlg() },
        { label: 'Применить комплект…', onClick: () => applyKitDlg() },
        '-',
        { label: 'Сохранить как шаблон конструкции…', onClick: () => saveAsTemplate() },
      ], '.sm'),
      menuButton('PDF', [
        { label: 'Для клиента', onClick: () => download(`/api/orders/${order.id}/pdf?mode=client&product_id=${pid}`) },
        { label: 'Для производства', onClick: () => download(`/api/orders/${order.id}/pdf?mode=production&product_id=${pid}`) },
        { label: 'Полный', onClick: () => download(`/api/orders/${order.id}/pdf?mode=full&product_id=${pid}`) },
      ], '.sm'),
      menuButton('DXF', [
        { label: 'Все стекла (zip)', onClick: () => download(`/api/products/${pid}/dxf`) },
        { label: 'Конструкция целиком', onClick: () => download(`/api/products/${pid}/dxf?whole=true`) },
        { label: 'Стекла без размеров (zip)', onClick: () => download(`/api/products/${pid}/dxf?dims=false`) },
      ], '.sm.primary')));
  const shell = h('div.cad', toolbar, left, center, right);
  root.appendChild(shell);

  const dimBtns = {};
  const canvasTools = h('div.canvas-tools',
    h('button.btn.sm', { onclick: () => canvas.fit(), title: 'Показать всё' }, '⤢ Вписать'),
    ...[['detail', 'Размеры детали'], ['overview', 'Общие размеры'], ['none', 'Без размеров']].map(([k, label]) => {
      dimBtns[k] = h('button.btn.sm' + (k === 'detail' ? '.on' : ''), { onclick: () => { canvas.showDims = k; Object.entries(dimBtns).forEach(([kk, b]) => b.classList.toggle('on', kk === k)); canvas.render(); } }, label);
      return dimBtns[k];
    }));
  const msgs = h('div.canvas-msgs');
  center.append(canvasTools, msgs);
  const canvas = new CadCanvas(center, {
    onSelect: (sel) => select(sel),
    onDragEnd: (src, dx, dy) => dragEnd(src, dx, dy),
  });

  // ---------------------------------------------------------------- состояние и сохранение
  function change(mutator, { record = true } = {}) {
    if (record) { st.undo.push(clone(st.data)); if (st.undo.length > 100) st.undo.shift(); st.redo = []; }
    mutator(st.data);
    st.version++;
    renderTree();
    renderRight();
    scheduleSave();
  }
  function undo() { if (!st.undo.length) return; st.redo.push(clone(st.data)); st.data = st.undo.pop(); st.version++; validateSel(); renderAll(); scheduleSave(0); }
  function redo() { if (!st.redo.length) return; st.undo.push(clone(st.data)); st.data = st.redo.pop(); st.version++; validateSel(); renderAll(); scheduleSave(0); }

  function scheduleSave(delay = 120) {
    clearTimeout(st.saveTimer);
    saveState.textContent = 'Сохранение…'; saveState.className = 'saving';
    st.saveTimer = setTimeout(save, delay);
  }
  async function save() {
    if (st.inflight) { scheduleSave(150); return; }
    st.inflight = true;
    const v = st.version;
    try {
      const r = await api.put('/api/products/' + pid, { data: st.data }, { silent: true });
      st.res = r.resolved;
      if (v === st.version) { st.data = r.product.data; saveState.textContent = 'Сохранено'; saveState.className = 'saved'; }
      canvas.setData(st.res, canvasSel());
      renderMsgs();
      renderTree();
      renderRight(true);
    } catch (e) {
      saveState.textContent = 'Ошибка сохранения'; saveState.className = 'error';
      toast('Не удалось сохранить: ' + e.message, 'error');
    } finally { st.inflight = false; }
  }
  async function applyServer(promise) {
    const r = await promise;
    st.undo.push(clone(st.data));
    st.product = r.product; st.data = r.product.data; st.res = r.resolved; st.version++;
    validateSel(); renderAll();
    saveState.textContent = 'Сохранено'; saveState.className = 'saved';
  }

  // ---------------------------------------------------------------- выбор
  function kindOf(id) {
    if (st.data.panels.some((p) => p.id === id)) return 'glass';
    if (st.data.operations.some((o) => o.id === id)) return 'op';
    if (st.data.hardware.some((o) => o.id === id)) return 'hw';
    if (st.data.axes.some((o) => o.id === id)) return 'axis';
    if (st.data.extra_items.some((o) => o.id === id)) return 'extra';
    return null;
  }
  function select(sel) {
    if (sel && sel.type === 'src') { const t = kindOf(sel.id); sel = t ? { type: t, id: sel.id, glass: sel.glass } : null; }
    st.sel = sel;
    canvas.setSelection(canvasSel());
    renderTree();
    renderRight();
  }
  function canvasSel() { return st.sel; }
  function validateSel() { if (st.sel && !kindOf(st.sel.id)) st.sel = null; }
  function selectedGlassId() {
    if (!st.sel) return st.data.panels[0] && st.data.panels[0].id;
    if (st.sel.type === 'glass') return st.sel.id;
    if (st.sel.type === 'op') return (st.data.operations.find((o) => o.id === st.sel.id) || {}).panel_id;
    return st.sel.glass || (st.data.panels[0] && st.data.panels[0].id);
  }

  // ---------------------------------------------------------------- действия
  function addGlass() {
    const id = uid();
    change((d) => {
      d.panels.push({
        id, name: `Стекло ${d.panels.length + 1}`, type: 'fixed', plane: 'front',
        width: d.measurement.width_top || d.measurement.width_bottom || d.measurement.width_mid ? { mode: 'auto', value: null, formula: '' } : { mode: 'value', value: 800, formula: '' },
        width_override: null, height_override: null, x_formula: '', y_override: null, align_top_with: null,
        edges: { left: { kind: 'auto' }, right: { kind: 'auto' }, top: { kind: 'free' }, bottom: { kind: 'floor' } },
        shape: { type: 'rect' }, qty: 1,
      });
    });
    select({ type: 'glass', id });
  }
  function addOp(type, glassId) {
    const gid = glassId || selectedGlassId();
    if (!gid) { toast('Сначала добавьте стекло', 'error'); return; }
    const id = uid();
    const op = { id, panel_id: gid, type, name: '' };
    if (type === 'hole') Object.assign(op, { d: 12, x: { ref: 'left', value: 100 }, y: { ref: 'top', value: 100 } });
    if (type === 'group') Object.assign(op, { mirror: 'x', repeat: { count: 1, step: 0, dir: 'v' }, items: [{ d: 16, x: { ref: 'left', value: 80 }, y: { ref: 'top', value: 30 } }, { d: 10, x: { ref: 'left', value: 80 }, y: { ref: 'top', value: 60 } }] });
    if (type === 'cutout') Object.assign(op, { w: 40, h: 60, r: 5, x: { ref: 'right', value: 0 }, y: { ref: 'top', value: 300 } });
    change((d) => { d.operations.push(op); });
    select({ type: 'op', id, glass: gid });
  }
  function addAxis() {
    const id = uid();
    change((d) => { d.axes.push({ id, name: `Ось ${d.axes.length + 1}`, ref: 'top', offset: 250, panel_id: null }); });
    select({ type: 'axis', id });
  }
  function moveGlass(id, dir) {
    change((d) => {
      const i = d.panels.findIndex((p) => p.id === id);
      const j = i + dir;
      if (j < 0 || j >= d.panels.length) return;
      [d.panels[i], d.panels[j]] = [d.panels[j], d.panels[i]];
    });
  }
  function duplicateGlass(id) {
    const nid = uid();
    change((d) => {
      const i = d.panels.findIndex((p) => p.id === id);
      const c = clone(d.panels[i]); c.id = nid; c.name += ' (копия)';
      d.panels.splice(i + 1, 0, c);
      for (const o of d.operations.filter((o) => o.panel_id === id)) d.operations.push({ ...clone(o), id: uid(), panel_id: nid });
    });
    select({ type: 'glass', id: nid });
  }
  function duplicateSel() {
    const s = st.sel; if (!s) return;
    const coll = { op: 'operations', hw: 'hardware', axis: 'axes', extra: 'extra_items', glass: 'panels' }[s.type];
    if (s.type === 'glass') { duplicateGlass(s.id); return; }
    const nid = uid();
    change((d) => {
      const o = d[coll].find((x) => x.id === s.id);
      const c = clone(o); c.id = nid; if (c.name) c.name += ' (копия)'; delete c.from_kit;
      d[coll].push(c);
    });
    select({ ...s, id: nid });
  }
  async function removeSel() {
    const s = st.sel; if (!s) return;
    if (s.type === 'glass') {
      const p = st.data.panels.find((x) => x.id === s.id);
      if (!(await confirmDlg(`Удалить стекло «${p.name}» и его обработку?`))) return;
      change((d) => {
        d.panels = d.panels.filter((x) => x.id !== s.id);
        d.operations = d.operations.filter((o) => o.panel_id !== s.id);
        for (const hw of d.hardware) for (const k of Object.keys(hw.targets || {})) if (hw.targets[k].panel_id === s.id) delete hw.targets[k];
        d.hardware = d.hardware.filter((hw) => Object.keys(hw.targets || {}).length);
      });
    } else {
      const coll = { op: 'operations', hw: 'hardware', axis: 'axes', extra: 'extra_items' }[s.type];
      change((d) => { d[coll] = d[coll].filter((x) => x.id !== s.id); });
    }
    select(null);
  }
  function dragEnd(src, dx, dy) {
    const t = kindOf(src);
    if (t === 'op') {
      change((d) => {
        const o = d.operations.find((x) => x.id === src);
        const shiftX = (spec) => { if (!spec) return; spec.value = Math.round(((spec.ref === 'right') ? (spec.value || 0) - dx : (spec.value || 0) + dx) * 10) / 10; };
        const shiftY = (spec) => { if (!spec) return; spec.value = Math.round(((spec.ref === 'top') ? (spec.value || 0) - dy : (spec.value || 0) + dy) * 10) / 10; };
        if (o.type === 'group') for (const it of o.items) { if (dx) shiftX(it.x); if (dy) shiftY(it.y); }
        else { if (dx) shiftX(o.x); if (dy) shiftY(o.y); }
      });
    } else if (t === 'hw') {
      change((d) => {
        const hw = d.hardware.find((x) => x.id === src);
        const pos = hw.pos || (hw.pos = { ref: 'top', offset: 0 });
        const firstT = Object.values(hw.targets || {})[0] || {};
        const horiz = firstT.edge === 'top' || firstT.edge === 'bottom';
        const delta = horiz ? dx : dy;
        if (!delta) return;
        pos.offset = Math.round(((pos.ref === 'top' || pos.ref === 'right') ? (pos.offset || 0) - delta : (pos.offset || 0) + delta) * 10) / 10;
      });
    }
  }

  // ---------------------------------------------------------------- диалоги
  function joints() {
    const out = [];
    const byPlane = {};
    for (const g of st.res.glasses) (byPlane[g.plane] = byPlane[g.plane] || []).push(g);
    for (const gs of Object.values(byPlane)) {
      gs.sort((a, b) => a.x - b.x);
      for (let i = 0; i < gs.length - 1; i++) out.push([gs[i], gs[i + 1]]);
    }
    return out;
  }
  function installHardwareDlg() {
    if (!lists.hardware.length) { toast('В базе нет фурнитуры — добавьте модель в Библиотеке', 'error'); return; }
    const catName = (id) => (lists.categories.find((c) => c.id === id) || {}).name || 'Без категории';
    const opts = [...lists.hardware].sort((a, b) => catName(a.data.category_id).localeCompare(catName(b.data.category_id))).map((m) => [m.id, `${catName(m.data.category_id)} — ${m.name}`]);
    const v = { model_id: opts[0][0], joint: 0, glass: selectedGlassId(), edge: 'right', ref: 'top', offset: 250, swap: false };
    const body = h('div.col');
    const js = joints();
    const render = () => {
      const m = lists.hardware.find((x) => x.id === v.model_id);
      const sides = (m && m.data.sides) || [];
      const two = sides.length >= 2;
      clear(body,
        field('Модель', selectInput(opts, v.model_id, (x) => { v.model_id = x; render(); })),
        m ? h('div.readout', h('span', 'Тип соединения'), h('b', lists.meta.connection_types[m.data.connection] || '—'), h('span', 'Сторон с обработкой'), h('b', String(sides.length))) : null,
        two ? (js.length ? h('div.col',
          field('Между стеклами', selectInput(js.map(([a, b], i) => [String(i), `${a.name} | ${b.name}`]), String(v.joint), (x) => { v.joint = +x; })),
          h('label.check', h('input', { type: 'checkbox', checked: v.swap, onchange: (e) => { v.swap = e.target.checked; } }), h('span', 'Сторону A — на левое стекло (по умолчанию A — на неподвижное)')))
          : h('div.msg.warn', 'Нет соседних стекол для узла стекло–стекло')) :
          h('div.grid2',
            field('Стекло', selectInput(st.data.panels.map((p) => [p.id, p.name]), v.glass, (x) => { v.glass = x; })),
            field('Кромка', selectInput(Object.entries(EDGE_RU), v.edge, (x) => { v.edge = x; }))),
        h('div.grid2',
          field('Привязка', selectInput([['top', 'от верха'], ['bottom', 'от низа'], ['center', 'от центра'], ['left', 'от левого края'], ['right', 'от правого края']], v.ref, (x) => { v.ref = x; })),
          field('Отступ, мм', numInput(v.offset, (x) => { v.offset = x ?? 0; }))));
    };
    render();
    modal('Установить фурнитуру', body, {
      actions: [{ label: 'Отмена' }, {
        label: 'Установить', primary: true, onClick: () => {
          document.activeElement && document.activeElement.blur();
          const m = lists.hardware.find((x) => x.id === v.model_id);
          const sides = (m.data.sides || []);
          const targets = {};
          if (sides.length >= 2 && js.length) {
            const [a, b] = js[v.joint];
            const isDoor = (g) => g.type === 'door' || g.type === 'sliding_door';
            let A = { panel_id: a.id, edge: 'right' }, B = { panel_id: b.id, edge: 'left' };
            const aFirst = v.swap ? true : !isDoor(a) || isDoor(b);
            if (!aFirst) [A, B] = [B, A];
            targets[sides[0].key] = A; targets[sides[1].key] = B;
          } else if (sides.length) {
            targets[sides[0].key] = { panel_id: v.glass, edge: v.edge };
          }
          const id = uid();
          change((d) => { d.hardware.push({ id, model_id: m.id, targets, pos: { ref: v.ref, offset: v.offset, axis_id: null }, flip: false, qty: 1 }); });
          select({ type: 'hw', id });
        },
      }],
    });
  }
  function applyTemplateDlg() {
    let chosen = st.data.template_id;
    const grid = h('div.tmpl-grid');
    const render = () => clear(grid, lists.templates.map((t) => h('button.tmpl' + (chosen === t.id ? '.on' : ''), { type: 'button', onclick: () => { chosen = t.id; render(); } }, templateIcon(t.data), h('span.small', t.name))));
    render();
    modal('Конструкция', h('div.col', h('div.msg.warn', 'Стекла, обработка и фурнитура будут заменены схемой шаблона. Замер и настройки сохранятся. Комплект будет применён заново.'), grid), {
      wide: true,
      actions: [{ label: 'Отмена' }, { label: 'Применить', primary: true, onClick: () => applyServer(api.post(`/api/products/${pid}/apply_template`, { template_id: chosen })) }],
    });
  }
  function applyKitDlg() {
    if (!lists.kits.length) { toast('Комплекты создаются в Библиотеке → Комплекты', 'error'); return; }
    let chosen = st.data.kit_id || lists.kits[0].id;
    modal('Применить комплект', h('div.col',
      field('Комплект', selectInput(lists.kits.map((k) => [k.id, k.name]), chosen, (v) => { chosen = v; })),
      h('p.muted.small', 'Фурнитура и позиции предыдущего комплекта будут заменены. Вручную добавленная фурнитура сохранится.')), {
      actions: [{ label: 'Отмена' }, { label: 'Применить', primary: true, onClick: () => applyServer(api.post(`/api/products/${pid}/apply_kit`, { kit_id: chosen })) }],
    });
  }
  function applyOpTemplateDlg(glassId) {
    if (!lists.opTemplates.length) { toast('Шаблонов обработки пока нет', 'error'); return; }
    let chosen = lists.opTemplates[0].id;
    modal('Обработка из шаблона', field('Шаблон', selectInput(lists.opTemplates.map((t) => [t.id, t.name]), chosen, (v) => { chosen = v; })), {
      actions: [{ label: 'Отмена' }, {
        label: 'Применить', primary: true, onClick: () => {
          const t = lists.opTemplates.find((x) => x.id === chosen);
          change((d) => { for (const it of t.data.items || []) d.operations.push({ ...clone(it), id: uid(), panel_id: glassId, template_id: t.id }); });
        },
      }],
    });
  }
  async function saveAsTemplate() {
    const name = await promptDlg('Сохранить как шаблон конструкции', `${st.product.name} — шаблон`);
    if (!name) return;
    await api.post(`/api/products/${pid}/save_as_template`, { name });
    invalidateLib('construction_templates'); await reloadLists();
    toast('Шаблон сохранён', 'ok');
  }

  // ---------------------------------------------------------------- отрисовка
  const ctx = {
    get data() { return st.data; }, get res() { return st.res; }, get sel() { return st.sel; }, lists,
    change, addOp, moveGlass, duplicateGlass, duplicateSel, removeSel, applyTemplateDlg, applyKitDlg, applyOpTemplateDlg, reloadLists,
    downloadGlassDxf: (gid) => download(`/api/products/${pid}/dxf?glass_id=${gid}`),
  };

  function treeSec(title, onAdd, items, emptyText) {
    return h('div.tree-sec',
      h('div.tree-head', title, onAdd ? h('button.icon-btn', { title: 'Добавить', onclick: onAdd }, '+') : null),
      items.length ? items : h('div.tree-empty', emptyText));
  }
  function item(dotCls, label, sub, sel, onclick, child) {
    return h('div.tree-item' + (sel ? '.sel' : '') + (child ? '.child' : ''), { onclick }, h('span.dot.' + dotCls), h('span', label), sub ? h('span.sub', sub) : null);
  }
  function renderTree() {
    const d = st.data, r = st.res;
    const isSel = (id) => st.sel && st.sel.id === id;
    const gById = Object.fromEntries(r.glasses.map((g) => [g.id, g]));
    const hwName = (id) => (lists.hardware.find((m) => m.id === id) || {}).name || '(удалена)';
    const profName = (id) => (lists.profiles.find((m) => m.id === id) || {}).name || '(удалён)';
    const opLabel = (o) => o.name || (o.type === 'hole' ? `Отверстие Ø${fmt(o.d)}` : o.type === 'group' ? `Группа (${o.items.length})` : `Вырез ${fmt(o.w)}×${fmt(o.h)}`);
    const profItems = [];
    for (const p of d.panels) for (const [side, e] of Object.entries(p.edges)) if (e.profile_id) profItems.push(item('prof', `${p.name} — ${EDGE_RU[side].toLowerCase()}`, profName(e.profile_id), false, () => select({ type: 'glass', id: p.id })));
    clear(left,
      h('div.tree-sec', h('div.tree-item' + (!st.sel ? '.sel' : ''), { onclick: () => select(null) }, h('b', 'Изделие и замер'), h('span.sub', r.opening.W ? `${fmt(r.opening.W)}×${fmt(r.opening.H)}` : 'ручной'))),
      treeSec('Стекла', addGlass, d.panels.map((p) => {
        const g = gById[p.id];
        return item('glass', p.name, g ? `${fmt(g.w, 0)}×${fmt(g.h, 0)}` : '', isSel(p.id), () => select({ type: 'glass', id: p.id }));
      }), 'Нет стекол'),
      treeSec('Фурнитура', installHardwareDlg, d.hardware.map((x) => {
        const names = Object.values(x.targets || {}).map((t) => (d.panels.find((p) => p.id === t.panel_id) || {}).name).filter(Boolean);
        return item('hw', hwName(x.model_id), names.join(' | '), isSel(x.id), () => select({ type: 'hw', id: x.id }));
      }), 'Не установлена'),
      treeSec('Профили', null, profItems, 'Назначаются на кромки стекла'),
      treeSec('Обработка', () => addOp('hole'), d.panels.flatMap((p) => {
        const ops = d.operations.filter((o) => o.panel_id === p.id);
        return ops.length ? [h('div.tree-item.child', { style: { color: '#6b7680', cursor: 'default' } }, p.name), ...ops.map((o) => item('op', opLabel(o) + (o.disabled ? ' (откл.)' : ''), '', isSel(o.id), () => select({ type: 'op', id: o.id, glass: p.id }), true))] : [];
      }), 'Отверстия, группы и вырезы'),
      treeSec('Оси', addAxis, d.axes.map((a) => item('axis', a.name || 'Ось', `${a.ref === 'top' ? '↓' : '↑'}${fmt(a.offset)}`, isSel(a.id), () => select({ type: 'axis', id: a.id }))), 'Необязательны'),
      treeSec('Доп. позиции', () => { const id = uid(); change((dd) => { dd.extra_items.push({ id, name: 'Позиция', qty: 1, length_formula: '', note: '' }); }); select({ type: 'extra', id }); },
        d.extra_items.map((x) => item('prof', (lists.hardware.find((m) => m.id === x.model_id) || lists.profiles.find((m) => m.id === x.profile_id) || x).name || 'Позиция', `×${x.qty}`, isSel(x.id), () => select({ type: 'extra', id: x.id }))), 'Уплотнители, пороги и т.п.'),
      h('div.tree-sec', h('div.tree-head', 'Спецификация'),
        h('div.tree-empty', `Стекол: ${r.bom.glass.length}, площадь ${fmt(r.bom.glass.reduce((s, g) => s + g.area * g.qty, 0), 2)} м²`),
        h('div.tree-empty', `Позиций фурнитуры: ${r.bom.hardware.length}`)));
    undoBtn.disabled = !st.undo.length; redoBtn.disabled = !st.redo.length;
  }
  function renderRight(keepFocus) {
    const active = document.activeElement;
    const key = keepFocus && active && right.contains(active) ? active.getAttribute('data-key') : null;
    const scroll = right.scrollTop;
    clear(right, renderProps(ctx));
    right.scrollTop = scroll;
    if (key) { const el = right.querySelector(`[data-key="${key}"]`); if (el) { el.focus(); if (el.select) el.select(); } }
  }
  function renderMsgs() {
    clear(msgs, ...(st.res.errors || []).slice(0, 3).map((e) => h('div.msg.err', e)));
  }
  function renderAll() { canvas.setData(st.res, canvasSel()); renderTree(); renderRight(); renderMsgs(); }

  const onKey = (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd') { e.preventDefault(); duplicateSel(); }
    else if (e.key === 'Delete') removeSel();
    else if (e.key === 'Escape') select(null);
    else if (e.key === 'f' || e.key === 'а') canvas.fit();
  };
  document.addEventListener('keydown', onKey);
  renderAll();

  return () => { document.removeEventListener('keydown', onKey); canvas.destroy(); clearTimeout(st.saveTimer); if (st.version && saveState.className === 'saving') save(); };
}
