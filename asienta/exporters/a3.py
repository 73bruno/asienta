"""a3ASESOR | eco / con (Wolters Kluwer A3): the SUENLACE.DAT accounting link.

Fixed-width ASCII records of 512 bytes (510 of data + CRLF), Windows-1252. Each received invoice
is one type-1 header (the supplier and the total) followed by one type-9 detail per expense line
and VAT rate (base, rate, VAT, withholding, and the input-VAT account). Import it in a3 from
Utilidades > Importación/Exportación > Enlace contable.

Positions (1-based) follow the published record layout, cross-checked with two independent open
implementations of the format. Beta: import a first file into a test company and compare.

    [a3] company_code = 00001      a3's company code (5 digits)
"""
import re

from .base import Exporter, Skip, split_vat, text

RECORD = 510


def amount(v):
    """'+0000001000.00': sign, 10 integer digits, point, 2 decimals."""
    v = round(float(v or 0), 2)
    return ('-' if v < 0 else '+') + f'{abs(v):013.2f}'


def pct(v):
    return f'{abs(float(v or 0)):05.2f}'


def ymd(iso):
    return iso.replace('-', '') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', iso or '') else '00000000'


def field(value, width):
    return text(value, width).ljust(width)


def header(company, date, account, name, number, total, tax_id, invoice_date, kind, credit_note):
    r = ('5' + company + date + ('2' if credit_note else '1')
         + field(account, 12) + field(name, 30)
         + kind                                   # 58: invoice type (1 sales, 2 purchases, 3 assets)
         + field(number, 10) + 'I' + field(name, 30)
         + amount(total)                          # 100-113
         + ' ' * 62                               # 114-175
         + field(tax_id, 14) + field(name, 40)    # 176-189, 190-229
         + ' ' * 5 + ' ' * 2                      # 230-234 postcode, 235-236
         + invoice_date + invoice_date            # 237-244 operation date, 245-252 invoice date
         + field(number, 60)                      # 253-312 full number
         + ' ' * 196                              # 313-508
         + 'E' + 'N')                             # 509 currency, 510
    assert len(r) == RECORD, len(r)
    return r


def detail(company, date, account, name, number, last, desc, base, rate, vat, wh_rate, wh, vat_account, wh_account):
    r = ('5' + company + date + '9'
         + field(account, 12) + field(name, 30)
         + 'C'                                    # 58: amount type (charge)
         + field(number, 10) + ('U' if last else 'M') + field(desc, 30)
         + '01'                                   # 100-101: domestic operation subject to VAT
         + amount(base) + pct(rate) + amount(vat)            # 102-115, 116-120, 121-134
         + pct(0) + amount(0)                                # 135-139, 140-153 surcharge
         + pct(wh_rate) + amount(wh)                         # 154-158, 159-172 withholding
         + '01' + 'S' + 'N' + ' '                            # 173-174 347 form, 175 subject, 176 415, 177 cash
         + ' ' * 14                                          # 178-191
         + field(vat_account, 12) + ' ' * 12                 # 192-203 input VAT, 204-215 surcharge
         + field(wh_account, 12) + ' ' * 24                  # 216-227 withholding, 228-251
         + ' '                                               # 252 analytics
         + ' ' * 256                                         # 253-508
         + 'E' + 'N')
    assert len(r) == RECORD, len(r)
    return r


class A3(Exporter):
    key = 'a3'
    label = 'a3ASESOR eco/con (SUENLACE.DAT)'
    extension = '.dat'
    mime = 'text/plain; charset=windows-1252'
    docs = 'docs/exporters.md#a3'

    def write(self, path, invoices, ctx):
        company = re.sub(r'\D', '', self.settings.get('a3', 'company_code', '1') if self.settings else '1').zfill(5)[-5:]

        def build(_i, data, entry, supplier):
            if data.get('surcharge'):
                raise Skip('exp.surcharge', amount=data['surcharge'])
            date = ymd(entry['posting_date'])
            name = supplier.get('name') or data['supplier_name']
            number = data['invoice_number']
            kind = '3' if any(r['account'].startswith('2') for r in entry['split']) else '2'
            parts = split_vat(data, entry)
            if not parts:
                raise Skip('exp.unbalanced', diff=data['total'])
            base_total = sum(p[2] for p in parts)
            rows = [header(company, date, entry['supplier_account'], name, number, data['total'],
                           data['supplier_tax_id'] or supplier.get('tax_id', ''), ymd(data['invoice_date']),
                           kind, data['total'] < 0)]
            wh_left = round(data.get('withholding') or 0, 2)
            for n, (account, rate, base, vat) in enumerate(parts):
                last = n == len(parts) - 1
                wh = wh_left if last else round((data.get('withholding') or 0) * base / base_total, 2)
                wh_left = round(wh_left - wh, 2)
                wh_rate = round(100 * (data.get('withholding') or 0) / base_total, 2) if base_total else 0
                vat_acc = ctx.vat_accounts.get(round(float(rate), 2), '')
                if vat and not vat_acc:
                    raise Skip('exp.no_vat_account', rate=rate)
                if wh and not ctx.withholding_account:
                    raise Skip('exp.no_withholding_account', amount=data['withholding'])
                rows.append(detail(company, date, account, name, number, last, f'{number} {name}', base, rate,
                                   vat, wh_rate if wh else 0, wh, vat_acc, ctx.withholding_account if wh else ''))
            return rows

        res, lines = self.each(invoices, ctx, build)
        with open(path, 'w', encoding='cp1252', errors='replace', newline='') as f:
            f.write(''.join(ln + '\r\n' for ln in lines))
        return res
