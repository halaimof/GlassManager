import { api } from './api.js';
import { h, clear, field, textInput, toast } from './ui.js';
import { ordersPage, orderPage } from './orders.js';
import { constructorPage } from './constructor.js';
import { libraryPage } from './library.js';
import { hardwareEditor } from './hweditor.js';

const app = document.getElementById('app');
let cleanup = null;

async function route() {
  if (cleanup) { try { cleanup(); } catch (_) { /* */ } cleanup = null; }
  const hash = location.hash.replace(/^#\/?/, '') || 'orders';
  const [section, a, b] = hash.split('/');
  document.querySelectorAll('[data-nav]').forEach((el) => el.classList.toggle('active',
    el.dataset.nav === section || (el.dataset.nav === 'library' && section === 'hardware') ||
    (el.dataset.nav === 'orders' && (section === 'order' || section === 'product'))));
  clear(app);
  document.getElementById('save-state').textContent = '';
  try {
    if (section === 'orders') cleanup = await ordersPage(app);
    else if (section === 'order') cleanup = await orderPage(app, a);
    else if (section === 'product') cleanup = await constructorPage(app, a);
    else if (section === 'library') cleanup = await libraryPage(app, a || 'hardware', b);
    else if (section === 'hardware') cleanup = await hardwareEditor(app, a);
    else if (section === 'settings') cleanup = await settingsPage(app);
    else location.hash = '#/orders';
  } catch (e) {
    console.error(e);
    app.appendChild(h('div.page', h('div.msg.err', 'Ошибка: ' + e.message)));
  }
}

async function settingsPage(root) {
  const [st, ver, backups] = await Promise.all([api.get('/api/settings'), api.get('/api/version'), api.get('/api/backups')]);
  const c = st.company || {};
  const save = async (patch) => { await api.put('/api/settings', { company: patch }); toast('Сохранено', 'ok', 1200); };
  const logoBox = h('div.row');
  const renderLogo = (company) => {
    clear(logoBox,
      company.logo ? h('img', { src: '/api/settings/logo?ts=' + Date.now(), style: { maxHeight: '48px', maxWidth: '180px', border: '1px solid #dde3e8', padding: '4px', background: '#fff' } }) : h('span.muted', 'Логотип не загружен'),
      h('label.btn', 'Загрузить…', h('input', { type: 'file', accept: '.png,.jpg,.jpeg', style: { display: 'none' }, onchange: async (e) => {
        const fd = new FormData(); fd.append('file', e.target.files[0]);
        const r = await api.post('/api/settings/logo', fd); renderLogo(r.company);
      } })),
      company.logo ? h('button.btn.danger', { onclick: async () => { const r = await api.del('/api/settings/logo'); renderLogo(r.company); } }, 'Удалить') : null);
  };
  renderLogo(c);
  const f = (label, key, ph) => field(label, textInput(c[key], (v) => save({ [key]: v }), { placeholder: ph }));
  root.appendChild(h('div.page',
    h('div.page-head', h('h1', 'Настройки')),
    h('div.order-grid',
      h('div.card.card-pad.col',
        h('h2', 'Компания (шапка и подвал PDF)'),
        f('Название', 'name', 'ООО «Стекло»'), f('Подзаголовок', 'tagline', 'Душевые кабины и стеклянные конструкции'),
        f('Телефон', 'phone'), f('E-mail', 'email'), f('Адрес / сайт', 'address'),
        field('Логотип', logoBox)),
      h('div.card.card-pad.col',
        h('h2', 'Система'),
        h('div.readout', h('span', 'Версия приложения'), h('b', ver.version), h('span', 'Версия схемы БД'), h('b', String(ver.schema)),
          h('span', 'Папка данных'), h('b', ver.data_dir)),
        h('div.row', h('button.btn', { onclick: async () => { const r = await api.post('/api/backup'); toast('Копия создана: ' + r.file, 'ok'); route(); } }, 'Сделать резервную копию БД')),
        h('div.sec-title.muted.small', 'Резервные копии (последние)'),
        backups.length ? h('div.col', backups.slice(0, 12).map((b) => h('a', { href: '/api/backups/' + encodeURIComponent(b.name) }, `${b.name} · ${(b.size / 1024).toFixed(0)} КБ`)))
          : h('span.muted', 'Пока нет'),
        h('p.muted.small', 'Перед каждым обновлением и миграцией копия БД создаётся автоматически.')))));
}

window.addEventListener('hashchange', route);
api.get('/api/version', { silent: true }).then((v) => { document.getElementById('version').textContent = 'v' + v.version; }).catch(() => {});
route();
