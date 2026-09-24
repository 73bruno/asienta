"""Cloud accounting that thinks in bills (purchase invoices) instead of journal lines.

Holded       JSON payloads for POST /api/invoicing/v1/documents/purchase, optionally sent
             straight to the API ([holded] push = true and HOLDED_API_KEY).
Xero         the "Import bills" CSV template (Business > Bills to pay > Import).
QuickBooks   the bills import CSV of QuickBooks Online.

All three: one line per split row (account + VAT rate + base), so the wine on a food invoice still
lands on the drinks account. Tax codes differ per country and per company: map them in config.
"""
import csv
import datetime
import json
import urllib.error
import urllib.request

from ..config import parse_pairs
from .base import Exporter, Skip, split_vat


def due_date(data):
    dues = [d['date'] for d in data.get('due_dates') or [] if d.get('date')]
    return max(dues) if dues else data.get('invoice_date', '')


def lines_or_skip(data, entry):
    parts = split_vat(data, entry)
    if not parts:
        raise Skip('exp.unbalanced', diff=data['total'])
    return parts


def tax_code(codes, rate):
    return codes.get(round(float(rate), 2), '')


# ---------------------------------------------------------------------------- Holded
class Holded(Exporter):
    key = 'holded'
    label = 'Holded (API / JSON)'
    extension = '.json'
    mime = 'application/json'
    docs = 'docs/exporters.md#holded'
    URL = 'https://api.holded.com/api/invoicing/v1/documents/purchase'

    def payload(self, data, entry, supplier):
        date = datetime.date.fromisoformat(entry['posting_date'])
        stamp = int(datetime.datetime(date.year, date.month, date.day, 12).timestamp())
        items = [{'name': f'{data["invoice_number"]} · {account}', 'units': 1, 'subtotal': base,
                  'tax': rate, 'account': account}
                 for account, rate, base, _vat in lines_or_skip(data, entry)]
        if data.get('withholding'):                    # Holded takes the IRPF % per line
            pct = round(100 * data['withholding'] / sum(i['subtotal'] for i in items), 2)
            for i in items:
                i['retention'] = pct
        p = {'contactName': supplier.get('name') or data['supplier_name'], 'date': stamp,
             'invoiceNum': data['invoice_number'], 'currency': 'eur', 'items': items,
             'notes': f'Asienta · {data["supplier_tax_id"]}'}
        tid = data['supplier_tax_id'] or supplier.get('tax_id')
        if tid:
            p['contactCode'] = tid
        return p

    def write(self, path, invoices, ctx):
        res, payloads = self.each(invoices, ctx, lambda _i, d, e, s: [self.payload(d, e, s)])
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payloads, f, ensure_ascii=False, indent=2)
        if self.settings and self.settings.bool('holded', 'push'):
            key = self.settings.secret('holded', 'api_key', 'HOLDED_API_KEY')
            for p in payloads:
                req = urllib.request.Request(self.URL, data=json.dumps(p).encode(), method='POST',
                                             headers={'key': key, 'Content-Type': 'application/json',
                                                      'Accept': 'application/json'})
                try:
                    urllib.request.urlopen(req, timeout=30).read()
                except (urllib.error.URLError, OSError) as e:
                    res.warnings.append(('exp.push_failed', {'number': p['invoiceNum'], 'error': str(e)[:120]}))
        return res


# ---------------------------------------------------------------------------- Xero
XERO_COLUMNS = ['*ContactName', 'EmailAddress', 'POAddressLine1', 'POAddressLine2', 'POAddressLine3',
                'POAddressLine4', 'POCity', 'PORegion', 'POPostalCode', 'POCountry', '*InvoiceNumber',
                '*InvoiceDate', '*DueDate', 'Total', 'InventoryItemCode', 'Description', '*Quantity',
                '*UnitAmount', '*AccountCode', '*TaxType', 'TaxAmount', 'TrackingName1', 'TrackingOption1',
                'TrackingName2', 'TrackingOption2', 'Currency']


def dmy(iso):
    return f'{iso[8:10]}/{iso[5:7]}/{iso[:4]}' if iso else ''


class Xero(Exporter):
    key = 'xero'
    label = 'Xero (bills CSV)'
    docs = 'docs/exporters.md#xero'

    def write(self, path, invoices, ctx):
        codes = parse_pairs(self.settings.get('xero', 'tax_types', '') if self.settings else '')

        def build(_i, data, entry, supplier):
            name = supplier.get('name') or data['supplier_name']
            rows = []
            for account, rate, base, vat in lines_or_skip(data, entry):
                row = dict.fromkeys(XERO_COLUMNS, '')
                row.update({'*ContactName': name, '*InvoiceNumber': data['invoice_number'],
                            '*InvoiceDate': dmy(entry['posting_date']), '*DueDate': dmy(due_date(data)),
                            'Total': f'{data["total"]:.2f}', 'Description': f'{name} {data["invoice_number"]}',
                            '*Quantity': '1', '*UnitAmount': f'{base:.2f}', '*AccountCode': account,
                            '*TaxType': tax_code(codes, rate) or f'{rate:g}%', 'TaxAmount': f'{vat:.2f}',
                            'Currency': 'EUR'})
                rows.append(row)
            return rows

        res, rows = self.each(invoices, ctx, build)
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, XERO_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        return res


# ---------------------------------------------------------------------------- QuickBooks
QB_COLUMNS = ['Bill No', 'Supplier', 'Bill Date', 'Due Date', 'Memo', 'Account', 'Line Description',
              'Line Amount', 'Line Tax Code', 'Line Tax Amount', 'Currency Code']


class QuickBooks(Exporter):
    key = 'quickbooks'
    label = 'QuickBooks Online (bills CSV)'
    docs = 'docs/exporters.md#quickbooks'

    def write(self, path, invoices, ctx):
        codes = parse_pairs(self.settings.get('quickbooks', 'tax_codes', '') if self.settings else '')

        def build(_i, data, entry, supplier):
            name = supplier.get('name') or data['supplier_name']
            return [{'Bill No': data['invoice_number'], 'Supplier': name, 'Bill Date': dmy(entry['posting_date']),
                     'Due Date': dmy(due_date(data)), 'Memo': f'{data["supplier_tax_id"]}', 'Account': account,
                     'Line Description': f'{name} {data["invoice_number"]}', 'Line Amount': f'{base:.2f}',
                     'Line Tax Code': tax_code(codes, rate) or f'{rate:g}%', 'Line Tax Amount': f'{vat:.2f}',
                     'Currency Code': 'EUR'}
                    for account, rate, base, vat in lines_or_skip(data, entry)]

        res, rows = self.each(invoices, ctx, build)
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, QB_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        return res
