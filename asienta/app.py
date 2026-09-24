"""The application core, without HTTP: receive documents, read them in the background, propose,
check, approve and export. server.py puts a web interface on top; tests drive it directly.
"""
import datetime
import hashlib
import io
import os
import re
import threading
import time
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor

from . import checks, exporters, i18n, mailbox, rules, spain
from .config import parse_list, parse_pairs
from .db import DB, VIEWS
from .extraction import ReadError, open_reader, pretty_model
from .extraction.schema import build_prompt, date, invoice_schema, normalize, num
from .ledger import open_ledger

MAX_FILE = 15 * 1024 * 1024
READ_INTERVAL = 1.5          # minimum seconds between two AI calls, to be gentle with the API
STUCK_MINUTES = 10           # a reading older than this has hung
# $ per million tokens (input, output). Override with [reader] price_input / price_output.
PRICES = {'gemini-3.8-flash': (0.75, 3.75), 'gemini-3.7-flash': (0.75, 3.75), 'gemini-3.5-flash': (1.50, 9.00),
          'gemini-3.5-flash-lite': (0.30, 2.50), 'gemini-3.1-flash-lite': (0.25, 1.50),
          'claude-opus-5': (5.0, 25.0), 'claude-sonnet-5': (2.0, 10.0), 'claude-haiku-4-5': (1.0, 5.0),
          'demo': (0.75, 3.75)}


def sniff(b):
    """File type from its first bytes (not from what the browser or the name says)."""
    if b[:4] == b'%PDF':
        return 'application/pdf', '.pdf'
    if b[:3] == b'\xff\xd8\xff':
        return 'image/jpeg', '.jpg'
    if b[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png', '.png'
    if b[:4] == b'RIFF' and b[8:12] == b'WEBP':
        return 'image/webp', '.webp'
    if b[4:8] == b'ftyp' and b[8:12] in (b'heic', b'heix', b'mif1', b'msf1', b'hevc', b'heif'):
        return 'image/heic', '.heic'
    return None, None


def safe_filename(s, length=80):
    s = re.sub(r'[\\/:*?"<>|]', '-', ' '.join(str(s or '').split()))
    return s.strip(' .')[:length] or 'invoice'


class App:
    def __init__(self, settings, reader=None, ledger=None, log=None):
        self.s = settings
        self.log = log or (lambda msg: print(f'{datetime.datetime.now():%H:%M:%S}  {msg}', flush=True))
        self.data_dir = settings.data_dir
        for sub in ('files', 'batches', 'set_aside'):
            os.makedirs(os.path.join(self.data_dir, sub), exist_ok=True)
        self.db = DB(os.path.join(self.data_dir, 'asienta.db'))
        self.ledger = ledger or open_ledger(settings)
        self.reader = reader or open_reader(settings)
        self.categories = settings.categories()
        self.split_cfg = rules.SplitConfig(
            self.categories, parse_list(settings.get('split', 'only_prefixes', '600')),
            parse_list(settings.get('split', 'follow_main', '')), parse_list(settings.get('split', 'follow_when', '')))
        self.suggest_prefixes = parse_list(settings.get('ledger', 'suggest_prefixes', '6,21'))
        model = getattr(self.reader, 'model', '')
        default_prices = PRICES.get(model, (0.0, 0.0))
        self.prices = (settings.float('reader', 'price_input', default_prices[0]),
                       settings.float('reader', 'price_output', default_prices[1]))
        self.company = settings.get('company', 'name')
        self.company_tax_id = spain.normalize_tax_id(settings.get('company', 'tax_id'))
        self.format = settings.get('export', 'format', 'sage50').lower()
        self.manual_vat = parse_pairs(settings.get('accounts', 'input_vat'))
        self.withholding_account = re.sub(r'\D', '', settings.get('accounts', 'withholding'))
        self.drop_folder = settings.path_('export', 'drop_folder')
        self.fixed_name = settings.get('export', 'fixed_name')
        self.inbox_folder = settings.path_('inbox', 'folder')
        self.mailbox = settings.section('mailbox')
        if self.mailbox:
            self.mailbox['password'] = settings.secret('mailbox', 'password', 'ASIENTA_MAILBOX_PASSWORD')
        self.pool = ThreadPoolExecutor(max_workers=settings.int('reader', 'concurrency', 3))
        self._last_mail = 0.0
        self._last_read = 0.0
        self._read_lock = threading.Lock()
        self.mailbox_error = ''

    # -------------------------------------------------------------- helpers
    def today(self):
        """The real date, unless [app] today pins it (the demo does, so it looks the same any year)."""
        pinned = date(self.s.get('app', 'today'))
        return datetime.date.fromisoformat(pinned) if pinned else datetime.date.today()

    def closed(self):
        return spain.vat_filed_until(self.today(), self.s.get('ledger', 'vat_filed_until', 'auto'))

    def path(self, relative):
        p = os.path.normpath(os.path.join(self.data_dir, relative))
        if not p.startswith(os.path.normpath(self.data_dir) + os.sep):
            raise ValueError('path outside the data folder')
        return p

    def category_names(self):
        return [c.name for c in self.categories]

    def propose(self, data, chosen=None):
        return rules.propose(data, self.ledger, self.db, self.split_cfg, self.closed(), chosen)

    def findings(self, i, data, entry):
        ctx = {'directory': self.ledger, 'company_tax_id': self.company_tax_id, 'closed': self.closed(),
               'today': self.today(),
               'duplicate_in_app': lambda tid, number: self.db.duplicate(tid, entry.get('supplier_account'), number, i)}
        return checks.review(data, entry, ctx)

    # -------------------------------------------------------------- intake
    def receive(self, content, name, source, detail='', email=''):
        """Store a file and queue it for reading. Returns (id, already_there)."""
        mime, ext = sniff(content)
        if not mime:
            raise ValueError('not a PDF or a photo')
        if len(content) > MAX_FILE:
            raise ValueError('larger than 15 MB')
        fingerprint = hashlib.sha256(content).hexdigest()
        known = self.db.by_fingerprint(fingerprint)
        if known:
            return known['id'], True
        rel = os.path.join('files', datetime.date.today().strftime('%Y-%m'), fingerprint[:16] + ext)
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), 'wb') as f:
            f.write(content)
        name = os.path.basename(name.replace('\\', '/')) or 'invoice' + ext
        i = self.db.new(source, detail, rel.replace(os.sep, '/'), name, mime, fingerprint, email)
        self.log(f'invoice {i} received ({source}): {name}')
        self.enqueue(i)
        return i, False

    def set_aside(self, content, name, mime, reason, info):
        """An attachment that doesn't look like a document. NOT thrown away: kept and shown in the
        Mailbox screen in case the filter was wrong."""
        _m, ext = sniff(content)
        fingerprint = hashlib.sha256(content).hexdigest()
        rel = os.path.join('set_aside', datetime.date.today().strftime('%Y-%m'), fingerprint[:16] + (ext or '.bin'))
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), 'wb') as f:
            f.write(content)
        return self.db.add_set_aside({'message_id': info['mid'], 'sender': info['sender'], 'subject': info['subject'],
                                      'filename': os.path.basename(name.replace('\\', '/')) or 'attachment',
                                      'file': rel.replace(os.sep, '/'), 'mime': mime or '', 'size': len(content),
                                      'reason': reason})

    def take_set_aside(self, i):
        """'It is an invoice, take it': the set-aside attachment goes in like any other."""
        a = self.db.set_aside_item(i)
        if not a:
            raise ValueError('not found')
        if a['invoice']:
            return a['invoice'], True
        with open(self.path(a['file']), 'rb') as f:
            content = f.read()
        inv, known = self.receive(content, a['filename'], 'email', f'{a["sender"]} · {a["subject"]}', a['message_id'])
        self.db.set_aside_used(i, inv)
        return inv, known

    def load_samples(self):
        """Demo mode: take in every sample invoice shipped with the package."""
        from .extraction.demo import BY_EMAIL, SAMPLES
        added = 0
        for name in sorted(os.listdir(SAMPLES)):
            if name.endswith(('.pdf', '.jpg', '.png')) and name not in BY_EMAIL:
                with open(os.path.join(SAMPLES, name), 'rb') as f:
                    _i, known = self.receive(f.read(), name, 'upload')
                added += not known
        return added

    def simulate_email(self):
        """Demo mode: an email arrives and goes through the same code as a real IMAP message."""
        from .extraction.demo import demo_email
        msg = demo_email(self.mailbox.get('address') or 'invoices@example.com')
        return mailbox.process(msg, msg['Message-ID'], self.mailbox, self.db, self.receive, self.log, self.set_aside)

    # -------------------------------------------------------------- reading
    def ledger_ready(self):
        if self.ledger.ready():
            return True
        self.ledger.refresh()
        return self.ledger.ready()

    def enqueue(self, i):
        """Queue for reading, but only if the ledger answers: supplier and accounts come from it,
        so reading without it would spend a reading and propose badly."""
        if not self.ledger_ready():
            self.db.set_status(i, 'waiting', 'ledger not answering: waiting to read it')
            return False
        self.pool.submit(self.read, i)
        return True

    def resume_waiting(self):
        for r in self.db.with_status('waiting'):
            self.db.set_status(r['id'], 'reading', 'ledger is back: reading it')
            self.pool.submit(self.read, r['id'])

    def watch_readings(self):
        """A hung reading cannot stay like that forever."""
        limit = (datetime.datetime.now() - datetime.timedelta(minutes=STUCK_MINUTES)).strftime('%Y-%m-%d %H:%M:%S')
        for r in self.db.with_status('reading'):
            if (r['updated'] or r['received'] or '') < limit:
                self.db.save_error(r['id'], f'reading hung for more than {STUCK_MINUTES} minutes. Read it again.')

    def prompt(self):
        return build_prompt(self.company, self.company_tax_id, self.s.get('company', 'activity', 'business'),
                            self.categories, self.ledger.accounts_to_suggest(self.suggest_prefixes),
                            self.s.language, self.today())

    def read(self, i):
        """AI reading + proposal. Runs in the background."""
        try:
            f = self.db.invoice(i)
            if not self.ledger_ready():
                self.db.set_status(i, 'waiting', 'ledger not answering: waiting to read it')
                return
            with self._read_lock:                       # one call every few seconds, even in bursts
                pause = READ_INTERVAL - (time.time() - self._last_read)
                if pause > 0:
                    time.sleep(pause)
                self._last_read = time.time()
            with open(self.path(f['file']), 'rb') as fh:
                content = fh.read()
            r = self.reader.read(content, f['mime'], self.prompt(), invoice_schema(self.category_names()),
                                 self.category_names())
            cost = round(r.tokens_in / 1e6 * self.prices[0] + r.tokens_out / 1e6 * self.prices[1], 5)
            part = f.get('part') or 1
            if part > len(r.invoices):
                raise ReadError(f'on re-reading, the file no longer has invoice {part}')
            data = r.invoices[part - 1]
            entry = self.propose(data)
            sup = self.ledger.supplier(entry['supplier_account'])
            self.db.save_reading(i, data, data, entry, sup['name'] if sup else '', r.model, r.tokens_in,
                                 r.tokens_out, cost, r.seconds, data['start_page'])
            self.log(f'invoice {i} read in {r.seconds:.1f} s ({r.tokens_in}+{r.tokens_out} tokens)')
            if part == 1:                               # a PDF with several invoices: one record each
                for n, other in enumerate(r.invoices[1:], start=2):
                    if self.db.by_fingerprint(f['fingerprint'], n):
                        continue
                    e2 = self.propose(other)
                    s2 = self.ledger.supplier(e2['supplier_account'])
                    self.db.new_part(i, n, other['start_page'], other, other, e2, s2['name'] if s2 else '', r.model)
        except Exception as e:
            text = str(e) if isinstance(e, (ReadError, OSError)) else f'{e.__class__.__name__}: {e}'
            self.db.save_error(i, text)
            self.log(f'invoice {i} could not be read: {text}')
            if not isinstance(e, ReadError):
                traceback.print_exc()

    def resume(self):
        """At start-up: whatever was half-way goes back to the queue."""
        for r in self.db.with_status('reading', 'waiting'):
            self.enqueue(r['id'])

    # -------------------------------------------------------------- background
    def background(self):
        while True:
            try:
                self.tick()
            except Exception:
                traceback.print_exc()
            time.sleep(30)

    def tick(self):
        if self.ledger.stale():
            if self.ledger.refresh():
                self.mark_booked()
            elif self.ledger.error:
                self.log(f'ledger not answering: {self.ledger.error}')
        if self.ledger.ready():
            self.resume_waiting()
        self.watch_readings()
        self.check_folder()
        minutes = float(self.mailbox.get('every_minutes') or 5)
        if self.mailbox.get('server') and time.time() - self._last_mail > minutes * 60:
            self._last_mail = time.time()
            try:
                n = mailbox.check(self.mailbox, self.db, self.receive, self.log, self.set_aside)
                self.mailbox_error = ''
                if n:
                    self.log(f'mailbox: {n} new invoice(s)')
            except Exception as e:
                self.mailbox_error = f'{e.__class__.__name__}: {e}'[:200]
                self.log(f'mailbox: {self.mailbox_error}')

    def check_folder(self):
        """[inbox] folder: whatever lands there (a scanner's scan-to-folder, a synced Dropbox or
        shared drive) is taken and moved to done/ inside it; what isn't a PDF or photo to skipped/."""
        folder = self.inbox_folder
        if not folder or not os.path.isdir(folder):
            return 0
        n = 0
        for name in sorted(os.listdir(folder)):
            p = os.path.join(folder, name)
            if name.startswith('.') or not os.path.isfile(p) or time.time() - os.path.getmtime(p) < 3:
                continue                                # hidden, a folder, or still being written
            with open(p, 'rb') as f:
                content = f.read()
            try:
                self.receive(content, name, 'folder', detail=folder)
                sub, n = 'done', n + 1
            except ValueError as e:
                self.log(f'inbox folder: {name} left out ({e})')
                sub = 'skipped'
            target = os.path.join(folder, sub, name)
            if os.path.exists(target):
                target = os.path.join(folder, sub, f'{datetime.datetime.now():%Y%m%d_%H%M%S}_{name}')
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(p, target)
        return n

    def mark_booked(self):
        """Exported invoices that now appear in the ledger's VAT book become 'booked'."""
        for r in self.db.with_status('exported'):
            f = self.db.invoice(r['id'])
            found = self.ledger.already_booked(f['entry']['supplier_account'], f['data']['invoice_number'])
            if found:
                self.db.set_status(f['id'], 'posted', f'found in the ledger ({found["date"]})', f['batch'])

    # -------------------------------------------------------------- API views
    def state(self, lang):
        counts = self.db.counts()
        n, cost = self.db.month_cost(datetime.date.today().strftime('%Y-%m'))
        st = self.ledger.status()
        last = self.db.last_batch()
        return {
            'brand': self.s.brand(), 'company': self.company, 'language': lang,
            'views': {v: sum(counts.get(s, 0) for s in ss) for v, ss in VIEWS.items()},
            'reading': counts.get('reading', 0),
            'mailbox': self.mailbox.get('address', ''), 'mailbox_error': self.mailbox_error,
            'set_aside': self.db.open_set_aside(),
            'month': {'invoices': n, 'cost_usd': cost},
            'reader': {'name': self.reader.name, 'model': getattr(self.reader, 'model', ''),
                       'ready': getattr(self.reader, 'ready', True), 'demo': getattr(self.reader, 'model', '') == 'demo'},
            'ledger': {'kind': st['kind'], 'error': st['error'], 'suppliers': st['suppliers'],
                       'minutes_ago': round((time.time() - st['loaded']) / 60) if st['loaded'] else None},
            'vat_filed_until': i18n.quarter(self.closed(), lang),
            'exporters': [{'key': e.key, 'label': e.label, 'maturity': e.maturity} for e in exporters.EXPORTERS.values()],
            'format': self.format,
            'drop_path': self.fixed_path(),
            'last_batch': ({k: last[k] for k in ('id', 'created', 'invoices', 'total', 'posted', 'format')} if last else None),
        }

    def listing(self, view):
        out = []
        for f in self.db.listing(view):
            if f['status'] in ('review', 'approved'):
                d = self.db.invoice(f['id'])
                found = self.findings(f['id'], d['data'], d['entry'])
                f['errors'] = sum(a['level'] == 'error' for a in found)
                f['warnings'] = sum(a['level'] == 'warning' for a in found)
            out.append(f)
        return out

    def detail(self, i, view, lang):
        f = self.db.invoice(i)
        if not f:
            return None
        for k in ('fingerprint', 'file', 'reading'):
            f.pop(k, None)
        f['findings'], f['supplier_ledger'], f['usual'], f['names'] = [], None, [], {}
        if f['data']:
            e = f['entry']
            f['findings'] = i18n.render_findings(self.findings(i, f['data'], e), lang)
            f['reason'] = i18n.render_reason(e.get('reason'), lang)
            f['supplier_ledger'] = self.ledger.supplier(e['supplier_account'])
            f['usual'] = [{'account': c, 'name': self.ledger.name(c), 'pct': round(100 * p), 'invoices': n}
                          for c, _amount, n, p in self.ledger.usual(e['supplier_account'])[:4]]
            accounts = {r['account'] for r in e['split']} | {f['data'].get('suggested_account', '')}
            f['names'] = {c: self.ledger.name(c) for c in accounts if c}
            f['account_rule'] = self.db.rule_for_supplier(e['supplier_account']) if e['supplier_account'] else None
        f['previous'], f['next'] = self.db.neighbours(i, view)
        f['history'] = self.db.history(i)
        f['model_name'] = pretty_model(f['model'])
        return f

    def clean(self, body, f):
        """Data and entry sent by the browser, with safe types."""
        data = normalize(dict(f['data'] or {}, **(body.get('data') or {})), self.category_names())
        e = dict(f['entry'] or {}, **(body.get('entry') or {}))
        entry = {
            'supplier_account': re.sub(r'\D', '', str(e.get('supplier_account') or '')),
            'supplier_match': e.get('supplier_match') if e.get('supplier_match') in
            ('manual', 'rule', 'tax_id', 'name', 'similar') else '',
            'posting_date': date(e.get('posting_date')),
            'split': [{'account': re.sub(r'\D', '', str(r.get('account') or '')),
                       'vat_rate': num(r.get('vat_rate')), 'base': num(r.get('base'))}
                      for r in e.get('split') or []],
            'reason': e.get('reason') if isinstance(e.get('reason'), list) else [],
            'remember_account': bool(e.get('remember_account')),
        }
        if entry['supplier_account'] and not self.ledger.supplier(entry['supplier_account']):
            entry['supplier_account'] = ''
        return data, entry

    def save(self, i, body):
        f = self.db.invoice(i)
        if not f or f['status'] not in ('review', 'approved'):
            raise ValueError('this invoice can no longer be changed')
        data, entry = self.clean(body, f)
        sup = self.ledger.supplier(entry['supplier_account'])
        self.db.save(i, data, entry, sup['name'] if sup else '')
        return data, entry

    def repropose(self, i, body):
        f = self.db.invoice(i)
        data, entry = self.clean(body, f)
        new = self.propose(data, entry['supplier_account'] or None)
        if entry['supplier_account']:
            new['supplier_match'] = 'manual'
        if f['entry'] and f['entry'].get('posting_date') and entry['posting_date']:
            new['posting_date'] = entry['posting_date']        # re-proposing keeps the date
        return self.save(i, {'data': data, 'entry': new})

    def approve(self, i, body, lang='es'):
        data, entry = self.save(i, body)
        errors = [a for a in self.findings(i, data, entry) if a['level'] == 'error']
        if errors:
            return [a['text'] for a in i18n.render_findings(errors, lang)]
        acc = entry['supplier_account']
        tid = data['supplier_tax_id']
        if tid and entry['supplier_match'] in ('manual', 'name', 'similar') \
                and spain.tax_id_valid(tid) is not False and tid != self.company_tax_id:
            self.db.set_tax_id_rule(tid, acc)                 # next time, straight by tax ID
        accounts = {r['account'] for r in entry['split']}
        if entry['remember_account'] and len(accounts) == 1:
            self.db.set_account_rule(acc, accounts.pop())
        self.db.set_status(i, 'approved', 'approved')
        return []

    # -------------------------------------------------------------- export
    def vat_accounts(self):
        """{rate: input VAT account}: from the ledger's chart, overridden by config."""
        return dict(self.ledger.input_vat_accounts(), **self.manual_vat)

    def context(self):
        return exporters.Context(vat_accounts=self.vat_accounts(), withholding_account=self.withholding_account,
                                 description=self.s.get('export', 'description', 'S/ FRA. [{number}] {supplier}'),
                                 description_length=self.s.int('export', 'description_length', 25), settings=self.s)

    def export(self, fmt=None, lang='es'):
        """All approved invoices into one file. Returns (batch, warnings, path)."""
        fmt = (fmt or self.format).lower()
        exporter = exporters.get(fmt, self.s)
        ids = [r['id'] for r in self.db.with_status('approved')]
        if not ids:
            raise ValueError('no approved invoices')
        invoices = []
        for i in ids:
            f = self.db.invoice(i)
            if any(a['level'] == 'error' for a in self.findings(i, f['data'], f['entry'])):
                raise ValueError(f'invoice {i} has something to fix: open it and review it')
            invoices.append((f['data'], f['entry'], self.ledger.supplier(f['entry']['supplier_account']) or {}))
        name = f'{fmt}_{datetime.datetime.now():%Y%m%d_%H%M%S}{exporter.extension}'
        path = self.path(os.path.join('batches', name))
        res = exporter.write(path, invoices, self.context())
        warnings = [i18n.t(k, lang, **p) for k, p in res.warnings]
        if not res.included:
            os.remove(path)
            raise ValueError(' '.join(warnings) or 'no invoice could be exported')
        included = [ids[k] for k in res.included]        # the rest stay "ready to export"
        total = round(sum(invoices[k][0]['total'] for k in res.included), 2)
        batch = self.db.new_batch(fmt, name, included, res.rows, total)
        failed = self.drop(name)
        if failed:
            warnings.append(failed)
        self.log(f'batch {batch} ({fmt}): {len(included)} invoices, {res.rows} rows')
        return batch, warnings, self.fixed_path() or path

    def fixed_path(self):
        if not (self.drop_folder and self.fixed_name):
            return ''
        return os.path.join(self.drop_folder, self.fixed_name)

    def drop(self, name):
        """Copy the file to the drop folder: with its dated name (history) and again with the fixed
        name, which is what the accounting program's import wizard remembers."""
        if not self.drop_folder:
            return ''
        try:
            os.makedirs(self.drop_folder, exist_ok=True)
            with open(self.path(os.path.join('batches', name)), 'rb') as src:
                content = src.read()
            for as_ in [name] + ([self.fixed_name] if self.fixed_name else []):
                with open(os.path.join(self.drop_folder, as_), 'wb') as dst:
                    dst.write(content)
            return ''
        except OSError as e:
            return f'Could not copy the file to {self.drop_folder}: {e}'

    def undo_batch(self, n):
        """Invoices go back to 'ready to export'. If it was the last one, the fixed-name copy
        becomes the previous live batch, or disappears: an undone file must never stay there."""
        back = self.db.undo_batch(n)
        fixed = self.fixed_path()
        if fixed:
            last = self.db.last_batch()
            try:
                if last:
                    with open(self.path(os.path.join('batches', last['file'])), 'rb') as f:
                        content = f.read()
                    with open(fixed, 'wb') as f:
                        f.write(content)
                elif os.path.exists(fixed):
                    os.remove(fixed)
            except OSError as e:
                self.log(f'could not update {fixed}: {e}')
        return back

    def batch_pdfs(self, n):
        """ZIP with the batch's documents renamed '<entry> - <supplier> - <number>.pdf', to attach
        them in the accounting program with one drag. The entry number is asked to the ledger now
        (read-only); invoices not imported yet come out as 'no entry'."""
        rows = self.db.batch_invoices(n)
        if not rows:
            raise ValueError('that batch has no invoices')
        buf, used = io.BytesIO(), {}
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            for r in rows:
                f = self.db.invoice(r['id'])
                d, e = f['data'], f['entry']
                entry_no = self.ledger.entry_for(e['supplier_account'], e['posting_date'], d['total'])
                base = safe_filename(f'{entry_no or "no entry"} - {f["supplier"] or d["supplier_name"]} - {d["invoice_number"]}')
                used[base] = used.get(base, 0) + 1
                if used[base] > 1:
                    base += f' (p{f["page"]})'
                path = self.path(f['file'])
                if os.path.exists(path):
                    z.write(path, base + (os.path.splitext(f['filename'])[1].lower() or '.pdf'))
        return buf.getvalue()
