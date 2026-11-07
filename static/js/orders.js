import { api, lib, download } from './api.js';
import { h, clear, modal, confirmDlg, promptDlg, field, textInput, numInput, selectInput, toast, emptyState, menuButton } from './ui.js';
import { thumbSvg } from './draw.js';

let statusesCache = null;
async function statuses() {
  if (!statusesCache) statusesCache = await api.get('/api/orders/statuses');
  return statusesCache;
}
const stName = (list, key) => (list.find((s) => s.key === key) || {}).name || key;
const dateRu = (iso) => (iso ? iso.slice(0, 10).split('-').reverse().join('.') : '');

// ------------------------------------------------------------------ список заказов
export async function ordersPage(root) {
  const sts = await statuses();
  let q = '', status = '';
  const tbody = h('tbody');
  const load = async () => {
    const list = await api.get(`/api/orders?q=${encodeURIComponent(q)}&status=${status}`);
    clear(tbody);
    if (!list.length) tbody.appendChild(h('tr', h('td', { colspan: 7 }, emptyState(q || status ? 'Ничего не найдено' : 'Заказов пока нет. Создайте первый заказ.'))));
    for (const o of list) {
      tbody.appendChild(h('tr.clickable', { onclick: () => { location.hash = '#/order/' + o.id; } },
        h('td', h('b', '№' + o.number)),
        h('td', o.client || h('span.muted', '—')),
        h('td', o.phone || ''),
        h('td', dateRu(o.date)),
        h('td', h('span.badge.st-' + o.status, stName(sts, o.status))),
        h('td.num', String(o.products_count)),
        h('td.actions', { onclick: (e) => e.stopPropagation() },
          menuButton('⋯', [
            { label: 'Открыть', onClick: () => { location.hash = '#/order/' + o.id; } },
            { label: 'Дублировать', onClick: async () => { const n = await api.post(`/api/orders/${o.id}/duplicate`); toast(`Создан заказ №${n.number}`, 'ok'); load(); } },
            '-',
            { label: 'Удалить', onClick: async () => { if (await confirmDlg(`Удалить заказ №${o.number} со всеми изделиями?`)) { await api.del('/api/orders/' + o.id); load(); } } },
          ], '.sm'))));
    }
  };
  const search = h('input', { type: 'search', placeholder: 'Поиск: номер, клиент, телефон…', style: { maxWidth: '320px' } });
  search.addEventListener('input', () => { q = search.value; clearTimeout(search._t); search._t = setTimeout(load, 250); });
  root.appendChild(h('div.page',
    h('div.page-head', h('h1', 'Заказы'),
      h('div.right.row', search,
        selectInput(sts.map((s) => [s.key, s.name]), '', (v) => { status = v || ''; load(); }, { empty: 'Все статусы' }),
        h('button.btn.primary', { onclick: () => newOrderDialog() }, '+ Новый заказ'))),
    h('div.card', h('table.list', h('thead', h('tr', h('th', 'Номер'), h('th', 'Клиент'), h('th', 'Телефон'), h('th', 'Дата'), h('th', 'Статус'), h('th', { style: { textAlign: 'right' } }, 'Изделий'), h('th'))), tbody))));
  await load();
}

function newOrderDialog() {
  const v = { client: '', phone: '', comment: '' };
  modal('Новый заказ', h('div.col',
    field('Клиент', textInput('', (x) => { v.client = x; })),
    field('Телефон', textInput('', (x) => { v.phone = x; })),
    field('Комментарий', textInput('', (x) => { v.comment = x; })),
    h('p.muted.small', 'Номер присвоится автоматически, его можно изменить.')), {
    actions: [{ label: 'Отмена' }, {
      label: 'Создать', primary: true, onClick: async () => {
        document.activeElement && document.activeElement.blur();
        const o = await api.post('/api/orders', v);
        location.hash = '#/order/' + o.id;
      },
    }],
  });
}

// ------------------------------------------------------------------ заказ
export async function orderPage(root, id) {
  const sts = await statuses();
  let o = await api.get('/api/orders/' + id);
  const save = async (patch) => { o = await api.put('/api/orders/' + id, patch); toast('Сохранено', 'ok', 1000); };
  const cards = h('div.product-cards');
  const renderProducts = () => {
    clear(cards);
    if (!o.products.length) cards.appendChild(h('div.card.empty', h('p', 'В заказе пока нет изделий.'), h('button.btn.primary', { onclick: () => productWizard(o) }, '+ Добавить изделие')));
    for (const p of o.products) {
      cards.appendChild(h('div.card.product-card', { onclick: () => { location.hash = '#/product/' + p.id; } },
        h('div.thumb', thumbSvg(p.thumb)),
        h('div.row', h('b', p.name), h('span.right', { onclick: (e) => e.stopPropagation() }, menuButton('⋯', [
          { label: 'Открыть конструктор', onClick: () => { location.hash = '#/product/' + p.id; } },
          { label: 'Переименовать', onClick: async () => { const n = await promptDlg('Переименовать изделие', p.name); if (n) { await api.put('/api/products/' + p.id, { name: n }); reload(); } } },
          { label: 'Дублировать', onClick: async () => { await api.post(`/api/products/${p.id}/duplicate`); reload(); } },
          { label: 'PDF изделия (клиент)', onClick: () => download(`/api/orders/${id}/pdf?mode=client&product_id=${p.id}`) },
          { label: 'DXF всех стекол (zip)', onClick: () => download(`/api/products/${p.id}/dxf`) },
          '-',
          { label: 'Удалить', onClick: async () => { if (await confirmDlg(`Удалить изделие «${p.name}»?`)) { await api.del('/api/products/' + p.id); reload(); } } },
        ], '.sm'))),
        h('div.muted.small', [p.template_name, p.opening ? 'проём ' + p.opening : null].filter(Boolean).join(' · ') || '—'),
        p.kit_name ? h('div.small', '🔩 ' + p.kit_name) : null,
        h('div.small', (p.glass_sizes || []).join(', ') || h('span.muted', 'нет стекол')),
        p.problems ? h('div.msg.err', `Ошибок: ${p.problems}`) : null));
    }
  };
  const reload = async () => { o = await api.get('/api/orders/' + id); renderProducts(); };
  renderProducts();

  root.appendChild(h('div.page',
    h('div.page-head',
      h('a', { href: '#/orders' }, '← Заказы'),
      h('h1', 'Заказ №' + o.number),
      h('span.badge.st-' + o.status, stName(sts, o.status)),
      h('div.right.row',
        menuButton('PDF', [
          { label: 'PDF для клиента', onClick: () => download(`/api/orders/${id}/pdf?mode=client`) },
          { label: 'PDF для производства', onClick: () => download(`/api/orders/${id}/pdf?mode=production`) },
          { label: 'Полный PDF', onClick: () => download(`/api/orders/${id}/pdf?mode=full`) },
        ]),
        h('button.btn.primary', { onclick: () => productWizard(o) }, '+ Добавить изделие'))),
    h('div.order-grid',
      h('div.card.card-pad.col',
        h('h2', 'Данные заказа'),
        h('div.grid2',
          field('Номер', textInput(o.number, (v) => save({ number: v }).then(() => { root.querySelector('h1').textContent = 'Заказ №' + o.number; }))),
          field('Дата', h('input', { type: 'date', value: o.date, onchange: (e) => save({ date: e.target.value }) }))),
        field('Клиент', textInput(o.client, (v) => save({ client: v }))),
        field('Телефон', textInput(o.phone, (v) => save({ phone: v }))),
        field('Статус', selectInput(sts.map((s) => [s.key, s.name]), o.status, async (v) => {
          await save({ status: v });
          const b = root.querySelector('.page-head .badge'); b.className = 'badge st-' + v; b.textContent = stName(sts, v);
        })),
        field('Комментарий', h('textarea', { onchange: (e) => save({ comment: e.target.value }) }, o.comment || ''))),
      h('div.col', h('h2', 'Изделия'), cards))));
}

// ------------------------------------------------------------------ мастер изделия
export async function productWizard(order) {
  const [tmpls, kits, kinds] = await Promise.all([lib('construction_templates', true), lib('kits', true), api.get('/api/product-kinds')]);
  const st = {
    name: '', kind: 'shower', mode: 'quick',
    m: { width_top: null, width_mid: null, width_bottom: null, height_left: null, height_right: null, depth: null },
    top_height: 2000, template_id: null, kit_id: null,
  };
  const pickDefault = () => {
    const t = tmpls.find((x) => (x.data.kind || 'shower') === st.kind);
    st.template_id = t ? t.id : null;
  };
  pickDefault();
  const body = h('div.col');
  const render = () => {
    const tlist = tmpls.filter((t) => (t.data.kind || 'shower') === st.kind || st.kind === 'other');
    const needMeas = st.mode !== 'manual';
    const selTmpl = tmpls.find((t) => t.id === st.template_id);
    const isCorner = selTmpl && (selTmpl.data.panels || []).some((p) => p.plane === 'side');
    clear(body,
      h('div.grid2',
        field('Название изделия', textInput(st.name, (v) => { st.name = v; }, { placeholder: 'Душевая в ванной' })),
        field('Тип изделия', selectInput(kinds.map((k) => [k.key, k.name]), st.kind, (v) => { st.kind = v; pickDefault(); render(); }))),
      h('div.field', h('span.field-label', 'Режим создания'),
        h('div.wizard-modes', [
          ['quick', 'Быстрый', 'Проём + шаблон + комплект — стекла рассчитываются автоматически'],
          ['constructor', 'Конструктор', 'Проём и шаблон, фурнитура добавляется вручную'],
          ['manual', 'Ручной', 'Размеры каждого стекла и обработка вручную'],
        ].map(([k, t, d]) => h('button.wizard-mode' + (st.mode === k ? '.on' : ''), { type: 'button', onclick: () => { st.mode = k; render(); } }, h('b', t), h('span.small.muted', d))))),
      needMeas ? h('div.col',
        h('div.sec-title.small.muted', 'ЗАМЕР ПРОЁМА, мм (достаточно одной ширины и одной высоты)'),
        h('div.grid3',
          field('Ширина сверху', numInput(st.m.width_top, (v) => { st.m.width_top = v; })),
          field('Ширина по центру', numInput(st.m.width_mid, (v) => { st.m.width_mid = v; })),
          field('Ширина снизу', numInput(st.m.width_bottom, (v) => { st.m.width_bottom = v; })),
          field('Высота слева', numInput(st.m.height_left, (v) => { st.m.height_left = v; })),
          field('Высота справа', numInput(st.m.height_right, (v) => { st.m.height_right = v; })),
          field('Высота стекол', numInput(st.top_height, (v) => { st.top_height = v; }), 'верх стекол от пола')),
        isCorner ? field('Глубина (боковая сторона)', numInput(st.m.depth, (v) => { st.m.depth = v; })) : null) : null,
      h('div.field', h('span.field-label', 'Конструкция'),
        h('div.tmpl-grid', tlist.map((t) => h('button.tmpl' + (st.template_id === t.id ? '.on' : ''), { type: 'button', onclick: () => { st.template_id = t.id; render(); } },
          templateIcon(t.data), h('span.small', t.name))))),
      st.mode === 'quick' ? field('Комплект фурнитуры', selectInput(kits.map((k) => [k.id, k.name]), st.kit_id, (v) => { st.kit_id = v; }, { empty: '— без комплекта —' }),
        kits.length ? 'Комплект задаёт фурнитуру, профили и зазоры' : 'Комплекты создаются в Библиотеке') : null);
  };
  render();
  modal('Новое изделие', body, {
    wide: true,
    actions: [{ label: 'Отмена' }, {
      label: 'Создать и открыть', primary: true, onClick: async () => {
        document.activeElement && document.activeElement.blur();
        const kindName = (kinds.find((k) => k.key === st.kind) || {}).name;
        const payload = {
          name: st.name || kindName, kind: st.kind, mode: st.mode,
          measurement: st.mode === 'manual' ? {} : st.m,
          settings: { top_height: st.top_height || 2000, top_mode: 'fixed' },
          template_id: st.mode === 'manual' ? null : st.template_id,
          kit_id: st.mode === 'quick' ? st.kit_id : null,
        };
        if (st.mode !== 'manual' && !(st.m.width_top || st.m.width_mid || st.m.width_bottom)) { toast('Введите ширину проёма', 'error'); return false; }
        if (st.mode !== 'manual' && !(st.m.height_left || st.m.height_right)) { toast('Введите высоту проёма', 'error'); return false; }
        const r = await api.post(`/api/orders/${order.id}/products`, payload);
        location.hash = '#/product/' + r.product.id;
        return true;
      },
    }],
  });
}

export function templateIcon(data) {
  const panels = data.panels || [];
  const items = [];
  let x = 0;
  for (const p of panels) {
    const w = p.type === 'door' || p.type === 'sliding_door' ? 40 : 55;
    const hh = p.type === 'door' ? 96 : 100;
    const px = p.x_formula ? x - 30 : x;
    const contour = [[0, 0, 0], [w, 0, 0], [w, hh, 0], [0, hh, 0]];
    items.push({ contour, x: px + (p.plane === 'side' ? 20 : 0), y: 100 - hh, holes: [] });
    x = px + w + 3 + (p.plane === 'side' ? 20 : 0);
  }
  return thumbSvg(items);
}
