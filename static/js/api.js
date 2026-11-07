import { toast } from './ui.js';

async function request(method, url, body, { silent = false } = {}) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  let res;
  try { res = await fetch(url, opts); } catch (e) {
    if (!silent) toast('Нет связи с сервером', 'error');
    throw e;
  }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch (_) { /* */ }
    if (!silent) toast(msg, 'error', 5000);
    throw new Error(msg);
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('json') ? res.json() : res;
}

export const api = {
  get: (u, o) => request('GET', u, undefined, o),
  post: (u, b, o) => request('POST', u, b ?? {}, o),
  put: (u, b, o) => request('PUT', u, b, o),
  del: (u, o) => request('DELETE', u, undefined, o),
};

let metaCache = null;
export async function meta() {
  if (!metaCache) metaCache = await api.get('/api/meta');
  return metaCache;
}

// Кэш библиотеки на время сессии страницы; сбрасывается при изменениях.
const libCache = {};
export async function lib(coll, force = false) {
  if (force || !libCache[coll]) libCache[coll] = await api.get('/api/lib/' + coll);
  return libCache[coll];
}
export function invalidateLib(coll) { if (coll) delete libCache[coll]; else for (const k of Object.keys(libCache)) delete libCache[k]; }

export function download(url) {
  const a = document.createElement('a');
  a.href = url; a.target = '_blank'; a.rel = 'noopener';
  document.body.appendChild(a); a.click(); a.remove();
}
