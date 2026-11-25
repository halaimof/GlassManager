// Небольшие утилиты интерфейса: построение DOM, диалоги, формы, уведомления.

export function h(tag, attrs, ...children) {
  const m = /^([a-z0-9]+)?((?:[.#][\w-]+)*)$/i.exec(tag);
  const el = document.createElement((m && m[1]) || 'div');
  if (m && m[2]) {
    for (const part of m[2].match(/[.#][\w-]+/g)) {
      if (part[0] === '.') el.classList.add(part.slice(1)); else el.id = part.slice(1);
    }
  }
  if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs); attrs = null;
  }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked') el.checked = !!v;
    else if (k === 'html') el.innerHTML = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function clear(el, ...children) { el.innerHTML = ''; append(el, children); return el; }

export function uid() {
  let s = '';
  for (let i = 0; i < 32; i++) s += Math.floor(Math.random() * 16).toString(16);
  return s;
}

export function fmt(v, digits = 1) {
  if (v === null || v === undefined || v === '' || Number.isNaN(+v)) return '—';
  const r = Math.round(+v * 10 ** digits) / 10 ** digits;
  return (Math.abs(r - Math.round(r)) < 1e-9 ? String(Math.round(r)) : r.toFixed(digits)).replace('.', ',');
}

export function num(v) {
  if (v === '' || v === null || v === undefined) return null;
  const n = parseFloat(String(v).replace(',', '.').replace(/\s/g, ''));
  return Number.isFinite(n) ? n : null;
}

export function clone(o) { return JSON.parse(JSON.stringify(o)); }

// ---------------------------------------------------------------- уведомления
export function toast(msg, kind = 'info', ms = 3200) {
  const t = h('div.toast.' + kind, msg);
  document.getElementById('toasts').appendChild(t);
  setTimeout(() => t.classList.add('out'), ms);
  setTimeout(() => t.remove(), ms + 400);
}

// ---------------------------------------------------------------- модальные окна
const openModals = new Set();
export function closeAllModals() { for (const c of [...openModals]) c(); }

export function modal(title, body, { actions = [], wide = false, onClose } = {}) {
  const back = h('div.modal-back');
  const close = () => {
    if (!openModals.has(close)) return;
    openModals.delete(close);
    back.remove(); document.removeEventListener('keydown', onKey); onClose && onClose();
  };
  openModals.add(close);
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  const foot = h('div.modal-foot');
  for (const a of actions) {
    foot.appendChild(h('button.btn' + (a.primary ? '.primary' : '') + (a.danger ? '.danger' : ''), {
      onclick: async () => { const r = a.onClick ? await a.onClick() : true; if (r !== false) close(); },
    }, a.label));
  }
  const box = h('div.modal' + (wide ? '.wide' : ''),
    h('div.modal-head', h('h3', title), h('button.icon-btn', { onclick: close, title: 'Закрыть' }, '×')),
    h('div.modal-body', body), actions.length ? foot : null);
  back.appendChild(box);
  back.addEventListener('mousedown', (e) => { if (e.target === back) close(); });
  document.body.appendChild(back);
  const first = box.querySelector('input, select, textarea');
  if (first) setTimeout(() => first.focus(), 30);
  return { close, box };
}

export function confirmDlg(text, { danger = true, ok = 'Удалить' } = {}) {
  return new Promise((resolve) => {
    modal('Подтверждение', h('p', text), {
      onClose: () => resolve(false),
      actions: [
        { label: 'Отмена', onClick: () => resolve(false) },
        { label: ok, danger, primary: !danger, onClick: () => { resolve(true); } },
      ],
    });
  });
}

export function promptDlg(title, value = '', label = 'Название') {
  return new Promise((resolve) => {
    const inp = h('input', { value, type: 'text' });
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    const dlg = modal(title, field(label, inp), {
      onClose: () => finish(null),
      actions: [{ label: 'Отмена', onClick: () => finish(null) },
        { label: 'OK', primary: true, onClick: () => finish(inp.value.trim()) }],
    });
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { finish(inp.value.trim()); dlg.close(); } });
  });
}

// ---------------------------------------------------------------- формы
export function field(label, input, hint) {
  return h('label.field', h('span.field-label', label), input, hint ? h('span.hint', hint) : null);
}

export function numInput(value, onCommit, { placeholder = '', step = 'any', key, unit } = {}) {
  const inp = h('input.num', { type: 'text', inputmode: 'decimal', value: value ?? '', placeholder, 'data-key': key });
  const commit = () => {
    const raw = inp.value.trim();
    const v = raw === '' ? null : num(raw);
    if (raw !== '' && v === null) { inp.classList.add('bad'); return; }
    inp.classList.remove('bad');
    onCommit(v);
  };
  inp.addEventListener('change', commit);
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { inp.blur(); }
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      const cur = num(inp.value) ?? 0;
      const d = (e.shiftKey ? 10 : 1) * (e.key === 'ArrowUp' ? 1 : -1);
      inp.value = String(cur + d); e.preventDefault(); commit();
    }
  });
  void step;
  return unit ? h('span.with-unit', inp, h('span.unit', unit)) : inp;
}

export function textInput(value, onCommit, { placeholder = '', key } = {}) {
  const inp = h('input', { type: 'text', value: value ?? '', placeholder, 'data-key': key });
  inp.addEventListener('change', () => onCommit(inp.value));
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') inp.blur(); });
  return inp;
}

export function selectInput(options, value, onChange, { key, empty } = {}) {
  const sel = h('select', { 'data-key': key });
  if (empty !== undefined) sel.appendChild(h('option', { value: '' }, empty));
  for (const o of options) {
    const [v, label] = Array.isArray(o) ? o : [o.value ?? o.id ?? o.key, o.label ?? o.name];
    sel.appendChild(h('option', { value: v }, label));
  }
  sel.value = value ?? '';
  sel.addEventListener('change', () => onChange(sel.value === '' ? null : sel.value));
  return sel;
}

export function checkInput(value, onChange, label) {
  const inp = h('input', { type: 'checkbox', checked: !!value });
  inp.addEventListener('change', () => onChange(inp.checked));
  return h('label.check', inp, h('span', label));
}

export function segmented(options, value, onChange) {
  const wrap = h('div.segmented');
  for (const [v, label] of options) {
    wrap.appendChild(h('button' + (v === value ? '.on' : ''), {
      type: 'button',
      onclick: () => { onChange(v); },
    }, label));
  }
  return wrap;
}

// Одно открытое меню на страницу; позиционируется поверх (fixed), поэтому не обрезается
// прокручиваемыми таблицами. Один общий обработчик закрытия — без утечек при перерисовке.
let openMenu = null;
function closeMenu() { if (openMenu) { openMenu.classList.remove('open'); openMenu = null; } }
document.addEventListener('click', closeMenu);
window.addEventListener('resize', closeMenu);
window.addEventListener('scroll', (e) => { if (openMenu && !openMenu.contains(e.target)) closeMenu(); }, true);

export function menuButton(label, items, cls = '') {
  const wrap = h('div.menu-wrap');
  const menu = h('div.menu');
  for (const it of items) {
    if (it === '-') { menu.appendChild(h('div.menu-sep')); continue; }
    menu.appendChild(h('button', { onclick: (e) => { e.stopPropagation(); closeMenu(); it.onClick(); } }, it.label));
  }
  const btn = h('button.btn' + cls, {
    type: 'button',
    onclick: (e) => {
      e.stopPropagation();
      const was = openMenu === wrap;
      closeMenu();
      if (was) return;
      wrap.classList.add('open');
      openMenu = wrap;
      const r = btn.getBoundingClientRect();
      const mw = menu.offsetWidth, mh = menu.offsetHeight;
      const left = Math.max(8, Math.min(r.right - mw, window.innerWidth - mw - 8));
      let top = r.bottom + 4;
      if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 4);
      Object.assign(menu.style, { position: 'fixed', left: left + 'px', top: top + 'px', right: 'auto' });
    },
  }, label, ' ▾');
  wrap.append(btn, menu);
  return wrap;
}

export function emptyState(text, action) {
  return h('div.empty', h('p', text), action || null);
}
