'use strict';
/* Asienta — web interface. No libraries, no build step.
   Everything that comes from an invoice is rendered as text (textContent), never as HTML. */

// ============================================================ helpers
const $ = (s, el = document) => el.querySelector(s);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k in el && typeof el[k] !== 'function' && !['list', 'form'].includes(k)) el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}

function put(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter(c => c != null && c !== false));
}

function icon(d) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', d);
  s.append(p);
  return s;
}

// ------------------------------------------------------------ language
let LANG = (() => { try { return localStorage.getItem('asienta.lang'); } catch (e) { return null; } })();
function t(key, vars = {}) {
  const dict = I18N[LANG] || I18N.es;
  const s = dict[key] ?? I18N.es[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? `{${k}}`));
}
function setLang(l) {
  LANG = l;
  try { localStorage.setItem('asienta.lang', l); } catch (e) { /* private mode */ }
  document.documentElement.lang = l;
  E.accounts = null;
  go();
}

async function api(url, opts = {}) {
  const headers = {'X-Asienta': '1', 'X-Lang': LANG || '', ...(opts.headers || {})};
  if (opts.body && !(opts.body instanceof Blob)) headers['Content-Type'] = 'application/json';
  const r = await fetch(url, {...opts, headers});
  const d = await r.json().catch(() => ({}));
  if (r.status === 401) { showLogin(); throw new Error(t('login.wrong')); }
  if (!r.ok && !d.errors) throw new Error(d.error || `error ${r.status}`);
  return d;
}
const post = (url, body) => api(url, {method: 'POST', body: JSON.stringify(body || {})});

// ------------------------------------------------------------ formatting
function num2(v, forInput) {
  v = Number(v) || 0;
  const es = LANG !== 'en';
  let [i, d] = Math.abs(v).toFixed(2).split('.');
  i = i.replace(/\B(?=(\d{3})+(?!\d))/g, es ? '.' : ',');
  return (v < 0 ? (forInput ? '-' : '−') : '') + i + (es ? ',' : '.') + d;
}
const money = v => LANG === 'en' ? (Number(v) < 0 ? '−€' + num2(Math.abs(v)) : '€' + num2(v)) : num2(v) + ' €';
const pct = v => LANG === 'en' ? `${Number(v) || 0}%` : String(Number(v) || 0).replace('.', ',') + ' %';
const costTxt = c => (Number(c) || 0) < 0.001 ? '< $0.001' : '$' + Number(c).toFixed(3);

function readNum(s) {
  s = String(s ?? '').trim().replace(/[€$\s%]/g, '').replace('−', '-');
  if (!s) return 0;
  if (/^-?\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, '');
  else if (s.includes(',') && s.includes('.'))
    s = s.lastIndexOf(',') > s.lastIndexOf('.') ? s.replace(/\./g, '').replace(',', '.') : s.replace(/,/g, '');
  else if (s.includes(',')) s = s.replace(',', '.');
  const n = parseFloat(s);
  return isNaN(n) ? 0 : Math.round(n * 100) / 100;
}

function dmy(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  if (!m) return '—';
  if (LANG === 'en') return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString('en-GB', {day: 'numeric', month: 'short', year: 'numeric'});
  return `${m[3]}/${m[2]}/${m[1]}`;
}

const SMALL = new Set(['de', 'del', 'la', 'las', 'los', 'y', 'e', 'el', 'a', 'en', 'con', 'por']);
function nice(s) {
  return String(s || '').toLowerCase().split(/\s+/).filter(Boolean).map((p, i) =>
    i && SMALL.has(p) ? p : /^(s\.?l\.?[up]?\.?|s\.?a\.?u?\.?|c\.?b\.?)[,.]?$/.test(p) ? p.toUpperCase() : p[0].toUpperCase() + p.slice(1)
  ).join(' ');
}

let toastTimer;
function toast(text, kind = '') {
  const el = $('#toast');
  el.textContent = text;
  el.className = kind;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), kind === 'bad' ? 7000 : 3500);
}

// ============================================================ state and chrome
const E = {mail: {filter: 'all', offset: 0, emails: [], more: false, counts: {}, help: false},
           state: null, view: 'review', list: [], f: null, accounts: null, dirty: false, format: null};
const main = $('#main');

const NAV = [
  ['review', 'M4 5h16v12H4zM4 13h4l2 3h4l2-3h4'],
  ['approved', 'M20 6 9 17l-5-5'],
  ['exported', 'M12 3v12M7 10l5 5 5-5M5 21h14'],
  ['discarded', 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3'],
  ['mailbox', 'M4 6h16v12H4zM4 7l8 6 8-6'],
];

function applyBrand(b) {
  const root = document.documentElement.style;
  root.setProperty('--accent', b.accent);
  document.title = b.name;
  $('#favicon').href = b.has_logo ? '/logo' : '/favicon.svg';
}

function paintSidebar() {
  const s = E.state;
  const L = s.ledger;
  const ledgerTxt = L.kind === 'demo' ? t('side.ledger.demo')
    : L.error ? t('side.ledger.down') : t('side.ledger.ok');
  const ago = L.minutes_ago != null && L.kind !== 'demo' ? ` · ${t('side.ago', {n: L.minutes_ago})}` : '';
  const items = NAV.filter(([k]) => k !== 'mailbox' || s.mailbox);
  put($('#side'),
    h('a', {class: 'brand', href: '#/review'},
      h('img', {src: '/logo', alt: ''}),
      h('div', {}, h('b', {}, s.brand.name), s.brand.tagline ? h('small', {}, s.brand.tagline) : null)),
    s.reader.demo ? h('div', {class: 'demo-pill'}, h('i'), t('side.demo')) : null,
    h('nav', {}, items.map(([k, d]) => {
      const n = k === 'mailbox' ? s.set_aside : k === 'discarded' ? 0 : s.views[k];
      return h('a', {class: 'nav' + (E.view === k && !E.f ? ' on' : ''), href: `#/${k}`},
        icon(d), h('span', {}, t('nav.' + k)), n ? h('span', {class: 'count' + (k === 'review' ? ' hot' : '')}, n) : null);
    })),
    h('div', {class: 'status'},
      h('div', {class: 'row'}, h('span', {class: 'dot' + (L.kind === 'demo' ? ' demo' : L.error ? ' bad' : '')}), ledgerTxt + ago),
      h('div', {class: 'row'}, t('side.reader', {name: s.reader.demo ? t('reader.demo') : s.reader.name})),
      h('div', {class: 'row'}, t('side.vat', {q: s.vat_filed_until})),
      h('div', {class: 'row'}, t('side.month', {n: s.month.invoices, cost: Number(s.month.cost_usd).toFixed(2)})),
      h('div', {class: 'lang'}, ['es', 'en'].map(l => h('button', {class: l === LANG ? 'on' : '', onclick: () => setLang(l)}, l.toUpperCase())))));
}

async function loadState() {
  E.state = await api('/api/state');
  if (!LANG) LANG = E.state.language;
  document.documentElement.lang = LANG;
  applyBrand(E.state.brand);
  if (!E.format) E.format = E.state.format;
  paintSidebar();
}

// ============================================================ routing
const VIEWS = ['review', 'approved', 'exported', 'discarded', 'mailbox'];

async function go() {
  if (E.dirty && E.f) await saveNow();
  const r = location.hash.replace(/^#\/?/, '').split('/');
  if (r.join('/') !== E.route) window.scrollTo(0, 0);
  E.route = r.join('/');
  clearTimeout(pollTimer);
  clearTimeout(liveTimer);
  try {
    if (r[0] === 'invoice' && /^\d+$/.test(r[1] || '')) {
      await loadState();
      return await invoiceView(+r[1]);
    }
    E.view = VIEWS.includes(r[0]) ? r[0] : 'review';
    E.f = null;
    await loadState();
    await listView();
  } catch (e) {
    if (!$('#login')) put(main, h('div', {class: 'banner bad'}, t('load_failed', {e: e.message})));
  }
}
window.addEventListener('hashchange', go);

let pollTimer;
function poll(fn, ms = 2500) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(fn, ms);
}

// ============================================================ lists
async function listView() {
  const v = E.view;
  E.list = ['mailbox'].includes(v) ? [] : await api(`/api/invoices?view=${v}`);
  const batches = v === 'exported' ? await api('/api/batches') : [];
  if (v === 'mailbox') await loadMail(true);
  const s = E.state;
  put(main,
    h('header', {class: 'head'}, h('div', {}, h('h1', {}, t('title.' + v)), h('p', {class: 'sub'}, t('sub.' + v)))),
    !s.reader.ready ? h('div', {class: 'banner bad'}, t('banner.nokey')) : null,
    s.ledger.error && s.ledger.kind !== 'demo' ? h('div', {class: 'banner warn'}, t('banner.ledger')) : null,
    s.mailbox_error ? h('div', {class: 'banner warn'}, t('banner.mailbox', {e: s.mailbox_error})) : null,
    v === 'review' ? dropZone() : null,
    v === 'approved' && E.list.length ? exportBar() : null,
    v === 'exported' ? lastBatch() : null,
    v === 'exported' && batches.length ? batchList(batches) : null,
    v === 'mailbox' ? mailList()
      : (E.list.length ? invoiceTable() : h('div', {class: 'empty'}, h('p', {}, t('empty.' + v)))));
  const busy = v === 'mailbox' ? E.mail.emails.some(m => m.invoices.some(f => f.status === 'reading'))
                                : E.list.some(f => f.status === 'reading');
  if (busy) poll(async () => { await loadState(); await listView(); }, 1500);
}

function dropZone() {
  const pick = h('input', {type: 'file', accept: 'application/pdf,image/*', multiple: true, hidden: true,
                           onchange: e => upload([...e.target.files])});
  const camera = h('input', {type: 'file', accept: 'image/*', capture: 'environment', hidden: true,
                             onchange: e => upload([...e.target.files])});
  const s = E.state;
  const zone = h('div', {class: 'drop'},
    h('div', {class: 'drop-icon'}, icon('M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3')),
    h('div', {class: 'drop-text'}, h('b', {}, t('drop.title')),
      h('span', {}, t('drop.text'), ' ', s.mailbox ? t('drop.mail', {addr: s.mailbox}) : s.reader.demo ? t('drop.demo') : '')),
    h('div', {class: 'drop-actions'},
      s.reader.demo ? h('button', {class: 'btn', id: 'load-samples', onclick: loadSamples}, t('drop.samples')) : null,
      h('button', {class: 'btn primary', onclick: () => pick.click()}, t('drop.upload')),
      h('button', {class: 'btn mobile-only', onclick: () => camera.click()}, t('drop.photo'))),
    pick, camera);
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('over'); upload([...e.dataTransfer.files]); });
  return zone;
}

async function loadSamples(e) {
  e.currentTarget.disabled = true;
  try {
    const r = await post('/api/demo/samples');
    toast(t('up.new', {n: r.added}));
  } catch (err) { toast(err.message, 'bad'); }
  go();
}

async function upload(files) {
  if (!files.length) return;
  let fresh = 0, known = 0, done = 0, last = null;
  const bad = [], queue = [...files];
  toast(t('up.uploading', {n: files.length}));
  async function worker() {
    while (queue.length) {
      const f = queue.shift();
      try {
        const r = await api('/api/upload', {method: 'POST', body: f,
          headers: {'X-Filename': encodeURIComponent(f.name), 'Content-Type': 'application/octet-stream'}});
        r.known ? known++ : fresh++;
        last = r;
      } catch (e) { bad.push(`${f.name}: ${e.message}`); }
      done++;
      if (files.length > 1) toast(t('up.progress', {i: done, n: files.length}));
    }
  }
  await Promise.all([worker(), worker(), worker()]);
  if (files.length === 1 && last) {            // just one: open it and watch it being read
    toast(last.known ? t('up.known') : t('up.done'));
    location.hash = `#/invoice/${last.id}`;
    return;
  }
  const parts = [];
  if (fresh) parts.push(t('up.new', {n: fresh}));
  if (known) parts.push(t('up.repeated', {n: known}));
  toast(parts.concat(bad).join(' · '), bad.length ? 'bad' : '');
  if (location.hash !== '#/review') location.hash = '#/review';
  else go();
}

function statusChip(f) {
  if (f.status === 'reading') return h('span', {class: 'chip muted'}, h('i', {class: 'spin'}), t('st.reading'));
  if (f.status === 'waiting') return h('span', {class: 'chip warn'}, t('st.waiting'));
  if (f.status === 'error') return h('span', {class: 'chip bad'}, t('st.error'));
  if (f.errors) return h('span', {class: 'chip bad'}, t('st.errors', {n: f.errors}));
  if (f.warnings) return h('span', {class: 'chip warn'}, f.warnings === 1 ? t('st.warning') : t('st.warnings', {n: f.warnings}));
  if (f.status === 'review') return h('span', {class: 'chip good'}, t('st.ok'));
  if (f.status === 'approved') return h('span', {class: 'chip good'}, t('st.approved'));
  if (f.status === 'exported') return h('span', {class: 'chip muted'}, t('st.exported', {n: f.batch}));
  if (f.status === 'posted') return h('span', {class: 'chip good'}, t('st.posted'));
  return h('span', {class: 'chip muted'}, t('st.' + f.status));
}

function invoiceTable() {
  return h('div', {class: 'card table-card'}, h('table', {class: 'list'},
    h('thead', {}, h('tr', {}, h('th', {}, t('col.supplier')), h('th', {class: 'c-num'}, t('col.number')),
      h('th', {class: 'c-date'}, t('col.date')), h('th', {class: 'num'}, t('col.total')), h('th', {}, t('col.status')))),
    h('tbody', {}, E.list.map(f => h('tr', {class: 'click' + (f.status === 'reading' ? ' reading' : ''),
      onclick: () => (location.hash = `#/invoice/${f.id}`)},
      h('td', {}, h('b', {}, f.supplier ? nice(f.supplier) : f.filename),
        f.source === 'email' || f.source === 'folder' ? h('small', {}, ` · ${t('by_' + f.source)}`) : null),
      h('td', {class: 'c-num mono'}, f.number || '—'),
      h('td', {class: 'c-date'}, dmy(f.date)),
      h('td', {class: 'num'}, f.total ? money(f.total) : '—'),
      h('td', {}, statusChip(f)))))));
}

function exportBar() {
  const total = E.list.reduce((s, f) => s + (f.total || 0), 0);
  const n = E.list.length;
  const ex = E.state.exporters;
  return h('div', {class: 'card export'},
    h('div', {class: 'export-text'},
      h('b', {}, n === 1 ? t('export.one', {total: money(total)}) : t('export.count', {n, total: money(total)})),
      h('p', {}, t('help.' + E.format) )),
    h('button', {class: 'btn primary', onclick: doExport}, t('export.go')),
    h('div', {class: 'formats'}, h('span', {class: 'formats-label'}, t('export.to')),
      ex.map(x => h('button', {class: 'format' + (x.key === E.format ? ' on' : ''), 'data-format': x.key,
                               title: x.maturity === 'beta' ? t('export.beta') : null,
                               onclick: () => { E.format = x.key; listView(); }},
        x.label, x.maturity === 'beta' ? h('sup', {}, t('export.beta')) : null))));
}

async function doExport(e) {
  e.currentTarget.disabled = true;
  try {
    const r = await post('/api/batches', {format: E.format});
    if (r.warnings && r.warnings.length) alert(`${t('export.warn', {n: r.batch})}\n\n• ${r.warnings.join('\n• ')}`);
    else toast(t('export.done', {n: r.batch}));
    setTimeout(() => (location.hash = '#/exported'), 300);
  } catch (err) { toast(err.message, 'bad'); e.currentTarget.disabled = false; }
}

function lastBatch() {
  const b = E.state.last_batch;
  if (!b) return null;
  const done = b.posted >= b.invoices;
  return h('div', {class: 'card batch-hero' + (done ? ' done' : '')},
    h('div', {class: 'batch-icon'}, icon(done ? 'M20 6 9 17l-5-5' : 'M12 3v12M7 10l5 5 5-5M5 21h14')),
    h('div', {class: 'batch-text'},
      h('b', {}, t('batch.title', {n: b.id}), h('span', {class: 'fmt'}, b.format)),
      h('span', {}, `${b.invoices} · ${money(b.total)} · ${dmy(b.created)} ${b.created.slice(11, 16)}`),
      h('span', {class: 'batch-state'}, done ? t('batch.all') : b.posted ? t('batch.some', {a: b.posted, b: b.invoices}) : t('batch.pending')),
      E.state.drop_path ? h('code', {}, t('batch.drop', {path: E.state.drop_path})) : null,
      E.batchHelp ? h('p', {class: 'help'}, t('help.' + b.format)) : null),
    h('div', {class: 'batch-actions'},
      h('a', {class: 'btn' + (done ? '' : ' primary'), href: '/api/batches/latest/file'}, t('batch.download')),
      h('button', {class: 'btn icon-btn', title: t('batch.help'), onclick: () => { E.batchHelp = !E.batchHelp; listView(); }}, '?')));
}

function batchList(batches) {
  return h('div', {class: 'card batches'}, h('h3', {}, t('batch.list')),
    batches.map(b => h('div', {class: 'batch' + (b.undone ? ' undone' : '')},
      h('div', {class: 'batch-text'}, h('b', {}, t('batch.title', {n: b.id})), h('span', {class: 'fmt'}, b.format),
        h('small', {}, ` ${b.invoices} · ${money(b.total)} · ${dmy(b.created)} ${b.created.slice(11, 16)}`,
          b.undone ? ` · ${t('batch.undone')}` : b.posted ? ` · ${t('batch.some', {a: b.posted, b: b.invoices})}` : ` · ${t('batch.pending')}`)),
      b.undone ? null : h('a', {class: 'btn small', href: `/api/batches/${b.id}/file`}, t('batch.download')),
      b.undone ? null : h('a', {class: 'btn small', href: `/api/batches/${b.id}/pdfs`, title: t('batch.pdfs.hint')}, t('batch.pdfs')),
      b.undone || b.posted >= b.invoices ? null : h('button', {class: 'btn small', onclick: async () => {
        if (!confirm(t('batch.undo.confirm', {n: b.id}))) return;
        const r = await post(`/api/batches/${b.id}/undo`);
        toast(t('batch.undo.done', {n: r.invoices}));
        go();
      }}, t('batch.undo')))));
}

// ------------------------------------------------------------ mailbox
async function loadMail(fromStart) {
  const M = E.mail;
  if (fromStart) { M.offset = 0; M.emails = []; }
  const r = await api(`/api/mailbox?filter=${M.filter}&offset=${M.offset}`);
  M.emails = M.offset ? M.emails.concat(r.emails) : r.emails;
  M.more = r.more;
  M.counts = r.counts;
}

function mailList() {
  const M = E.mail;
  const refresh = async () => { await loadState(); await loadMail(true); await listView(); };
  return h('div', {class: 'mail'},
    h('div', {class: 'tabs'}, [['all', 'mb.all'], ['set_aside', 'mb.set_aside'], ['none', 'mb.none']].map(([k, key]) =>
      h('button', {class: 'tab' + (k === M.filter ? ' on' : ''), onclick: async () => { M.filter = k; await refresh(); }},
        t(key), M.counts[k] ? h('span', {class: 'count'}, M.counts[k]) : null)),
      h('button', {class: 'tab help-btn', onclick: () => { M.help = !M.help; listView(); }}, M.help ? '×' : '?'),
      E.state.reader.demo ? h('button', {class: 'btn small push-right', id: 'test-email', onclick: async e => {
        e.currentTarget.disabled = true;
        await post('/api/demo/email');
        await refresh();
      }}, t('mb.test')) : null),
    M.help ? h('p', {class: 'help'}, t('mb.help', {addr: E.state.mailbox})) : null,
    !M.emails.length ? h('div', {class: 'empty'}, h('p', {}, t('empty.mailbox'))) : null,
    M.emails.map(m => h('div', {class: 'card email'},
      h('b', {}, m.subject || t('mb.no_subject')),
      h('div', {class: 'from'}, `${dmy(m.received)} ${m.received.slice(11, 16)} · ${m.sender}`),
      !m.invoices.length && !m.set_aside.length ? h('div', {class: 'muted'}, t('mb.no_attach')) : null,
      m.invoices.map(f => h('a', {class: 'brought', href: `#/invoice/${f.id}`},
        h('span', {class: 'what'}, [f.supplier ? nice(f.supplier) : f.filename, f.number].filter(Boolean).join(' · ')),
        f.total ? h('span', {class: 'num'}, money(f.total)) : null, statusChip(f))),
      m.set_aside.map(a => h('div', {class: 'brought aside'},
        h('a', {class: 'what', href: `/api/set_aside/${a.id}/file`, target: '_blank'}, a.filename),
        h('span', {class: 'reason'}, a.reason),
        a.invoice ? h('a', {class: 'chip muted', href: `#/invoice/${a.invoice}`}, t('mb.taken', {n: a.invoice}))
          : a.dismissed ? h('span', {class: 'chip muted'}, t('mb.dismissed'))
          : [h('button', {class: 'btn small', onclick: async e => {
              e.currentTarget.disabled = true;
              const r = await post(`/api/set_aside/${a.id}/take`);
              toast(r.known ? t('mb.known') : t('mb.taken.toast'));
              await refresh();
            }}, t('mb.take')),
            h('button', {class: 'btn small', onclick: async e => {
              e.currentTarget.disabled = true;
              await post(`/api/set_aside/${a.id}/dismiss`);
              await refresh();
            }}, t('mb.dismiss'))])))),
    M.more ? h('button', {class: 'btn', onclick: async e => {
      e.currentTarget.disabled = true; M.offset += 20; await loadMail(false); await listView();
    }}, t('mb.more')) : null);
}

// ============================================================ one invoice
async function invoiceView(id) {
  const f = await api(`/api/invoices/${id}?view=${E.view}`);
  if (!E.accounts) E.accounts = await api('/api/accounts');
  E.f = f;
  E.dirty = false;
  paintSidebar();
  put(main,
    h('div', {class: 'detail-head', id: 'dhead'}),
    h('div', {class: 'detail'}, viewer(f), h('div', {class: 'form', id: 'form'})),
    h('div', {class: 'actionbar', id: 'actions'}));
  paintHead();
  paintForm();
  if (f.status === 'reading') followReading(id);
}

function paintHead() {
  if (!$('#dhead')) return;
  const f = E.f, d = f.data;
  const title = d ? nice(f.supplier_ledger ? f.supplier_ledger.name : d.supplier_name) || '—' : f.filename;
  put($('#dhead'),
    h('a', {class: 'back', href: `#/${E.view}`}, t('back')),
    h('h1', {}, title, d && d.invoice_number ? h('span', {class: 'muted'}, ` · ${d.invoice_number}`) : null),
    h('span', {class: 'chip ' + ({approved: 'good', posted: 'good', error: 'bad', review: 'warn'}[f.status] || 'muted')},
      f.status === 'exported' ? t('st.exported', {n: f.batch}) : t('st.' + f.status)),
    h('div', {class: 'pager'},
      h('button', {class: 'btn small', disabled: !f.previous, onclick: () => (location.hash = `#/invoice/${f.previous}`)}, t('prev')),
      h('button', {class: 'btn small', disabled: !f.next, onclick: () => (location.hash = `#/invoice/${f.next}`)}, t('next'))));
}

function viewer(f) {
  const url = `/api/invoices/${f.id}/file`;
  let view;
  if (f.mime === 'application/pdf' && matchMedia('(max-width: 900px)').matches)
    return h('div', {class: 'viewer short'}, h('a', {class: 'btn', href: url, target: '_blank', rel: 'noopener'}, t('view_pdf')));
  if (f.mime === 'application/pdf')      // a PDF with several invoices opens on this one's page
    view = h('iframe', {src: `${url}#page=${f.page || 1}&view=FitH&navpanes=0&toolbar=0`, title: 'invoice'});
  else {
    view = h('img', {src: url, alt: ''});
    view.addEventListener('error', () => view.replaceWith(h('div', {class: 'no-preview'}, t('no_preview'))));
  }
  return h('div', {class: 'viewer'}, view, f.status === 'reading' ? scanner() : null,
    h('a', {class: 'open', href: url, target: '_blank', rel: 'noopener'}, t('open_tab')));
}

// ------------------------------------------------------------ live reading
/* While the AI reads, the document gets "scanned" and the form waits with placeholders. When the
   reading arrives they fill with what was REALLY read, and each check shows its real result
   (the findings, grouped). Then it moves on to the form. */
let liveTimer;
const calm = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const LIVE_FIELDS = [['supplier', 70], ['tax_id', 55], ['number', 45], ['date', 50], ['lines', 25],
                     ['base', 50], ['vat', 40], ['total', 35]];
const STEPS = ['document', 'supplier', 'dates', 'amounts', 'split', 'duplicates', 'reading'];
const ALWAYS = new Set(['supplier', 'dates', 'amounts', 'split', 'duplicates']);
const SPARK = 'M12 3Q13 11 21 12Q13 13 12 21Q11 13 3 12Q11 11 12 3Z';
const CHECK = 'M5 12.5l4.2 4.2L19 7';
const secs = s => (Number(s) || 0).toFixed(1).replace('.', LANG === 'en' ? '.' : ',') + ' s';

function scanner() {
  return h('div', {class: 'scanner', id: 'scanner', 'aria-hidden': 'true'},
    h('i', {class: 'beam'}), ['a', 'b', 'c', 'd'].map(k => h('i', {class: 'corner ' + k})));
}

const stepEl = (title, text = '') =>
  h('div', {class: 'step'}, h('span', {class: 'si'}), h('div', {class: 'sc'}, h('b', {}, title), h('span', {class: 'st'}, text)));

function liveCard() {
  const reader = E.state.reader;
  return h('div', {class: 'live', id: 'live', 'aria-live': 'polite'},
    h('div', {class: 'live-head'},
      h('div', {class: 'orb'}, h('i', {class: 'ring'}), icon(SPARK)),
      h('div', {class: 'live-title'}, h('b', {id: 'live-title'}, t('live.reading')),
        h('small', {id: 'live-sub'}, t('live.usually', {model: reader.demo ? t('reader.demo') : reader.name}))),
      h('div', {class: 'live-clock', id: 'live-clock'}, secs(0))),
    h('div', {class: 'live-fields'}, LIVE_FIELDS.map(([k, w], i) =>
      h('div', {class: 'live-field'}, h('span', {class: 'k'}, t('live.f.' + k)),
        h('span', {class: 'v', id: 'lv' + i}, h('i', {class: 'bone', style: `--w:${w}%`}))))),
    h('div', {class: 'steps', id: 'steps'}, STEPS.filter(g => ALWAYS.has(g)).map(g => stepEl(t('step.' + g)))),
    h('div', {class: 'live-foot', id: 'live-foot'}));
}

function followReading(id) {
  clearTimeout(liveTimer);
  const clock = $('#live-clock');
  if (!clock) return;
  const start = performance.now();
  const tick = setInterval(() => {
    if (!clock.isConnected) return clearInterval(tick);
    clock.textContent = secs((performance.now() - start) / 1000);
  }, 100);
  const look = async () => {
    const f = clock.isConnected ? await api(`/api/invoices/${id}?view=${E.view}`).catch(() => null) : null;
    if (!clock.isConnected) return clearInterval(tick);
    if (!f || f.status === 'reading') { liveTimer = setTimeout(look, 700); return; }
    clearInterval(tick);
    reveal(f);
  };
  liveTimer = setTimeout(look, 700);
}

function stepResults(f) {
  const found = f.findings || [], e = f.entry, d = f.data, sup = f.supplier_ledger;
  const accounts = [...new Set(e.split.map(r => r.account).filter(Boolean))];
  const good = {
    supplier: sup ? [nice(sup.name), sup.account, e.supplier_match ? t('match.' + e.supplier_match) : ''].filter(Boolean).join(' · ') : '',
    dates: t('ok.dates', {n: d.invoice_number, d: dmy(e.posting_date)}),
    amounts: t('ok.amounts', {total: money(d.total)}),
    split: accounts.map(c => `${c} ${nice(f.names?.[c] || '')}`.trim()).join(' + '),
    duplicates: t('ok.duplicates'),
  };
  return STEPS.map(g => {
    const m = found.find(x => x.group === g && x.level === 'error') || found.find(x => x.group === g && x.level === 'warning');
    if (m) return {title: t('step.' + g), level: m.level, text: m.text};
    return ALWAYS.has(g) ? {title: t('step.' + g), level: 'ok', text: good[g]} : null;
  }).filter(Boolean);
}

function typeIn(el, txt) {
  if (calm()) return (el.textContent = txt);
  let i = 0;
  const n = Math.max(1, Math.ceil(txt.length / 14));
  const tm = setInterval(() => { i += n; el.textContent = txt.slice(0, i); if (i >= txt.length) clearInterval(tm); }, 22);
}

function countUp(el, v, fmt) {
  if (calm()) return (el.textContent = fmt(v));
  const t0 = performance.now();
  const step = now => {
    const k = Math.min(1, (now - t0) / 550);
    el.textContent = fmt(v * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

async function reveal(f) {
  const card = $('#live');
  if (!card) return;
  const wait = ms => new Promise(r => setTimeout(r, calm() ? 0 : ms));
  E.f = f;
  paintHead();
  const sc = $('#scanner');
  if (sc) { sc.classList.add('done'); setTimeout(() => sc.remove(), 1000); }
  put($('.orb', card), icon(f.data ? CHECK : 'M12 7v6M12 17h.01'));
  card.classList.add('read');
  if (f.seconds) $('#live-clock').textContent = secs(f.seconds);
  if (!f.data) {
    card.classList.add('failed');
    $('#live-title').textContent = t('live.failed');
    $('#live-sub').textContent = f.error || '';
    await wait(1500);
    return card.isConnected && finishReading();
  }
  $('#live-title').textContent = t('live.read');
  $('#live-sub').textContent = `${f.model === 'demo' ? t('reader.demo') : f.model_name} · ${costTxt(f.cost)}`;
  const d = f.data, vat = d.vat_breakdown || [];
  const values = [
    [nice(d.supplier_name) || '—'], [d.supplier_tax_id || '—'], [d.invoice_number || '—'], [dmy(d.invoice_date)],
    [(d.lines || []).length, x => String(Math.round(x))],
    [vat.reduce((s, x) => s + x.base, 0), money], [vat.reduce((s, x) => s + x.vat, 0), money, vat.map(x => pct(x.vat_rate)).join(' + ')],
    [d.total, money, d.doc_type === 'credit_note' ? t('live.credit') : null]];
  for (const [i, [v, fmt, extra]] of values.entries()) {
    if (!card.isConnected) return;
    const slot = $('#lv' + i), val = h('span', {class: 'val'});
    put(slot, val, extra ? h('small', {}, extra) : null);
    slot.classList.add('new');
    fmt ? countUp(val, Number(v) || 0, fmt) : typeIn(val, String(v));
    await wait(130);
  }
  await wait(250);
  const steps = stepResults(f);
  const els = steps.map(s => stepEl(s.title, s.text));
  put($('#steps'), els);
  for (const [i, s] of steps.entries()) {
    if (!card.isConnected) return;
    els[i].classList.add('busy');
    await wait(300);
    els[i].classList.replace('busy', {ok: 'ok', error: 'bad'}[s.level] || 'warn');
    put($('.si', els[i]), s.level === 'ok' ? icon(CHECK) : '!');
    await wait(90);
  }
  await wait(200);
  if (!card.isConnected) return;
  const bad = steps.filter(s => s.level === 'error').length, warn = steps.filter(s => s.level === 'warning').length;
  put($('#live-foot'),
    h('span', {class: 'result ' + (bad ? 'bad' : warn ? 'warn' : 'good')},
      bad ? t('res.errors', {n: bad}) : warn ? t('res.warnings', {n: warn}) : t('res.ok')),
    h('button', {class: 'btn primary go-on', onclick: finishReading}, t('live.review'),
      h('i', {class: 'countdown', onanimationend: finishReading})));
  card.classList.add('ready');
}

function finishReading() {
  if (!$('#live') || !E.f || E.f.status === 'reading') return;
  $('#scanner')?.remove();
  paintHead();
  paintForm();
  $('#form')?.classList.add('appear');
}

const editable = () => E.f && E.f.data && ['review', 'approved'].includes(E.f.status);

function paintForm() {
  const f = E.f;
  const form = $('#form');
  if (!form) return;
  if (f.status === 'reading') put(form, liveCard());
  else if (!f.data) put(form, h('div', {class: 'finding error'}, h('span', {class: 'fi'}, '!'),
    h('span', {class: 'ft'}, `${t('st.error')}: `, f.error || '')));
  else {
    put(form, h('div', {class: 'findings', id: 'findings'}), secSupplier(), secInvoice(), secAmounts(), secSplit(),
      secLines(), secMore());
    paintFindings();
  }
  paintActions();
}

function paintFindings() {
  const box = $('#findings');
  if (!box) return;
  const found = E.f.findings || [];
  put(box, found.map(a => h('div', {class: 'finding ' + a.level},
    h('span', {class: 'fi'}, a.level === 'info' ? 'i' : '!'), h('span', {class: 'ft'}, a.text),
    a.fix && editable() ? h('button', {class: 'btn small', onclick: () => applyFix(a.fix)}, a.fix.label) : null)));
  if (!found.some(a => a.level !== 'info') && E.f.status === 'review')
    box.prepend(h('div', {class: 'finding ok'}, h('span', {class: 'fi'}, '✓'), h('span', {class: 'ft'}, t('all_ok'))));
  const b = $('#btn-approve');
  if (b) b.disabled = found.some(a => a.level === 'error');
}

function applyFix(fix) {
  const [obj, k] = fix.field.split('.');
  E.f[obj][k] = fix.value;
  if (fix.field === 'data.supplier_tax_id') return repropose('');        // with the right ID, back to the ledger
  if (fix.field === 'entry.supplier_account') return repropose(fix.value);
  paintForm();
  saveNow();
}

// ------------------------------------------------------------ saving
let saveTimer;
function mark(txt, bad) {
  const g = $('#saved');
  if (g) { g.textContent = txt; g.className = 'saved' + (bad ? ' bad' : ''); }
}
function changed() {
  E.dirty = true;
  mark(t('unsaved'));
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, 700);
}
async function saveNow() {
  clearTimeout(saveTimer);
  const f = E.f;
  if (!f || !editable()) return;
  mark(t('saving'));
  try {
    const r = await post(`/api/invoices/${f.id}/save`, {data: f.data, entry: f.entry, view: E.view});
    if (E.f && E.f.id === r.id) {
      Object.assign(E.f, {findings: r.findings, names: r.names, supplier_ledger: r.supplier_ledger, usual: r.usual, reason: r.reason});
      E.dirty = false;
      paintFindings();
      mark(t('saved'));
    }
  } catch (e) { mark(t('save_failed', {e: e.message}), true); }
}

async function repropose(supplierAccount) {
  const f = E.f;
  clearTimeout(saveTimer);
  const entry = {...f.entry, supplier_account: supplierAccount};
  try {
    E.f = await post(`/api/invoices/${f.id}/propose`, {data: f.data, entry, view: E.view});
    E.dirty = false;
    paintHead();
    paintForm();
    mark(t('saved'));
  } catch (e) { toast(e.message, 'bad'); }
}

// ------------------------------------------------------------ form controls
function sec(title, ...kids) { return h('section', {class: 'sec'}, h('h3', {}, title), ...kids); }
function field(label, control, hint, cls) {
  return h('label', {class: 'field' + (cls ? ' ' + cls : '')}, h('span', {}, label), control, hint ? h('small', {}, hint) : null);
}
function inText(obj, k, {onChange, ...extra} = {}) {
  return h('input', {type: 'text', value: obj[k] || '', disabled: !editable(), ...extra,
    onchange: e => { obj[k] = e.target.value.trim(); changed(); if (onChange) onChange(); }});
}
function inRate(obj, k) {
  return h('input', {type: 'text', inputMode: 'decimal', class: 'num', value: String(obj[k] ?? '').replace('.', LANG === 'en' ? '.' : ','),
    disabled: !editable(), onchange: e => { obj[k] = readNum(e.target.value); e.target.value = String(obj[k]); changed(); }});
}
function inDate(obj, k) {
  return h('input', {type: 'date', value: obj[k] || '', disabled: !editable(), onchange: e => { obj[k] = e.target.value; changed(); }});
}
function inMoney(obj, k) {
  return h('input', {type: 'text', inputMode: 'decimal', class: 'num', value: num2(obj[k], true), disabled: !editable(),
    onchange: e => { obj[k] = readNum(e.target.value); e.target.value = num2(obj[k], true); changed(); }});
}
function select(obj, k, options, onChange) {
  return h('select', {disabled: !editable(), onchange: e => { obj[k] = e.target.value; changed(); if (onChange) onChange(); }},
    options.map(([v, label]) => h('option', {value: v, selected: String(obj[k] ?? '') === String(v)}, label)));
}
const removeBtn = fn => h('button', {class: 'remove', title: '×', onclick: fn}, '×');

// searchable combo (suppliers, accounts)
function combo({text, search, choose, placeholder}) {
  const input = h('input', {type: 'text', value: text, placeholder, disabled: !editable(), autocomplete: 'off', spellcheck: false});
  const list = h('div', {class: 'combo-list', hidden: true});
  let items = [], sel = 0, timer, asked = 0;
  async function show() {
    const me = ++asked;
    const r = await search(input.value === text ? '' : input.value);
    if (me !== asked) return;
    items = r; sel = 0; paint();
  }
  function paint() {
    put(list, items.length ? items.map((it, i) => h('div', {class: 'opt' + (i === sel ? ' sel' : ''),
      onmousedown: e => { e.preventDefault(); pick(it); }}, h('b', {}, it.account), it.name, it.extra ? h('small', {}, it.extra) : null))
      : [h('div', {class: 'none'}, t('f.nothing'))]);
    list.hidden = false;
  }
  function pick(it) { list.hidden = true; text = `${it.account} · ${it.name}`; input.value = text; input.blur(); choose(it); }
  input.addEventListener('focus', () => { input.select(); show(); });
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(show, 160); });
  input.addEventListener('keydown', e => {
    if (list.hidden) return;
    if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, items.length - 1); paint(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); paint(); e.preventDefault(); }
    else if (e.key === 'Enter') { if (items[sel]) pick(items[sel]); e.preventDefault(); }
    else if (e.key === 'Escape') { list.hidden = true; input.value = text; input.blur(); }
  });
  input.addEventListener('blur', () => setTimeout(() => { list.hidden = true; input.value = text; }, 120));
  return h('div', {class: 'combo'}, input, list);
}

function searchAccounts(q) {
  const all = E.accounts || [];
  q = q.trim().toLowerCase();
  let r;
  if (!q) r = all.filter(c => c.used > 0).sort((a, b) => b.used - a.used);
  else {
    const words = q.normalize('NFD').replace(/[̀-ͯ]/g, '').split(/\s+/);
    r = all.filter(c => {
      const n = (c.account + ' ' + c.name).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
      return /^\d+$/.test(q) ? c.account.startsWith(q) : words.every(w => n.includes(w));
    }).sort((a, b) => b.used - a.used);
  }
  return r.slice(0, 40).map(c => ({...c, extra: c.used > 0 ? t('f.this_year', {v: money(c.used)}) : null}));
}
const accountName = c => (E.accounts || []).find(x => x.account === c)?.name || E.f.names?.[c] || '';

// ------------------------------------------------------------ sections
function secSupplier() {
  const f = E.f, d = f.data, e = f.entry, s = f.supplier_ledger;
  const usual = f.usual || [];
  return sec(t('sec.supplier'),
    h('div', {class: 'read-line'}, t('f.on_invoice'), h('b', {}, d.supplier_name || '—'), `· ${t('f.tax_id')}`,
      inText(d, 'supplier_tax_id', {onChange: () => { if (!e.supplier_account || e.supplier_match !== 'manual') repropose(''); }})),
    field(t('f.supplier_account'), combo({
      text: s ? `${s.account} · ${s.name}` : '',
      placeholder: t('f.search_supplier'),
      search: async q => {
        const r = await api('/api/suppliers?q=' + encodeURIComponent(q || d.supplier_name.split(' ').slice(0, 2).join(' ') || d.supplier_tax_id));
        return r.map(x => ({...x, extra: [x.tax_id && `${t('f.tax_id')} ${x.tax_id}`, x.bought && t('f.this_year', {v: money(x.bought)})].filter(Boolean).join(' · ')}));
      },
      choose: it => repropose(it.account),
    }), s ? (e.supplier_match ? t('match.' + e.supplier_match) : '') : t('f.not_chosen')),
    usual.length ? h('p', {class: 'usual'}, t('f.usual'),
      usual.map((x, i) => [i ? ' · ' : '', h('b', {}, x.account), ' ', nice(x.name), ` (${x.pct} %)`])) : null);
}

function secInvoice() {
  const d = E.f.data, e = E.f.entry;
  const due = d.due_dates || [];
  return sec(t('sec.invoice'), h('div', {class: 'grid'},
    field(t('f.type'), select(d, 'doc_type', [['invoice', t('f.invoice')], ['credit_note', t('f.credit_note')], ['other', t('f.other')]])),
    field(t('f.number'), inText(d, 'invoice_number')),
    field(t('f.date'), inDate(d, 'invoice_date')),
    d.accounting_date ? field(t('f.other_date'), inDate(d, 'accounting_date')) : null,
    field(t('f.posting_date'), inDate(e, 'posting_date'), t('f.posting_hint')),
    field(t('f.due'), h('div', {class: 'fixed' + (due.length ? '' : ' muted')},
      due.length ? due.map(v => `${dmy(v.date)} · ${money(v.amount)}`).join(' / ') : t('f.no_due')))));
}

function secAmounts() {
  const d = E.f.data;
  const ed = editable();
  const repaint = () => { paintForm(); changed(); };
  return sec(t('sec.amounts'),
    h('table', {class: 'edit-table'},
      h('thead', {}, h('tr', {}, h('th', {class: 'w-rate'}, t('f.vat_rate')), h('th', {class: 'num'}, t('f.base')), h('th', {class: 'num'}, t('f.vat')), h('th', {class: 'w-x'}))),
      h('tbody', {}, d.vat_breakdown.map((x, i) => h('tr', {},
        h('td', {}, inRate(x, 'vat_rate')), h('td', {}, inMoney(x, 'base')), h('td', {}, inMoney(x, 'vat')),
        h('td', {}, ed ? removeBtn(() => { d.vat_breakdown.splice(i, 1); repaint(); }) : null)))),
      ed ? h('tfoot', {}, h('tr', {}, h('td', {colSpan: 4},
        h('button', {class: 'btn small', onclick: () => { d.vat_breakdown.push({vat_rate: 21, base: 0, vat: 0}); repaint(); }}, t('f.add_rate'))))) : null),
    h('div', {class: 'grid', style: 'margin-top:12px'},
      field(t('f.surcharge'), inMoney(d, 'surcharge')),
      field(t('f.withholding'), inMoney(d, 'withholding')),
      field(t('f.total'), inMoney(d, 'total'), null, 'strong')));
}

function secSplit() {
  const f = E.f, e = f.entry, d = f.data;
  const ed = editable();
  const rates = [...new Set(d.vat_breakdown.map(x => x.vat_rate))];
  const repaint = () => { paintForm(); changed(); };
  const accounts = new Set(e.split.map(r => r.account));
  return sec(t('sec.split'),
    f.reason ? h('p', {class: 'reason'}, f.reason) : null,
    h('table', {class: 'edit-table'},
      h('thead', {}, h('tr', {}, h('th', {}, t('f.account')), h('th', {class: 'w-rate'}, t('f.vat_rate')), h('th', {class: 'num w-amount'}, t('f.base')), h('th', {class: 'w-x'}))),
      h('tbody', {}, e.split.map((r, i) => h('tr', {},
        h('td', {}, combo({text: r.account ? `${r.account} · ${accountName(r.account)}` : '', placeholder: t('f.pick_account'),
          search: async q => searchAccounts(q), choose: it => { r.account = it.account; E.f.names[it.account] = it.name; changed(); }})),
        h('td', {}, select(r, 'vat_rate', rates.map(x => [x, pct(x)]), () => { r.vat_rate = Number(r.vat_rate); })),
        h('td', {}, inMoney(r, 'base')),
        h('td', {}, ed && e.split.length > 1 ? removeBtn(() => { e.split.splice(i, 1); repaint(); }) : null)))),
      ed ? h('tfoot', {}, h('tr', {}, h('td', {colSpan: 4},
        h('button', {class: 'btn small', onclick: () => { e.split.push({account: '', vat_rate: rates[0] ?? 21, base: 0}); repaint(); }}, t('f.add_split')),
        ' ', h('button', {class: 'btn small', onclick: () => repropose(e.supplier_account)}, t('f.repropose'))))) : null),
    ed && accounts.size === 1 && e.supplier_account ? h('label', {class: 'check'},
      h('input', {type: 'checkbox', checked: e.remember_account, onchange: ev => { e.remember_account = ev.target.checked; changed(); }}),
      t('f.remember')) : null,
    f.account_rule ? h('p', {class: 'note'}, t('f.rule', {a: f.account_rule})) : null);
}

function secLines() {
  const lines = E.f.data.lines || [];
  return h('details', {class: 'sec'}, h('summary', {}, t('sec.lines', {n: lines.length})),
    lines.length ? h('table', {class: 'lines'},
      h('thead', {}, h('tr', {}, h('th', {}, t('f.description')), h('th', {}, t('f.category')), h('th', {class: 'num'}, t('f.vat_rate')), h('th', {class: 'num'}, t('f.amount')))),
      h('tbody', {}, lines.map(l => h('tr', {}, h('td', {}, l.description), h('td', {}, h('span', {class: 'cat cat-' + l.category}, l.category)),
        h('td', {class: 'num'}, pct(l.vat_rate)), h('td', {class: 'num'}, money(l.amount))))))
      : h('p', {class: 'muted'}, t('f.no_lines')));
}

function secMore() {
  const f = E.f;
  return h('details', {class: 'sec more'}, h('summary', {}, t('sec.more')),
    h('dl', {},
      h('dt', {}, t('f.received')), h('dd', {}, `${dmy(f.received)} ${f.received.slice(11, 16)} · ${f.source === 'email' || f.source === 'folder' ? t('by_' + f.source) : t('f.uploaded')}`),
      f.source_detail ? [h('dt', {}, t(f.source === 'folder' ? 'f.folder' : 'f.email')), h('dd', {}, f.source_detail)] : null,
      h('dt', {}, t('f.file')), h('dd', {}, f.filename),
      f.model ? [h('dt', {}, t('f.reading')), h('dd', {}, `${f.model === 'demo' ? t('reader.demo') : f.model_name} · ${secs(f.seconds)} · ${costTxt(f.cost)}`)] : null),
    h('ul', {}, (f.history || []).map(x => h('li', {}, `${dmy(x.at)} ${x.at.slice(11, 16)} · ${x.what}`))));
}

// ------------------------------------------------------------ actions
function paintActions() {
  const f = E.f;
  const bar = $('#actions');
  if (!bar) return;
  const action = (label, fn, cls = 'btn', id) => h('button', {class: cls, id, onclick: async e => {
    const b = e.currentTarget;
    b.disabled = true;
    try { await fn(); } catch (err) { toast(err.message, 'bad'); }
    finally { if (document.body.contains(b)) b.disabled = false; }
  }}, label);
  const kids = [];
  if (['review', 'error', 'approved'].includes(f.status))
    kids.push(action(t('a.discard'), async () => {
      if (!confirm(t('a.discard.confirm'))) return;
      await post(`/api/invoices/${f.id}/discard`); toast(t('a.discarded')); nextOr('review');
    }, 'btn danger'));
  if (['review', 'error', 'discarded'].includes(f.status))
    kids.push(action(t('a.reread'), async () => {
      if (f.data && !confirm(t('a.reread.confirm'))) return;
      await post(`/api/invoices/${f.id}/reread`); invoiceView(f.id);
    }));
  if (['approved', 'discarded'].includes(f.status))
    kids.push(action(f.status === 'approved' ? t('a.reopen') : t('a.recover'), async () => {
      E.view = 'review'; await post(`/api/invoices/${f.id}/reopen`); location.hash = `#/invoice/${f.id}`; invoiceView(f.id);
    }));
  if (f.status === 'exported')
    kids.push(action(t('a.booked'), async () => { await post(`/api/invoices/${f.id}/booked`); invoiceView(f.id); }));
  kids.push(h('span', {class: 'grow'}));
  if (editable()) kids.push(h('span', {class: 'saved', id: 'saved'}, t('saved')));
  if (f.status === 'review') kids.push(action(t('a.approve'), approve, 'btn primary', 'btn-approve'));
  put(bar, kids);
  const b = $('#btn-approve');
  if (b) b.disabled = (f.findings || []).some(a => a.level === 'error');
}

function nextOr(view) {
  const f = E.f;
  E.dirty = false;
  location.hash = f.next ? `#/invoice/${f.next}` : `#/${view}`;
}

async function approve() {
  clearTimeout(saveTimer);
  const f = E.f;
  const r = await post(`/api/invoices/${f.id}/approve`, {data: f.data, entry: f.entry, view: E.view});
  if (r.errors) {
    E.f = r.detail;
    paintForm();
    toast(t('a.fix_first', {e: r.errors[0]}), 'bad');
    return;
  }
  E.dirty = false;
  toast(t('a.approved'));
  location.hash = r.next ? `#/invoice/${r.next}` : '#/review';
}

// ============================================================ login
function showLogin() {
  if ($('#login')) return;
  const input = h('input', {type: 'password', autocomplete: 'current-password', placeholder: t('login.token')});
  const form = h('form', {class: 'card login', id: 'login', onsubmit: async e => {
    e.preventDefault();
    const r = await fetch('/api/login', {method: 'POST', headers: {'X-Asienta': '1', 'Content-Type': 'application/json'},
                                         body: JSON.stringify({token: input.value})});
    if (r.ok) { form.remove(); go(); } else toast(t('login.wrong'), 'bad');
  }}, h('img', {src: '/logo', alt: ''}), h('h1', {}, t('login.title', {name: 'Asienta'})), input,
    h('button', {class: 'btn primary', type: 'submit'}, t('login.go')));
  put(main, form);
  input.focus();
}

window.addEventListener('beforeunload', e => { if (E.dirty) { saveNow(); e.preventDefault(); } });

(async () => {
  const s = await fetch('/api/session').then(r => r.json()).catch(() => ({}));
  if (s.needs_login) return showLogin();
  if (!location.hash) location.hash = '#/review';
  else go();
})();
