// Общие данные и элементы CRM.
import { api } from './api.js';
import { h, modal, field, textInput, selectInput, toast } from './ui.js';

let metaC = null, usersC = null, pipesC = null;
export async function crmMeta() { if (!metaC) metaC = await api.get('/api/crm/meta'); return metaC; }
export async function crmUsers(force) { if (force || !usersC) usersC = await api.get('/api/crm/users'); return usersC; }
export async function pipelines(force) { if (force || !pipesC) pipesC = await api.get('/api/crm/pipelines'); return pipesC; }
export function resetCrmCache() { usersC = null; pipesC = null; }

export function currentUser() { try { return localStorage.getItem('gc-user') || ''; } catch (_) { return ''; } }
export function setCurrentUser(id) { try { localStorage.setItem('gc-user', id || ''); } catch (_) { /* */ } }

export const money = (v) => (v ? Math.round(+v).toLocaleString('ru-RU') + ' ₽' : '—');

export function dt(s, withTime = true) {
  if (!s) return '—';
  const d = new Date(s);
  if (Number.isNaN(+d)) return s;
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()}` + (withTime ? ` ${p(d.getHours())}:${p(d.getMinutes())}` : '');
}

export const localISO = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 16);

export function dueState(s) {
  if (!s) return 'none';
  const d = new Date(s), now = new Date();
  const today = localISO(now).slice(0, 10);
  if (s.slice(0, 10) < today || (s.length > 10 && d < now && s.slice(0, 10) === today)) return 'overdue';
  if (s.slice(0, 10) === today) return 'today';
  return 'later';
}

export function dueLabel(s) {
  if (!s) return 'без срока';
  const st = dueState(s);
  const d = s.slice(0, 10), now = new Date();
  const tomorrow = localISO(new Date(now.getTime() + 864e5)).slice(0, 10);
  const time = s.length > 10 ? ' ' + s.slice(11, 16) : '';
  if (st === 'today') return 'Сегодня' + time;
  if (d === tomorrow) return 'Завтра' + time;
  return dt(s, s.length > 10);
}

export function userDot(name, color) {
  return h('span.user-dot', { title: name || 'Без ответственного', style: { background: color || '#c3ccd4' } }, (name || '?').slice(0, 1).toUpperCase());
}

export function toLocalInput(s) { return s ? s.slice(0, 16) : ''; }

// Диалог задачи (создание/изменение)
export async function taskDialog({ task = null, deal_id = null, contact_id = null, due_at = null, onSaved }) {
  const [m, users] = await Promise.all([crmMeta(), crmUsers()]);
  const tomorrow = new Date(Date.now() + 864e5); tomorrow.setHours(10, 0, 0, 0);
  const local = localISO;
  const v = task ? { ...task } : { text: '', kind: 'call', due_at: due_at || local(tomorrow), responsible_id: currentUser() || null, deal_id, contact_id };
  const due = h('input', { type: 'datetime-local', value: toLocalInput(v.due_at) });
  const quick = h('div.row', [['Через час', 1 / 24], ['Сегодня 18:00', 'today'], ['Завтра', 1], ['Через 3 дня', 3], ['Через неделю', 7]].map(([l, d]) =>
    h('button.btn.sm', { type: 'button', onclick: () => {
      let x = new Date();
      if (d === 'today') x.setHours(18, 0, 0, 0); else { x = new Date(Date.now() + d * 864e5); if (d >= 1) x.setHours(10, 0, 0, 0); }
      due.value = local(x);
    } }, l)));
  modal(task ? 'Задача' : 'Новая задача', h('div.col',
    h('div.grid2', field('Тип', selectInput(Object.entries(m.task_kinds), v.kind, (x) => { v.kind = x; })),
      field('Ответственный', selectInput(users.map((u) => [u.id, u.name]), v.responsible_id, (x) => { v.responsible_id = x; }, { empty: '—' }))),
    field('Что сделать', textInput(v.text, (x) => { v.text = x; }, { placeholder: 'Позвонить и согласовать дату замера' })),
    field('Срок', due), quick), {
    actions: [{ label: 'Отмена' }, {
      label: 'Сохранить', primary: true, onClick: async () => {
        document.activeElement && document.activeElement.blur();
        if (!v.text.trim()) { toast('Опишите задачу', 'error'); return false; }
        const body = { text: v.text, kind: v.kind, due_at: due.value || null, responsible_id: v.responsible_id, deal_id: v.deal_id, contact_id: v.contact_id };
        const r = task ? await api.put('/api/crm/tasks/' + task.id, body) : await api.post('/api/crm/tasks', body);
        onSaved && onSaved(r);
      },
    }],
  });
}

export function completeTaskDialog(task, onDone) {
  const v = { result: '', next: '' };
  modal('Выполнить задачу', h('div.col', h('p', task.text),
    field('Результат', textInput('', (x) => { v.result = x; }, { placeholder: 'Договорились о замере в четверг' })),
    field('Следующая задача (необязательно)', textInput('', (x) => { v.next = x; }, { placeholder: 'Перезвонить после замера' }))), {
    actions: [{ label: 'Отмена' }, {
      label: 'Выполнено', primary: true, onClick: async () => {
        document.activeElement && document.activeElement.blur();
        const nextDue = new Date(Date.now() + 864e5); nextDue.setHours(10, 0, 0, 0);
        await api.post(`/api/crm/tasks/${task.id}/complete`, { result: v.result, next: v.next ? { text: v.next, kind: task.kind, due_at: localISO(nextDue) } : null });
        onDone && onDone();
      },
    }],
  });
}

export const KIND_ICON = { call: '📞', measure: '📐', meeting: '🤝', install: '🛠', email: '✉', other: '•' };
export const EVENT_ICON = { note: '📝', created: '✨', stage: '➜', task_done: '✔', message_in: '💬', message_out: '📤', call: '📞', email_in: '📨', email_out: '📧', system: '⚙', field: '✎' };
