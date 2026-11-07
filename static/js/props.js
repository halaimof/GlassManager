// Панель свойств конструктора. Все производственные значения — точные числа.
import { h, field, numInput, textInput, selectInput, checkInput, segmented, fmt, uid, clone, promptDlg } from './ui.js';
import { api, invalidateLib } from './api.js';

const EDGE_RU = { left: 'Лево', right: 'Право', top: 'Верх', bottom: 'Низ' };
const SIDE_KINDS = [['auto', 'Авто'], ['wall', 'Стена'], ['glass', 'Стекло'], ['free', 'Свободный']];
const TOP_KINDS = [['free', 'Свободный'], ['ceiling', 'Потолок']];
const BOTTOM_KINDS = [['floor', 'Пол'], ['free', 'Свободный']];
const X_REFS = [['left', 'от левого края'], ['right', 'от правого края'], ['center', 'от центра'], ['abs', 'вручную (X)']];
const Y_REFS = [['top', 'от верха'], ['bottom', 'от низа'], ['center', 'от центра'], ['axis', 'от оси'], ['abs', 'вручную (Y)']];
const POS_REFS = [['top', 'от верха стекла A'], ['bottom', 'от низа стекла A'], ['center', 'от центра'], ['axis', 'от оси']];
const POS_REFS_H = [['left', 'от левого края'], ['right', 'от правого края'], ['center', 'от центра']];

const sec = (title, ...children) => h('div.props-sec', title ? h('div.sec-title', title) : null, ...children);

export function renderProps(ctx) {
  const { sel } = ctx;
  if (!sel) return productProps(ctx);
  if (sel.type === 'glass') return glassProps(ctx, sel.id);
  if (sel.type === 'op') return opProps(ctx, sel.id);
  if (sel.type === 'hw') return hwProps(ctx, sel.id);
  if (sel.type === 'axis') return axisProps(ctx, sel.id);
  if (sel.type === 'extra') return extraProps(ctx, sel.id);
  return productProps(ctx);
}

function messages(res) {
  return [
    ...(res.errors || []).map((e) => h('div.msg.err', e)),
    ...(res.warnings || []).map((w) => h('div.msg.warn', w)),
  ];
}

// ------------------------------------------------------------------ изделие
function productProps(ctx) {
  const { data, res, change, lists } = ctx;
  const m = data.measurement, st = data.settings, gp = data.gaps;
  const mset = (k) => (v) => change((d) => { d.measurement[k] = v; });
  const sset = (k) => (v) => change((d) => { d.settings[k] = v; });
  const gset = (k) => (v) => change((d) => { d.gaps[k] = v ?? 0; });
  const hasSide = data.panels.some((p) => p.plane === 'side');
  const tmpl = lists.templates.find((t) => t.id === data.template_id);
  const kit = lists.kits.find((k) => k.id === data.kit_id);
  return h('div.props',
    h('h3', 'Изделие'),
    ...messages(res),
    res.opening && res.opening.W ? h('div.readout',
      h('span', 'Расчётный проём'), h('b', `${fmt(res.opening.W)} × ${fmt(res.opening.H)}`),
      ...res.planes.map((p) => [h('span', `${p.name}: доступно под стекла`), h('b', fmt(p.A))])) : null,
    sec('Замер проёма, мм',
      h('div.grid3',
        field('Ш. сверху', numInput(m.width_top, mset('width_top'), { key: 'm.wt' })),
        field('Ш. центр', numInput(m.width_mid, mset('width_mid'), { key: 'm.wm' })),
        field('Ш. снизу', numInput(m.width_bottom, mset('width_bottom'), { key: 'm.wb' })),
        field('В. слева', numInput(m.height_left, mset('height_left'), { key: 'm.hl' })),
        field('В. справа', numInput(m.height_right, mset('height_right'), { key: 'm.hr' })),
        hasSide ? field('Глубина', numInput(m.depth, mset('depth'), { key: 'm.d' })) : h('span')),
      h('span.hint', 'Расчёт ведётся по минимальной ширине и высоте.')),
    sec('Высота стекол',
      segmented([['fixed', 'Задана'], ['opening', 'По проёму']], st.top_mode, sset('top_mode')),
      st.top_mode === 'fixed' ? field('Верх стекол от пола', numInput(st.top_height, sset('top_height'), { key: 's.th', unit: 'мм' })) :
        field('Зазор верх стекла ↔ верх проёма', numInput(gp.top, gset('top'), { key: 'g.top', unit: 'мм' })),
      checkInput(st.common_top, sset('common_top'), 'Общий верх стекол (перепады — снизу)')),
    sec('Технологические зазоры, мм',
      h('div.grid2',
        field('Стекло ↔ стекло', numInput(gp.glass_glass, gset('glass_glass'), { key: 'g.gg' })),
        field('Дверь ↔ пол', numInput(gp.door_floor, gset('door_floor'), { key: 'g.df' })),
        field('Глухарь ↔ пол', numInput(gp.fixed_floor, gset('fixed_floor'), { key: 'g.ff' }), 'без профиля'),
        field('Стекло ↔ стена', numInput(gp.wall, gset('wall'), { key: 'g.w' }), 'без профиля/петли')),
      h('span.hint', 'Профиль на кромке и зазор петли из базы имеют приоритет. Точное значение можно задать на кромке стекла.')),
    sec('Стекло по умолчанию',
      h('div.grid2',
        field('Толщина', numInput(st.thickness, sset('thickness'), { key: 's.t', unit: 'мм' })),
        field('Цвет', colorInput(st.color, sset('color'))),
        field('Тип стекла', textInput(st.glass_type, sset('glass_type'))),
        field('Обработка кромки', textInput(st.edge_work, sset('edge_work')))),
      checkInput(st.tempered, sset('tempered'), 'Закалка')),
    sec('Фурнитура и чертёж',
      field('Цвет фурнитуры', textInput(st.hardware_color, sset('hardware_color'))),
      field('Габарит высоты на чертеже', segmented([['auto', 'Авто'], ['left', 'Слева'], ['right', 'Справа']], st.dim_side, sset('dim_side')),
        'Авто — с противоположной стороны от основной фурнитуры')),
    sec('Шаблон и комплект',
      h('div.readout', h('span', 'Конструкция'), h('b', tmpl ? tmpl.name : '—'), h('span', 'Комплект'), h('b', kit ? kit.name : '—')),
      h('div.row', h('button.btn.sm', { onclick: ctx.applyTemplateDlg }, 'Сменить конструкцию…'), h('button.btn.sm', { onclick: ctx.applyKitDlg }, 'Применить комплект…'))));
}

const COLORS = ['Прозрачное', 'Осветлённое', 'Бронза', 'Графит', 'Матовое', 'Зеркало серебро', 'Зеркало бронза', 'Зеркало графит'];
function colorInput(value, onChange) {
  const id = 'colors-' + uid().slice(0, 6);
  const inp = textInput(value, onChange);
  inp.setAttribute('list', id);
  return h('span', inp, h('datalist', { id }, COLORS.map((c) => h('option', { value: c }))));
}

// ------------------------------------------------------------------ стекло
function glassProps(ctx, id) {
  const { data, res, change, lists } = ctx;
  const p = data.panels.find((x) => x.id === id);
  const g = res.glasses.find((x) => x.id === id);
  if (!p) return productProps(ctx);
  const set = (fn) => change((d) => { fn(d.panels.find((x) => x.id === id), d); });
  const wm = p.width.mode;
  const shape = p.shape || { type: 'rect' };
  const others = data.panels.filter((x) => x.id !== id);
  const ops = data.operations.filter((o) => o.panel_id === id);
  const profOpts = lists.profiles.map((pr) => [pr.id, `${pr.name} (−${fmt(pr.deduction)})`]);
  const edgeRow = (side) => {
    const e = p.edges[side];
    const kinds = side === 'top' ? TOP_KINDS : side === 'bottom' ? BOTTOM_KINDS : SIDE_KINDS;
    return [
      h('span', EDGE_RU[side]),
      selectInput(kinds, e.kind, (v) => set((x) => { x.edges[side].kind = v; })),
      selectInput(profOpts, e.profile_id, (v) => set((x) => { x.edges[side].profile_id = v; }), { empty: '— без профиля —' }),
      numInput(e.override, (v) => set((x) => { x.edges[side].override = v; }), { placeholder: 'авто', key: `e.${side}` }),
    ];
  };
  return h('div.props',
    h('h3', h('span.dot.glass'), p.name),
    g ? h('div.readout',
      h('span', 'Размер стекла'), h('b', `${fmt(g.w)} × ${fmt(g.h)} × ${fmt(g.thickness)}`),
      h('span', 'Положение X / Y (низ)'), h('b', `${fmt(g.x)} / ${fmt(g.y)}`),
      h('span', 'Отверстий / вырезов'), h('b', `${g.holes.length} / ${g.cut_boxes.length + g.inner.length}`)) : null,
    ...(res.errors || []).filter((e) => e.startsWith(p.name)).map((e) => h('div.msg.err', e)),
    sec(null,
      h('div.grid2',
        field('Название', textInput(p.name, (v) => set((x) => { x.name = v || x.name; }), { key: 'p.name' })),
        field('Тип', selectInput(Object.entries(lists.meta.panel_types), p.type, (v) => set((x) => { x.type = v; })))),
      data.panels.some((x) => x.plane === 'side') || p.plane === 'side' ?
        field('Плоскость', segmented([['front', 'Фронт'], ['side', 'Боковая']], p.plane, (v) => set((x) => { x.plane = v; }))) : null),
    sec('Ширина',
      segmented([['auto', 'Авто'], ['value', 'Число'], ['formula', 'Формула']], wm, (v) => set((x) => { x.width.mode = v; if (v === 'value' && x.width.value == null && g) x.width.value = Math.round(g.w); })),
      wm === 'value' ? field('Ширина', numInput(p.width.value, (v) => set((x) => { x.width.value = v; }), { key: 'p.wv', unit: 'мм' })) : null,
      wm === 'formula' ? field('Формула ширины', textInput(p.width.formula, (v) => set((x) => { x.width.formula = v; }), { key: 'p.wf', placeholder: 'A / 2 + 30' }),
        'L — проём, A — доступно под стекла, H — высота, dl/dr — вычеты у стен, T — толщина') : null,
      wm === 'auto' ? h('span.hint', 'Остаток проёма после вычетов, зазоров и стекол с заданной шириной.') : null,
      field('Ручная корректировка ширины', numInput(p.width_override, (v) => set((x) => { x.width_override = v; }), { key: 'p.wo', placeholder: 'нет', unit: 'мм' }), 'Перекрывает расчёт'),
      field('Положение X (формула)', textInput(p.x_formula, (v) => set((x) => { x.x_formula = v; }), { key: 'p.xf', placeholder: 'по порядку' }),
        'Для раздвижных: L - dr - w. Пусто — по порядку с зазорами.')),
    sec('Высота',
      field('Ручная высота', numInput(p.height_override, (v) => set((x) => { x.height_override = v; }), { key: 'p.ho', placeholder: 'авто', unit: 'мм' }), 'Отсчёт сверху вниз — верх сохраняется'),
      field('Выровнять по верху с…', selectInput(others.map((o) => [o.id, o.name]), p.align_top_with, (v) => set((x) => { x.align_top_with = v; }), { empty: '— общий/свой верх —' })),
      field('Низ стекла от пола (вручную)', numInput(p.y_override, (v) => set((x) => { x.y_override = v; }), { key: 'p.yo', placeholder: 'авто', unit: 'мм' }))),
    sec('Кромки: тип, профиль, вычет',
      h('div.edge-table', h('span.eh', ''), h('span.eh', 'Примыкание'), h('span.eh', 'Профиль'), h('span.eh', 'Вычет'),
        ...['left', 'right', 'top', 'bottom'].flatMap(edgeRow)),
      h('span.hint', 'Вычет — точное значение зазора/посадки на эту кромку (мм). Пусто — по профилю, фурнитуре и правилам зазоров.')),
    shapeSection(p, set),
    sec('Стекло',
      h('div.grid2',
        field('Толщина', numInput(p.thickness, (v) => set((x) => { x.thickness = v; }), { placeholder: String(data.settings.thickness), key: 'p.t' })),
        field('Цвет', colorInput(p.color || '', (v) => set((x) => { x.color = v || null; }))),
        field('Тип стекла', textInput(p.glass_type || '', (v) => set((x) => { x.glass_type = v || null; }), { placeholder: data.settings.glass_type })),
        field('Кромка', textInput(p.edge_work || '', (v) => set((x) => { x.edge_work = v || null; }), { placeholder: data.settings.edge_work })),
        field('Количество', numInput(p.qty, (v) => set((x) => { x.qty = Math.max(1, Math.round(v || 1)); }), { key: 'p.q' }))),
      h('span.hint', 'Пустые поля — значения изделия.')),
    sec('Обработка стекла',
      h('div.row',
        h('button.btn.sm', { onclick: () => ctx.addOp('hole', id) }, '+ Отверстие'),
        h('button.btn.sm', { onclick: () => ctx.addOp('group', id) }, '+ Группа'),
        h('button.btn.sm', { onclick: () => ctx.addOp('cutout', id) }, '+ Вырез')),
      h('div.row',
        h('button.btn.sm', { onclick: () => ctx.applyOpTemplateDlg(id) }, 'Из шаблона…'),
        ops.length ? h('button.btn.sm', { onclick: async () => {
          const name = await promptDlg('Сохранить обработку как шаблон', `${p.name} — схема`);
          if (!name) return;
          const items = ops.map((o) => { const c = clone(o); delete c.id; delete c.panel_id; return c; });
          await api.post('/api/lib/op_templates', { name, data: { items, description: `Из стекла «${p.name}»` } });
          invalidateLib('op_templates'); await ctx.reloadLists();
        } }, 'Сохранить как шаблон') : null)),
    sec(null, h('div.row',
      h('button.btn.sm', { onclick: () => ctx.moveGlass(id, -1) }, '← Левее'),
      h('button.btn.sm', { onclick: () => ctx.moveGlass(id, 1) }, 'Правее →'),
      h('button.btn.sm', { onclick: () => ctx.duplicateGlass(id) }, 'Дублировать'),
      h('button.btn.sm', { onclick: () => ctx.downloadGlassDxf(id) }, 'DXF'),
      h('button.btn.sm.danger', { onclick: () => ctx.removeSel() }, 'Удалить'))));
}

function shapeSection(p, set) {
  const shape = p.shape || { type: 'rect' };
  const body = [segmented([['rect', 'Прямоугольник'], ['quad', 'Четырёхугольник'], ['polygon', 'Многоугольник']], shape.type, (v) => set((x) => {
    if (v === 'quad') x.shape = { type: 'quad', top: x.width.value || 700, bottom: x.width.value || 700, left: 2000, right: 2000, corner: 'tl', angle: 90 };
    else if (v === 'polygon') x.shape = { type: 'polygon', points: [[0, 0], [800, 0], [800, 1800], [0, 2000]] };
    else x.shape = { type: 'rect' };
  }))];
  if (shape.type === 'quad') {
    const q = (k) => (v) => set((x) => { x.shape[k] = v; });
    body.push(h('div.grid2',
      field('Верх', numInput(shape.top, q('top'), { key: 'q.t', unit: 'мм' })),
      field('Низ', numInput(shape.bottom, q('bottom'), { key: 'q.b', unit: 'мм' })),
      field('Левая сторона', numInput(shape.left, q('left'), { key: 'q.l', unit: 'мм' })),
      field('Правая сторона', numInput(shape.right, q('right'), { key: 'q.r', unit: 'мм' })),
      field('Известный угол', selectInput([['tl', 'верхний левый'], ['tr', 'верхний правый'], ['bl', 'нижний левый'], ['br', 'нижний правый']], shape.corner, q('corner'))),
      field('Значение угла', numInput(shape.angle ?? 90, q('angle'), { key: 'q.a', unit: '°' }))),
      h('span.hint', 'Остальные вершины вычисляются. Невозможная геометрия — ошибка над панелью.'));
  } else if (shape.type === 'polygon') {
    const ta = h('textarea', { rows: 5, 'data-key': 'poly' }, (shape.points || []).map((pt) => pt.join('; ')).join('\n'));
    ta.addEventListener('change', () => {
      const pts = ta.value.split('\n').map((ln) => ln.split(/[;\t ]+/).map((v) => parseFloat(v.replace(',', '.')))).filter((pt) => pt.length >= 2 && pt.every(Number.isFinite)).map((pt) => pt.slice(0, 2));
      set((x) => { x.shape.points = pts; });
    });
    body.push(field('Вершины X; Y (мм), по строке на вершину', ta, 'Против часовой стрелки от левого нижнего угла'));
  } else {
    body.push(h('span.hint', 'Ширина и высота — из расчёта проёма или вручную.'));
  }
  return sec('Форма', ...body);
}

// ------------------------------------------------------------------ обработка
function refEditor(spec, refs, onChange, axes, key) {
  const cur = spec || {};
  return h('div.grid2',
    selectInput(refs, cur.ref, (v) => onChange({ ...cur, ref: v })),
    numInput(cur.value ?? 0, (v) => onChange({ ...cur, value: v ?? 0 }), { key, unit: 'мм' }),
    cur.ref === 'axis' ? selectInput(axes.map((a) => [a.id, a.name || 'Ось']), cur.axis_id, (v) => onChange({ ...cur, axis_id: v }), { empty: '— ось —' }) : null);
}

function opProps(ctx, id) {
  const { data, change } = ctx;
  const op = data.operations.find((o) => o.id === id);
  if (!op) return productProps(ctx);
  const set = (fn) => change((d) => { fn(d.operations.find((o) => o.id === id)); });
  const glassOpts = data.panels.map((p) => [p.id, p.name]);
  const axes = data.axes;
  const title = { hole: 'Отверстие', group: 'Группа отверстий', cutout: 'Вырез / паз' }[op.type] || 'Обработка';
  const common = [
    field('Название', textInput(op.name || '', (v) => set((o) => { o.name = v; }), { placeholder: title })),
    field('Стекло', selectInput(glassOpts, op.panel_id, (v) => set((o) => { o.panel_id = v; }))),
  ];
  let body;
  if (op.type === 'hole') {
    body = [
      field('Диаметр Ø', numInput(op.d, (v) => set((o) => { o.d = v; }), { key: 'o.d', unit: 'мм' })),
      field('Привязка X', refEditor(op.x, X_REFS, (v) => set((o) => { o.x = v; }), axes, 'o.x')),
      field('Привязка Y', refEditor(op.y, Y_REFS, (v) => set((o) => { o.y = v; }), axes, 'o.y')),
      h('span.hint', 'При изменении размера стекла отступ от выбранной кромки сохраняется.'),
    ];
  } else if (op.type === 'cutout') {
    body = [
      h('div.grid3',
        field('Ширина', numInput(op.w, (v) => set((o) => { o.w = v; }), { key: 'o.w' })),
        field('Высота', numInput(op.h, (v) => set((o) => { o.h = v; }), { key: 'o.h' })),
        field('Радиус', numInput(op.r, (v) => set((o) => { o.r = v; }), { key: 'o.r' }))),
      field('Центр X', refEditor(op.x, X_REFS, (v) => set((o) => { o.x = v; }), axes, 'o.x')),
      field('Центр Y', refEditor(op.y, Y_REFS, (v) => set((o) => { o.y = v; }), axes, 'o.y')),
      h('span.hint', 'Если вырез пересекает кромку — контур стекла меняется (вырез на кромке).'),
    ];
  } else {
    const rep = op.repeat || { count: 1, step: 0, dir: 'v' };
    body = [
      ...op.items.map((it, i) => h('div.item-row',
        h('div.row', h('b.small', `Отверстие ${i + 1}`), h('button.icon-btn.right', { title: 'Удалить', onclick: () => set((o) => { o.items.splice(i, 1); }) }, '×')),
        field('Ø', numInput(it.d, (v) => set((o) => { o.items[i].d = v; }), { key: `gi${i}.d`, unit: 'мм' })),
        field('X', refEditor(it.x, X_REFS.filter((r) => r[0] !== 'abs'), (v) => set((o) => { o.items[i].x = v; }), axes, `gi${i}.x`)),
        field('Y', refEditor(it.y, Y_REFS, (v) => set((o) => { o.items[i].y = v; }), axes, `gi${i}.y`)))),
      h('button.btn.sm', { onclick: () => set((o) => { o.items.push({ d: 10, x: { ref: 'left', value: 80 }, y: { ref: 'top', value: 60 } }); }) }, '+ Отверстие в группу'),
      h('div.grid3',
        field('Количество', numInput(rep.count, (v) => set((o) => { o.repeat = { ...rep, count: Math.max(1, Math.round(v || 1)) }; }), { key: 'r.c' })),
        field('Шаг', numInput(rep.step, (v) => set((o) => { o.repeat = { ...rep, step: v || 0 }; }), { key: 'r.s' })),
        field('Направление', selectInput([['v', 'вертикально'], ['h', 'горизонтально']], rep.dir, (v) => set((o) => { o.repeat = { ...rep, dir: v }; })))),
      field('Зеркально', selectInput([['none', 'нет'], ['x', 'на противоположной стороне (слева↔справа)'], ['y', 'сверху↔снизу'], ['xy', 'по обеим осям']], op.mirror || 'none', (v) => set((o) => { o.mirror = v; }))),
    ];
  }
  return h('div.props', h('h3', h('span.dot.op'), op.name || title),
    sec(null, ...common), sec('Параметры', ...body),
    sec(null, h('div.row',
      h('button.btn.sm', { onclick: () => ctx.duplicateSel() }, 'Дублировать'),
      h('button.btn.sm', { onclick: () => set((o) => { o.disabled = !o.disabled; }) }, op.disabled ? 'Включить' : 'Отключить'),
      h('button.btn.sm.danger', { onclick: () => ctx.removeSel() }, 'Удалить'))));
}

// ------------------------------------------------------------------ фурнитура
function hwProps(ctx, id) {
  const { data, change, lists } = ctx;
  const inst = data.hardware.find((x) => x.id === id);
  if (!inst) return productProps(ctx);
  const model = lists.hardware.find((m) => m.id === inst.model_id);
  const set = (fn) => change((d) => { fn(d.hardware.find((x) => x.id === id)); });
  const sides = model ? (model.data.sides || []) : [];
  const glassOpts = data.panels.map((p) => [p.id, p.name]);
  const edgeOpts = Object.entries(EDGE_RU).map(([k, v]) => [k, v]);
  const firstEdge = (inst.targets[(sides[0] || {}).key || 'A'] || {}).edge || 'right';
  const horiz = firstEdge === 'top' || firstEdge === 'bottom';
  const pos = inst.pos || { ref: 'top', offset: 0 };
  return h('div.props',
    h('h3', h('span.dot.hw'), model ? model.name : 'Модель удалена'),
    model ? h('div.readout', h('span', 'Соединение'), h('b', lists.meta.connection_types[model.data.connection] || '—'),
      h('span', 'Зазор узла'), h('b', model.data.joint_gap != null ? fmt(model.data.joint_gap) + ' мм' : '—')) : h('div.msg.err', 'Модель удалена из базы'),
    sec(null, field('Модель', selectInput(lists.hardware.map((m) => [m.id, m.name]), inst.model_id, (v) => set((x) => { x.model_id = v; })))),
    sec('Стороны узла',
      ...sides.map((sd) => {
        const t = inst.targets[sd.key] || {};
        return h('div.item-row', h('b.small', `Сторона ${sd.key}${sd.label ? ' — ' + sd.label : ''}`),
          h('div.grid2',
            selectInput(glassOpts, t.panel_id, (v) => set((x) => { x.targets[sd.key] = { ...(x.targets[sd.key] || { edge: 'right' }), panel_id: v }; }), { empty: '— не применять —' }),
            selectInput(edgeOpts, t.edge || 'right', (v) => set((x) => { x.targets[sd.key] = { ...(x.targets[sd.key] || {}), edge: v }; }))));
      }),
      sides.length >= 2 ? h('button.btn.sm', { onclick: () => set((x) => {
        const [a, b] = [sides[0].key, sides[1].key];
        const ta = x.targets[a], tb = x.targets[b];
        x.targets[a] = tb; x.targets[b] = ta;
      }) }, '⇄ Поменять стороны A/B') : null,
      !sides.length ? h('span.hint', 'У модели нет обработки — только позиция спецификации.') : null),
    sec('Положение',
      field('Привязка', selectInput(horiz ? POS_REFS_H : POS_REFS, pos.ref, (v) => set((x) => { x.pos = { ...pos, ref: v }; }))),
      field('Отступ', numInput(pos.offset, (v) => set((x) => { x.pos = { ...pos, offset: v ?? 0 }; }), { key: 'hw.off', unit: 'мм' }), 'До точки привязки модели (оси узла)'),
      pos.ref === 'axis' ? field('Ось', selectInput(data.axes.map((a) => [a.id, a.name]), pos.axis_id, (v) => set((x) => { x.pos = { ...pos, axis_id: v }; }), { empty: '— выберите ось —' })) : null,
      checkInput(inst.flip, (v) => set((x) => { x.flip = v; }), 'Развернуть вдоль кромки'),
      field('Количество в спецификации', numInput(inst.qty || 1, (v) => set((x) => { x.qty = Math.max(1, Math.round(v || 1)); }), { key: 'hw.q' }))),
    sec(null, h('div.row',
      h('button.btn.sm', { onclick: () => ctx.duplicateSel() }, 'Дублировать'),
      h('button.btn.sm', { onclick: () => { location.hash = '#/hardware/' + inst.model_id; } }, 'Открыть модель'),
      h('button.btn.sm.danger', { onclick: () => ctx.removeSel() }, 'Удалить'))));
}

// ------------------------------------------------------------------ ось
function axisProps(ctx, id) {
  const { data, change, res } = ctx;
  const a = data.axes.find((x) => x.id === id);
  if (!a) return productProps(ctx);
  const ra = res.axes.find((x) => x.id === id);
  const set = (fn) => change((d) => { fn(d.axes.find((x) => x.id === id)); });
  const used = [...data.hardware.filter((x) => (x.pos || {}).axis_id === id), ...data.operations.filter((o) => (o.y || {}).axis_id === id)].length;
  return h('div.props', h('h3', h('span.dot.axis'), a.name || 'Ось'),
    ra ? h('div.readout', h('span', 'Высота от пола'), h('b', fmt(ra.y) + ' мм'), h('span', 'Привязано объектов'), h('b', String(used))) : null,
    sec(null,
      field('Название', textInput(a.name, (v) => set((x) => { x.name = v; }), { key: 'a.n' })),
      field('Отсчёт', selectInput([['top', 'от верха'], ['bottom', 'от низа']], a.ref, (v) => set((x) => { x.ref = v; }))),
      field('Отступ', numInput(a.offset, (v) => set((x) => { x.offset = v ?? 0; }), { key: 'a.o', unit: 'мм' })),
      field('Базовое стекло', selectInput(data.panels.map((p) => [p.id, p.name]), a.panel_id, (v) => set((x) => { x.panel_id = v; }), { empty: '— общий верх / пол —' })),
      h('span.hint', 'Фурнитура и отверстия могут ссылаться на ось («от оси») — так обеспечивается соосность.')),
    sec(null, h('div.row', h('button.btn.sm', { onclick: () => ctx.duplicateSel() }, 'Дублировать'), h('button.btn.sm.danger', { onclick: () => ctx.removeSel() }, 'Удалить'))));
}

// ------------------------------------------------------------------ доп. позиции
function extraProps(ctx, id) {
  const { data, change, lists } = ctx;
  const it = data.extra_items.find((x) => x.id === id);
  if (!it) return productProps(ctx);
  const set = (fn) => change((d) => { fn(d.extra_items.find((x) => x.id === id)); });
  return h('div.props', h('h3', 'Позиция спецификации'),
    sec(null,
      field('Фурнитура из базы', selectInput(lists.hardware.map((m) => [m.id, m.name]), it.model_id, (v) => set((x) => { x.model_id = v; x.profile_id = null; }), { empty: '—' })),
      field('или профиль', selectInput(lists.profiles.map((m) => [m.id, m.name]), it.profile_id, (v) => set((x) => { x.profile_id = v; x.model_id = null; }), { empty: '—' })),
      field('или произвольное название', textInput(it.name, (v) => set((x) => { x.name = v; }))),
      h('div.grid2',
        field('Количество', numInput(it.qty, (v) => set((x) => { x.qty = v; }), { key: 'x.q' })),
        field('Длина (формула)', textInput(it.length_formula, (v) => set((x) => { x.length_formula = v; }), { placeholder: 'H_door' }))),
      h('span.hint', 'Переменные: W, H (проём), W_door, H_door, W_fixed, H_fixed, H_max, W_total'),
      field('Примечание', textInput(it.note, (v) => set((x) => { x.note = v; })))),
    sec(null, h('div.row', h('button.btn.sm', { onclick: () => ctx.duplicateSel() }, 'Дублировать'), h('button.btn.sm.danger', { onclick: () => ctx.removeSel() }, 'Удалить'))));
}

export { EDGE_RU };
