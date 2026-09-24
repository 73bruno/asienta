"""How a read invoice is proposed for posting. Plain rules, no AI:

  1. Supplier: the one the user picked > their saved rule (tax ID already linked) > by tax ID
     > by name.
  2. Main expense account: the one the user fixed for that supplier > the usual one in the
     ledger this year > the one the reading suggests from the content.
  3. Split by line: if the main account is a purchases account (600...), each line goes to the
     account of its category (the wine from a food wholesaler goes to drinks). Otherwise
     everything goes to the main account.
  4. Posting date: the invoice date, unless its VAT quarter is already filed; then the first
     day of the first open month.

`reason` is kept as message codes so the UI can show it in any language.
"""
from .spain import posting_date


class SplitConfig:
    """From [categories] and [split] in the config."""

    def __init__(self, categories=(), only_prefixes=('600',), follow_main=(), follow_when=()):
        self.accounts = {c.name: c.account for c in categories if c.account}
        self.only_prefixes = tuple(only_prefixes)
        self.follow_main = set(follow_main)
        # main accounts that make those categories follow them (default: any category account)
        self.follow_when = {self.accounts[c] for c in follow_when if c in self.accounts} or set(self.accounts.values())


def find_supplier(data, directory, rules, chosen=None):
    """(supplier | None, how). how: manual, rule, tax_id, name, similar or ''."""
    if chosen:
        s = directory.supplier(chosen)
        return (s, 'manual') if s else (None, '')
    tid = data.get('supplier_tax_id') or ''
    if tid:
        c = rules.rule_for_tax_id(tid)
        if c and directory.supplier(c):
            return directory.supplier(c), 'rule'
        s = directory.by_tax_id(tid)
        if s:
            return s, 'tax_id'
    s, how = directory.by_name(data.get('supplier_name') or '')
    return (s, how) if s else (None, '')


def main_account(supplier_account, data, directory, rules):
    """(account, [reason], from_rule)."""
    if supplier_account:
        c = rules.rule_for_supplier(supplier_account)
        if c:
            return c, [{'k': 'reason.rule'}], True
        usual = directory.usual(supplier_account)
        if usual:
            c, _amount, n, share = usual[0]
            if share > 0.995:
                return c, [{'k': 'reason.always', 'n': n}], False
            return c, [{'k': 'reason.usual', 'pct': round(100 * share)}], False
    suggested = data.get('suggested_account') or ''
    if suggested and directory.name(suggested):
        return suggested, [{'k': 'reason.content_new' if supplier_account else 'reason.content'}], False
    return '', [{'k': 'reason.pick'}], False


def split(data, main, cfg, allow=True):
    """[{account, vat_rate, base}] for every VAT rate. With a purchases main account, lines are
    separated by category; what doesn't match any line (shipping, fees, discounts) goes to the
    account with the largest amount of that rate. allow=False: everything to the main account
    (the user fixed the supplier's account)."""
    allow = allow and (not main or main.startswith(cfg.only_prefixes))
    # On a drinks or food invoice, "packaging" lines are deposits and returns of crates, bottles
    # and kegs: they follow the main account instead of going to packaging.
    out = []
    for t in data.get('vat_breakdown') or []:
        by_account = {}
        for ln in data.get('lines') or []:
            if abs(ln['vat_rate'] - t['vat_rate']) > 0.01:
                continue
            cat = ln['category']
            if cat in cfg.follow_main and main in cfg.follow_when:
                cat = None
            acc = (cfg.accounts.get(cat) if allow and cat else None) or main
            by_account[acc] = by_account.get(acc, 0.0) + ln['amount']
        if len(by_account) <= 1:
            out.append({'account': next(iter(by_account), main), 'vat_rate': t['vat_rate'], 'base': t['base']})
            continue
        ordered = sorted(by_account.items(), key=lambda x: -abs(x[1]))
        total = sum(v for _a, v in ordered)
        if abs(total - t['base']) <= max(0.05, abs(t['base']) * 0.10):
            parts = [round(v, 2) for _a, v in ordered[1:]]          # the leftover goes to the largest
        else:                                                       # global discount: proportional
            parts = [round(t['base'] * v / total, 2) for _a, v in ordered[1:]] if total else [0.0] * (len(ordered) - 1)
        largest = round(t['base'] - sum(parts), 2)
        for (acc, _v), b in zip(ordered, [largest] + parts, strict=True):
            out.append({'account': acc, 'vat_rate': t['vat_rate'], 'base': b})
    return out


def propose(data, directory, rules, split_cfg, closed, chosen=None):
    """The proposed entry (editable by the user)."""
    supplier, how = find_supplier(data, directory, rules, chosen)
    supplier_account = supplier['account'] if supplier else ''
    main, reason, from_rule = main_account(supplier_account, data, directory, rules)
    lines = split(data, main, split_cfg, allow=not from_rule)
    others = {r['account'] for r in lines if r['account'] and r['account'] != main}
    if others and main:
        reason.append({'k': 'reason.split_rest'})
    elif others:
        reason = [{'k': 'reason.split'}]
    return {
        'supplier_account': supplier_account,
        'supplier_match': how,
        'posting_date': posting_date(data.get('invoice_date') or '', closed),
        'split': lines,
        'reason': reason,
        'remember_account': False,
    }
