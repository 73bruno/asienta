"""Sage 50 (Spain) and ContaPlus: the XDIARIO journal file.

Sage 50's FREE add-on "Importación / Exportación de asientos" (menu Archivos > Importación de
asientos) reads files with ContaPlus's structure, the so-called XDIARIO, as .csv, .txt or .dbf.
This writes the .csv: one line per posting, 116 fields separated by semicolons, ALL fields
present even when empty, ANSI (cp1252), CRLF line ends, in the order of ContaPlus's
"Protocolo de comunicación de programas de gestión con ContaPlus" (fields 1..116), which Sage 50
follows. Amounts in euros (MonedaUso = 2, EuroDebe/EuroHaber), pesetas at 0.

What makes Sage create the VAT-book record (not just the entry) are the auxiliary fields of the
VAT line: Contra (the supplier account), Baseimpo/BaseEuro, IVA (the rate), Factura (the digits of
the number: exactly what Sage keeps in ivasopor.NUMFRA), FacturaEx (the full number), TipoFac = R,
TipoIVA = O and TerIdNif/TerNif/TerNom.

`contaplus` writes the classic fixed-width XDIARIO.TXT (287 characters per line) for old ContaPlus
versions. It has no room for the full number, the third party's tax ID or the invoice type, so the
VAT book comes out poorer: use it only if your version rejects the .csv.
"""
import re

from .base import Exporter, description, digits, journal, text

# Default of every field by position (1..116); also marks the type: '' text or date,
# '0' integer, '0.00' decimal, '.F.' logical.
DEFAULTS = [
    '0', '', '', '', '0.00', '', '0.00', '0', '0.00', '0.00',          # 1..10
    '0.00', '', '', '', '', '0', '0', '0', '0.000000', '0.00',         # 11..20
    '0.00', '', '', '', '', '0.00', '2', '0.00', '0.00', '0.00',       # 21..30
    '.F.', '', '', '0', '0.00', '0.00', '.F.', '', '', '.F.',          # 31..40
    '0', '.F.', '', '', '.F.', '', '', '', '', '0.00',                 # 41..50
    '0.00', '0', '0.00', '', '', '', '', '0', '', '',                  # 51..60
    '0', '', '', '', '.F.', '', '.F.', '.F.', '0.00', '',              # 61..70
    '0', '', '', '', '', '.F.', '0', '', '', '',                       # 71..80
    '0.00', '', '', '', '0.00', '', '0', '.F.', '0', '',               # 81..90
    '0', '0', '0', '.F.', '', '0.00', '', '0.00', '0', '',             # 91..100
    '.F.', '', '', '.F.', '', '0', '0', '0', '', '0',                  # 101..110
    '', '0.00', '.F.', '.F.', '0', '',                                 # 111..116
]
FIELDS = len(DEFAULTS)

# Fields used here, by their name in the protocol (position - 1).
F = {'Asien': 0, 'Fecha': 1, 'SubCta': 2, 'Contra': 3, 'Concepto': 5, 'Factura': 7,
     'Baseimpo': 8, 'IVA': 9, 'Recequiv': 10, 'Documento': 11, 'MonedaUso': 26, 'EuroDebe': 27,
     'EuroHaber': 28, 'BaseEuro': 29, 'Fecha_EX': 46, 'TerIdNif': 60, 'TerNif': 61, 'TerNom': 62,
     'OpBienes': 70, 'FacturaEx': 71, 'TipoFac': 72, 'TipoIVA': 73}

DOMESTIC_DEDUCTIBLE = 'O'          # TipoIVA
RECEIVED = 'R'                     # TipoFac
CURRENT, INVESTMENT = 1, 2         # OpBienes


def euros(x):
    return f'{round(float(x or 0), 2):.2f}'


def ymd(iso):
    """'2026-09-15' -> '20260915'."""
    return iso.replace('-', '') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', iso or '') else ''


class Line(list):
    """One line of the file: the 116 fields with their defaults."""

    def __init__(self):
        super().__init__(DEFAULTS)

    def put(self, **kv):
        for k, v in kv.items():
            self[F[k]] = v
        return self


def postings(number, data, entry, supplier, ctx):
    """The XDIARIO lines of one invoice."""
    post = ymd(entry['posting_date'])
    inv_date = ymd(data['invoice_date']) or post
    sup = entry['supplier_account']
    name = supplier.get('name') or data['supplier_name']
    tid = data['supplier_tax_id'] or supplier.get('tax_id') or ''
    common = {'Asien': str(number), 'Fecha': post, 'Concepto': description(ctx, data, supplier), 'MonedaUso': '2'}
    investment = INVESTMENT if any(r['account'].startswith('2') for r in entry['split']) else CURRENT
    first_expense = next((r['account'] for r in entry['split'] if r['base']), '')
    out = []
    for p in journal(data, entry, supplier, ctx):
        if p['kind'] == 'expense':
            out.append(Line().put(**common, SubCta=p['account'], Contra=sup, EuroDebe=euros(p['debit'])))
        elif p['kind'] == 'vat':
            out.append(Line().put(
                **common, SubCta=p['account'], Contra=sup, EuroDebe=euros(p['debit']),
                Baseimpo=euros(p['base']), BaseEuro=euros(p['base']), IVA=euros(p['rate']),
                Factura=digits(data['invoice_number']), FacturaEx=text(data['invoice_number'], 40),
                Fecha_EX=inv_date, TipoFac=RECEIVED, TipoIVA=DOMESTIC_DEDUCTIBLE, OpBienes=str(investment),
                TerIdNif='1', TerNif=text(tid, 15), TerNom=text(name, 40)))
        elif p['kind'] == 'withholding':
            out.append(Line().put(**common, SubCta=p['account'], Contra=sup, EuroHaber=euros(p['credit'])))
        else:
            out.append(Line().put(**common, SubCta=sup, Contra=first_expense, EuroHaber=euros(p['credit'])))
    return out


def write_lines(path, lines):
    with open(path, 'w', encoding='cp1252', errors='replace', newline='') as f:
        f.write(''.join(ln + '\r\n' for ln in lines))


class Sage50(Exporter):
    key = 'sage50'
    label = 'Sage 50 (XDIARIO .csv)'
    extension = '.csv'
    mime = 'text/csv; charset=windows-1252'
    maturity = 'stable'
    warn_zero_vat = True
    docs = 'docs/exporters.md#sage-50'

    def write(self, path, invoices, ctx):
        start = int((self.settings.get('export', 'first_entry', '1') if self.settings else '1') or 1)
        counter = [start]

        def build(_i, data, entry, supplier):
            lines = postings(counter[0], data, entry, supplier, ctx)
            counter[0] += 1
            return [';'.join(ln) for ln in lines]

        res, lines = self.each(invoices, ctx, build)
        write_lines(path, lines)
        return res


# XDIARIO.TXT, fixed width: (width, field or fixed value, 'N' numeric right-aligned / 'T' text left)
FIXED = [
    (6, 'Asien', 'N'), (8, 'Fecha', 'T'), (12, 'SubCta', 'T'), (12, 'Contra', 'T'),
    (16, '0.00', 'N'), (25, 'Concepto', 'T'), (16, '0.00', 'N'), (8, 'Factura', 'N'),
    (16, 'Baseimpo', 'N'), (5, 'IVA', 'N'), (5, 'Recequiv', 'N'),
    (25, '', 'T'), (2, '00', 'N'), (5, '', 'T'), (1, '0', 'N'), (8, '', 'T'),
    (8, '0.000000', 'N'), (16, '0.00', 'N'), (16, '0.00', 'N'), (27, '0.00', 'N'),
    (1, '2', 'T'), (16, 'EuroDebe', 'N'), (16, 'EuroHaber', 'N'), (16, 'BaseEuro', 'N'),
    (1, 'F', 'T'),
]


def fixed_width(line):
    out = ''
    for width, key, kind in FIXED:
        v = (line[F[key]] if key in F else key)[:width]
        out += v.ljust(width) if kind != 'N' else v.rjust(width)
    return out


class ContaPlus(Sage50):
    key = 'contaplus'
    label = 'ContaPlus classic (XDIARIO.TXT)'
    extension = '.txt'
    mime = 'text/plain; charset=windows-1252'
    maturity = 'beta'

    def write(self, path, invoices, ctx):
        counter = [1]

        def build(_i, data, entry, supplier):
            lines = postings(counter[0], data, entry, supplier, ctx)
            counter[0] += 1
            return [fixed_width(ln) for ln in lines]

        res, lines = self.each(invoices, ctx, build)
        write_lines(path, lines)
        return res
