"""Checks on an invoice, by code (no AI). Every finding has a level:

  error    -> cannot be approved until fixed (missing data, sums don't match, already booked...)
  warning  -> worth a look, but can be approved
  info     -> for the record

and optionally a one-click fix ({'field', 'value', 'label'}), e.g. "Use B87654323".

The metric that matters is SILENT errors: data misread without any warning. A misread tax ID
that fails its check digit, a total that doesn't add up, a date in the future: each of these
turns a silent error into a visible one.
"""
import datetime

from .spain import first_open_day, in_closed_period, near_miss, tax_id_candidates, tax_id_valid

ORDER = {'error': 0, 'warning': 1, 'info': 2}


def suggest_tax_id(tid, supplier, directory):
    """The most likely correct ID for one that fails its check digit, or None. The ledger wins:
    the chosen supplier's ID; else a candidate that exists in the ledger; else the only one."""
    cand = tax_id_candidates(tid)
    if supplier and supplier.get('tax_id') and (supplier['tax_id'] in cand or near_miss(tid, supplier['tax_id'])):
        return supplier['tax_id'], {'k': 'why.supplier'}
    in_ledger = [c for c in cand if directory.by_tax_id(c)]
    if len(in_ledger) == 1:
        return in_ledger[0], {'k': 'why.ledger', 'name': directory.by_tax_id(in_ledger[0])['name']}
    if len(cand) == 1:
        return cand[0], {'k': 'why.only'}
    return None


def review(data, entry, ctx):
    """ctx: directory, duplicate_in_app(tax_id, number) -> row | None, company_tax_id, closed, today."""
    out = []
    group = 'document'          # which check each finding belongs to (the live-reading screen groups them)

    def add(level, key, fix=None, **params):
        item = {'level': level, 'k': key, 'p': params, 'group': group}
        if fix:
            item['fix'] = fix
        out.append(item)

    d, e, dr = data, entry, ctx['directory']
    today = ctx['today']
    tid = d.get('supplier_tax_id') or ''
    sup = dr.supplier(e.get('supplier_account') or '')

    # ------------------------------------------------------------------ what it is
    if d.get('doc_type') == 'other':
        add('warning', 'chk.not_invoice')
    elif d.get('doc_type') == 'credit_note':
        add('info', 'chk.credit_note')

    # ------------------------------------------------------------------ supplier
    group = 'supplier'
    # If the ledger never loaded we cannot claim a supplier "is missing": we don't know. Saying so
    # would lead people to create suppliers that already exist.
    ready = dr.ready()
    if not ready:
        add('error', 'chk.ledger_down')
    if not sup:
        if not ready:
            pass
        elif tid and tid != ctx['company_tax_id'] and not dr.by_tax_id(tid):
            add('error', 'chk.new_supplier', tax_id=tid)
        else:
            add('error', 'chk.pick_supplier')
    elif e.get('supplier_match') in ('name', 'similar'):
        add('warning', 'chk.matched_by_name')
    if sup and tid:
        others = [p for p in dr.all_by_tax_id(tid) if p['account'] != sup['account']]
        if others:
            o = others[0]
            add('warning', 'chk.several_accounts',
                {'field': 'entry.supplier_account', 'value': o['account'], 'label': {'k': 'fix.use', 'v': o['account']}},
                n=len(others) + 1, tax_id=tid, account=sup['account'], name=sup['name'], bought=sup.get('bought') or 0,
                other=o['account'], other_name=o['name'], other_bought=o.get('bought') or 0)
    if not tid:
        add('warning', 'chk.no_tax_id')
    elif tid == ctx['company_tax_id']:
        add('warning', 'chk.own_tax_id')
    elif tax_id_valid(tid) is False:
        s = suggest_tax_id(tid, sup, dr)
        if s:
            add('warning', 'chk.tax_id_fix',
                {'field': 'data.supplier_tax_id', 'value': s[0], 'label': {'k': 'fix.use', 'v': s[0]}},
                tax_id=tid, good=s[0], why=s[1])
        else:
            add('warning', 'chk.tax_id_invalid', tax_id=tid)
    elif sup and sup['tax_id'] and sup['tax_id'] != tid:
        if near_miss(tid, sup['tax_id']):
            add('warning', 'chk.tax_id_misread',
                {'field': 'data.supplier_tax_id', 'value': sup['tax_id'], 'label': {'k': 'fix.use', 'v': sup['tax_id']}},
                tax_id=tid, ledger=sup['tax_id'])
        else:
            add('warning', 'chk.tax_id_differs', tax_id=tid, ledger=sup['tax_id'])

    # ------------------------------------------------------------------ number and dates
    group = 'dates'
    if not d.get('invoice_number'):
        add('error', 'chk.no_number')
    inv, acc, post = d.get('invoice_date') or '', d.get('accounting_date') or '', e.get('posting_date') or ''
    closed = ctx['closed']
    if not inv:
        add('error', 'chk.no_date')
    if not post:
        add('error', 'chk.no_posting_date')
    if inv and acc and acc != inv:
        other = acc if post != acc else inv
        add('warning', 'chk.two_dates',
            {'field': 'entry.posting_date', 'value': other, 'label': {'k': 'fix.use_date', 'd': other}},
            issue=inv, accounting=acc, used=post)
    if post and in_closed_period(post, closed):
        day = first_open_day(closed).isoformat()
        add('warning', 'chk.closed_quarter',
            {'field': 'entry.posting_date', 'value': day, 'label': {'k': 'fix.use_date', 'd': day}},
            date=post, closed=list(closed))
    elif post and inv and post != inv and post != acc and in_closed_period(inv, closed):
        add('info', 'chk.moved_to_open',
            {'field': 'entry.posting_date', 'value': inv, 'label': {'k': 'fix.use_invoice_date'}},
            date=inv, posted=post)
    try:
        dt = datetime.date.fromisoformat(inv)
        if dt > today + datetime.timedelta(days=1):
            add('warning', 'chk.future_date', date=inv)
        elif (today - dt).days > 365:
            add('warning', 'chk.old_date', date=inv)
    except ValueError:
        pass

    # ------------------------------------------------------------------ amounts
    group = 'amounts'
    vat = d.get('vat_breakdown') or []
    if not vat:
        add('error', 'chk.no_vat')
    for t in vat:
        expected = round(t['base'] * t['vat_rate'] / 100, 2)
        if abs(expected - t['vat']) > 0.02:
            add('warning', 'chk.vat_mismatch', rate=t['vat_rate'], base=t['base'], expected=expected, printed=t['vat'])
    total = round(sum(t['base'] + t['vat'] for t in vat) + d.get('surcharge', 0) - d.get('withholding', 0), 2)
    if vat and abs(total - d.get('total', 0)) > 0.05:
        add('error', 'chk.total_mismatch', sum=total, total=d.get('total', 0))
    elif vat and abs(total - d.get('total', 0)) > 0.02:
        add('warning', 'chk.rounding', diff=abs(total - d['total']))
    lines = d.get('lines') or []
    for t in vat:
        of_rate = [ln for ln in lines if abs(ln['vat_rate'] - t['vat_rate']) < 0.01]
        if not of_rate:
            continue
        s = round(sum(ln['amount'] for ln in of_rate), 2)
        diff = round(t['base'] - s, 2)
        if diff > 0.05:
            add('info', 'chk.unlined', rate=t['vat_rate'], diff=diff)
        elif diff < -0.05:
            add('info', 'chk.discount', rate=t['vat_rate'], sum=s, base=t['base'])
    if d.get('surcharge'):
        add('info', 'chk.surcharge', amount=d['surcharge'])
    if d.get('withholding'):
        add('info', 'chk.withholding', amount=d['withholding'])

    # ------------------------------------------------------------------ split
    group = 'split'
    split = e.get('split') or []
    if any(not r.get('account') for r in split):
        add('error', 'chk.split_no_account')
    for r in split:
        if r.get('account') and not dr.name(r['account']):
            add('warning', 'chk.unknown_account', account=r['account'])
        elif r.get('account') and not r['account'].startswith(dr.expense_prefixes):
            add('warning', 'chk.not_expense', account=r['account'])
    rates = {round(t['vat_rate'], 2): t['base'] for t in vat}
    for rate, base in rates.items():
        s = round(sum(r['base'] for r in split if round(r['vat_rate'], 2) == rate), 2)
        if abs(s - base) > 0.01:
            add('error', 'chk.split_sum', rate=rate, sum=s, base=base)
    for r in split:
        if round(r['vat_rate'], 2) not in rates:
            add('error', 'chk.split_rate', rate=r['vat_rate'])
            break
    if d.get('possible_asset'):
        add('warning', 'chk.asset')

    # ------------------------------------------------------------------ duplicates
    group = 'duplicates'
    if d.get('invoice_number'):
        other = ctx['duplicate_in_app'](tid, d['invoice_number'])
        if other:
            add('error', 'chk.dup_app', id=other['id'], status=other['status'])
    if sup:
        base_total = round(sum(t['base'] for t in vat), 2)
        r = dr.already_booked(sup['account'], d.get('invoice_number') or '', base_total, inv)
        if r and r['by'] == 'number':
            add('error', 'chk.dup_ledger', date=r['date'], base=r['base'])
        elif r:
            add('warning', 'chk.maybe_dup_ledger', number=r['number'])

    # ------------------------------------------------------------------ what the reader said
    group = 'reading'
    for note in d.get('notes') or []:
        add('warning', 'chk.reader_note', note=note)

    return sorted(out, key=lambda x: ORDER[x['level']])
