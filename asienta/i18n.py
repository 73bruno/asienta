"""Server-side messages (check findings, proposal reasons) in Spanish and English.

Findings are stored as codes with parameters and rendered in the reader's language when sent to
the browser, so switching language never needs a re-read. Adding a language = adding a dict.
"""
import datetime

MONEY = {'base', 'expected', 'printed', 'sum', 'total', 'diff', 'amount', 'bought', 'other_bought'}
RATES = {'rate'}
DATES = {'date', 'issue', 'accounting', 'used', 'posted', 'd'}

M = {
    'es': {
        'reason.rule': 'la cuenta que fijaste para este proveedor',
        'reason.always': 'la de siempre con este proveedor ({n} facturas este año)',
        'reason.usual': 'la más habitual con este proveedor ({pct} % de lo de este año)',
        'reason.content': 'por el contenido de la factura',
        'reason.content_new': 'por el contenido de la factura, es un proveedor sin compras este año',
        'reason.pick': 'elige la cuenta',
        'reason.split_rest': 'lo demás, separado por lo que es cada línea',
        'reason.split': 'separado por lo que es cada línea',

        'why.supplier': 'es el que tiene la contabilidad para este proveedor',
        'why.ledger': 'es el de {name} en la contabilidad',
        'why.only': 'es el único válido cambiando un carácter',
        'fix.use': 'Usar {v}',
        'fix.use_date': 'Usar {d}',
        'fix.use_invoice_date': 'Usar la de la factura',

        'chk.not_invoice': 'No parece una factura (¿albarán, presupuesto o pedido?). Si no lo es, descártala.',
        'chk.credit_note': 'Es un abono: los importes van en negativo.',
        'chk.ledger_down': 'La contabilidad no responde, así que no se ha podido comprobar ni el proveedor ni si '
                           'esta factura ya está contabilizada. Vuelve a abrirla cuando vuelva la conexión.',
        'chk.new_supplier': 'Proveedor nuevo: su NIF ({tax_id}) no está en la contabilidad. Dalo de alta y '
                            'luego elígelo aquí.',
        'chk.pick_supplier': 'Elige el proveedor.',
        'chk.matched_by_name': 'Proveedor encontrado por el nombre, no por el NIF: comprueba que es este.',
        'chk.several_accounts': 'Hay {n} cuentas con el NIF {tax_id}. Se usa {account} {name} ({bought} este '
                                'año), la que más se usa; la otra es {other} {other_name} ({other_bought}).',
        'chk.no_tax_id': 'No se ha leído el NIF del proveedor.',
        'chk.own_tax_id': 'Ha leído el NIF de tu empresa en vez del del proveedor.',
        'chk.tax_id_fix': 'El NIF {tax_id} no es válido: seguramente es {good} ({why}).',
        'chk.tax_id_invalid': 'El NIF {tax_id} no es válido: puede estar mal leído.',
        'chk.tax_id_misread': 'El NIF de la factura ({tax_id}) no coincide con el de la contabilidad '
                              '({ledger}): seguramente está mal leído.',
        'chk.tax_id_differs': 'El NIF de la factura ({tax_id}) no coincide con el de la contabilidad ({ledger}).',
        'chk.no_number': 'Falta el número de factura.',
        'chk.no_date': 'Falta la fecha de la factura.',
        'chk.no_posting_date': 'Falta la fecha del asiento.',
        'chk.two_dates': 'La factura trae dos fechas: {issue} (emisión) y {accounting} (contable). '
                         'Ahora se usa la del {used}.',
        'chk.closed_quarter': 'El {date} cae en un trimestre con el IVA ya presentado (hasta el {closed}).',
        'chk.moved_to_open': 'Es del {date}, pero ese trimestre ya tiene el IVA presentado: se contabiliza '
                             'el {posted}.',
        'chk.future_date': 'La fecha de la factura ({date}) es futura: puede estar mal leída.',
        'chk.old_date': 'La factura es de hace más de un año ({date}).',
        'chk.no_vat': 'No hay bases de IVA.',
        'chk.vat_mismatch': 'IVA del {rate}: {base} × {rate} = {expected}, pero pone {printed}.',
        'chk.total_mismatch': 'Bases más IVA suman {sum}, pero el total de la factura es {total}.',
        'chk.rounding': 'Hay {diff} de diferencia por redondeo en el total.',
        'chk.unlined': 'En el {rate} hay {diff} que no están en ninguna línea (tasas, portes…). '
                       'Van a la cuenta con más importe.',
        'chk.discount': 'Las líneas del {rate} suman {sum} y la base es {base} (¿descuento?).',
        'chk.surcharge': 'Lleva recargo de equivalencia ({amount}).',
        'chk.withholding': 'Lleva retención de IRPF ({amount}).',
        'chk.split_no_account': 'Falta la cuenta en alguna línea de «Se contabiliza así».',
        'chk.unknown_account': 'La cuenta {account} no está en el plan de cuentas.',
        'chk.not_expense': 'La cuenta {account} no es de gasto ni de inversión.',
        'chk.split_sum': '«Se contabiliza así» suma {sum} en el {rate} y la base es {base}.',
        'chk.split_rate': 'Hay una línea al {rate} y la factura no tiene ese IVA.',
        'chk.asset': 'Parece una inversión (mobiliario, maquinaria u obra): mira si va a inmovilizado '
                     'en vez de a gasto.',
        'chk.dup_app': 'Ya está en la app: la factura n.º {id} ({status}).',
        'chk.dup_ledger': 'Ya está contabilizada: registrada con fecha {date} por {base}.',
        'chk.maybe_dup_ledger': 'Puede que ya esté contabilizada: hay una de este proveedor del mismo mes y con '
                                'la misma base (n.º {number}).',
        'chk.reader_note': 'La lectura avisa: {note}',

        'exp.surcharge': '{number} ({supplier}) se queda fuera: lleva recargo de equivalencia ({amount}), '
                         'que este formato no admite.',
        'exp.no_vat_account': '{number} ({supplier}) se queda fuera: no sé qué cuenta de IVA soportado usar '
                              'para el {rate}. Ponla en config.ini, [accounts] input_vat.',
        'exp.no_withholding_account': '{number} ({supplier}) se queda fuera: lleva retención ({amount}) y no hay '
                                      'cuenta de retenciones en config.ini, [accounts] withholding.',
        'exp.unbalanced': '{number} ({supplier}) se queda fuera: el asiento no cuadra por {diff}. Ábrela y repásala.',
        'exp.zero_vat': '{number}: la base al {rate} no tiene cuota, así que no genera registro de IVA ({base}).',
        'exp.push_failed': '{number}: no se ha podido enviar a la API ({error}). Está en el fichero.',

        'status.reading': 'leyendo', 'status.waiting': 'esperando a la contabilidad',
        'status.error': 'no se ha podido leer', 'status.review': 'por revisar',
        'status.approved': 'lista para exportar', 'status.exported': 'exportada',
        'status.posted': 'contabilizada', 'status.discarded': 'descartada',
    },
    'en': {
        'reason.rule': 'the account you set for this supplier',
        'reason.always': 'the one always used with this supplier ({n} invoices this year)',
        'reason.usual': 'the most usual one with this supplier ({pct} % of this year)',
        'reason.content': 'from what the invoice contains',
        'reason.content_new': 'from what the invoice contains; no purchases from this supplier this year',
        'reason.pick': 'pick the account',
        'reason.split_rest': 'the rest split by what each line is',
        'reason.split': 'split by what each line is',

        'why.supplier': 'the one your ledger has for this supplier',
        'why.ledger': "{name}'s in your ledger",
        'why.only': 'the only valid one changing a single character',
        'fix.use': 'Use {v}',
        'fix.use_date': 'Use {d}',
        'fix.use_invoice_date': 'Use the invoice date',

        'chk.not_invoice': "This doesn't look like an invoice (delivery note, quote or order?). If it isn't, discard it.",
        'chk.credit_note': 'Credit note: amounts are negative.',
        'chk.ledger_down': "Your ledger isn't answering, so the supplier and duplicates couldn't be checked. "
                           'Open it again once the connection is back.',
        'chk.new_supplier': "New supplier: tax ID {tax_id} isn't in your ledger. Create it there, then pick it here.",
        'chk.pick_supplier': 'Pick the supplier.',
        'chk.matched_by_name': 'Supplier matched by name, not by tax ID: check it is the right one.',
        'chk.several_accounts': '{n} accounts share tax ID {tax_id}. Using {account} {name} ({bought} this year), '
                                'the most used; the other is {other} {other_name} ({other_bought}).',
        'chk.no_tax_id': "The supplier's tax ID wasn't read.",
        'chk.own_tax_id': "It read your company's tax ID instead of the supplier's.",
        'chk.tax_id_fix': 'Tax ID {tax_id} is invalid: most likely {good} ({why}).',
        'chk.tax_id_invalid': 'Tax ID {tax_id} is invalid: it may be misread.',
        'chk.tax_id_misread': "The invoice's tax ID ({tax_id}) differs from your ledger's ({ledger}): probably misread.",
        'chk.tax_id_differs': "The invoice's tax ID ({tax_id}) differs from your ledger's ({ledger}).",
        'chk.no_number': 'Invoice number missing.',
        'chk.no_date': 'Invoice date missing.',
        'chk.no_posting_date': 'Posting date missing.',
        'chk.two_dates': 'The invoice has two dates: {issue} (issue) and {accounting} (accounting). Using {used}.',
        'chk.closed_quarter': '{date} falls in a quarter whose VAT is already filed (up to {closed}).',
        'chk.moved_to_open': "It's dated {date}, but that quarter's VAT is filed: posted on {posted}.",
        'chk.future_date': 'The invoice date ({date}) is in the future: it may be misread.',
        'chk.old_date': 'The invoice is more than a year old ({date}).',
        'chk.no_vat': 'No VAT bases.',
        'chk.vat_mismatch': 'VAT at {rate}: {base} × {rate} = {expected}, but it says {printed}.',
        'chk.total_mismatch': "Bases plus VAT add up to {sum}, but the invoice total is {total}.",
        'chk.rounding': '{diff} rounding difference in the total.',
        'chk.unlined': "At {rate} there's {diff} not on any line (fees, shipping…). It goes to the largest account.",
        'chk.discount': 'Lines at {rate} add up to {sum} and the base is {base} (a discount?).',
        'chk.surcharge': 'Includes equivalence surcharge ({amount}).',
        'chk.withholding': 'Includes IRPF withholding ({amount}).',
        'chk.split_no_account': 'A line in "Posted as" has no account.',
        'chk.unknown_account': "Account {account} isn't in your chart of accounts.",
        'chk.not_expense': "Account {account} isn't an expense or asset account.",
        'chk.split_sum': '"Posted as" adds up to {sum} at {rate} and the base is {base}.',
        'chk.split_rate': "There's a line at {rate} and the invoice has no such VAT rate.",
        'chk.asset': 'Looks like an investment (furniture, machinery, works): consider fixed assets instead of expenses.',
        'chk.dup_app': 'Already in the app: invoice #{id} ({status}).',
        'chk.dup_ledger': 'Already booked: recorded on {date} for {base}.',
        'chk.maybe_dup_ledger': 'Maybe already booked: same supplier, same month and same base (#{number}).',
        'chk.reader_note': 'The reader says: {note}',

        'exp.surcharge': '{number} ({supplier}) left out: it has equivalence surcharge ({amount}), '
                         'which this format does not support.',
        'exp.no_vat_account': '{number} ({supplier}) left out: no input VAT account for {rate}. '
                              'Set it in config.ini, [accounts] input_vat.',
        'exp.no_withholding_account': '{number} ({supplier}) left out: it has withholding ({amount}) and no '
                                      'withholding account in config.ini, [accounts] withholding.',
        'exp.unbalanced': '{number} ({supplier}) left out: the entry is off by {diff}. Open it and review it.',
        'exp.zero_vat': '{number}: the {rate} base has no VAT, so it creates no VAT-book record ({base}).',
        'exp.push_failed': '{number}: could not send it to the API ({error}). It is in the file.',

        'status.reading': 'reading', 'status.waiting': 'waiting for the ledger',
        'status.error': "couldn't be read", 'status.review': 'to review',
        'status.approved': 'ready to export', 'status.exported': 'exported',
        'status.posted': 'booked', 'status.discarded': 'discarded',
    },
}


def money(v, lang):
    s = f'{abs(v):,.2f}'
    s = s.replace(',', ' ').replace('.', ',').replace(' ', '.') if lang == 'es' else s
    return ('−' if v < 0 else '') + (f'{s} €' if lang == 'es' else f'€{s}')


def rate(v, lang):
    s = f'{float(v):g}'
    return (s.replace('.', ',') + ' %') if lang == 'es' else s + '%'


def date(iso, lang):
    try:
        d = datetime.date.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or '—'
    return d.strftime('%d/%m/%Y') if lang == 'es' else d.strftime('%d %b %Y')


def quarter(closed, lang):
    y, m = closed
    q = (m - 1) // 3 + 1
    return f'{q}.º trimestre de {y}' if lang == 'es' else f'Q{q} {y}'


def t(key, lang='es', **p):
    lang = lang if lang in M else 'es'
    tpl = M[lang].get(key) or M['es'].get(key) or key
    out = {}
    for k, v in p.items():
        if isinstance(v, dict) and 'k' in v:
            out[k] = t(v['k'], lang, **{a: b for a, b in v.items() if a != 'k'})
        elif k in MONEY and isinstance(v, (int, float)):
            out[k] = money(v, lang)
        elif k in RATES:
            out[k] = rate(v, lang)
        elif k in DATES:
            out[k] = date(v, lang)
        elif k == 'closed':
            out[k] = quarter(tuple(v), lang)
        elif k == 'status':
            out[k] = t(f'status.{v}', lang)
        else:
            out[k] = v
    try:
        return tpl.format(**out)
    except (KeyError, IndexError):
        return tpl


def render_findings(items, lang):
    """Add 'text' (and a translated fix label) to each finding."""
    out = []
    for a in items:
        b = dict(a, text=t(a['k'], lang, **a.get('p', {})))
        if a.get('fix'):
            lbl = a['fix']['label']
            b['fix'] = dict(a['fix'], label=t(lbl['k'], lang, **{k: v for k, v in lbl.items() if k != 'k'}))
        out.append(b)
    return out


def render_reason(reason, lang):
    parts = [t(r['k'], lang, **{k: v for k, v in r.items() if k != 'k'}) for r in reason or []]
    s = '; '.join(parts)
    return s[:1].upper() + s[1:]
