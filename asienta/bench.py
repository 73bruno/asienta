"""Benchmark: read a folder of invoices with one or more models and score them against a
hand-checked truth file.

    asienta bench invoices/ --truth truth.json --models gemini-3.8-flash,gemini-3.5-flash-lite
    asienta bench asienta/demo/invoices --truth asienta/demo/truth.json --demo

What it reports per model: fields read right, perfect invoices, supplier and accounts proposed
right, cost and time per document and, above all, SILENT ERRORS: data read wrong that the app
does not flag. A wrong value with a warning is caught at review; a silent one reaches your books.

Truth file (see asienta/demo/truth.json):
  {"invoices": {"<file name>": [{"tax_id", "number", "number_alt": [], "dates": [], "dates_alt": [[]],
     "vat": {"21": [base, vat]}, "surcharge", "withholding", "total",
     "supplier_account", "accounts": {"<account>": base} | null}]}}
"""
import datetime
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

from . import checks, rules, spain
from .app import PRICES, sniff
from .config import Settings, parse_list
from .db import DB
from .extraction import open_reader
from .extraction.schema import build_prompt, invoice_schema
from .ledger import open_ledger
from .ledger.directory import number_key

FIELDS = ['tax_id', 'number', 'dates', 'vat', 'total', 'withholding']
# words in a finding that make a reviewer look at that field (wrong + no such finding = silent)
HINTS = {'tax_id': ('chk.tax_id', 'chk.new_supplier', 'chk.no_tax_id', 'chk.matched_by_name', 'chk.own_tax_id'),
         'dates': ('chk.two_dates', 'chk.future_date', 'chk.old_date', 'chk.no_date'),
         'vat': ('chk.vat_mismatch', 'chk.total_mismatch', 'chk.discount', 'chk.unlined'),
         'total': ('chk.total_mismatch',), 'withholding': ('chk.total_mismatch',),
         'number': ('chk.no_number',)}


def close(a, b, tol=0.011):
    return abs(float(a or 0) - float(b or 0)) <= tol


def compare(d, e):
    """{field: right?} for one invoice read (d) against the expected one (e)."""
    got = {round(t['vat_rate']): (t['base'], t['vat']) for t in d['vat_breakdown']}
    exp = {round(float(k)): v for k, v in e['vat'].items()}
    dates = {x for x in (d['invoice_date'], d['accounting_date']) if x}
    valid = [set(e['dates'])] + [set(x) for x in e.get('dates_alt', [])]
    return {
        'tax_id': spain.normalize_tax_id(d['supplier_tax_id']) == e['tax_id'],
        'number': number_key(d['invoice_number']) in {number_key(x) for x in [e['number']] + e.get('number_alt', [])},
        'dates': dates in valid,
        'vat': set(got) == set(exp) and all(close(got[k][0], b) and close(got[k][1], c) for k, (b, c) in exp.items()),
        'total': close(d['total'], e['total']),
        'withholding': close(d['withholding'], e.get('withholding', 0)) and close(d['surcharge'], e.get('surcharge', 0)),
    }


def pair(read, expected):
    """[(expected, read or None)] by invoice number, else by order."""
    free, out = list(read), []
    for e in expected:
        keys = {number_key(x) for x in [e['number']] + e.get('number_alt', [])}
        r = next((x for x in free if number_key(x['data']['invoice_number']) in keys), None)
        if r is None and free and len(read) == len(expected):
            r = free[0]
        if r is not None:
            free.remove(r)
        out.append((e, r))
    return out


def run(args):
    from .cli import demo_settings
    settings = demo_settings() if args.demo else Settings(args.config)
    truth = json.load(open(args.truth, encoding='utf-8'))['invoices']
    ledger = open_ledger(settings)
    if not ledger.refresh():
        sys.exit(f'ledger not answering: {ledger.error}')
    empty_rules = DB(os.path.join(tempfile.mkdtemp(), 'rules.db'))        # no rules: like day one
    cats = settings.categories()
    split_cfg = rules.SplitConfig(cats, parse_list(settings.get('split', 'only_prefixes', '600')),
                                  parse_list(settings.get('split', 'follow_main', '')),
                                  parse_list(settings.get('split', 'follow_when', '')))
    pinned = settings.get('app', 'today')
    today = datetime.date.fromisoformat(pinned) if pinned else datetime.date.today()
    closed = spain.vat_filed_until(today, settings.get('ledger', 'vat_filed_until', 'auto'))
    company_tid = spain.normalize_tax_id(settings.get('company', 'tax_id'))
    prompt = build_prompt(settings.get('company', 'name'), company_tid, settings.get('company', 'activity'),
                          cats, ledger.accounts_to_suggest(parse_list(settings.get('ledger', 'suggest_prefixes', '6'))),
                          settings.language)
    schema = invoice_schema([c.name for c in cats])
    files = []
    for n in sorted(os.listdir(args.folder)):
        p = os.path.join(args.folder, n)
        if os.path.isfile(p) and n in truth:
            with open(p, 'rb') as f:
                b = f.read()
            mime, _ext = sniff(b)
            if mime:
                files.append((n, mime, b))
    if not files:
        sys.exit('No documents of the truth file found in that folder.')
    models = parse_list(args.models) or [settings.get('reader', 'model', '')]
    report = [f'# Benchmark · {len(files)} documents · {today}', '',
              '| Model | Fields right | Perfect invoices | Silent errors | Supplier right | Accounts right | $/doc | s/doc |',
              '|---|---|---|---|---|---|---|---|']
    detail = []
    for model in models:
        if model:
            settings.cfg.set('reader', 'model', model)
        reader = open_reader(settings)
        prices = PRICES.get(reader.model, (0, 0))

        def one(item):
            name, mime, b = item
            t0 = time.time()
            try:
                r = reader.read(b, mime, prompt, schema, [c.name for c in cats])
            except Exception as e:
                return name, {'error': str(e)}
            out = []
            for d in r.invoices:
                e = rules.propose(d, ledger, empty_rules, split_cfg, closed)
                found = checks.review(d, e, {'directory': ledger, 'company_tax_id': company_tid, 'closed': closed,
                                             'today': today, 'duplicate_in_app': lambda *_: None})
                out.append({'data': d, 'entry': e, 'findings': found})
            return name, {'invoices': out, 'seconds': time.time() - t0,
                          'cost': r.tokens_in / 1e6 * prices[0] + r.tokens_out / 1e6 * prices[1]}

        with ThreadPoolExecutor(3) as pool:
            results = dict(pool.map(one, files))
        right = total = perfect = sup_ok = sup_n = acc_ok = acc_n = 0
        silent, noticed = [], []
        n_inv = sum(len(truth[n]) for n, _m, _b in files)
        for name, _m, _b in files:
            res, expected = results[name], truth[name]
            if 'error' in res:
                noticed.append(f'{name}: could not be read ({res["error"][:80]})')
                total += len(expected) * len(FIELDS)
                continue
            if len(res['invoices']) < len(expected):
                silent.append(f'{name}: {len(expected) - len(res["invoices"])} invoice(s) skipped')
            for e, x in pair(res['invoices'], expected):
                if x is None:
                    total += len(FIELDS)
                    continue
                c = compare(x['data'], e)
                right += sum(c.values())
                total += len(c)
                perfect += all(c.values())
                keys = {f['k'] for f in x['findings'] if f['level'] in ('error', 'warning')}
                for fld, ok in c.items():
                    if not ok:
                        seen = any(k.startswith(h) for k in keys for h in HINTS[fld])
                        where = f'{name} · {e["number"]} · {fld}'
                        (noticed if seen else silent).append(where + ('' if seen else ' (NO WARNING)'))
                sup_n += 1
                sup_ok += x['entry']['supplier_account'] == e['supplier_account']
                if e.get('accounts'):
                    acc_n += 1
                    got = {}
                    for r in x['entry']['split']:
                        got[r['account']] = round(got.get(r['account'], 0) + r['base'], 2)
                    acc_ok += set(got) == set(e['accounts']) and all(close(got[k], v, 0.05) for k, v in e['accounts'].items())
        ok = [r for r in results.values() if 'error' not in r]
        cost = sum(r['cost'] for r in ok) / max(1, len(ok))
        secs = sum(r['seconds'] for r in ok) / max(1, len(ok))
        report.append(f'| {reader.name} | {right}/{total} | {perfect}/{n_inv} | **{len(silent)}** | {sup_ok}/{sup_n} '
                      f'| {acc_ok}/{acc_n} | {cost:.4f} | {secs:.1f} |')
        detail += ['', f'## {reader.name}', '', '**Silent errors:**', ''] + [f'- {s}' for s in silent or ['none']]
        detail += ['', '**Caught by a warning, or unreadable:**', ''] + [f'- {s}' for s in noticed or ['none']]
    text = '\n'.join(report + detail) + '\n'
    out = os.path.join(args.folder, 'bench.md')
    try:
        with open(out, 'w', encoding='utf-8') as f:
            f.write(text)
    except OSError:
        out = None
    print(text)
    if out:
        print(f'Saved to {out}')
