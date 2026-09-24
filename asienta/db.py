"""The app's database: one SQLite file in the data folder.

  invoices   -> every document received: what the AI read (reading, never modified), the data
                with the user's corrections (data) and the proposed posting (entry).
  batches    -> every file generated for an accounting program.
  rules_*    -> what the user taught it: this tax ID is this supplier, this supplier goes here.
  emails     -> mailbox messages already processed (never processed twice).
  set_aside  -> mailbox attachments that didn't look like invoices (logos, signatures), kept.
  history    -> what happened to each invoice and when.
"""
import datetime
import json
import sqlite3

from .ledger.directory import number_key

VIEWS = {
    'review': ('reading', 'waiting', 'error', 'review'),
    'approved': ('approved',),
    'exported': ('exported', 'posted'),
    'discarded': ('discarded',),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  received TEXT NOT NULL,
  source TEXT NOT NULL,
  source_detail TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  file TEXT NOT NULL,
  filename TEXT NOT NULL,
  mime TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  part INTEGER NOT NULL DEFAULT 1,
  page INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL,
  error TEXT NOT NULL DEFAULT '',
  reading TEXT, data TEXT, entry TEXT,
  model TEXT NOT NULL DEFAULT '', tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0, seconds REAL NOT NULL DEFAULT 0,
  read_at TEXT NOT NULL DEFAULT '',
  batch INTEGER,
  updated TEXT NOT NULL DEFAULT '',
  supplier TEXT NOT NULL DEFAULT '', tax_id TEXT NOT NULL DEFAULT '', supplier_account TEXT NOT NULL DEFAULT '',
  number TEXT NOT NULL DEFAULT '', number_key TEXT NOT NULL DEFAULT '', date TEXT NOT NULL DEFAULT '',
  total REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS i_invoices_status ON invoices(status);
CREATE UNIQUE INDEX IF NOT EXISTS u_invoices_fingerprint ON invoices(fingerprint, part);
CREATE INDEX IF NOT EXISTS i_invoices_number ON invoices(number_key);
CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL, format TEXT NOT NULL, file TEXT NOT NULL,
  invoices INTEGER NOT NULL, rows INTEGER NOT NULL, total REAL NOT NULL, undone TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS rules_tax_id (tax_id TEXT PRIMARY KEY, account TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rules_account (supplier_account TEXT PRIMARY KEY, expense_account TEXT NOT NULL,
                                          created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS emails (message_id TEXT PRIMARY KEY, received TEXT NOT NULL, sender TEXT,
                                   subject TEXT, attachments INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS set_aside (
  id INTEGER PRIMARY KEY AUTOINCREMENT, received TEXT NOT NULL, message_id TEXT NOT NULL,
  sender TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', filename TEXT NOT NULL,
  file TEXT NOT NULL, mime TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
  reason TEXT NOT NULL, invoice INTEGER, dismissed TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS i_set_aside ON set_aside(message_id);
CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice INTEGER NOT NULL,
                                    at TEXT NOT NULL, what TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS i_history ON history(invoice);
"""


def now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


class DB:
    def __init__(self, path):
        self.path = path
        with self._con() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript(SCHEMA)

    def _con(self):
        c = sqlite3.connect(self.path, timeout=20)
        c.row_factory = sqlite3.Row
        return c

    def _one(self, sql, args=()):
        with self._con() as c:
            r = c.execute(sql, args).fetchone()
        return dict(r) if r else None

    def _all(self, sql, args=()):
        with self._con() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def _do(self, sql, args=()):
        with self._con() as c:
            return c.execute(sql, args).lastrowid

    # ------------------------------------------------------------------ invoices
    def new(self, source, detail, file, filename, mime, fingerprint, email=''):
        i = self._do("""INSERT INTO invoices (received, source, source_detail, file, filename, mime, fingerprint,
                        status, updated, email) VALUES (?,?,?,?,?,?,?, 'reading', ?,?)""",
                     (now(), source, detail[:300], file, filename[:200], mime, fingerprint, now(), email[:300]))
        self.log(i, f'received ({source})')
        return i

    def by_fingerprint(self, fingerprint, part=1):
        return self._one('SELECT id, status FROM invoices WHERE fingerprint=? AND part=?', (fingerprint, part))

    def new_part(self, origin_id, part, page, reading, data, entry, supplier_name, model):
        """Another invoice inside the SAME file (a PDF carrying several). Arrives already read."""
        o = self.invoice(origin_id)
        with self._con() as c:
            i = c.execute("""INSERT INTO invoices (received, source, source_detail, email, file, filename, mime,
                             fingerprint, part, page, status, reading, data, entry, model, read_at, updated,
                             supplier, tax_id, supplier_account, number, number_key, date, total)
                             VALUES (?,?,?,?,?,?,?,?,?,?, 'review', ?,?,?,?,?,?, ?,?,?,?,?,?,?)""",
                          (o['received'], o['source'], o['source_detail'], o['email'], o['file'], o['filename'],
                           o['mime'], o['fingerprint'], part, page, json.dumps(reading, ensure_ascii=False),
                           json.dumps(data, ensure_ascii=False), json.dumps(entry, ensure_ascii=False), model,
                           now(), now()) + self._derived(data, entry, supplier_name)).lastrowid
        self.log(i, f'invoice {part} of the same file as #{origin_id} (starts on page {page})')
        return i

    def invoice(self, i):
        f = self._one('SELECT * FROM invoices WHERE id=?', (i,))
        if f:
            for k in ('reading', 'data', 'entry'):
                f[k] = json.loads(f[k]) if f[k] else None
        return f

    def listing(self, view):
        statuses = VIEWS.get(view, VIEWS['review'])
        return self._all(f"""SELECT id, received, source, status, error, supplier, tax_id, supplier_account,
                                    number, date, total, batch, filename
                             FROM invoices WHERE status IN ({','.join('?' * len(statuses))})
                             ORDER BY {'received DESC, id DESC' if view != 'review' else 'id'}""", statuses)

    def counts(self):
        return {r['status']: r['n'] for r in self._all('SELECT status, COUNT(*) n FROM invoices GROUP BY status')}

    def with_status(self, *statuses):
        return self._all(f"""SELECT id, status, updated, received FROM invoices
                             WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY id""", statuses)

    def _derived(self, data, entry, supplier_name):
        return (supplier_name or data.get('supplier_name', ''), data.get('supplier_tax_id', ''),
                entry.get('supplier_account', ''), data.get('invoice_number', ''),
                number_key(data.get('invoice_number', '')), data.get('invoice_date', ''), data.get('total', 0))

    def save_reading(self, i, reading, data, entry, supplier_name, model, tokens_in, tokens_out, cost, seconds, page=1):
        with self._con() as c:
            c.execute("""UPDATE invoices SET status='review', error='', page=?, reading=?, data=?, entry=?, model=?,
                         tokens_in=?, tokens_out=?, cost=?, seconds=?, read_at=?, updated=?,
                         supplier=?, tax_id=?, supplier_account=?, number=?, number_key=?, date=?, total=?
                         WHERE id=?""",
                      (page, json.dumps(reading, ensure_ascii=False), json.dumps(data, ensure_ascii=False),
                       json.dumps(entry, ensure_ascii=False), model, tokens_in, tokens_out, cost, round(seconds, 1),
                       now(), now()) + self._derived(data, entry, supplier_name) + (i,))
        self.log(i, f'read with {model} in {seconds:.0f} s')

    def save_error(self, i, text):
        self._do("UPDATE invoices SET status='error', error=?, updated=? WHERE id=?", (text[:500], now(), i))
        self.log(i, f'could not be read: {text[:200]}')

    def save(self, i, data, entry, supplier_name):
        with self._con() as c:
            c.execute("""UPDATE invoices SET data=?, entry=?, updated=?, supplier=?, tax_id=?, supplier_account=?,
                         number=?, number_key=?, date=?, total=? WHERE id=?""",
                      (json.dumps(data, ensure_ascii=False), json.dumps(entry, ensure_ascii=False), now())
                      + self._derived(data, entry, supplier_name) + (i,))

    def set_status(self, i, status, what, batch=None):
        self._do('UPDATE invoices SET status=?, batch=?, updated=? WHERE id=?', (status, batch, now(), i))
        self.log(i, what)

    def duplicate(self, tax_id, account, number, exclude):
        """Another invoice in the app with the same number and the same tax ID or supplier."""
        nk = number_key(number)
        if not nk or not (tax_id or account):
            return None
        return self._one("""SELECT id, status FROM invoices
                            WHERE number_key=? AND id<>? AND status NOT IN ('discarded', 'reading', 'error')
                              AND ((tax_id<>'' AND tax_id=?) OR (supplier_account<>'' AND supplier_account=?))
                            ORDER BY id LIMIT 1""", (nk, exclude, tax_id or '-', account or '-'))

    def neighbours(self, i, view):
        """(previous, next) within the same list, to go through them one by one."""
        ids = [f['id'] for f in self.listing(view)]
        if i not in ids:
            return None, None
        k = ids.index(i)
        return (ids[k - 1] if k > 0 else None), (ids[k + 1] if k + 1 < len(ids) else None)

    def log(self, i, what):
        self._do('INSERT INTO history (invoice, at, what) VALUES (?,?,?)', (i, now(), what))

    def history(self, i):
        return self._all('SELECT at, what FROM history WHERE invoice=? ORDER BY id', (i,))

    def month_cost(self, yyyy_mm):
        r = self._one("SELECT COUNT(*) n, COALESCE(SUM(cost), 0) c FROM invoices WHERE read_at LIKE ?", (yyyy_mm + '%',))
        return r['n'], round(r['c'], 4)

    # ------------------------------------------------------------------ batches
    def new_batch(self, fmt, file, ids, rows, total):
        with self._con() as c:
            b = c.execute('INSERT INTO batches (created, format, file, invoices, rows, total) VALUES (?,?,?,?,?,?)',
                          (now(), fmt, file, len(ids), rows, total)).lastrowid
            c.executemany("UPDATE invoices SET status='exported', batch=?, updated=? WHERE id=?",
                          [(b, now(), i) for i in ids])
        for i in ids:
            self.log(i, f'exported in batch #{b} ({fmt})')
        return b

    def batch_invoices(self, n):
        return self._all('SELECT id FROM invoices WHERE batch=? ORDER BY id', (n,))

    def batch(self, n):
        return self._one('SELECT * FROM batches WHERE id=?', (n,))

    def batches(self):
        return self._all("""SELECT b.*, (SELECT COUNT(*) FROM invoices f WHERE f.batch=b.id AND f.status='posted')
                            posted FROM batches b ORDER BY id DESC""")

    def last_batch(self):
        """The last batch still alive (not undone): the one to import."""
        return self._one("""SELECT b.*, (SELECT COUNT(*) FROM invoices f WHERE f.batch=b.id AND f.status='posted') posted
                            FROM batches b WHERE b.undone = '' ORDER BY b.id DESC LIMIT 1""")

    def undo_batch(self, n):
        ids = [r['id'] for r in self._all("SELECT id FROM invoices WHERE batch=? AND status='exported'", (n,))]
        with self._con() as c:
            c.execute('UPDATE batches SET undone=? WHERE id=?', (now(), n))
            c.executemany("UPDATE invoices SET status='approved', batch=NULL, updated=? WHERE id=?",
                          [(now(), i) for i in ids])
        for i in ids:
            self.log(i, f'back to "ready to export": batch #{n} undone')
        return len(ids)

    # ------------------------------------------------------------------ mailbox
    def add_set_aside(self, o):
        return self._do("""INSERT INTO set_aside (received, message_id, sender, subject, filename, file, mime, size,
                           reason) VALUES (?,?,?,?,?,?,?,?,?)""",
                        (now(), o['message_id'], o['sender'], o['subject'], o['filename'], o['file'], o['mime'],
                         o['size'], o['reason']))

    def set_aside_item(self, i):
        return self._one('SELECT * FROM set_aside WHERE id=?', (i,))

    def set_aside_used(self, i, invoice):
        self._do('UPDATE set_aside SET invoice=? WHERE id=?', (invoice, i))

    def dismiss_set_aside(self, i):
        self._do("UPDATE set_aside SET dismissed=? WHERE id=? AND invoice IS NULL", (now(), i))

    def open_set_aside(self):
        return self._one("SELECT COUNT(*) n FROM set_aside WHERE invoice IS NULL AND dismissed = ''")['n']

    def mailbox(self, limit=20, offset=0, flt='all'):
        """Latest emails with what each brought (and how it ended) and what was set aside."""
        where = {'set_aside': """WHERE EXISTS (SELECT 1 FROM set_aside a WHERE a.message_id = e.message_id
                                 AND a.invoice IS NULL AND a.dismissed = '')""",
                 'none': 'WHERE e.attachments = 0'}.get(flt, '')
        emails = self._all(f"""SELECT e.* FROM emails e {where}
                               ORDER BY e.received DESC, e.rowid DESC LIMIT ? OFFSET ?""", (limit + 1, offset))
        more = len(emails) > limit
        emails = emails[:limit]
        counts = {
            'all': self._one('SELECT COUNT(*) n FROM emails')['n'],
            'set_aside': self._one("""SELECT COUNT(DISTINCT message_id) n FROM set_aside
                                      WHERE invoice IS NULL AND dismissed = ''""")['n'],
            'none': self._one('SELECT COUNT(*) n FROM emails WHERE attachments = 0')['n'],
        }
        if not emails:
            return {'emails': [], 'more': False, 'counts': counts}
        ids = [e['message_id'] for e in emails]
        holes = ','.join('?' * len(ids))
        invoices, aside = {}, {}
        for f in self._all(f"""SELECT id, email, status, supplier, number, total, date, filename FROM invoices
                               WHERE email IN ({holes}) ORDER BY id""", ids):
            invoices.setdefault(f['email'], []).append(f)
        for a in self._all(f'SELECT * FROM set_aside WHERE message_id IN ({holes}) ORDER BY id', ids):
            aside.setdefault(a['message_id'], []).append(a)
        for e in emails:
            e['invoices'] = invoices.get(e['message_id'], [])
            e['set_aside'] = aside.get(e['message_id'], [])
        return {'emails': emails, 'more': more, 'counts': counts}

    def email_seen(self, message_id):
        return self._one('SELECT 1 x FROM emails WHERE message_id=?', (message_id,)) is not None

    def add_email(self, message_id, sender, subject, attachments):
        self._do('INSERT OR IGNORE INTO emails VALUES (?,?,?,?,?)',
                 (message_id, now(), sender[:200], subject[:300], attachments))

    # ------------------------------------------------------------------ rules
    def rule_for_tax_id(self, tax_id):
        r = self._one('SELECT account FROM rules_tax_id WHERE tax_id=?', (tax_id,))
        return r['account'] if r else None

    def rule_for_supplier(self, supplier_account):
        r = self._one('SELECT expense_account FROM rules_account WHERE supplier_account=?', (supplier_account,))
        return r['expense_account'] if r else None

    def set_tax_id_rule(self, tax_id, account):
        self._do('INSERT OR REPLACE INTO rules_tax_id (tax_id, account, created) VALUES (?,?,?)', (tax_id, account, now()))

    def set_account_rule(self, supplier_account, expense_account):
        self._do('INSERT OR REPLACE INTO rules_account (supplier_account, expense_account, created) VALUES (?,?,?)',
                 (supplier_account, expense_account, now()))
