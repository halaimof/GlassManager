// Сделки: канбан воронки и карточка сделки с лентой, задачами и сообщениями.
import { api, download } from './api.js';
import { h, clear, modal, confirmDlg, promptDlg, field, textInput, numInput, selectInput, toast, menuButton, emptyState } from './ui.js';
import { crmMeta, crmUsers, pipelines, currentUser, money, dt, dueState, dueLabel, userDot, taskDialog, completeTaskDialog, KIND_ICON, EVENT_ICON } from './crm-common.js';
import { productWizard } from './orders.js';

const PREF = 'gc-pipeline';
const getPref = () => { try { return localStorage.getItem(PREF) || ''; } catch (_) { return ''; } };
const setPref = (v) => { try { localStorage.setItem(PREF, v); } catch (_) { /* */ } };

// ------------------------------------------------------------------ канбан
export async function dealsPage(root) {
  const [pipes, users] = await Promise.all([pipelines(true), crmUsers(true)]);
  const st = { pipeline: pipes.find((p) => p.id === getPref()) ? getPref() : pipes[0].id, q: '', resp: '', closed: false };
  const board = h('div.kanban');
  const totals = h('span.muted.small');
  const load = async () => {
    const pipe = pipes.find((p) => p.id === st.pipeline);
    const list = await api.get(`/api/crm/deals?pipeline_id=${st.pipeline}&q=${encodeURIComponent(st.q)}&responsible_id=${st.resp}`);
    clear(board);
    const open = list.filter((d) => d.stage_kind === 'open');
    totals.textContent = `Открытых сделок: ${open.length} · ${money(open.reduce((s, d) => s + (d.amount || 0), 0))}`;
    for (const s of pipe.stages) {
      const items = list.filter((d) => d.stage_id === s.id);
      const closedCol = s.kind !== 'open';
      const col = h('div.kcol' + (closedCol ? '.closed' : '') + (closedCol && !st.closed ? '.collapsed' : ''), { 'data-stage': s.id });
      const sum = items.reduce((a, d) => a + (d.amount || 0), 0);
      col.appendChild(h('div.khead', { style: { borderTopColor: s.color } },
        h('div.row', h('b', s.name), h('span.badge.right', String(items.length))),
        h('div.small.muted', money(sum))));
      const body = h('div.kbody');
      if (s === pipe.stages.find((x) => x.kind === 'open')) {
        body.appendChild(h('button.kadd', { onclick: () => newDealDialog({ pipeline_id: st.pipeline, stage_id: s.id }, load) }, '+ Быстрое добавление'));
      }
      if (!(closedCol && !st.closed)) for (const d of items) body.appendChild(dealCard(d));
      else if (items.length) body.appendChild(h('div.small.muted', { style: { padding: '8px' } }, 'Перетащите сюда, чтобы закрыть'));
      col.appendChild(body);
      col.addEventListener('dragover', (e) => { e.preventDefault(); col.classList.add('over'); });
      col.addEventListener('dragleave', () => col.classList.remove('over'));
      col.addEventListener('drop', async (e) => {
        e.preventDefault(); col.classList.remove('over');
        const id = e.dataTransfer.getData('text/deal');
        if (!id) return;
        let reason = '';
        if (s.kind === 'lost') { reason = await promptDlg('Причина отказа', '', 'Причина'); if (reason === null) return; }
        await api.put('/api/crm/deals/' + id, { stage_id: s.id, lost_reason: reason });
        load();
      });
      board.appendChild(col);
    }
  };
  const dealCard = (d) => {
    const ds = dueState(d.next_task_at);
    const card = h('div.kcard', { draggable: 'true', onclick: () => { location.hash = '#/deal/' + d.id; } },
      h('div.row', h('b.kname', d.name), userDot(d.responsible_name, d.responsible_color)),
      d.contact_name ? h('div.small', d.contact_name + (d.company_name ? ' · ' + d.company_name : '')) : null,
      h('div.row.small',
        h('span', money(d.amount)),
        d.order_number ? h('span.badge', 'заказ №' + d.order_number) : null,
        h('span.right.task-due.' + (d.open_tasks ? ds : 'none'), d.open_tasks ? dueLabel(d.next_task_at) : 'нет задач')));
    card.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/deal', d.id); card.classList.add('dragging'); });
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
    return card;
  };
  const search = h('input', { type: 'search', placeholder: 'Поиск: сделка, клиент, телефон, заказ…', style: { maxWidth: '280px' } });
  search.addEventListener('input', () => { st.q = search.value; clearTimeout(search._t); search._t = setTimeout(load, 250); });
  root.appendChild(h('div.crm-page',
    h('div.page-head',
      h('h1', 'Сделки'),
      selectInput(pipes.map((p) => [p.id, p.name]), st.pipeline, (v) => { st.pipeline = v; setPref(v); load(); }),
      totals,
      h('div.right.row', search,
        selectInput(users.map((u) => [u.id, u.name]), '', (v) => { st.resp = v || ''; load(); }, { empty: 'Все ответственные' }),
        h('label.check', h('input', { type: 'checkbox', onchange: (e) => { st.closed = e.target.checked; load(); } }), h('span', 'Закрытые')),
        h('button.btn.primary', { onclick: () => newDealDialog({ pipeline_id: st.pipeline }, load) }, '+ Сделка'))),
    board));
  await load();
}

export async function newDealDialog(preset = {}, onCreated) {
  const [pipes, users] = await Promise.all([pipelines(), crmUsers()]);
  const v = { name: '', amount: null, pipeline_id: preset.pipeline_id || pipes[0].id, stage_id: preset.stage_id || '', responsible_id: currentUser() || null,
    source: '', contact_id: preset.contact_id || null, company_id: preset.company_id || null, nc: { name: '', phone: '', email: '' } };
  const stageSel = h('span');
  const renderStages = () => {
    const p = pipes.find((x) => x.id === v.pipeline_id);
    clear(stageSel, selectInput(p.stages.map((s) => [s.id, s.name]), v.stage_id || p.stages[0].id, (x) => { v.stage_id = x; }));
    v.stage_id = v.stage_id && p.stages.some((s) => s.id === v.stage_id) ? v.stage_id : p.stages[0].id;
  };
  renderStages();
  const contactBox = h('div.col');
  if (!v.contact_id) {
    contactBox.append(h('div.sec-title.small.muted', 'КЛИЕНТ (найдётся по телефону или e-mail, если уже есть)'),
      h('div.grid3', field('Имя', textInput('', (x) => { v.nc.name = x; })), field('Телефон', textInput('', (x) => { v.nc.phone = x; })),
        field('E-mail', textInput('', (x) => { v.nc.email = x; }))));
  }
  modal('Новая сделка', h('div.col',
    field('Название', textInput('', (x) => { v.name = x; }, { placeholder: 'Душевая в ванную, Петрова' })),
    h('div.grid3',
      field('Воронка', selectInput(pipes.map((p) => [p.id, p.name]), v.pipeline_id, (x) => { v.pipeline_id = x; v.stage_id = ''; renderStages(); })),
      field('Этап', stageSel),
      field('Бюджет, ₽', numInput(null, (x) => { v.amount = x; }))),
    h('div.grid2',
      field('Ответственный', selectInput(users.map((u) => [u.id, u.name]), v.responsible_id, (x) => { v.responsible_id = x; }, { empty: '—' })),
      field('Источник', textInput('', (x) => { v.source = x; }, { placeholder: 'Сайт, Авито, рекомендация…' }))),
    contactBox), {
    wide: true,
    actions: [{ label: 'Отмена' }, {
      label: 'Создать', primary: true, onClick: async () => {
        document.activeElement && document.activeElement.blur();
        const body = { name: v.name, amount: v.amount || 0, pipeline_id: v.pipeline_id, stage_id: v.stage_id, responsible_id: v.responsible_id,
          source: v.source, contact_id: v.contact_id, company_id: v.company_id };
        if (!v.contact_id && (v.nc.name || v.nc.phone || v.nc.email)) body.new_contact = v.nc;
        const d = await api.post('/api/crm/deals', body);
        if (onCreated) onCreated(d); else location.hash = '#/deal/' + d.id;
      },
    }],
  });
}

// ------------------------------------------------------------------ карточка сделки
export async function dealPage(root, id) {
  const [m, pipes, users, channels] = await Promise.all([crmMeta(), pipelines(true), crmUsers(), api.get('/api/crm/channels')]);
  let d = await api.get('/api/crm/deals/' + id);
  const left = h('div.deal-left');
  const right = h('div.deal-right');
  root.appendChild(h('div.deal-page', left, right));
  const save = async (patch) => { d = await api.put('/api/crm/deals/' + id, patch); render(); };

  const render = () => { renderLeft(); renderRight(); };
  function renderLeft() {
    const pipe = pipes.find((p) => p.id === d.pipeline_id) || pipes[0];
    const allStages = pipes.flatMap((p) => p.stages.map((s) => [s.id, (pipes.length > 1 ? p.name + ' → ' : '') + s.name]));
    const c = d.contact;
    clear(left,
      h('div.row', h('a', { href: '#/deals' }, '← Сделки'), h('span.right', menuButton('⋯', [
        { label: 'Переименовать', onClick: async () => { const n = await promptDlg('Название сделки', d.name); if (n) save({ name: n }); } },
        { label: 'Дублировать', onClick: async () => { const n = await api.post(`/api/crm/deals/${id}/duplicate`); location.hash = '#/deal/' + n.id; } },
        '-',
        { label: 'Удалить сделку', onClick: async () => { if (await confirmDlg(`Удалить сделку «${d.name}» вместе с лентой и задачами?`)) { await api.del('/api/crm/deals/' + id); location.hash = '#/deals'; } } },
      ], '.sm'))),
      h('h2.deal-title', d.name),
      h('div.stage-bar', pipe.stages.filter((s) => s.kind === 'open').map((s) => h('button.stage-step' + (s.id === d.stage_id ? '.on' : '') + (s.position < (pipe.stages.find((x) => x.id === d.stage_id) || {}).position ? '.passed' : ''), {
        title: s.name, style: { '--c': s.color }, onclick: () => save({ stage_id: s.id }) }, s.name))),
      h('div.row',
        h('span.badge', { style: { background: d.stage_color } }, d.stage_name || '—'),
        d.stage_kind === 'open' ? h('button.btn.sm', { onclick: () => { const w = pipe.stages.find((s) => s.kind === 'won'); if (w) save({ stage_id: w.id }); } }, '✔ Успешно') : null,
        d.stage_kind === 'open' ? h('button.btn.sm', { onclick: async () => { const l = pipe.stages.find((s) => s.kind === 'lost'); const r = await promptDlg('Причина отказа', '', 'Причина'); if (l && r !== null) save({ stage_id: l.id, lost_reason: r }); } }, '✖ Отказ') : null,
        d.stage_kind !== 'open' && d.data && d.data.lost_reason ? h('span.small.muted', 'Причина: ' + d.data.lost_reason) : null),
      h('div.props-sec',
        field('Этап', selectInput(allStages, d.stage_id, (v) => save({ stage_id: v }))),
        h('div.grid2',
          field('Бюджет, ₽', numInput(d.amount || null, (v) => save({ amount: v || 0 }))),
          field('Ответственный', selectInput(users.map((u) => [u.id, u.name]), d.responsible_id, (v) => save({ responsible_id: v }), { empty: '—' }))),
        h('div.grid2',
          field('Источник', textInput(d.source, (v) => save({ source: v }))),
          field('Теги', textInput(d.tags, (v) => save({ tags: v }), { placeholder: 'через запятую' }))),
        field('Комментарий', h('textarea', { onchange: (e) => save({ comment: e.target.value }) }, d.comment || ''))),
      h('div.props-sec', h('div.sec-title', 'Клиент'),
        c ? h('div.col',
          h('a', { href: '#/contact/' + c.id }, h('b', c.name)),
          c.phone ? h('a', { href: 'tel:' + c.phone }, '📞 ' + c.phone) : null,
          c.email ? h('a', { href: 'mailto:' + c.email }, '✉ ' + c.email) : null,
          (c.data || {}).telegram_username ? h('span.small', 'Telegram: @' + c.data.telegram_username) : (c.data || {}).telegram_chat_id ? h('span.small', 'Telegram подключён') : null,
          d.company ? h('a.small', { href: '#/company/' + d.company.id }, '🏢 ' + d.company.name) : null,
          h('button.btn.sm', { onclick: () => pickContact() }, 'Сменить клиента'))
          : h('button.btn.sm', { onclick: () => pickContact() }, '+ Привязать клиента')),
      h('div.props-sec', h('div.sec-title', 'Заказ и изделия'),
        d.order_id ? h('div.col',
          h('a', { href: '#/order/' + d.order_id }, h('b', `Заказ №${d.order_number}`), ' · ', h('span.badge.st-' + d.order_status, (m.order_statuses.find((s) => s.key === d.order_status) || {}).name || '')),
          ...(d.products || []).map((p) => h('a.small', { href: '#/product/' + p.id }, '▫ ' + p.name)),
          h('div.row',
            h('button.btn.sm', { onclick: async () => productWizard(await api.get('/api/orders/' + d.order_id)) }, '+ Изделие'),
            h('button.btn.sm', { onclick: () => download(`/api/orders/${d.order_id}/pdf?mode=client`) }, 'PDF клиенту')))
          : h('div.row',
            h('button.btn.sm.primary', { onclick: async () => { d = await api.post(`/api/crm/deals/${id}/order`); render(); toast('Заказ создан', 'ok'); } }, 'Создать заказ'),
            h('button.btn.sm', { onclick: () => linkOrder() }, 'Привязать существующий'))));
  }

  async function pickContact() {
    const list = await api.get('/api/crm/contacts');
    const v = { id: d.contact_id, name: '', phone: '' };
    modal('Клиент сделки', h('div.col',
      field('Существующий контакт', selectInput(list.map((c) => [c.id, `${c.name}${c.phone ? ' · ' + c.phone : ''}`]), v.id, (x) => { v.id = x; }, { empty: '— новый —' })),
      h('div.grid2', field('или новый: имя', textInput('', (x) => { v.name = x; })), field('телефон', textInput('', (x) => { v.phone = x; })))), {
      actions: [{ label: 'Отмена' }, { label: 'Сохранить', primary: true, onClick: async () => {
        document.activeElement && document.activeElement.blur();
        let cid = v.id;
        if (!cid && (v.name || v.phone)) {
          const r = await api.post('/api/crm/contacts', { name: v.name || v.phone, phone: v.phone, force: true });
          cid = r.id;
        }
        await save({ contact_id: cid || '' });
      } }],
    });
  }
  async function linkOrder() {
    const orders = await api.get('/api/orders');
    let oid = orders[0] && orders[0].id;
    modal('Привязать заказ', field('Заказ', selectInput(orders.map((o) => [o.id, `№${o.number} · ${o.client || '—'}`]), oid, (x) => { oid = x; })), {
      actions: [{ label: 'Отмена' }, { label: 'Привязать', primary: true, onClick: async () => { d = await api.post(`/api/crm/deals/${id}/order`, { order_id: oid }); render(); } }],
    });
  }

  let composerTab = 'note';
  function renderRight() {
    const openTasks = d.tasks.filter((t) => !t.done);
    const input = h('textarea', { rows: 3, placeholder: composerTab === 'note' ? 'Примечание (видно только сотрудникам)' : 'Сообщение клиенту' });
    let chan = '';
    const sendable = channels.filter((c) => c.active && ['telegram', 'email', 'http'].includes(c.kind));
    const composer = h('div.composer',
      h('div.segmented', [['note', 'Примечание'], ['message', 'Сообщение клиенту'], ['task', 'Задача']].map(([k, l]) =>
        h('button' + (composerTab === k ? '.on' : ''), { onclick: () => { if (k === 'task') { taskDialog({ deal_id: id, contact_id: d.contact_id, onSaved: reload }); return; } composerTab = k; renderRight(); } }, l))),
      input,
      h('div.row',
        composerTab === 'message' ? selectInput(sendable.map((c) => [c.id, c.name]), '', (x) => { chan = x || ''; }, { empty: 'Канал: автоматически' }) : null,
        composerTab === 'message' && !sendable.length ? h('span.small.muted', 'Каналы настраиваются в CRM → Настройки → Каналы') : null,
        h('button.btn.primary.right', { onclick: async () => {
          const text = input.value.trim(); if (!text) return;
          d = composerTab === 'note' ? await api.post(`/api/crm/deals/${id}/notes`, { text }) : await api.post(`/api/crm/deals/${id}/message`, { text, channel_id: chan });
          renderRight();
        } }, composerTab === 'note' ? 'Добавить' : 'Отправить')));
    clear(right,
      h('div.tasks-box',
        h('div.row', h('b', `Задачи (${openTasks.length})`), h('button.btn.sm.right', { onclick: () => taskDialog({ deal_id: id, contact_id: d.contact_id, onSaved: reload }) }, '+ Задача')),
        openTasks.length ? openTasks.map((t) => taskRow(t, reload)) : h('div.small.muted', 'Нет открытых задач — поставьте следующий шаг')),
      composer,
      h('div.feed', d.events.length ? d.events.map((e) => eventRow(e, m, reload)) : emptyState('Лента пуста')));
  }
  async function reload() { d = await api.get('/api/crm/deals/' + id); render(); }
  render();
}

export function taskRow(t, onChange, { showDeal = false } = {}) {
  const ds = dueState(t.due_at);
  return h('div.task-row' + (t.done ? '.done' : ''),
    h('input', { type: 'checkbox', checked: !!t.done, title: 'Выполнить', onclick: async (e) => {
      e.preventDefault();
      if (t.done) { await api.post(`/api/crm/tasks/${t.id}/reopen`); onChange(); } else completeTaskDialog(t, onChange);
    } }),
    h('span', KIND_ICON[t.kind] || '•'),
    h('div.col', { style: { gap: '1px', flex: 1, minWidth: 0 } },
      h('span', t.text),
      h('span.small.muted', [showDeal && t.deal_name ? h('a', { href: '#/deal/' + t.deal_id }, t.deal_name) : null, showDeal && t.contact_name ? ' · ' + t.contact_name : '',
        t.responsible_name ? ' · ' + t.responsible_name : '', t.result ? ' · ' + t.result : ''])),
    h('span.task-due.' + (t.done ? 'none' : ds), t.done ? 'выполнено' : dueLabel(t.due_at)),
    menuButton('⋯', [
      { label: 'Изменить', onClick: () => taskDialog({ task: t, onSaved: onChange }) },
      { label: 'Дублировать', onClick: async () => { await api.post(`/api/crm/tasks/${t.id}/duplicate`); onChange(); } },
      { label: 'Удалить', onClick: async () => { if (await confirmDlg('Удалить задачу?')) { await api.del('/api/crm/tasks/' + t.id); onChange(); } } },
    ], '.sm'));
}

export function eventRow(e, m, onChange) {
  const rec = (e.data || {}).record_url;
  return h('div.event.ev-' + e.kind,
    h('span.ev-icon', EVENT_ICON[e.kind] || '•'),
    h('div.col', { style: { gap: '2px', flex: 1, minWidth: 0 } },
      h('div.small.muted', `${dt(e.created_at)} · ${m.event_kinds[e.kind] || e.kind}${e.author ? ' · ' + e.author : ''}${(e.data || {}).channel && e.data.channel !== e.author ? ' · ' + e.data.channel : ''}`),
      h('div.ev-text', e.text),
      rec ? h('audio', { controls: true, src: rec, preload: 'none', style: { maxWidth: '100%' } }) : null,
      (e.data || {}).fields && Object.keys(e.data.fields).length ? h('div.small.muted', Object.entries(e.data.fields).map(([k, v]) => `${k}: ${v}`).join(' · ')) : null),
    e.kind === 'note' ? menuButton('⋯', [
      { label: 'Изменить', onClick: async () => { const t = await promptDlg('Примечание', e.text, 'Текст'); if (t !== null) { await api.put('/api/crm/events/' + e.id, { text: t }); onChange(); } } },
      { label: 'Удалить', onClick: async () => { if (await confirmDlg('Удалить примечание?')) { await api.del('/api/crm/events/' + e.id); onChange(); } } },
    ], '.sm') : null);
}
