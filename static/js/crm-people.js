// Контакты и компании.
import { api } from './api.js';
import { h, clear, modal, confirmDlg, field, textInput, selectInput, toast, menuButton, emptyState } from './ui.js';
import { crmMeta, money, dt } from './crm-common.js';
import { newDealDialog, taskRow, eventRow } from './crm-deals.js';
import { taskDialog } from './crm-common.js';

function listPage(root, { title, url, cols, onOpen, onCreate, rowActions }) {
  let q = '';
  const tbody = h('tbody');
  const load = async () => {
    const list = await api.get(`${url}?q=${encodeURIComponent(q)}`);
    clear(tbody);
    if (!list.length) tbody.appendChild(h('tr', h('td', { colspan: cols.length + 1 }, emptyState(q ? 'Ничего не найдено' : 'Пока пусто'))));
    for (const it of list) {
      tbody.appendChild(h('tr.clickable', { onclick: () => onOpen(it) }, ...cols.map((c) => h('td' + (c.num ? '.num' : ''), c.get(it))),
        h('td.actions', { onclick: (e) => e.stopPropagation() }, menuButton('⋯', rowActions(it, load), '.sm'))));
    }
  };
  const search = h('input', { type: 'search', placeholder: 'Поиск…', style: { maxWidth: '300px' } });
  search.addEventListener('input', () => { q = search.value; clearTimeout(search._t); search._t = setTimeout(load, 250); });
  root.appendChild(h('div.page',
    h('div.page-head', h('h1', title), h('div.tabs.inline', h('a' + (url.endsWith('contacts') ? '.active' : ''), { href: '#/contacts' }, 'Контакты'), h('a' + (url.endsWith('companies') ? '.active' : ''), { href: '#/companies' }, 'Компании')),
      h('div.right.row', search, h('button.btn.primary', { onclick: () => onCreate(load) }, '+ Добавить'))),
    h('div.card', h('table.list', h('thead', h('tr', ...cols.map((c) => h('th', c.title)), h('th'))), tbody))));
  return load();
}

// ------------------------------------------------------------------ контакты
export async function contactsPage(root) {
  await listPage(root, {
    title: 'Контакты', url: '/api/crm/contacts',
    cols: [{ title: 'Имя', get: (c) => h('b', c.name) }, { title: 'Телефон', get: (c) => c.phone }, { title: 'E-mail', get: (c) => c.email },
      { title: 'Компания', get: (c) => c.company_name || '' }, { title: 'Сделок', num: true, get: (c) => String(c.deals_count) }],
    onOpen: (c) => { location.hash = '#/contact/' + c.id; },
    onCreate: (load) => contactDialog(null, load),
    rowActions: (c, load) => [
      { label: 'Изменить', onClick: () => contactDialog(c, load) },
      { label: 'Дублировать', onClick: async () => { await api.post(`/api/crm/contacts/${c.id}/duplicate`); load(); } },
      { label: 'Удалить', onClick: async () => { if (await confirmDlg(`Удалить контакт «${c.name}»? Сделки сохранятся без клиента.`)) { await api.del('/api/crm/contacts/' + c.id); load(); } } },
    ],
  });
}

async function contactDialog(c, onSaved) {
  const companies = await api.get('/api/crm/companies');
  const v = c ? { ...c } : { name: '', phone: '', email: '', position: '', company_id: null, comment: '' };
  const f = (label, key) => field(label, textInput(v[key], (x) => { v[key] = x; }));
  modal(c ? 'Контакт' : 'Новый контакт', h('div.col', f('Имя', 'name'), h('div.grid2', f('Телефон', 'phone'), f('E-mail', 'email')),
    h('div.grid2', field('Компания', selectInput(companies.map((x) => [x.id, x.name]), v.company_id, (x) => { v.company_id = x; }, { empty: '—' })), f('Должность', 'position')),
    f('Комментарий', 'comment')), {
    actions: [{ label: 'Отмена' }, { label: 'Сохранить', primary: true, onClick: async () => {
      document.activeElement && document.activeElement.blur();
      const body = { name: v.name, phone: v.phone, email: v.email, position: v.position, company_id: v.company_id || '', comment: v.comment };
      try {
        const r = c ? await api.put('/api/crm/contacts/' + c.id, body) : await api.post('/api/crm/contacts', body, { silent: true });
        onSaved && onSaved(r);
      } catch (e) {
        if (!c && /уже есть/.test(e.message) && await confirmDlg(e.message + '. Всё равно создать?', { danger: false, ok: 'Создать' })) {
          onSaved && onSaved(await api.post('/api/crm/contacts', { ...body, force: true }));
        } else if (c || !/уже есть/.test(e.message)) toast(e.message, 'error');
        else return false;
      }
    } }],
  });
}

export async function contactPage(root, id) {
  const [m, channels] = await Promise.all([crmMeta(), api.get('/api/crm/channels')]);
  const wrap = h('div.deal-page');
  root.appendChild(wrap);
  const render = async () => {
    const c = await api.get('/api/crm/contacts/' + id);
    const input = h('textarea', { rows: 2, placeholder: 'Сообщение клиенту (Telegram / e-mail / WhatsApp через провайдера)' });
    let chan = '';
    const sendable = channels.filter((x) => x.active && ['telegram', 'email', 'http'].includes(x.kind));
    clear(wrap,
      h('div.deal-left',
        h('div.row', h('a', { href: '#/contacts' }, '← Контакты'), h('span.right', menuButton('⋯', [
          { label: 'Изменить', onClick: () => contactDialog(c, render) },
          { label: 'Дублировать', onClick: async () => { const n = await api.post(`/api/crm/contacts/${id}/duplicate`); location.hash = '#/contact/' + n.id; } },
          { label: 'Удалить', onClick: async () => { if (await confirmDlg('Удалить контакт?')) { await api.del('/api/crm/contacts/' + id); location.hash = '#/contacts'; } } },
        ], '.sm'))),
        h('h2.deal-title', c.name),
        h('div.col',
          c.phone ? h('a', { href: 'tel:' + c.phone }, '📞 ' + c.phone) : null,
          c.email ? h('a', { href: 'mailto:' + c.email }, '✉ ' + c.email) : null,
          (c.data || {}).telegram_chat_id ? h('span.small', 'Telegram подключён' + ((c.data || {}).telegram_username ? ' (@' + c.data.telegram_username + ')' : '')) : null,
          c.company ? h('a', { href: '#/company/' + c.company.id }, '🏢 ' + c.company.name) : null,
          c.position ? h('span.small.muted', c.position) : null,
          c.comment ? h('p.small', c.comment) : null,
          (c.data || {}).source ? h('span.small.muted', 'Источник: ' + c.data.source) : null,
          h('button.btn.sm', { onclick: () => contactDialog(c, render) }, 'Изменить')),
        h('div.props-sec', h('div.row', h('div.sec-title', `Сделки (${c.deals.length})`), h('button.btn.sm.right', { onclick: () => newDealDialog({ contact_id: id }) }, '+ Сделка')),
          ...c.deals.map((d) => h('a.mini-deal', { href: '#/deal/' + d.id }, h('b', d.name), h('span.badge', { style: { background: d.stage_color } }, d.stage_name), h('span.small', money(d.amount)))))),
      h('div.deal-right',
        h('div.tasks-box', h('div.row', h('b', 'Задачи'), h('button.btn.sm.right', { onclick: () => taskDialog({ contact_id: id, onSaved: render }) }, '+ Задача')),
          c.tasks.filter((t) => !t.done).map((t) => taskRow(t, render))),
        h('div.composer', input, h('div.row',
          selectInput(sendable.map((x) => [x.id, x.name]), '', (x) => { chan = x || ''; }, { empty: 'Канал: автоматически' }),
          h('button.btn.primary.right', { onclick: async () => { if (!input.value.trim()) return; await api.post(`/api/crm/contacts/${id}/message`, { text: input.value, channel_id: chan }); render(); } }, 'Отправить'))),
        h('div.feed', c.events.length ? c.events.map((e) => eventRow(e, m, render)) : emptyState('Истории пока нет'))));
  };
  await render();
}

// ------------------------------------------------------------------ компании
export async function companiesPage(root) {
  await listPage(root, {
    title: 'Компании', url: '/api/crm/companies',
    cols: [{ title: 'Название', get: (c) => h('b', c.name) }, { title: 'Телефон', get: (c) => c.phone }, { title: 'ИНН', get: (c) => c.inn },
      { title: 'Контактов', num: true, get: (c) => String(c.contacts_count) }, { title: 'Сделок', num: true, get: (c) => String(c.deals_count) }],
    onOpen: (c) => { location.hash = '#/company/' + c.id; },
    onCreate: (load) => companyDialog(null, load),
    rowActions: (c, load) => [
      { label: 'Изменить', onClick: () => companyDialog(c, load) },
      { label: 'Дублировать', onClick: async () => { await api.post(`/api/crm/companies/${c.id}/duplicate`); load(); } },
      { label: 'Удалить', onClick: async () => { if (await confirmDlg(`Удалить компанию «${c.name}»?`)) { await api.del('/api/crm/companies/' + c.id); load(); } } },
    ],
  });
}

function companyDialog(c, onSaved) {
  const v = c ? { ...c } : { name: '', phone: '', email: '', address: '', inn: '', comment: '' };
  const f = (label, key) => field(label, textInput(v[key], (x) => { v[key] = x; }));
  modal(c ? 'Компания' : 'Новая компания', h('div.col', f('Название', 'name'), h('div.grid2', f('Телефон', 'phone'), f('E-mail', 'email')),
    h('div.grid2', f('ИНН', 'inn'), f('Адрес', 'address')), f('Комментарий', 'comment')), {
    actions: [{ label: 'Отмена' }, { label: 'Сохранить', primary: true, onClick: async () => {
      document.activeElement && document.activeElement.blur();
      const body = { name: v.name, phone: v.phone, email: v.email, address: v.address, inn: v.inn, comment: v.comment };
      onSaved && onSaved(c ? await api.put('/api/crm/companies/' + c.id, body) : await api.post('/api/crm/companies', body));
    } }],
  });
}

export async function companyPage(root, id) {
  const wrap = h('div.page');
  root.appendChild(wrap);
  const render = async () => {
    const c = await api.get('/api/crm/companies/' + id);
    clear(wrap,
      h('div.page-head', h('a', { href: '#/companies' }, '← Компании'), h('h1', c.name),
        h('div.right.row', h('button.btn', { onclick: () => companyDialog(c, render) }, 'Изменить'), h('button.btn.primary', { onclick: () => newDealDialog({ company_id: id }) }, '+ Сделка'))),
      h('div.order-grid',
        h('div.card.card-pad.col', c.phone ? h('a', { href: 'tel:' + c.phone }, '📞 ' + c.phone) : null, c.email ? h('a', { href: 'mailto:' + c.email }, '✉ ' + c.email) : null,
          c.inn ? h('span', 'ИНН ' + c.inn) : null, c.address ? h('span', c.address) : null, c.comment ? h('p.small', c.comment) : null,
          h('div.sec-title.small.muted', 'СОТРУДНИКИ'), ...c.contacts.map((x) => h('a', { href: '#/contact/' + x.id }, x.name + (x.position ? ' · ' + x.position : '')))),
        h('div.col', h('h2', 'Сделки'), c.deals.length ? c.deals.map((d) => h('a.mini-deal', { href: '#/deal/' + d.id }, h('b', d.name), h('span.badge', { style: { background: d.stage_color } }, d.stage_name), h('span.small', money(d.amount) + ' · ' + dt(d.created_at, false)))) : emptyState('Сделок нет'))));
  };
  await render();
}
