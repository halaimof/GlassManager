// Задачи: список по срокам и календарь недели. Аналитика продаж.
import { api } from './api.js';
import { h, clear, selectInput, segmented, emptyState } from './ui.js';
import { crmUsers, pipelines, money, dueState, localISO, taskDialog, KIND_ICON } from './crm-common.js';
import { taskRow } from './crm-deals.js';

export async function tasksPage(root) {
  const users = await crmUsers();
  const st = { view: 'list', scope: 'open', resp: '', week: 0 };
  const body = h('div');
  const load = async () => {
    if (st.view === 'calendar') return renderCalendar();
    const list = await api.get(`/api/crm/tasks?scope=${st.scope}&responsible_id=${st.resp}`);
    clear(body);
    if (!list.length) { body.appendChild(h('div.card', emptyState(st.scope === 'done' ? 'Выполненных задач нет' : 'Открытых задач нет 🎉'))); return; }
    if (st.scope === 'done') { body.appendChild(h('div.card.task-list', list.map((t) => taskRow(t, load, { showDeal: true })))); return; }
    const groups = [['overdue', 'Просрочено'], ['today', 'Сегодня'], ['later', 'Позже'], ['none', 'Без срока']];
    for (const [k, title] of groups) {
      const items = list.filter((t) => dueState(t.due_at) === k);
      if (!items.length) continue;
      body.appendChild(h('div.task-group', h('h3.tg-' + k, `${title} · ${items.length}`), h('div.card.task-list', items.map((t) => taskRow(t, load, { showDeal: true })))));
    }
  };
  async function renderCalendar() {
    const start = new Date(); start.setHours(0, 0, 0, 0);
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7) + st.week * 7);
    const days = [...Array(7)].map((_, i) => new Date(start.getTime() + i * 864e5));
    const from = localISO(days[0]).slice(0, 10), to = localISO(days[6]).slice(0, 10);
    const list = await api.get(`/api/crm/tasks?scope=all&responsible_id=${st.resp}&date_from=${from}&date_to=${to}`);
    const today = localISO(new Date()).slice(0, 10);
    clear(body,
      h('div.row', { style: { marginBottom: '10px' } },
        h('button.btn.sm', { onclick: () => { st.week--; load(); } }, '←'), h('button.btn.sm', { onclick: () => { st.week = 0; load(); } }, 'Эта неделя'),
        h('button.btn.sm', { onclick: () => { st.week++; load(); } }, '→'), h('b', `${from.split('-').reverse().join('.')} — ${to.split('-').reverse().join('.')}`)),
      h('div.calendar', days.map((d) => {
        const key = localISO(d).slice(0, 10);
        const items = list.filter((t) => (t.due_at || '').slice(0, 10) === key);
        return h('div.cal-day' + (key === today ? '.today' : ''),
          h('div.cal-head', d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'short' }),
            h('button.icon-btn', { title: 'Задача на этот день', onclick: () => { const x = new Date(d); x.setHours(10); taskDialog({ due_at: localISO(x), onSaved: load }); } }, '+')),
          ...items.map((t) => h('div.cal-task' + (t.done ? '.done' : '') + '.' + (t.done ? 'none' : dueState(t.due_at)), {
            title: t.text, onclick: () => (t.deal_id ? (location.hash = '#/deal/' + t.deal_id) : taskDialog({ task: t, onSaved: load })),
          }, `${(t.due_at || '').slice(11, 16)} ${KIND_ICON[t.kind] || ''} ${t.text}`, t.contact_name ? h('div.small.muted', t.contact_name) : null)));
      })));
  }
  root.appendChild(h('div.page',
    h('div.page-head', h('h1', 'Задачи'),
      segmented([['list', 'Список'], ['calendar', 'Календарь']], st.view, () => {}),
      h('div.right.row',
        selectInput([['open', 'Открытые'], ['overdue', 'Просроченные'], ['done', 'Выполненные']], st.scope, (v) => { st.scope = v; load(); }),
        selectInput(users.map((u) => [u.id, u.name]), st.resp, (v) => { st.resp = v || ''; load(); }, { empty: 'Все сотрудники' }),
        h('button.btn.primary', { onclick: () => taskDialog({ onSaved: load }) }, '+ Задача'))),
    body));
  const seg = root.querySelector('.segmented');
  seg.querySelectorAll('button').forEach((b, i) => b.addEventListener('click', () => {
    st.view = i ? 'calendar' : 'list';
    seg.querySelectorAll('button').forEach((x, j) => x.classList.toggle('on', j === i));
    load();
  }));
  await load();
}

// ------------------------------------------------------------------ аналитика
export async function analyticsPage(root) {
  const pipes = await pipelines(true);
  const now = new Date();
  const st = { pipeline: pipes[0].id, from: localISO(new Date(now.getTime() - 30 * 864e5)).slice(0, 10), to: localISO(now).slice(0, 10) };
  const body = h('div.col');
  const preset = (days) => { st.from = localISO(new Date(Date.now() - days * 864e5)).slice(0, 10); st.to = localISO(new Date()).slice(0, 10); fromI.value = st.from; toI.value = st.to; load(); };
  const fromI = h('input', { type: 'date', value: st.from, onchange: (e) => { st.from = e.target.value; load(); } });
  const toI = h('input', { type: 'date', value: st.to, onchange: (e) => { st.to = e.target.value; load(); } });
  const kpi = (label, value, sub) => h('div.card.kpi', h('span.small.muted', label), h('b', value), sub ? h('span.small.muted', sub) : null);
  const bar = (v, max, color) => h('div.bar', h('span', { style: { width: (max && v ? Math.max(2, 100 * v / max) : 0) + '%', background: color || 'var(--accent)' } }));
  async function load() {
    const a = await api.get(`/api/crm/analytics?pipeline_id=${st.pipeline}&date_from=${st.from}&date_to=${st.to}`);
    const s = a.summary;
    const maxF = Math.max(1, ...a.funnel.map((f) => f.count));
    const maxM = Math.max(1, ...a.months.map((x) => x.won_sum));
    const maxS = Math.max(1, ...a.sources.map((x) => x.count));
    clear(body,
      h('div.kpis',
        kpi('Новых сделок', String(s.created)), kpi('Успешных', String(s.won), money(s.won_sum)), kpi('Отказов', String(s.lost)),
        kpi('Конверсия в успех', s.win_rate + ' %', 'успешные / закрытые'), kpi('Средний чек', money(s.avg_check)),
        kpi('Средний цикл', s.avg_cycle_days != null ? s.avg_cycle_days + ' дн.' : '—'), kpi('В работе', String(s.open_count), money(s.open_sum)),
        kpi('Задачи', `${a.tasks.overdue} просрочено`, `${a.tasks.today} на сегодня · ${a.tasks.done} выполнено за период`)),
      h('div.an-grid',
        h('div.card.card-pad.col', h('h3', 'Воронка: сколько сделок дошло до этапа'),
          ...a.funnel.map((f) => h('div.an-row', h('span', f.name), bar(f.count, maxF), h('b', String(f.count)), h('span.small.muted', f.conversion + ' %')))),
        h('div.card.card-pad.col', h('h3', 'Сейчас на этапах'),
          ...a.current.map((c) => h('div.an-row', h('span', c.name), bar(c.count, Math.max(1, ...a.current.map((x) => x.count)), c.color), h('b', String(c.count)), h('span.small.muted', money(c.amount))))),
        h('div.card.card-pad.col', h('h3', 'Выручка по месяцам (успешные сделки)'),
          h('div.months', a.months.map((x) => h('div.mcol', { title: `${x.month}: ${money(x.won_sum)}, сделок ${x.won}, новых ${x.created}` },
            h('div.mbar', { style: { height: Math.max(2, 140 * x.won_sum / maxM) + 'px' } }), h('span.small.muted', x.month.slice(5)))))),
        h('div.card.card-pad.col', h('h3', 'Источники'),
          a.sources.length ? a.sources.map((x) => h('div.an-row', h('span', x.source), bar(x.count, maxS), h('b', String(x.count)), h('span.small.muted', `${x.won} усп. · ${money(x.won_sum)}`))) : h('span.muted', 'Нет данных')),
        h('div.card.card-pad.col', h('h3', 'Сотрудники'),
          h('table.list', h('thead', h('tr', h('th', 'Сотрудник'), h('th', 'В работе'), h('th', 'Успешно'), h('th', 'Выручка'), h('th', 'Задач выполнено'), h('th', 'Просрочено'))),
            h('tbody', a.managers.map((x) => h('tr', h('td', x.name), h('td.num', String(x.open)), h('td.num', String(x.won)), h('td.num', money(x.won_sum)), h('td.num', String(x.tasks_done)), h('td.num', String(x.tasks_overdue))))))),
        h('div.card.card-pad.col', h('h3', 'Причины отказов'),
          a.lost_reasons.length ? a.lost_reasons.map((x) => h('div.an-row', h('span', x.reason), bar(x.count, Math.max(...a.lost_reasons.map((r) => r.count)), '#b83a2e'), h('b', String(x.count)))) : h('span.muted', 'Отказов за период нет'))));
  }
  root.appendChild(h('div.page',
    h('div.page-head', h('h1', 'Аналитика'), selectInput(pipes.map((p) => [p.id, p.name]), st.pipeline, (v) => { st.pipeline = v; load(); }),
      h('div.right.row', h('button.btn.sm', { onclick: () => preset(7) }, '7 дней'), h('button.btn.sm', { onclick: () => preset(30) }, '30 дней'),
        h('button.btn.sm', { onclick: () => preset(90) }, 'Квартал'), h('button.btn.sm', { onclick: () => preset(365) }, 'Год'), fromI, toI)),
    body));
  await load();
}
