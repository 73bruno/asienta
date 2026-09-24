#!/usr/bin/env python3
"""Generate the demo: a fictional restaurant, its ledger and nine supplier invoices.

Every company, person, address and tax ID here is invented (tax IDs are built to pass the check
digit, nothing else). Run it again after changing anything below; the output is committed.

    pip install reportlab
    python scripts/make_demo.py

Writes asienta/demo/ledger/*.csv, asienta/demo/invoices/*.pdf|jpg (+ the reading the demo reader
returns for each, .json) and asienta/demo/truth.json (the correct values, for `asienta bench`).
The restaurant ticket photo comes from scripts/assets/ (a staged sample, customer set to the demo
company).
"""
import copy
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from asienta.spain import cif_check_digit  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..', 'asienta', 'demo')
INVOICES = os.path.join(ROOT, 'invoices')
LEDGER = os.path.join(ROOT, 'ledger')


def cif(letter, digits):
    return letter + digits + cif_check_digit(letter, digits)


COMPANY = {'name': 'Demo Bistro, S.L.', 'tax_id': cif('B', '9876543'),
           'address': 'Paseo del Puerto 12, 03001 Alicante, Spain'}

S = {  # account: (name, tax_id, address, colour, style)
    '400000001': ('Mediterranean Foods Demo, S.L.', cif('B', '4618273'), 'Pol. Ind. Las Atalayas, C/ Dracma 9, 03114 Alicante', '#0F766E', 'band'),
    '400000002': ('Levante Drinks Demo, S.A.', cif('A', '3920156'), 'Av. de Elche 140, 03008 Alicante', '#1D4ED8', 'box'),
    '400000003': ('Sparkle Cleaning Demo, S.L.', cif('B', '5507381'), 'C/ Italia 22, 03003 Alicante', '#7C3AED', 'minimal'),
    '400000004': ('Brothers Butchery Demo, S.L.', cif('B', '6283419'), 'Mercado Central, puesto 31, 03002 Alicante', '#B91C1C', 'box'),
    '400000005': ('Orchard Fruit Demo, S.L.', cif('B', '7714025'), 'Partida de Bacarot 5, 03690 Alicante', '#15803D', 'band'),
    '410000007': ('Café Restaurante Norte, S.L.', cif('B', '8765432'), 'C/ Gran Vía 45, 28013 Madrid', '#111827', 'photo'),
    '410000001': ('Harbour Accountants Demo, S.L.P.', cif('B', '8840217'), 'C/ Pintor Aparicio 18, 03003 Alicante', '#334155', 'minimal'),
    '410000002': ('Terrace Furniture Demo, S.L.', cif('B', '2395864'), 'Ctra. de Ocaña 60, 03007 Alicante', '#C2410C', 'band'),
}
OTHER_SUPPLIERS = [
    ('400000007', 'Fish Market Demo, S.L.', cif('B', '1047382')),
    ('400000008', 'Coffee Roasters Demo, S.L.', cif('B', '2269104')),
    ('400000009', 'North Frozen Foods Demo, S.A.', cif('A', '5590316')),
    ('400000010', 'Wine & Cava Demo, S.L.', cif('B', '6613570')),
    ('400000011', 'Catering Supplies Demo, S.L.', cif('B', '7708825')),
    ('400000012', 'Valley Dairy Demo, S.A.', cif('A', '8124093')),
    ('410000003', 'Quick Repairs Demo, S.L.', cif('B', '9031658')),
    ('410000004', 'Green Energy Demo, S.A.', cif('A', '4176209')),
    ('410000005', 'Telecom Demo, S.A.', cif('A', '3358471')),
    ('410000006', 'Payroll Services Demo, S.L.', cif('B', '2710946')),
]
ACCOUNTS = [
    ('600000100', 'Food purchases'), ('600000200', 'Drinks purchases'),
    ('600000300', 'Packaging purchases'), ('600000400', 'Cleaning supplies'),
    ('621000000', 'Rent'), ('622000000', 'Repairs and maintenance'),
    ('623000000', 'Professional services'), ('625000000', 'Insurance'),
    ('627000000', 'Advertising'), ('628000000', 'Utilities'), ('629000000', 'Other services'),
    ('216000000', 'Furniture'), ('217000000', 'Computer equipment'),
    ('472000004', 'Input VAT 4%'), ('472000010', 'Input VAT 10%'),
    ('472000021', 'Input VAT 21%'), ('475100000', 'Withholding tax payable'),
]
HISTORY = [  # supplier, expense account, amount this year, invoices
    ('400000001', '600000100', 18450.20, 42), ('400000001', '600000200', 3120.50, 15),
    ('400000002', '600000200', 9800.00, 30), ('400000003', '600000400', 1450.00, 12),
    ('400000004', '600000100', 7300.00, 26), ('400000005', '600000100', 5120.00, 38),
    ('410000007', '629000000', 612.40, 17), ('410000001', '623000000', 3150.00, 9),
    ('400000007', '600000100', 6400.00, 20), ('400000008', '600000200', 1900.00, 10),
    ('400000010', '600000200', 4200.00, 11), ('410000004', '628000000', 8900.00, 9),
    ('410000005', '628000000', 720.00, 9), ('410000006', '623000000', 1800.00, 9),
]


def line(desc, qty, price, rate, cat):
    return {'description': desc, 'qty': qty, 'price': price, 'amount': round(qty * price, 2), 'vat_rate': rate,
            'category': cat}


def invoice(acc, number, date, lines, kind='invoice', due=None, withholding_pct=0, asset=False,
            suggested='', notes=(), page=1):
    name, tid = S[acc][0], S[acc][1]
    by_rate = {}
    for ln in lines:
        by_rate.setdefault(ln['vat_rate'], 0.0)
        by_rate[ln['vat_rate']] += ln['amount']
    vat = [{'vat_rate': r, 'base': round(b, 2), 'vat': round(b * r / 100, 2)} for r, b in sorted(by_rate.items(), reverse=True)]
    base = round(sum(v['base'] for v in vat), 2)
    withholding = round(base * withholding_pct / 100, 2)
    total = round(sum(v['base'] + v['vat'] for v in vat) - withholding, 2)
    return {'account': acc, 'supplier_name': name, 'supplier_tax_id': tid, 'invoice_number': number,
            'invoice_date': date, 'accounting_date': None, 'doc_type': kind, 'start_page': page,
            'lines': lines, 'vat_breakdown': vat, 'surcharge': 0, 'withholding': withholding,
            'withholding_pct': withholding_pct, 'total': total,
            'due_dates': [{'date': due, 'amount': total}] if due else [], 'possible_asset': asset,
            'suggested_account': suggested, 'notes': list(notes)}


DOCS = [
    ('01_mediterranean_foods.pdf', [invoice('400000001', 'MED-26/0917', '2026-09-15', [
        line('Wheat flour T-55, 25 kg sack', 2, 18.40, 4, 'food'),
        line('Crushed tomato, 5 kg tin', 6, 6.85, 10, 'food'),
        line('Aged Manchego cheese, 3 kg wedge', 2, 41.20, 10, 'food'),
        line('Gordal olives, 2 kg tub', 3, 9.90, 10, 'food'),
        line('Red wine D.O. Alicante crianza, case of 6', 4, 38.50, 21, 'drinks'),
        line('Paper napkins 2-ply, pack of 500', 5, 7.20, 21, 'packaging'),
    ], due='2026-10-15')]),
    ('02_levante_drinks.pdf', [invoice('400000002', 'LD-2026-4471', '2026-09-16', [
        line('Draught beer keg 30 L', 4, 72.00, 21, 'drinks'),
        line('Cola, case of 24 x 33 cl', 5, 14.60, 21, 'drinks'),
        line('Mineral water 1.5 L, pack of 6', 12, 2.40, 10, 'drinks'),
        line('Returnable keg deposit', 4, 30.00, 21, 'packaging'),
        line('Deposit refund, empty kegs', -3, 30.00, 21, 'packaging'),
    ], due='2026-10-16')]),
    ('03_sparkle_cleaning.pdf', [invoice('400000003', 'SC/0388', '2026-09-10', [
        line('Industrial dishwasher detergent 20 L', 2, 48.90, 21, 'cleaning'),
        line('Rinse aid 10 L', 1, 36.50, 21, 'cleaning'),
        line('Kitchen degreaser 5 L', 3, 12.75, 21, 'cleaning'),
    ], due='2026-10-10')]),
    ('04_brothers_butchery.pdf', [
        invoice('400000004', 'BB-1182', '2026-09-08', [
            line('Beef tenderloin', 4.2, 32.50, 10, 'food'),
            line('Iberian pork secreto', 6.0, 17.90, 10, 'food')], due='2026-10-08', page=1),
        invoice('400000004', 'BB-1183', '2026-09-12', [
            line('Free-range whole chicken', 8.0, 6.40, 10, 'food'),
            line('Fresh sausage', 3.5, 9.80, 10, 'food'),
            line('Pork ribs', 5.0, 8.60, 10, 'food')], due='2026-10-12', page=2),
    ]),
    ('05_orchard_fruit_credit_note.pdf', [invoice('400000005', 'CN-26/015', '2026-09-18', [
        line('Returned: vine tomatoes, damaged', -12, 1.85, 4, 'food'),
        line('Returned: Hass avocado', -4, 4.60, 10, 'food'),
    ], kind='credit_note')]),
    ('06_harbour_accountants.pdf', [invoice('410000001', 'HA-2026/091', '2026-09-01', [
        line('Accounting and tax advice, September 2026', 1, 350.00, 21, 'other'),
    ], withholding_pct=15, due='2026-09-10')]),
    ('07_terrace_furniture.pdf', [invoice('410000002', 'T-0045', '2026-09-19', [
        line('Aluminium terrace table 70x70', 6, 145.00, 21, 'other'),
        line('Stackable aluminium and rattan chair', 24, 58.00, 21, 'other'),
        line('Delivery and assembly', 1, 90.00, 21, 'other'),
    ], asset=True, suggested='216000000', due='2026-10-19')]),
    # a real-looking photo of a restaurant ticket (scripts/assets), for a business lunch. It arrives by
    # email in the demo. Its printed tax ID fails the check digit: the ledger has the right one.
    ('08_cafe_norte_ticket.jpg', [invoice('410000007', 'F-2026/04192', '2026-09-24', [
        line('Menú Ejecutivo Diario', 2, 14.545, 10, 'food'),
        line('Agua Mineral 1L', 1, 2.2727, 10, 'drinks'),
        line('Café solo', 2, 1.3636, 10, 'drinks'),
    ])]),
    ('09_orchard_fruit_june.pdf', [invoice('400000005', 'OF-26/0612', '2026-06-28', [
        line('Vine tomatoes', 25, 1.85, 4, 'food'),
        line('Romaine lettuce', 30, 0.65, 4, 'food'),
        line('Lemons', 10, 1.30, 4, 'food'),
        line('Strawberries, 2 kg box', 4, 7.40, 4, 'food'),
    ], due='2026-07-28')]),
]
DOCS[7][1][0]['supplier_tax_id'] = 'B87654321'      # as printed on the ticket (invalid check digit)
DOCS[7][1][0]['supplier_name'] = 'Café Restaurante Norte'
for _f, invs in DOCS:                 # credit note: everything negative
    for inv in invs:
        if inv['doc_type'] == 'credit_note':
            assert inv['total'] < 0


# ---------------------------------------------------------------------------- rendering
def eur(v):
    return ('-' if v < 0 else '') + f'€{abs(v):,.2f}'


def dmy(iso):
    return f'{iso[8:]}/{iso[5:7]}/{iso[:4]}'


def draw_invoice(c, inv):
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.lib.pagesizes import A4
    W, H = A4
    name, tid, addr, colour, style = S[inv['account']]
    col = HexColor(colour)
    grey = HexColor('#6B7280')
    m = 42
    if style == 'band':
        c.setFillColor(col)
        c.rect(0, H - 120, W, 120, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont('Helvetica-Bold', 20)
        c.drawString(m, H - 58, name.split(',')[0])
        c.setFont('Helvetica', 9.5)
        c.drawString(m, H - 76, f'{addr}  ·  Tax ID {tid}')
        c.setFont('Helvetica-Bold', 26)
        c.drawRightString(W - m, H - 60, 'CREDIT NOTE' if inv['doc_type'] == 'credit_note' else 'INVOICE')
        top = H - 150
    elif style == 'box':
        c.setStrokeColor(col)
        c.setLineWidth(2)
        c.roundRect(m, H - 130, W - 2 * m, 92, 8)
        c.setFillColor(col)
        c.setFont('Helvetica-Bold', 17)
        c.drawString(m + 16, H - 70, name)
        c.setFillColor(black)
        c.setFont('Helvetica', 9.5)
        c.drawString(m + 16, H - 88, addr)
        c.drawString(m + 16, H - 102, f'Tax ID: {tid}   ·   Tel. +34 965 00 00 00')
        c.setFont('Helvetica-Bold', 13)
        c.drawRightString(W - m - 16, H - 70, 'INVOICE')
        top = H - 160
    else:
        c.setFillColor(col)
        c.circle(m + 12, H - 60, 12, stroke=0, fill=1)
        c.setFillColor(black)
        c.setFont('Helvetica-Bold', 15)
        c.drawString(m + 34, H - 65, name)
        c.setFont('Helvetica', 9)
        c.setFillColor(grey)
        c.drawString(m + 34, H - 80, f'{addr}  ·  Tax ID {tid}')
        c.setFillColor(col)
        c.rect(m, H - 96, W - 2 * m, 1.5, stroke=0, fill=1)
        top = H - 130
    # invoice meta and customer
    c.setFillColor(black)
    c.setFont('Helvetica-Bold', 10)
    title = 'Credit note' if inv['doc_type'] == 'credit_note' else 'Invoice'
    c.drawString(m, top, f'{title} no. {inv["invoice_number"]}')
    c.setFont('Helvetica', 10)
    c.drawString(m, top - 15, f'Issue date: {dmy(inv["invoice_date"])}')
    if inv['due_dates']:
        c.drawString(m, top - 30, f'Due date: {dmy(inv["due_dates"][0]["date"])}')
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(grey)
    c.drawString(W / 2 + 20, top, 'BILL TO')
    c.setFillColor(black)
    c.setFont('Helvetica-Bold', 10)
    c.drawString(W / 2 + 20, top - 15, COMPANY['name'])
    c.setFont('Helvetica', 9.5)
    c.drawString(W / 2 + 20, top - 29, COMPANY['address'])
    c.drawString(W / 2 + 20, top - 43, f'Tax ID {COMPANY["tax_id"]}')
    # lines
    y = top - 80
    cols = [m, W - m - 230, W - m - 160, W - m - 90, W - m]
    c.setFillColor(HexColor('#F3F4F6'))
    c.rect(m, y - 6, W - 2 * m, 20, stroke=0, fill=1)
    c.setFillColor(black)
    c.setFont('Helvetica-Bold', 8.5)
    c.drawString(cols[0] + 6, y, 'DESCRIPTION')
    c.drawRightString(cols[1] + 40, y, 'QTY')
    c.drawRightString(cols[2] + 50, y, 'PRICE')
    c.drawRightString(cols[3] + 40, y, 'VAT')
    c.drawRightString(cols[4] - 6, y, 'AMOUNT')
    c.setFont('Helvetica', 9.5)
    for ln in inv['lines']:
        y -= 20
        c.drawString(cols[0] + 6, y, ln['description'])
        q = ln['qty']
        c.drawRightString(cols[1] + 40, y, f'{q:g}' if q == int(q) else f'{q:.2f}')
        c.drawRightString(cols[2] + 50, y, eur(ln['price']))
        c.drawRightString(cols[3] + 40, y, f'{ln["vat_rate"]:g} %')
        c.drawRightString(cols[4] - 6, y, eur(ln['amount']))
        c.setStrokeColor(HexColor('#E5E7EB'))
        c.setLineWidth(0.5)
        c.line(m, y - 6, W - m, y - 6)
    # totals box
    y -= 40
    bx = W - m - 250
    c.setFont('Helvetica-Bold', 8.5)
    c.setFillColor(grey)
    for x, t in ((bx, 'VAT RATE'), (bx + 90, 'BASE'), (bx + 170, 'VAT')):
        c.drawString(x, y, t)
    c.setFillColor(black)
    c.setFont('Helvetica', 9.5)
    for v in inv['vat_breakdown']:
        y -= 16
        c.drawString(bx, y, f'{v["vat_rate"]:g} %')
        c.drawRightString(bx + 150, y, eur(v['base']))
        c.drawRightString(W - m, y, eur(v['vat']))
    if inv['withholding']:
        y -= 16
        c.drawString(bx, y, f'IRPF withholding {inv["withholding_pct"]:g} %')
        c.drawRightString(W - m, y, eur(-inv['withholding']))
    y -= 28
    c.setFillColor(HexColor(S[inv['account']][3]))
    c.roundRect(bx - 10, y - 10, W - m - bx + 10, 30, 6, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 13)
    c.drawString(bx, y, 'TOTAL')
    c.drawRightString(W - m - 8, y, eur(inv['total']))
    # footer
    c.setFillColor(grey)
    c.setFont('Helvetica', 7.5)
    c.drawString(m, 40, f'{name} · Registered in Alicante · Fictional document generated for the Asienta demo.')
    c.drawString(m, 30, 'Payment: bank transfer.')


def render_pdf(invs):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    for inv in invs:
        draw_invoice(c, inv)
        c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------- outputs
def reading(inv):
    """What the demo reader returns for this invoice (the AI's answer)."""
    r = {k: copy.deepcopy(inv[k]) for k in ('start_page', 'doc_type', 'supplier_name', 'supplier_tax_id',
                                            'invoice_number', 'invoice_date', 'accounting_date', 'vat_breakdown',
                                            'surcharge', 'withholding', 'total', 'due_dates', 'possible_asset',
                                            'suggested_account', 'notes')}
    r['lines'] = [{k: ln[k] for k in ('description', 'amount', 'vat_rate', 'category')} for ln in inv['lines']]
    return r


def truth(inv, expected_split):
    return {'tax_id': inv['supplier_tax_id'], 'number': inv['invoice_number'], 'number_alt': [],
            'dates': [inv['invoice_date']], 'dates_alt': [],
            'vat': {f'{v["vat_rate"]:g}': [v['base'], v['vat']] for v in inv['vat_breakdown']},
            'surcharge': 0, 'withholding': inv['withholding'], 'total': inv['total'],
            'supplier_account': inv['account'], 'accounts': expected_split}


def main():
    os.makedirs(INVOICES, exist_ok=True)
    os.makedirs(LEDGER, exist_ok=True)
    for f in os.listdir(INVOICES):
        os.remove(os.path.join(INVOICES, f))
    truths = {}
    for filename, invs in DOCS:
        path = os.path.join(INVOICES, filename)
        if filename.endswith('.jpg'):
            with open(os.path.join(os.path.dirname(__file__), 'assets', 'cafe_norte_ticket.jpg'), 'rb') as f:
                content = f.read()
        else:
            content = render_pdf(invs)
        with open(path, 'wb') as f:
            f.write(content)
        readings = [reading(i) for i in invs]
        with open(path.rsplit('.', 1)[0] + '.json', 'w', encoding='utf-8') as f:
            json.dump({'invoices': readings}, f, ensure_ascii=False, indent=1)
        truths[filename] = []
        for inv in invs:
            split = {}
            for ln in inv['lines']:
                acc = {'food': '600000100', 'drinks': '600000200', 'cleaning': '600000400'}.get(ln['category'])
                if ln['category'] == 'packaging':
                    acc = '600000200' if inv['account'] == '400000002' else '600000100'
                fixed = {'410000001': '623000000', '410000002': '216000000', '410000007': '629000000'}
                acc = fixed.get(inv['account']) or acc
                split[acc] = round(split.get(acc, 0) + ln['amount'], 2)
            truths[filename].append(truth(inv, split))
    with open(os.path.join(ROOT, 'truth.json'), 'w', encoding='utf-8') as f:
        json.dump({'invoices': truths}, f, ensure_ascii=False, indent=1)

    with open(os.path.join(LEDGER, 'accounts.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['account', 'name', 'tax_id'])
        for acc, name in ACCOUNTS:
            w.writerow([acc, name, ''])
        for acc, (name, tid, *_rest) in S.items():
            w.writerow([acc, name.upper(), tid])
        for acc, name, tid in OTHER_SUPPLIERS:
            w.writerow([acc, name.upper(), tid])
    with open(os.path.join(LEDGER, 'history.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['supplier_account', 'expense_account', 'amount', 'invoices'])
        w.writerows(HISTORY)
    booked = [inv for _f, invs in DOCS for inv in invs if inv['invoice_number'] == 'SC/0388']
    with open(os.path.join(LEDGER, 'booked.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['supplier_account', 'number', 'date', 'base'])
        w.writerow(['400000001', 'MED-26/0822', '2026-08-22', '612.40'])
        w.writerow(['400000002', 'LD-2026-4390', '2026-09-02', '388.10'])
        for inv in booked:          # this one was already booked by hand: the demo catches the duplicate
            w.writerow([inv['account'], inv['invoice_number'], inv['invoice_date'],
                        f'{sum(v["base"] for v in inv["vat_breakdown"]):.2f}'])
    print(f'company {COMPANY["tax_id"]} · {sum(len(i) for _f, i in DOCS)} invoices in {len(DOCS)} documents')


if __name__ == '__main__':
    main()
