// Библиотека: производители, категории, фурнитура, профили, комплекты, шаблоны, DXF.
import { api, lib, invalidateLib, meta } from './api.js';
import { h, clear, modal, confirmDlg, promptDlg, field, textInput, numInput, selectInput, toast, emptyState, menuButton, fmt, uid, clone } from './ui.js';
import { s, segPath } from './draw.js';
import { templateIcon } from './orders.js';

const TABS = [
  ['hardware', 'Фурнитура'], ['profiles', 'Профили'], ['kits', 'Комплекты'], ['construction_templates', 'Шаблоны конструкций'],
  ['op_templates', 'Шаблоны обработки'], ['manufacturers', 'Производители'], ['categories', 'Категории'], ['dxf', 'DXF-файлы'],
];

export async function libraryPage(root, tab) {
  const page = h('div.page');
  root.appendChild(page);
  const tabs = h('div.tabs', TABS.map(([k, t]) => h('a' + (k === tab ? '.active' : ''), { href: '#/library/' + k }, t)));
  const body = h('div');
  clear(page, h('div.page-head', h('h1', 'Библиотека')), tabs, body);
  if (tab === 'dxf') return dxfTab(body);
  return collectionTab(body, tab);
}

async function ctxLists() {
  const [mans, cats, profs, hw] = await Promise.all([lib('manufacturers'), lib('categories'), lib('profiles'), lib('hardware')]);
  return { mans, cats, profs, hw, manName: (id) => (mans.find((m) => m.id === id) || {}).name || '—', catName: (id) => (cats.find((m) => m.id === id) || {}).name || '—' };
}

async function collectionTab(body, coll) {
  const load = async () => {
    invalidateLib();
    const [items, L, m] = await Promise.all([lib(coll, true), ctxLists(), meta()]);
    const cols = columnsFor(coll, L, m);
    const tbody = h('tbody');
    for (const it of items) {
      tbody.appendChild(h('tr.clickable', { onclick: () => edit(it) },
        ...cols.map((c) => h('td' + (c.num ? '.num' : ''), c.get(it))),
        h('td.actions', { onclick: (e) => e.stopPropagation() }, menuButton('⋯', [
          { label: 'Изменить', onClick: () => edit(it) },
          { label: 'Переименовать', onClick: async () => { const n = await promptDlg('Переименовать', it.name); if (n) { await api.put(`/api/lib/${coll}/${it.id}`, { name: n }); load(); } } },
          { label: 'Дублировать', onClick: async () => { await api.post(`/api/lib/${coll}/${it.id}/duplicate`); load(); } },
          '-',
          { label: 'Удалить', onClick: async () => { if (await confirmDlg(`Удалить «${it.name}»? Существующие изделия сохранятся, но ссылки на эту запись будут показаны как удалённые.`)) { await api.del(`/api/lib/${coll}/${it.id}`); load(); } } },
        ], '.sm'))));
    }
    clear(body,
      h('div.row', { style: { marginBottom: '12px' } }, h('span.muted', hints[coll] || ''), h('button.btn.primary.right', { onclick: () => create() }, '+ Добавить')),
      items.length ? h('div.card', h('table.list', h('thead', h('tr', ...cols.map((c) => h('th', c.title)), h('th'))), tbody)) : h('div.card', emptyState('Пока пусто')));
  };
  const create = async () => {
    if (coll === 'hardware') {
      const n = await promptDlg('Новая модель фурнитуры', '', 'Название / модель');
      if (!n) return;
      const it = await api.post('/api/lib/hardware', { name: n, data: { connection: 'glass-glass', sides: [{ key: 'A', label: 'Стекло A', dxf_id: null, roles: {}, edge_pid: null, glass_side: 'left', anchor: null, holes: [] }] } });
      location.hash = '#/hardware/' + it.id;
      return;
    }
    edit({ id: null, name: '', data: defaults[coll] ? clone(defaults[coll]) : {} });
  };
  const edit = async (it) => {
    if (coll === 'hardware') { location.hash = '#/hardware/' + it.id; return; }
    const L = await ctxLists();
    const form = editors[coll](it, L);
    modal(it.id ? `Изменить: ${it.name}` : 'Новая запись', form.el, {
      wide: form.wide,
      actions: [{ label: 'Отмена' }, {
        label: 'Сохранить', primary: true, onClick: async () => {
          document.activeElement && document.activeElement.blur();
          const name = (form.name() || '').trim();
          if (!name) { toast('Введите название', 'error'); return false; }
          if (it.id) await api.put(`/api/lib/${coll}/${it.id}`, { name, data: form.data() });
          else await api.post(`/api/lib/${coll}`, { name, data: form.data() });
          invalidateLib(coll);
          load();
          return true;
        },
      }],
    });
  };
  await load();
}

const hints = {
  hardware: 'Модель = производитель + категория + обработка на каждой стороне узла (DXF и/или отверстия).',
  profiles: 'Профиль назначается на кромку стекла и уменьшает размер стекла на вычет.',
  kits: 'Параметрический набор: фурнитура с правилами установки, профили, зазоры. Без размеров стекол.',
  construction_templates: 'Схема стекол. Работает с любым комплектом. Свои шаблоны — «Сохранить как шаблон» в конструкторе.',
  op_templates: 'Схемы отверстий с семантическими привязками — сохраняются из конструктора.',
};

const defaults = {
  profiles: { kind: 'u', depth: 20, seat_depth: 15, mounting_gap: 3, thickness_min: 6, thickness_max: 10, length: 3000, color: '' },
  kits: { gaps: {}, profiles: [], items: [], color: '' },
  construction_templates: { kind: 'shower', panels: [], description: '' },
  op_templates: { items: [] },
  manufacturers: {},
  categories: {},
};

function columnsFor(coll, L, m) {
  const name = { title: 'Название', get: (it) => h('b', it.name) };
  switch (coll) {
    case 'hardware': return [name, { title: 'Производитель', get: (it) => L.manName(it.data.manufacturer_id) }, { title: 'Категория', get: (it) => L.catName(it.data.category_id) },
      { title: 'Артикул', get: (it) => it.data.article || '' }, { title: 'Соединение', get: (it) => m.connection_types[it.data.connection] || '—' },
      { title: 'Стороны', get: (it) => (it.data.sides || []).map((sd) => sd.key + (sd.dxf_id ? ' (DXF)' : '') + ((sd.holes || []).length ? ` (${sd.holes.length} отв.)` : '')).join(', ') || '—' }];
    case 'profiles': return [name, { title: 'Производитель', get: (it) => L.manName(it.data.manufacturer_id) }, { title: 'Цвет', get: (it) => it.data.color || '' },
      { title: 'Глубина / посадка / запас', get: (it) => `${fmt(it.data.depth)} / ${fmt(it.data.seat_depth)} / ${fmt(it.data.mounting_gap)}` }, { title: 'Вычет, мм', num: true, get: (it) => fmt(it.deduction) }];
    case 'kits': return [name, { title: 'Производитель', get: (it) => L.manName(it.data.manufacturer_id) }, { title: 'Цвет', get: (it) => it.data.color || '' },
      { title: 'Позиций', num: true, get: (it) => String((it.data.items || []).length) }];
    case 'construction_templates': return [{ title: '', get: (it) => h('div', { style: { width: '70px' } }, templateIcon(it.data)) }, name, { title: 'Описание', get: (it) => h('span.muted', it.data.description || '') }, { title: 'Стекол', num: true, get: (it) => String((it.data.panels || []).length) }];
    case 'op_templates': return [name, { title: 'Описание', get: (it) => h('span.muted', it.data.description || '') }, { title: 'Элементов', num: true, get: (it) => String((it.data.items || []).length) }];
    case 'manufacturers': return [name, { title: 'Страна', get: (it) => it.data.country || '' }, { title: 'Сайт', get: (it) => it.data.site || '' }];
    default: return [name];
  }
}

// ------------------------------------------------------------------ редакторы
function nameField(it) {
  const inp = h('input', { type: 'text', value: it.name || '' });
  return { el: field('Название', inp), get: () => inp.value };
}

const editors = {
  manufacturers(it) {
    const d = clone(it.data); const n = nameField(it);
    return { el: h('div.col', n.el, field('Страна', textInput(d.country, (v) => { d.country = v; })), field('Сайт / каталог', textInput(d.site, (v) => { d.site = v; })), field('Примечание', textInput(d.note, (v) => { d.note = v; }))), name: n.get, data: () => d };
  },
  categories(it) {
    const d = clone(it.data); const n = nameField(it);
    return { el: h('div.col', n.el), name: n.get, data: () => d };
  },
  profiles(it, L) {
    const d = clone(it.data); const n = nameField(it);
    const out = h('b');
    const upd = () => { out.textContent = d.deduction != null ? fmt(d.deduction) + ' мм (задан вручную)' : fmt(Math.max(0, (d.depth || 0) - (d.seat_depth || 0)) + (d.mounting_gap || 0)) + ' мм'; };
    const nf = (k, label, hint) => field(label, numInput(d[k], (v) => { d[k] = v; upd(); }, { unit: 'мм' }), hint);
    upd();
    return {
      wide: true, name: n.get, data: () => d,
      el: h('div.col', h('div.grid2', n.el,
        field('Производитель', selectInput(L.mans.map((m) => [m.id, m.name]), d.manufacturer_id, (v) => { d.manufacturer_id = v; }, { empty: '—' }))),
      h('div.grid3',
        field('Вид', selectInput([['u', 'П-образный'], ['alu', 'Алюминиевый'], ['other', 'Другой']], d.kind, (v) => { d.kind = v; })),
        field('Артикул', textInput(d.article, (v) => { d.article = v; })),
        field('Цвет', textInput(d.color, (v) => { d.color = v; })),
        nf('thickness_min', 'Толщина стекла от'), nf('thickness_max', 'Толщина стекла до'), nf('length', 'Длина хлыста'),
        nf('depth', 'Глубина профиля', 'от стены до края'), nf('seat_depth', 'Глубина посадки', 'насколько заходит стекло'), nf('mounting_gap', 'Монтажный запас'),
        nf('adjust_range', 'Регулировка ±'), nf('deduction', 'Вычет вручную', 'пусто — по формуле')),
      h('div.readout', h('span', 'Вычет из стекла на кромку = глубина − посадка + запас'), out)),
    };
  },
  kits(it, L) {
    const d = clone(it.data); const n = nameField(it);
    d.gaps = d.gaps || {}; d.profiles = d.profiles || []; d.items = d.items || [];
    const wrap = h('div.col');
    const PLACEMENTS = [['hinge', 'Петли двери (стекло–стекло или стена)'], ['handle', 'Ручка на двери'], ['wall_connector', 'К стене (неподвижные стекла)'], ['floor', 'К полу (неподвижные стекла)'], ['door_edge', 'На кромку двери'], ['none', 'Только в спецификацию']];
    const posText = (ps) => (ps || []).map((p) => `${{ top: 'верх', bottom: 'низ', center: 'центр', axis: 'ось', left: 'лево', right: 'право' }[p.ref] || p.ref} ${fmt(p.offset)}`).join('; ');
    const parsePos = (t) => t.split(/[;,]/).map((x) => x.trim()).filter(Boolean).map((x) => {
      const [r, v] = x.split(/\s+/);
      const ref = { верх: 'top', низ: 'bottom', центр: 'center', лево: 'left', право: 'right', top: 'top', bottom: 'bottom', center: 'center' }[r.toLowerCase()] || 'top';
      return { ref, offset: parseFloat((v || '0').replace(',', '.')) || 0 };
    });
    const render = () => clear(wrap,
      h('div.grid3', n.el,
        field('Производитель', selectInput(L.mans.map((m) => [m.id, m.name]), d.manufacturer_id, (v) => { d.manufacturer_id = v; }, { empty: '—' })),
        field('Цвет фурнитуры', textInput(d.color, (v) => { d.color = v; }))),
      field('Описание', textInput(d.description, (v) => { d.description = v; })),
      h('div.sec-title.small.muted', 'ЗАЗОРЫ КОМПЛЕКТА, мм (пусто — не менять)'),
      h('div.grid3', ...[['glass_glass', 'Стекло ↔ стекло'], ['door_floor', 'Дверь ↔ пол'], ['fixed_floor', 'Глухарь ↔ пол'], ['wall', 'Стекло ↔ стена'], ['top', 'Верх']].map(([k, l]) =>
        field(l, numInput(d.gaps[k], (v) => { if (v === null) delete d.gaps[k]; else d.gaps[k] = v; })))),
      h('div.sec-title.small.muted', 'ПРОФИЛИ'),
      ...d.profiles.map((pr, i) => h('div.row',
        selectInput([['wall', 'На кромки у стены (неподвижные стекла)'], ['floor_fixed', 'На низ неподвижных стекол'], ['top', 'На верх стекол']], pr.target, (v) => { pr.target = v; }),
        selectInput(L.profs.map((p) => [p.id, p.name]), pr.profile_id, (v) => { pr.profile_id = v; }, { empty: '—' }),
        h('button.icon-btn', { onclick: () => { d.profiles.splice(i, 1); render(); } }, '×'))),
      h('button.btn.sm', { onclick: () => { d.profiles.push({ target: 'wall', profile_id: L.profs[0] && L.profs[0].id }); render(); } }, '+ Правило профиля'),
      h('div.sec-title.small.muted', 'ФУРНИТУРА'),
      ...d.items.map((itm, i) => h('div.item-row', { style: { gridTemplateColumns: '2fr 2fr 1.5fr 0.6fr 1fr auto' } },
        field('Модель', selectInput(L.hw.map((m) => [m.id, m.name]), itm.model_id, (v) => { itm.model_id = v; }, { empty: '—' })),
        field('Установка', selectInput(PLACEMENTS, itm.placement, (v) => { itm.placement = v; render(); })),
        itm.placement !== 'none' ? field('Положения', textInput(posText(itm.positions), (v) => { itm.positions = parsePos(v); }, { placeholder: 'верх 250; низ 246' })) :
          field('Длина (формула)', textInput(itm.length_formula, (v) => { itm.length_formula = v; }, { placeholder: 'H_door' })),
        field('Кол.', numInput(itm.qty ?? 1, (v) => { itm.qty = v; })),
        field('Примечание', textInput(itm.note, (v) => { itm.note = v; })),
        h('button.icon-btn', { onclick: () => { d.items.splice(i, 1); render(); } }, '×'))),
      h('button.btn.sm', { onclick: () => { d.items.push({ id: uid(), model_id: L.hw[0] && L.hw[0].id, placement: 'hinge', positions: [{ ref: 'top', offset: 250 }, { ref: 'bottom', offset: 250 }], qty: 1 }); render(); } }, '+ Позиция'),
      h('p.hint', 'Положения: «верх 250; низ 246» — отступ от верха/низа стекла A до оси узла. Переменные длины: W, H, W_door, H_door, W_fixed, H_fixed, H_max.'));
    render();
    return { el: wrap, wide: true, name: n.get, data: () => d };
  },
  construction_templates(it) {
    const d = clone(it.data); const n = nameField(it);
    d.panels = d.panels || [];
    const wrap = h('div.col');
    const render = () => clear(wrap, h('div.grid2', n.el, field('Тип изделия', selectInput([['shower', 'Душевая'], ['railing', 'Ограждение'], ['mirror', 'Зеркало'], ['apron', 'Фартук'], ['partition', 'Перегородка'], ['other', 'Другое']], d.kind, (v) => { d.kind = v; }))),
      field('Описание', textInput(d.description, (v) => { d.description = v; })),
      h('div.sec-title.small.muted', 'СТЕКЛА (слева направо)'),
      ...d.panels.map((p, i) => h('div.item-row', { style: { gridTemplateColumns: '1.4fr 1.2fr 1fr 1.2fr 1.2fr 0.9fr auto' } },
        field('Название', textInput(p.name, (v) => { p.name = v; })),
        field('Тип', selectInput([['door', 'Дверь'], ['fixed', 'Глухарь'], ['stationary', 'Стационар'], ['sliding_door', 'Раздвижная дверь'], ['mirror', 'Зеркало'], ['other', 'Другое']], p.type, (v) => { p.type = v; })),
        field('Ширина', selectInput([['auto', 'Авто'], ['value', 'Число'], ['formula', 'Формула']], p.width.mode, (v) => { p.width.mode = v; render(); })),
        p.width.mode === 'value' ? field('Значение', numInput(p.width.value, (v) => { p.width.value = v; })) : p.width.mode === 'formula' ? field('Формула', textInput(p.width.formula, (v) => { p.width.formula = v; })) : h('span'),
        field('X (формула)', textInput(p.x_formula, (v) => { p.x_formula = v; }, { placeholder: 'по порядку' })),
        field('Плоскость', selectInput([['front', 'Фронт'], ['side', 'Бок']], p.plane || 'front', (v) => { p.plane = v; })),
        h('button.icon-btn', { onclick: () => { d.panels.splice(i, 1); render(); } }, '×'))),
      h('button.btn.sm', { onclick: () => { d.panels.push({ id: uid(), name: 'Стекло', type: 'fixed', plane: 'front', width: { mode: 'auto', value: null, formula: '' }, x_formula: '', edges: { left: { kind: 'auto' }, right: { kind: 'auto' }, top: { kind: 'free' }, bottom: { kind: 'floor' } }, shape: { type: 'rect' } }); render(); } }, '+ Стекло'),
      h('p.hint', 'Кромки, профили, обработка и фурнитура сохраняются из конструктора: «Шаблоны → Сохранить как шаблон конструкции».'));
    render();
    return { el: wrap, wide: true, name: n.get, data: () => d };
  },
  op_templates(it) {
    const d = clone(it.data); const n = nameField(it);
    d.items = d.items || [];
    const wrap = h('div.col');
    const desc = (o) => o.type === 'hole' ? `Отверстие Ø${fmt(o.d)}, X ${o.x.ref} ${fmt(o.x.value)}, Y ${o.y.ref} ${fmt(o.y.value)}`
      : o.type === 'group' ? `Группа: ${o.items.map((x) => `Ø${fmt(x.d)} (${x.x.ref} ${fmt(x.x.value)} / ${x.y.ref} ${fmt(x.y.value)})`).join(', ')}${o.mirror && o.mirror !== 'none' ? ', зеркально ' + o.mirror : ''}`
        : `Вырез ${fmt(o.w)}×${fmt(o.h)} R${fmt(o.r)}`;
    const render = () => clear(wrap, n.el, field('Описание', textInput(d.description, (v) => { d.description = v; })),
      h('div.sec-title.small.muted', 'ЭЛЕМЕНТЫ'),
      ...d.items.map((o, i) => h('div.row', h('span.small', desc(o)), h('button.icon-btn.right', { onclick: () => { d.items.splice(i, 1); render(); } }, '×'))),
      h('p.hint', 'Элементы добавляются из конструктора («Сохранить как шаблон» в свойствах стекла). Привязки семантические — при другой ширине стекла схема перестраивается.'));
    render();
    return { el: wrap, wide: true, name: n.get, data: () => d };
  },
};

// ------------------------------------------------------------------ DXF-файлы
async function dxfTab(body) {
  const load = async () => {
    const list = await api.get('/api/dxf');
    const tbody = h('tbody');
    for (const d of list) {
      tbody.appendChild(h('tr.clickable', { onclick: () => preview(d.id) }, h('td', h('b', d.name)), h('td.muted', d.original_filename), h('td', (d.created_at || '').slice(0, 10)),
        h('td.actions', { onclick: (e) => e.stopPropagation() }, menuButton('⋯', [
          { label: 'Просмотр', onClick: () => preview(d.id) },
          { label: 'Скачать исходный файл', onClick: () => window.open(`/api/dxf/${d.id}/file`) },
          { label: 'Переименовать', onClick: async () => { const nm = await promptDlg('Переименовать DXF', d.name); if (nm) { await api.put('/api/dxf/' + d.id, { name: nm }); load(); } } },
          { label: 'Дублировать', onClick: async () => { await api.post(`/api/dxf/${d.id}/duplicate`); load(); } },
          '-',
          { label: 'Удалить', onClick: async () => { if (await confirmDlg(`Удалить DXF «${d.name}»? Модели, которые его используют, потеряют геометрию.`)) { await api.del('/api/dxf/' + d.id); load(); } } },
        ], '.sm'))));
    }
    clear(body,
      h('div.row', { style: { marginBottom: '12px' } }, h('span.muted', 'Чертежи обработки фурнитуры. Хранятся отдельно от кода, в папке данных.'),
        h('label.btn.primary.right', 'Загрузить DXF…', h('input', { type: 'file', accept: '.dxf', style: { display: 'none' }, onchange: async (e) => {
          const fd = new FormData(); fd.append('file', e.target.files[0]);
          await api.post('/api/dxf', fd); toast('DXF загружен', 'ok'); load();
        } }))),
      list.length ? h('div.card', h('table.list', h('thead', h('tr', h('th', 'Название'), h('th', 'Файл'), h('th', 'Загружен'), h('th'))), tbody)) : h('div.card', emptyState('DXF-файлов нет')));
  };
  await load();
}

async function preview(id) {
  const d = await api.get('/api/dxf/' + id);
  const [x0, y0, x1, y1] = d.data.bbox;
  const pad = Math.max(x1 - x0, y1 - y0) * 0.08 + 1;
  const svg = s('svg', { viewBox: `${x0 - pad} ${-y1 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`, style: 'width:100%;height:420px;background:#fbfcfd;border:1px solid #dde3e8;border-radius:6px' });
  for (const p of d.data.primitives) for (const sg of p.segs) svg.appendChild(s('path', { d: segPath(sg), fill: 'none', stroke: '#24323c', 'stroke-width': 1, 'vector-effect': 'non-scaling-stroke' }));
  modal(d.name, h('div.col', svg, h('span.muted.small', `Примитивов: ${d.data.primitives.length} · габарит ${fmt(x1 - x0)} × ${fmt(y1 - y0)} мм`)), { wide: true });
}
