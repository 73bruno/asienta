"""What the AI is asked for, and how its answer is cleaned up.

The model only READS: it returns what the document says, in a fixed shape. Everything else
(checking the sums, finding the supplier in the ledger, proposing accounts) is done afterwards by
plain rules in rules.py and checks.py. That split is what makes the result auditable.
"""
import datetime
import re

from ..spain import normalize_tax_id

DOC_TYPES = ['invoice', 'credit_note', 'other']


def _obj(props):
    order = list(props)
    return {'type': 'object', 'properties': props, 'required': order, 'additionalProperties': False}


def invoice_schema(categories):
    """JSON Schema of one reading. `categories` are the names from [categories] (+ 'other')."""
    S, N, B = {'type': 'string'}, {'type': 'number'}, {'type': 'boolean'}
    cats = list(dict.fromkeys([c for c in categories if c] + ['other']))
    invoice = _obj({
        'start_page': {'type': 'integer'},
        'doc_type': {'type': 'string', 'enum': DOC_TYPES},
        'supplier_name': S,
        'supplier_tax_id': S,
        'invoice_number': S,
        'invoice_date': S,
        'accounting_date': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
        'lines': {'type': 'array', 'items': _obj({
            'description': S, 'amount': N, 'vat_rate': N,
            'category': {'type': 'string', 'enum': cats}})},
        'vat_breakdown': {'type': 'array', 'items': _obj({'vat_rate': N, 'base': N, 'vat': N})},
        'surcharge': N,
        'withholding': N,
        'total': N,
        'due_dates': {'type': 'array', 'items': _obj({'date': S, 'amount': N})},
        'possible_asset': B,
        'suggested_account': S,
        'notes': {'type': 'array', 'items': S},
    })
    # One document can carry several invoices (a PDF with one invoice per page).
    return _obj({'invoices': {'type': 'array', 'items': invoice}})


PROMPT = """You read purchase invoices received by {company} (tax ID {tax_id}), a {activity}. \
Today is {today}: invoices are from this year or the previous one. Return the data exactly as it \
appears on the document.

- invoices: one per distinct invoice in the document (each with its own number and total). \
Usually one. An invoice may span several pages, and delivery notes or tickets stapled behind it \
are not separate invoices: their amounts are already in the invoice. start_page is the page \
(1, 2...) where each invoice starts.
- doc_type: "invoice"; "credit_note" for a corrective, refund or negative invoice (then bases, \
VAT, lines and total are ALL negative); "other" if it is not an invoice (delivery note, quote, \
order, receipt).
- The supplier is whoever issues the invoice, never {company}. Its tax ID may appear as CIF, NIF, \
VAT or inside the company-registry text.
- Amounts in euros with a dot as decimal separator (1.234,56 becomes 1234.56).
- Dates as YYYY-MM-DD. invoice_date is the issue date. If the invoice shows a different second \
date (for example an "accounting date"), put it in accounting_date; otherwise null.
- vat_breakdown: one entry per VAT rate in the totals box, with its base and VAT as printed.
- lines: every product or service line, with its amount before VAT as printed (even if 0), its \
VAT rate and one category:
{categories}
- surcharge (recargo de equivalencia) and withholding (IRPF): the total amount, or 0.
- possible_asset: true if what is invoiced is furniture, machinery, equipment or building work \
(something that lasts years), false for consumables or everyday services.
- suggested_account: the code of the expense account from this list that best fits the invoice \
as a whole, or "" if none fits:
{accounts}
- Do not invent anything. If something is unreadable or ambiguous, explain it in notes, in \
{language}, in one short sentence. Sums and mismatches between lines, bases and total are checked \
separately: do not report them."""


def build_prompt(company, tax_id, activity, categories, accounts, language='es', today=None):
    """categories: [Category]; accounts: [(code, name)] offered to suggest an account."""
    cats = [f'  {c.name}: {c.description or c.name}' for c in categories]
    cats.append('  other: anything else (services, tableware, furniture...)')
    acc = '\n'.join(f'  {c} {n}' for c, n in accounts) or '  (none)'
    today = today or datetime.date.today()
    return PROMPT.format(company=company or 'the company', tax_id=tax_id or '-',
                         activity=activity or 'business', categories='\n'.join(cats), accounts=acc,
                         today=today.isoformat(), language={'es': 'Spanish', 'en': 'English'}.get(language, 'Spanish'))


# ---------------------------------------------------------------------------- normalize
def num(v):
    """Robust number: accepts 1234.56, '1.234,56', '1234,56', None."""
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = str(v or '').strip().replace('€', '').replace(' ', '')
    if not s:
        return 0.0
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.') if s.rfind(',') > s.rfind('.') else s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def date(v):
    """YYYY-MM-DD or '' (also accepts DD/MM/YYYY)."""
    s = str(v or '').strip()
    m = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', s)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.fullmatch(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})', s)
        if not m:
            return ''
        d, mo, y = m.groups()
    try:
        return datetime.date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return ''


def invoice_number(v):
    """'A / 26001234' -> 'A/26001234' (spaces around / and - removed)."""
    s = ' '.join(str(v or '').split())
    return re.sub(r'\s*([/-])\s*', r'\1', s)


def normalize(d, categories=None):
    """Safe types and rounding. Tax lines with the same rate are merged into one."""
    categories = set(categories or []) | {'other'}
    brackets = {}
    for t in d.get('vat_breakdown') or []:
        k = num(t.get('vat_rate'))
        b, c = brackets.get(k, (0.0, 0.0))
        brackets[k] = (round(b + num(t.get('base')), 2), round(c + num(t.get('vat')), 2))
    kind = d.get('doc_type') if d.get('doc_type') in DOC_TYPES else 'invoice'
    acc_date, inv_date = date(d.get('accounting_date')), date(d.get('invoice_date'))
    lines = [{'description': ' '.join(str(ln.get('description') or '').split()),
              'amount': num(ln.get('amount')), 'vat_rate': num(ln.get('vat_rate')),
              'category': ln.get('category') if ln.get('category') in categories else 'other'}
             for ln in d.get('lines') or []]
    total = num(d.get('total'))
    surcharge = num(d.get('surcharge'))
    # CREDIT NOTES: on paper the base and VAT are often positive and only the total negative.
    # Everything takes the sign of the total so that it adds up and the ledger gets a credit note.
    bases = sum(b for b, _c in brackets.values())
    if total > 0 and kind == 'credit_note':
        total = -total
    if total < 0 and bases > 0:
        brackets = {k: (-b, -c) for k, (b, c) in brackets.items()}
        surcharge = -abs(surcharge)
        if sum(ln['amount'] for ln in lines) > 0:
            for ln in lines:
                ln['amount'] = -ln['amount']
    if total < 0 and kind == 'invoice':
        kind = 'credit_note'
    return {
        'start_page': max(1, int(num(d.get('start_page')) or 1)),
        'doc_type': kind,
        'supplier_name': ' '.join(str(d.get('supplier_name') or '').split()),
        'supplier_tax_id': normalize_tax_id(d.get('supplier_tax_id')),
        'invoice_number': invoice_number(d.get('invoice_number')),
        'invoice_date': inv_date,
        'accounting_date': acc_date if acc_date and acc_date != inv_date else '',
        'lines': lines,
        'vat_breakdown': [{'vat_rate': k, 'base': b, 'vat': c}
                          for k, (b, c) in sorted(brackets.items(), key=lambda x: -x[0])],
        'surcharge': surcharge,
        'withholding': num(d.get('withholding')),
        'total': total,
        'due_dates': [{'date': date(v.get('date')), 'amount': num(v.get('amount'))}
                      for v in d.get('due_dates') or []],
        'possible_asset': bool(d.get('possible_asset')),
        'suggested_account': re.sub(r'\D', '', str(d.get('suggested_account') or '')),
        'notes': [str(x).strip() for x in d.get('notes') or [] if str(x).strip()],
    }


def unwrap(data, categories):
    """The model's JSON -> [normalized invoices]."""
    invoices = data.get('invoices') if isinstance(data, dict) and 'invoices' in data else [data]
    return [normalize(f, categories) for f in invoices if isinstance(f, dict)]
