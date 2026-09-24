"""The ledger from plain files, for any accounting software that can export a list.

A folder with (only accounts.csv is required; UTF-8 or Windows-1252, comma or semicolon):

  accounts.csv   account,name[,tax_id][,vat_rate]   the chart of accounts, suppliers included
  history.csv    supplier_account,expense_account,amount[,invoices]
                 what each supplier's invoices were booked to this year (drives the proposals)
  booked.csv     supplier_account,number,date,base
                 invoices already in the ledger (to catch duplicates)

Or, for Sage 50 / ContaPlus without touching SQL: the subaccounts file that Sage's free
"Importación/Exportación de asientos" add-on exports (XSUBCTA, .csv), with [ledger]
contaplus_accounts = path/to/file.csv. It brings names, tax IDs and each VAT account's rate.
"""
import csv
import io
import os
import re

from ..spain import normalize_tax_id


def read_text(path):
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1')


def rows(path):
    """Rows of a CSV as dicts with lower-case keys, sniffing ',' or ';'."""
    if not path or not os.path.exists(path):
        return []
    text = read_text(path)
    first = text.split('\n', 1)[0]
    delim = ';' if first.count(';') > first.count(',') else ','
    return [{(k or '').strip().lower(): (v or '').strip() for k, v in r.items()}
            for r in csv.DictReader(io.StringIO(text), delimiter=delim)]


def amount(v):
    s = str(v or '0').strip().replace(' ', '')
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.') if s.rfind(',') > s.rfind('.') else s.replace(',', '')
    else:
        s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def code(v):
    return re.sub(r'\D', '', str(v or ''))


def contaplus_accounts(path):
    """Sage 50 / ContaPlus XSUBCTA export: field 1 code, 2 title, 3 NIF, 12 VAT type, 18 rate."""
    names, tax_ids, rates = {}, {}, {}
    for line in read_text(path).replace('\r\n', '\n').split('\n'):
        f = line.split(';')
        if len(f) < 18 or not code(f[0]):
            continue
        c = code(f[0])
        names[c] = f[1].strip()
        if f[2].strip():
            tax_ids[c] = normalize_tax_id(f[2])
        if f[11].strip() and amount(f[17]):
            rates[c] = round(amount(f[17]), 2)
    return names, tax_ids, rates


class CSVSource:
    kind = 'csv'

    def __init__(self, folder, contaplus=''):
        self.folder = folder
        self.contaplus = contaplus

    def load(self):
        f = lambda n: os.path.join(self.folder, n)
        names, tax_ids, rates = {}, {}, {}
        if self.contaplus:
            if not os.path.exists(self.contaplus):
                raise FileNotFoundError(self.contaplus)
            names, tax_ids, rates = contaplus_accounts(self.contaplus)
        elif not os.path.exists(f('accounts.csv')):
            raise FileNotFoundError(f'{f("accounts.csv")} (see docs/ledger.md)')
        for r in rows(f('accounts.csv')):
            c = code(r.get('account') or r.get('cuenta'))
            if not c:
                continue
            names[c] = r.get('name') or r.get('nombre') or names.get(c, '')
            tid = r.get('tax_id') or r.get('nif') or r.get('cif')
            if tid:
                tax_ids[c] = normalize_tax_id(tid)
            if r.get('vat_rate'):
                rates[c] = round(amount(r['vat_rate']), 2)
        usual = {}
        for r in rows(f('history.csv')):
            s, e = code(r.get('supplier_account')), code(r.get('expense_account'))
            if s and e:
                prev = usual.setdefault(s, {}).get(e, (0.0, 0))
                usual[s][e] = (round(prev[0] + amount(r.get('amount')), 2),
                               prev[1] + int(amount(r.get('invoices') or 1)))
        booked = {}
        for r in rows(f('booked.csv')):
            s = code(r.get('supplier_account'))
            if s:
                booked.setdefault(s, []).append({'number': r.get('number', ''), 'date': r.get('date', ''),
                                                 'base': amount(r.get('base'))})
        return {'names': names, 'tax_ids': tax_ids, 'usual': usual, 'invoices': booked,
                'vat_usage': {}, 'vat_rates': rates}
