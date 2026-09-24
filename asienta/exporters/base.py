"""What every exporter shares.

An exporter turns approved invoices into the file (or API calls) your accounting program imports.
Each invoice arrives as (data, entry, supplier):

    data      what the invoice says (after the user's review): number, dates, vat_breakdown...
    entry     how it is posted: supplier_account, posting_date, split=[{account, vat_rate, base}]
    supplier  {'account', 'name', 'tax_id'} from the ledger

`journal()` turns one invoice into balanced double-entry postings, so formats that think in
journal lines (Sage 50, ContaPlus) and formats that think in bills (Holded, Xero, QuickBooks)
start from the same validated numbers. An invoice that cannot be exported cleanly is left out
whole, with a warning: a half-written or unbalanced entry never reaches your books.
"""
import re
from dataclasses import dataclass, field


class Skip(Exception):
    """This invoice cannot be exported: carries an i18n key and params."""

    def __init__(self, key, **params):
        super().__init__(key)
        self.key, self.params = key, params


@dataclass
class Context:
    vat_accounts: dict                       # {21.0: '472000021', ...}
    withholding_account: str = ''
    description: str = 'S/ FRA. [{number}] {supplier}'
    description_length: int = 25
    settings: object = None


@dataclass
class Result:
    rows: int = 0
    included: list = field(default_factory=list)     # positions of the invoices written
    warnings: list = field(default_factory=list)     # [(key, params)]


def text(s, length):
    """Trim to fit and drop separators."""
    return ' '.join(str(s or '').replace(';', ' ').replace('\t', ' ').split())[:length]


def description(ctx, data, supplier):
    d = data.get('invoice_date') or ''
    return text(ctx.description.format(number=data.get('invoice_number', ''),
                                       supplier=supplier.get('name') or data.get('supplier_name', ''),
                                       date=f'{d[8:]}/{d[5:7]}' if d else ''), ctx.description_length)


def digits(number, length=8):
    """Invoice number for numeric fields: 'A/26001234' -> '26001234'."""
    d = re.sub(r'\D', '', number or '')[-length:]
    return str(int(d)) if d else '0'


def split_vat(data, entry):
    """[(account, rate, base, vat)]: each split line with its share of the printed VAT, so the VAT
    per rate adds up to exactly what the invoice says (the largest line takes the cents)."""
    out = []
    for t in data['vat_breakdown']:
        rows = [r for r in entry['split'] if abs(r['vat_rate'] - t['vat_rate']) < 0.005 and r['base']]
        if not rows:
            continue
        base_total = sum(r['base'] for r in rows)
        shares = [round(t['vat'] * r['base'] / base_total, 2) if base_total else 0.0 for r in rows]
        biggest = max(range(len(rows)), key=lambda i: abs(rows[i]['base']))
        shares[biggest] = round(t['vat'] - sum(s for i, s in enumerate(shares) if i != biggest), 2)
        out += [(r['account'], t['vat_rate'], r['base'], s) for r, s in zip(rows, shares, strict=True)]
    return out


def journal(data, entry, supplier, ctx):
    """Balanced postings for one purchase invoice:

        expense accounts   DEBIT   base      (one per account of the split)
        input VAT          DEBIT   VAT       (one per rate; carries the VAT-book data)
        withholding        CREDIT  IRPF      (only if any)
        supplier           CREDIT  total
    """
    if data.get('surcharge'):
        raise Skip('exp.surcharge', amount=data['surcharge'])
    lines = []
    by_account = {}
    for r in entry['split']:
        if r['base']:
            by_account[r['account']] = round(by_account.get(r['account'], 0) + r['base'], 2)
    for account, base in by_account.items():
        lines.append({'kind': 'expense', 'account': account, 'debit': base, 'credit': 0.0})
    for t in data['vat_breakdown']:
        if not t['vat']:
            continue
        acc = ctx.vat_accounts.get(round(float(t['vat_rate']), 2))
        if not acc:
            raise Skip('exp.no_vat_account', rate=t['vat_rate'])
        lines.append({'kind': 'vat', 'account': acc, 'debit': t['vat'], 'credit': 0.0,
                      'rate': t['vat_rate'], 'base': t['base']})
    if data.get('withholding'):
        if not ctx.withholding_account:
            raise Skip('exp.no_withholding_account', amount=data['withholding'])
        lines.append({'kind': 'withholding', 'account': ctx.withholding_account, 'debit': 0.0,
                      'credit': data['withholding']})
    lines.append({'kind': 'supplier', 'account': entry['supplier_account'], 'debit': 0.0, 'credit': data['total']})
    diff = round(sum(ln['debit'] - ln['credit'] for ln in lines), 2)
    if diff:
        raise Skip('exp.unbalanced', diff=diff)
    return lines


class Exporter:
    key = ''
    label = ''
    extension = '.csv'
    mime = 'text/csv; charset=utf-8'
    maturity = 'beta'              # 'stable' = used in production · 'beta' = follows the spec, verify first
    docs = ''
    warn_zero_vat = False          # journal formats: a 0 % base gets no VAT-book record

    def __init__(self, settings=None):
        self.settings = settings

    def write(self, path, invoices, ctx):
        """Write the file. Returns Result."""
        raise NotImplementedError

    def each(self, invoices, ctx, build):
        """Run build(i, data, entry, supplier) per invoice, collecting skips as warnings."""
        res, out = Result(), []
        for i, (data, entry, supplier) in enumerate(invoices):
            try:
                rows = build(i, data, entry, supplier)
            except Skip as e:
                res.warnings.append((e.key, dict(e.params, number=data.get('invoice_number', ''),
                                                  supplier=supplier.get('name') or data.get('supplier_name', ''))))
                continue
            for zero in (t for t in data['vat_breakdown'] if self.warn_zero_vat and t['base'] and not t['vat']):
                res.warnings.append(('exp.zero_vat', {'number': data.get('invoice_number', ''),
                                                      'rate': zero['vat_rate'], 'base': zero['base']}))
            out += rows
            res.included.append(i)
        res.rows = len(out)
        return res, out
