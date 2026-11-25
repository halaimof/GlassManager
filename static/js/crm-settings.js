// Настройки CRM: воронки и этапы, автоматизация, каналы, сотрудники.
import { api } from './api.js';
import { h, clear, modal, confirmDlg, promptDlg, field, textInput, numInput, selectInput, checkInput, toast, menuButton, emptyState, clone } from './ui.js';
import { crmMeta, crmUsers, pipelines, resetCrmCache, currentUser, setCurrentUser } from './crm-common.js';

const TABS = [['pipelines', 'Воронки и этапы'], ['automations', 'Автоматизация'], ['channels', 'Каналы'], ['users', 'Сотрудники']];

export async function crmSettingsPage(root, tab = 'pipelines') {
  const body = h('div');
  root.appendChild(h('div.page', h('div.page-head', h('h1', 'Настройки CRM')),
    h('div.tabs', TABS.map(([k, t]) => h('a' + (k === tab ? '.active' : ''), { href: '#/crm-settings/' + k }, t))), body));
  resetCrmCache();
  if (tab === 'automations') return automationsTab(body);
  if (tab === 'channels') return channelsTab(body);
  if (tab === 'users') return usersTab(body);
  return pipelinesTab(body);
}

// ------------------------------------------------------------------ воронки
async function pipelinesTab(body) {
  const render = (pipes) => {
    clear(body, h('div.row', { style: { marginBottom: '12px' } }, h('span.muted', 'Этапы можно переименовать, перекрасить, менять местами. Последние два — закрывающие (успех/отказ).'),
      h('button.btn.primary.right', { onclick: async () => { const n = await promptDlg('Новая воронка', 'Новая воронка'); if (n) render(await api.post('/api/crm/pipelines', { name: n })); } }, '+ Воронка')),
    ...pipes.map((p) => h('div.card.card-pad.col', { style: { marginBottom: '14px' } },
      h('div.row', h('h2', p.name), h('span.right', menuButton('⋯', [
        { label: 'Переименовать', onClick: async () => { const n = await promptDlg('Название воронки', p.name); if (n) render(await api.put('/api/crm/pipelines/' + p.id, { name: n })); } },
        { label: 'Дублировать', onClick: async () => render(await api.post(`/api/crm/pipelines/${p.id}/duplicate`)) },
        { label: 'Удалить', onClick: async () => { if (await confirmDlg(`Удалить воронку «${p.name}»?`)) render(await api.del('/api/crm/pipelines/' + p.id)); } },
      ], '.sm'))),
      h('div.stage-list', p.stages.map((s, i) => h('div.stage-edit',
        h('input', { type: 'color', value: s.color, onchange: async (e) => render(await api.put('/api/crm/stages/' + s.id, { color: e.target.value })) }),
        textInput(s.name, async (v) => render(await api.put('/api/crm/stages/' + s.id, { name: v }))),
        selectInput([['open', 'В работе'], ['won', 'Успех'], ['lost', 'Отказ']], s.kind, async (v) => render(await api.put('/api/crm/stages/' + s.id, { kind: v }))),
        h('button.icon-btn', { title: 'Выше', disabled: i === 0, onclick: async () => { const o = p.stages.map((x) => x.id); [o[i - 1], o[i]] = [o[i], o[i - 1]]; render(await api.put('/api/crm/pipelines/' + p.id, { stage_order: o })); } }, '↑'),
        h('button.icon-btn', { title: 'Ниже', disabled: i === p.stages.length - 1, onclick: async () => { const o = p.stages.map((x) => x.id); [o[i + 1], o[i]] = [o[i], o[i + 1]]; render(await api.put('/api/crm/pipelines/' + p.id, { stage_order: o })); } }, '↓'),
        h('button.icon-btn', { title: 'Дублировать', onclick: async () => render(await api.post(`/api/crm/stages/${s.id}/duplicate`)) }, '⧉'),
        h('button.icon-btn', { title: 'Удалить', onclick: async () => {
          if (!(await confirmDlg(`Удалить этап «${s.name}»?`))) return;
          try { render(await api.del('/api/crm/stages/' + s.id, { silent: true })); } catch (e) {
            let target = p.stages.find((x) => x.id !== s.id).id;
            modal('Перенести сделки', h('div.col', h('p', e.message), field('Куда', selectInput(p.stages.filter((x) => x.id !== s.id).map((x) => [x.id, x.name]), target, (v) => { target = v; }))), {
              actions: [{ label: 'Отмена' }, { label: 'Перенести и удалить', danger: true, primary: true, onClick: async () => render(await api.del(`/api/crm/stages/${s.id}?move_to=${target}`)) }],
            });
          }
        } }, '×')))),
      h('button.btn.sm', { onclick: async () => render(await api.post(`/api/crm/pipelines/${p.id}/stages`, { name: 'Новый этап' })) }, '+ Этап'))));
  };
  render(await pipelines(true));
}

// ------------------------------------------------------------------ автоматизация
async function automationsTab(body) {
  const [m, pipes, users, channels] = await Promise.all([crmMeta(), pipelines(true), crmUsers(true), api.get('/api/crm/channels')]);
  const stageName = (id) => { for (const p of pipes) for (const s of p.stages) if (s.id === id) return `${p.name} → ${s.name}`; return '—'; };
  const actText = (a) => `${m.actions[a.type] || a.type}${a.text ? ': «' + a.text + '»' : ''}${a.status ? ': ' + ((m.order_statuses.find((x) => x.key === a.status) || {}).name || a.status) : ''}${a.stage_id ? ': ' + stageName(a.stage_id) : ''}`;
  const load = async () => {
    const list = await api.get('/api/crm/automations');
    clear(body, h('div.row', { style: { marginBottom: '12px' } },
      h('span.muted', 'Правила срабатывают автоматически: при создании сделки, переходе на этап, успехе или отказе.'),
      h('button.btn.primary.right', { onclick: () => editAuto(null) }, '+ Правило')),
    list.length ? h('div.card', h('table.list', h('thead', h('tr', h('th', ''), h('th', 'Правило'), h('th', 'Когда'), h('th', 'Действия'), h('th'))),
      h('tbody', list.map((a) => h('tr.clickable', { onclick: () => editAuto(a) },
        h('td', { onclick: (e) => e.stopPropagation() }, h('input', { type: 'checkbox', checked: !!a.active, title: 'Включено', onchange: async (e) => { await api.put('/api/crm/automations/' + a.id, { active: e.target.checked ? 1 : 0 }); } })),
        h('td', h('b', a.name)),
        h('td', m.triggers[a.trigger] + (a.trigger === 'stage_enter' ? ' «' + stageName(a.stage_id) + '»' : '')),
        h('td.small', (a.data.actions || []).map(actText).join('; ')),
        h('td.actions', { onclick: (e) => e.stopPropagation() }, menuButton('⋯', [
          { label: 'Изменить', onClick: () => editAuto(a) },
          { label: 'Дублировать', onClick: async () => { await api.post(`/api/crm/automations/${a.id}/duplicate`); load(); } },
          { label: 'Удалить', onClick: async () => { if (await confirmDlg(`Удалить правило «${a.name}»?`)) { await api.del('/api/crm/automations/' + a.id); load(); } } },
        ], '.sm'))))))) : h('div.card', emptyState('Правил нет')));
  };
  const allStages = pipes.flatMap((p) => p.stages.map((s) => [s.id, `${p.name} → ${s.name}`]));
  function editAuto(a) {
    const v = a ? clone(a) : { name: 'Новое правило', trigger: 'stage_enter', stage_id: allStages[1] ? allStages[1][0] : null, data: { actions: [] } };
    v.data.actions = v.data.actions || [];
    const wrap = h('div.col');
    const render = () => clear(wrap,
      field('Название', textInput(v.name, (x) => { v.name = x; })),
      h('div.grid2',
        field('Когда', selectInput(Object.entries(m.triggers), v.trigger, (x) => { v.trigger = x; render(); })),
        v.trigger === 'stage_enter' ? field('Этап', selectInput(allStages, v.stage_id, (x) => { v.stage_id = x; })) :
          field('Воронка', selectInput(pipes.map((p) => [p.id, p.name]), v.data.pipeline_id, (x) => { v.data.pipeline_id = x; }, { empty: 'Любая' }))),
      h('div.sec-title.small.muted', 'ДЕЙСТВИЯ (по порядку)'),
      ...v.data.actions.map((act, i) => h('div.item-row',
        h('div.row', selectInput(Object.entries(m.actions), act.type, (x) => { v.data.actions[i] = { type: x }; render(); }),
          h('button.icon-btn.right', { onclick: () => { v.data.actions.splice(i, 1); render(); } }, '×')),
        ...actionFields(act))),
      h('button.btn.sm', { onclick: () => { v.data.actions.push({ type: 'create_task', kind: 'call', text: 'Позвонить {contact}', due_days: 1 }); render(); } }, '+ Действие'),
      h('p.hint', 'В тексте можно использовать: {contact} {phone} {name} {amount} {stage} {order}'));
    const actionFields = (act) => {
      switch (act.type) {
        case 'create_task': return [h('div.grid3',
          field('Тип', selectInput(Object.entries(m.task_kinds), act.kind, (x) => { act.kind = x; })),
          field('Через, дней', numInput(act.due_days, (x) => { act.due_days = x; })),
          field('Время', textInput(act.at_time, (x) => { act.at_time = x; }, { placeholder: '10:00' }))),
        field('Текст задачи', textInput(act.text, (x) => { act.text = x; })),
        field('Ответственный', selectInput(users.map((u) => [u.id, u.name]), act.responsible_id, (x) => { act.responsible_id = x; }, { empty: 'Ответственный сделки' }))];
        case 'add_note': return [field('Текст', textInput(act.text, (x) => { act.text = x; }))];
        case 'set_order_status': return [field('Статус заказа', selectInput(m.order_statuses.map((x) => [x.key, x.name]), act.status, (x) => { act.status = x; }, { empty: '—' })),
          checkInput(act.create_if_missing, (x) => { act.create_if_missing = x; }, 'Создать заказ, если его нет')];
        case 'set_responsible': return [field('Сотрудник', selectInput(users.map((u) => [u.id, u.name]), act.user_id, (x) => { act.user_id = x; }, { empty: '—' }))];
        case 'move_stage': return [field('Этап', selectInput(allStages, act.stage_id, (x) => { act.stage_id = x; }, { empty: '—' }))];
        case 'send_message': return [field('Текст сообщения', textInput(act.text, (x) => { act.text = x; }, { placeholder: 'Здравствуйте, {contact}! Замерщик приедет завтра.' })),
          field('Канал', selectInput(channels.filter((c) => ['telegram', 'email', 'http'].includes(c.kind)).map((c) => [c.id, c.name]), act.channel_id, (x) => { act.channel_id = x; }, { empty: 'Автоматически' }))];
        default: return [];
      }
    };
    render();
    modal(a ? 'Правило автоматизации' : 'Новое правило', wrap, {
      wide: true,
      actions: [{ label: 'Отмена' }, { label: 'Сохранить', primary: true, onClick: async () => {
        document.activeElement && document.activeElement.blur();
        const bodyA = { name: v.name, trigger: v.trigger, stage_id: v.trigger === 'stage_enter' ? v.stage_id : null, data: v.data };
        if (a) await api.put('/api/crm/automations/' + a.id, bodyA); else await api.post('/api/crm/automations', bodyA);
        load();
      } }],
    });
  }
  await load();
}

// ------------------------------------------------------------------ каналы
const CH_FIELDS = {
  form: [],
  telephony: [['create_deal', 'check', 'Создавать сделку на входящий звонок с нового номера']],
  telegram: [['bot_token', 'secret', 'Токен бота (от @BotFather)']],
  email: [['imap_host', 'text', 'IMAP-сервер', 'imap.yandex.ru'], ['imap_port', 'text', 'IMAP-порт', '993'], ['imap_user', 'text', 'Логин'],
    ['imap_password', 'secret', 'Пароль приложения (IMAP)'], ['imap_folder', 'text', 'Папка', 'INBOX'], ['poll_seconds', 'text', 'Проверять каждые, с', '120'],
    ['smtp_host', 'text', 'SMTP-сервер', 'smtp.yandex.ru'], ['smtp_port', 'text', 'SMTP-порт', '465'], ['smtp_user', 'text', 'SMTP-логин'],
    ['smtp_password', 'secret', 'SMTP-пароль'], ['from', 'text', 'Отправитель', 'info@example.ru']],
  http: [['send_url', 'text', 'URL отправки сообщений провайдера', 'https://api.provider.ru/send'], ['auth_header', 'secret', 'Заголовок авторизации', 'Authorization: Bearer …']],
};
const CH_HELP = {
  form: 'Вставьте HTML-форму на сайт или отправляйте POST-запрос (JSON или форма) на адрес webhook: name, phone, email, message, utm_*. Подходит для Tilda, WordPress, Битрикс и квизов.',
  telephony: 'Укажите адрес webhook в личном кабинете телефонии (Mango, Zadarma, Sipuni, Манго и др.). Поля: phone, direction (in/out), status (answered/missed), duration, record_url. Пропущенный входящий → задача «Перезвонить».',
  telegram: 'Создайте бота у @BotFather и вставьте токен. Входящие сообщения проверяются каждые ~15 секунд (не нужен внешний IP). Ответить можно из карточки сделки.',
  email: 'Входящие письма читаются по IMAP и попадают в ленту сделки; ответы отправляются через SMTP. Для Яндекс/Mail.ru используйте пароль приложения.',
  http: 'Для WhatsApp, VK, Avito и др. через провайдера-посредника (Wazzup, Chat2Desk, Green API…). Входящие — на webhook этого канала (phone, name, text), исходящие отправляются POST-запросом {to, phone, text, name} на URL провайдера.',
};

async function channelsTab(body) {
  const [m, pipes, users] = await Promise.all([crmMeta(), pipelines(true), crmUsers(true)]);
  const load = async () => {
    const list = await api.get('/api/crm/channels');
    clear(body, h('div.row', { style: { marginBottom: '12px' } },
      h('span.muted', 'Внешние каналы требуют доступа сервера в интернет. Для webhook (сайт, телефония, провайдеры) адрес сервера должен быть доступен извне.'),
      h('span.right', menuButton('+ Канал', Object.entries(m.channel_kinds).map(([k, n]) => ({ label: n, onClick: async () => { const ch = await api.post('/api/crm/channels', { kind: k }); load(); editChannel(ch); } })), '.primary'))),
    list.length ? h('div.card', h('table.list', h('thead', h('tr', h('th', ''), h('th', 'Канал'), h('th', 'Тип'), h('th', 'Состояние'), h('th'))),
      h('tbody', list.map((ch) => h('tr.clickable', { onclick: () => editChannel(ch) },
        h('td', { onclick: (e) => e.stopPropagation() }, h('input', { type: 'checkbox', checked: !!ch.active, title: 'Включён', onchange: async (e) => { await api.put('/api/crm/channels/' + ch.id, { active: e.target.checked ? 1 : 0 }); } })),
        h('td', h('b', ch.name)), h('td', m.channel_kinds[ch.kind]),
        h('td.small', (ch.state || {}).last_error ? h('span', { style: { color: 'var(--danger)' } }, ch.state.last_error) : (ch.state || {}).last_ok ? 'OK, ' + ch.state.last_ok.replace('T', ' ') : '—'),
        h('td.actions', { onclick: (e) => e.stopPropagation() }, menuButton('⋯', [
          { label: 'Настроить', onClick: () => editChannel(ch) },
          { label: 'Дублировать', onClick: async () => { await api.post(`/api/crm/channels/${ch.id}/duplicate`); load(); } },
          { label: 'Удалить', onClick: async () => { if (await confirmDlg(`Удалить канал «${ch.name}»?`)) { await api.del('/api/crm/channels/' + ch.id); load(); } } },
        ], '.sm'))))))) : h('div.card', emptyState('Каналов нет')));
  };
  const allStages = pipes.flatMap((p) => p.stages.filter((s) => s.kind === 'open').map((s) => [s.id, `${p.name} → ${s.name}`]));
  async function editChannel(ch) {
    const v = { name: ch.name, data: clone(ch.data || {}) };
    const fields = (CH_FIELDS[ch.kind] || []).map(([k, type, label, ph]) => type === 'check'
      ? checkInput(v.data[k] !== false, (x) => { v.data[k] = x; }, label)
      : field(label, h('input', { type: type === 'secret' ? 'password' : 'text', value: v.data[k] ?? '', placeholder: ph || '', autocomplete: 'off', onchange: (e) => { v.data[k] = e.target.value; } })));
    const extra = h('div.col');
    if (ch.kind === 'form') {
      const r = await api.get(`/api/crm/channels/${ch.id}/form`);
      extra.append(field('HTML-форма для сайта', h('textarea', { rows: 8, readonly: true, style: { fontFamily: 'monospace', fontSize: '11.5px' } }, r.html)));
    }
    modal(ch.name, h('div.col',
      h('p.small.muted', CH_HELP[ch.kind]),
      field('Название', textInput(v.name, (x) => { v.name = x; })),
      ['form', 'telephony', 'http'].includes(ch.kind) ? field('Адрес webhook (входящие)', h('div.row', h('input', { readonly: true, value: ch.webhook_url, onclick: (e) => e.target.select() }),
        h('button.btn.sm', { onclick: async () => { try { await navigator.clipboard.writeText(ch.webhook_url); toast('Скопировано', 'ok', 1000); } catch (_) { toast('Скопируйте вручную', 'error'); } } }, 'Копировать'),
        h('button.btn.sm', { onclick: async () => { if (await confirmDlg('Сгенерировать новый адрес? Старый перестанет работать.', { danger: true, ok: 'Сменить' })) { await api.put('/api/crm/channels/' + ch.id, { regenerate_token: true }); load(); } } }, 'Новый ключ')),
        'Адрес содержит секретный ключ — не публикуйте его, кроме как в форме своего сайта') : null,
      ...fields,
      h('div.grid3',
        field('Новые сделки — на этап', selectInput(allStages, v.data.stage_id, (x) => { v.data.stage_id = x; v.data.pipeline_id = (pipes.find((p) => p.stages.some((s) => s.id === x)) || {}).id; }, { empty: 'Первый этап' })),
        field('Ответственный', selectInput(users.map((u) => [u.id, u.name]), v.data.responsible_id, (x) => { v.data.responsible_id = x; }, { empty: '—' })),
        field('Задача на новую заявку', textInput(v.data.task_text, (x) => { v.data.task_text = x; }, { placeholder: 'не создавать' }))),
      checkInput(v.data.always_new_deal, (x) => { v.data.always_new_deal = x; }, 'Каждое обращение — новая сделка (иначе — в открытую сделку клиента)'),
      extra,
      ['telegram', 'email'].includes(ch.kind) ? h('button.btn.sm', { onclick: async () => {
        document.activeElement && document.activeElement.blur();
        await api.put('/api/crm/channels/' + ch.id, { name: v.name, data: v.data });
        const r = await api.post(`/api/crm/channels/${ch.id}/poll`);
        toast(`Проверено, получено: ${r.received}`, 'ok');
      } }, 'Сохранить и проверить сейчас') : null), {
      wide: true,
      actions: [{ label: 'Отмена' }, { label: 'Сохранить', primary: true, onClick: async () => {
        document.activeElement && document.activeElement.blur();
        await api.put('/api/crm/channels/' + ch.id, { name: v.name, data: v.data }); load();
      } }],
    });
  }
  await load();
}

// ------------------------------------------------------------------ сотрудники
async function usersTab(body) {
  const load = async () => {
    const users = await crmUsers(true);
    window.dispatchEvent(new Event('gc-users-changed'));
    const me = currentUser();
    clear(body, h('div.row', { style: { marginBottom: '12px' } },
      h('span.muted', 'Сотрудник, выбранный «Это я», подставляется ответственным и автором записей в ленте на этом компьютере.'),
      h('button.btn.primary.right', { onclick: async () => { const n = await promptDlg('Новый сотрудник', '', 'Имя'); if (n) { await api.post('/api/crm/users', { name: n }); load(); } } }, '+ Сотрудник')),
    h('div.card', h('table.list', h('tbody', users.map((u) => h('tr',
      h('td', h('input', { type: 'color', value: u.color, onchange: async (e) => { await api.put('/api/crm/users/' + u.id, { color: e.target.value }); } })),
      h('td', textInput(u.name, async (v) => { await api.put('/api/crm/users/' + u.id, { name: v }); })),
      h('td', checkInput(u.active, async (v) => { await api.put('/api/crm/users/' + u.id, { active: v ? 1 : 0 }); }, 'Активен')),
      h('td', me === u.id ? h('b', '✓ Это я') : h('button.btn.sm', { onclick: () => { setCurrentUser(u.id); load(); } }, 'Это я')),
      h('td.actions', menuButton('⋯', [
        { label: 'Дублировать', onClick: async () => { await api.post(`/api/crm/users/${u.id}/duplicate`); load(); } },
        { label: 'Удалить', onClick: async () => { if (await confirmDlg(`Удалить сотрудника «${u.name}»? Его сделки останутся без ответственного.`)) { await api.del('/api/crm/users/' + u.id); load(); } } },
      ], '.sm'))))))));
  };
  await load();
}
