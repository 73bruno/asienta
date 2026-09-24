"""What Asienta needs to know from your accounting, READ-ONLY: suppliers (account, name, tax ID),
which expense accounts each supplier usually goes to, the chart of accounts and the invoices
already booked (to catch duplicates).

Asienta never writes into your accounting database. Invoices go in through your software's own
importer, with the file an exporter generates.

The Directory is an in-memory cache over a *source* (CSV files, Sage 50's SQL Server, ...). A
source is any object with:

    kind: str
    load() -> {'names': {account: name}, 'tax_ids': {supplier_account: tax_id},
               'usual': {supplier_account: {expense_account: (amount, invoices)}},
               'invoices': {supplier_account: [{'number', 'date', 'base'}]},
               'vat_usage': {account: uses}, 'vat_rates': {account: rate}}   (the last two optional)
    entry_for(supplier_account, date, total) -> entry number or ''       (optional)
"""
import difflib
import re
import threading
import time
import unicodedata
from collections import defaultdict


def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s or '')) if unicodedata.category(c) != 'Mn')


LEGAL_FORMS = r'\b(S\s*L\s*U?|S\s*A\s*U?|S\s*C\s*P?|C\s*B|S\s*COOP|SOCIEDAD LIMITADA|SOCIEDAD ANONIMA|SLL|SLU|SL|SA)\b'


def name_key(s):
    """'Frutas La Huerta, S.L.' -> 'FRUTAS LA HUERTA' (to compare supplier names)."""
    s = strip_accents(s).upper().replace('.', ' ').replace(',', ' ')
    s = re.sub(LEGAL_FORMS, ' ', s)
    return ' '.join(re.sub(r'[^A-Z0-9 ]', ' ', s).split())


def number_key(s):
    """Comparable invoice number: letters and digits only, no leading zeros."""
    s = re.sub(r'[^0-9A-Z]', '', strip_accents(s).upper())
    return s.lstrip('0') or s


def digits_key(s, n=6):
    """The last n digits, without leading zeros. Sage 50 stores only the digits of the supplier's
    invoice number, without its prefix (A/26001234 -> 001234), so this is how both compare."""
    d = re.sub(r'\D', '', s or '')[-n:]
    return d.lstrip('0') or d


EMPTY = {'names': {}, 'tax_ids': {}, 'usual': {}, 'invoices': {}, 'vat_usage': {}, 'vat_rates': {}}


class Directory:
    """Thread-safe: on refresh the whole snapshot is replaced at once."""

    def __init__(self, source, minutes=30, supplier_prefixes=('400', '410'), expense_prefixes=('6', '2'),
                 vat_prefix='472'):
        self.source = source
        self.minutes = minutes
        self.supplier_prefixes = tuple(supplier_prefixes)
        self.expense_prefixes = tuple(expense_prefixes)
        self.vat_prefix = vat_prefix
        self.d = dict(EMPTY)
        self.loaded = None                 # time.time() of the last good load
        self.error = ''
        self._lock = threading.Lock()
        self._by_tax_id = {}
        self._by_name = {}

    # -------------------------------------------------------------- loading
    def refresh(self, force=False):
        with self._lock:
            if not force and not self.stale():            # another thread just loaded
                return True
            try:
                d = dict(EMPTY, **self.source.load())
            except Exception as e:                        # offline: keep what we had
                self.error = f'{e.__class__.__name__}: {e}'[:300]
                return False
            by_tax_id, by_name = defaultdict(list), defaultdict(list)
            # The same tax ID can sit on several supplier accounts (a duplicate, or a supplier that
            # changed name). Sort by what was bought this year: the account in real use wins.
            bought = lambda c: sum(v[0] for v in d['usual'].get(c, {}).values())
            for code, tid in d['tax_ids'].items():
                if tid:
                    by_tax_id[tid].append(code)
            by_tax_id = {t: sorted(cs, key=lambda c: (-bought(c), c)) for t, cs in by_tax_id.items()}
            for code, name in d['names'].items():
                if code.startswith(self.supplier_prefixes):
                    by_name[name_key(name)].append(code)
            self.d, self._by_tax_id, self._by_name = d, by_tax_id, dict(by_name)
            self.loaded, self.error = time.time(), ''
            return True

    def ready(self):
        """Has the ledger loaded at least once? If not, we cannot say a supplier 'is missing':
        we simply don't know."""
        return self.loaded is not None

    def stale(self):
        return self.loaded is None or time.time() - self.loaded > self.minutes * 60

    def status(self):
        return {'kind': self.source.kind, 'loaded': self.loaded, 'error': self.error,
                'suppliers': sum(1 for c in self.d['names'] if c.startswith(self.supplier_prefixes)),
                'with_tax_id': len(self._by_tax_id)}

    # -------------------------------------------------------------- lookups
    def name(self, account):
        return self.d['names'].get(account, '')

    def is_supplier(self, account):
        return account in self.d['names'] and account.startswith(self.supplier_prefixes)

    def _bought(self, account):
        return round(sum(v[0] for v in self.d['usual'].get(account, {}).values()), 2)

    def supplier(self, account):
        if not self.is_supplier(account or ''):
            return None
        return {'account': account, 'name': self.name(account), 'tax_id': self.d['tax_ids'].get(account, ''),
                'bought': self._bought(account)}

    def by_tax_id(self, tax_id):
        cs = self._by_tax_id.get(tax_id or '') or []
        return self.supplier(cs[0]) if cs else None

    def all_by_tax_id(self, tax_id):
        """Every supplier account with that tax ID, the most used first."""
        return [p for c in (self._by_tax_id.get(tax_id or '') or []) if (p := self.supplier(c))]

    def by_name(self, name):
        """Supplier by name: identical (ignoring S.L., accents...) or very similar and unambiguous.
        Returns (supplier, 'name'|'similar') or (None, '')."""
        k = name_key(name)
        if not k:
            return None, ''
        same = self._by_name.get(k, [])
        if len(same) == 1:
            return self.supplier(same[0]), 'name'
        if same:
            return None, ''                               # several with that name: let the user pick
        # similar: high threshold (0.82 already produced false matches on real data)
        best = difflib.get_close_matches(k, list(self._by_name), n=2, cutoff=0.9)
        if len(best) == 1 and len(self._by_name[best[0]]) == 1:
            return self.supplier(self._by_name[best[0]][0]), 'similar'
        return None, ''

    def search(self, text, limit=20):
        """Suppliers by tax ID, account code or pieces of the name."""
        t = text.strip()
        if not t:
            return []
        tn = re.sub(r'[^0-9A-Za-z]', '', t).upper()
        words = name_key(t).split()
        out = []
        for code, name in self.d['names'].items():
            if not code.startswith(self.supplier_prefixes):
                continue
            tid = self.d['tax_ids'].get(code, '')
            k = name_key(name)
            if (tn and (code.startswith(tn) or (tid and tn in tid))) or (words and all(w in k for w in words)):
                out.append({'account': code, 'name': name, 'tax_id': tid, 'bought': self._bought(code)})
        out.sort(key=lambda p: (-p['bought'], p['name']))
        return out[:limit]

    def usual(self, supplier_account):
        """[(expense_account, amount, invoices, share)] this year, largest first."""
        h = self.d['usual'].get(supplier_account, {})
        total = sum(v[0] for v in h.values() if v[0] > 0)
        rows = [(c, round(v[0], 2), v[1], (v[0] / total if total else 0)) for c, v in h.items() if v[0] > 0]
        return sorted(rows, key=lambda x: -x[1])

    def expense_accounts(self):
        """Expense and asset accounts, with this year's usage."""
        used = defaultdict(float)
        for h in self.d['usual'].values():
            for c, (amount, _n) in h.items():
                used[c] += amount
        out = [{'account': c, 'name': n, 'used': round(used.get(c, 0), 2)}
               for c, n in self.d['names'].items() if c.startswith(self.expense_prefixes) and len(c) >= 6]
        return sorted(out, key=lambda x: x['account'])

    def input_vat_accounts(self):
        """{rate: account} for input VAT, from the chart of accounts. A rate configured in the ledger
        wins; otherwise the rate written in the name ('H.P. IVA Soportado 21%', 'Input VAT 21%'). Output,
        intra-EU, reverse charge and surcharge accounts are left out; with several per rate, the most
        used wins."""
        out = {}
        rates = self.d.get('vat_rates') or {}
        for code, name in self.d['names'].items():
            if not code.startswith(self.vat_prefix):
                continue
            rate = rates.get(code)
            if rate is None:
                n = strip_accents(name).upper()
                if not re.search(r'\b(IVA|VAT)\b', n) or any(x in n for x in (
                        'INTRACOMUNITARI', 'INVERSION', 'REPERCUT', 'RECARGO', 'OUTPUT', 'INTRA-EU', 'REVERSE', 'SURCHARGE')):
                    continue
                m = re.search(r'(\d{1,2})(?:[.,](\d{1,2}))?\s*%', n)
                if not m:
                    continue
                rate = float(f'{int(m.group(1))}.{m.group(2) or 0}')
            rate = round(float(rate), 2)
            uses = self.d['vat_usage'].get(code, 0)
            if rate not in out or (uses, code) > (self.d['vat_usage'].get(out[rate], 0), out[rate]):
                out[rate] = code
        return out

    def accounts_to_suggest(self, prefixes):
        """The accounts shown to the AI: used this year and within the prefixes."""
        return [(c['account'], c['name']) for c in self.expense_accounts()
                if c['used'] > 0 and c['account'].startswith(tuple(prefixes))]

    def entry_for(self, supplier_account, date, total):
        """Number of the ledger entry holding this invoice, or '' if unknown."""
        find = getattr(self.source, 'entry_for', None)
        if not find or not (supplier_account and date):
            return ''
        try:
            return find(supplier_account, date, total)
        except Exception as e:                            # ledger down: carry on without it
            self.error = f'{e.__class__.__name__}: {e}'[:300]
            return ''

    def already_booked(self, supplier_account, number, base_total=None, date=''):
        """Is this invoice already in the ledger's VAT book? By number and, failing that, by the
        same base in the same month. Returns {'number','date','base','by'} or None."""
        rows = self.d['invoices'].get(supplier_account, [])
        nk, nd = number_key(number), digits_key(number)
        for r in rows:
            if nk and (number_key(r['number']) == nk or (nd and digits_key(r['number']) == nd)):
                return dict(r, by='number')
        if base_total is not None and date:
            for r in rows:
                if abs(r['base'] - base_total) <= 0.01 and r['date'][:7] == date[:7]:
                    return dict(r, by='amount')
        return None
