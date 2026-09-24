"""Formats that are not tied to one program.

csv         one row per split line with everything: for spreadsheets, Contasol, Odoo imports,
            or as the starting point of your own importer.
json        the full reviewed invoice and its posting, for scripts and APIs.
sage50xls   the Excel of Sage 50's PAID add-on "Importador Excel de facturas en asientos".
"""
import csv
import json

from .base import Exporter, split_vat

CSV_COLUMNS = ['invoice_number', 'invoice_date', 'posting_date', 'supplier_account', 'supplier_name',
               'supplier_tax_id', 'expense_account', 'vat_rate', 'base', 'vat', 'withholding', 'total',
               'doc_type', 'due_date']


class GenericCSV(Exporter):
    key = 'csv'
    label = 'CSV (universal)'
    maturity = 'stable'
    docs = 'docs/exporters.md#csv-and-json'

    def write(self, path, invoices, ctx):
        def build(_i, data, entry, supplier):
            due =max((d['date'] for d in data.get('due_dates') or [] if d.get('date')), default='')
            return [{'invoice_number': data['invoice_number'], 'invoice_date': data['invoice_date'],
                     'posting_date': entry['posting_date'], 'supplier_account': entry['supplier_account'],
                     'supplier_name': supplier.get('name') or data['supplier_name'],
                     'supplier_tax_id': data['supplier_tax_id'], 'expense_account': account, 'vat_rate': rate,
                     'base': f'{base:.2f}', 'vat': f'{vat:.2f}', 'withholding': f'{data.get("withholding", 0):.2f}',
                     'total': f'{data["total"]:.2f}', 'doc_type': data['doc_type'], 'due_date': due}
                    for account, rate, base, vat in split_vat(data, entry)]

        res, rows = self.each(invoices, ctx, build)
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, CSV_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        return res


class GenericJSON(Exporter):
    key = 'json'
    label = 'JSON'
    extension = '.json'
    mime = 'application/json'
    maturity = 'stable'
    docs = 'docs/exporters.md#csv-and-json'

    def write(self, path, invoices, ctx):
        res, rows = self.each(invoices, ctx, lambda _i, d, e, s: [{'invoice': d, 'posting': e, 'supplier': s}])
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        return res


class Sage50Excel(Exporter):
    """One row per VAT rate and expense account. If a rate goes to one account, ImporteContrapartida
    is empty; if it is split, one row per account repeating the rate's base and VAT, with each
    account's amount in ImporteContrapartida."""
    key = 'sage50xls'
    label = 'Sage 50 (Excel importer add-on)'
    extension = '.xlsx'
    mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    docs = 'docs/exporters.md#sage-50'
    COLUMNS = ['Cuenta', 'Fecha', 'Factura', 'BaseIva', 'ImporteIva', 'TipoIva', 'Contrapartida',
               'ImporteContrapartida', 'Referencia']

    def write(self, path, invoices, ctx):
        try:
            import openpyxl
            from openpyxl.styles import Font
        except ImportError:
            raise RuntimeError('this format needs openpyxl: pip install "asienta[excel]"') from None
        from ..config import parse_pairs
        codes = parse_pairs(self.settings.get('sage50xls', 'vat_codes', '') if self.settings else '')

        def build(_i, data, entry, supplier):
            date = f'{entry["posting_date"][8:]}/{entry["posting_date"][5:7]}/{entry["posting_date"][:4]}'
            rows = []
            for t in data['vat_breakdown']:
                split = [r for r in entry['split'] if abs(r['vat_rate'] - t['vat_rate']) < 0.005]
                code = codes.get(float(t['vat_rate']), f'{t["vat_rate"]:g}')
                for r in split:
                    rows.append([entry['supplier_account'], date, data['invoice_number'], t['base'], t['vat'], code,
                                 r['account'], r['base'] if len(split) > 1 else None, None])
            return rows

        res, rows = self.each(invoices, ctx, build)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Facturas'
        ws.append(self.COLUMNS)
        for c in ws[1]:
            c.font = Font(bold=True)
        for row in rows:
            ws.append(row)
        wb.save(path)
        return res
