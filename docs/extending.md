# Extending Asienta

Three extension points, each a small class. No plugin system to learn: add the file, register it
in one dictionary, run `pytest`.

## An exporter

Everything an exporter receives is already reviewed, approved and balanced. Most exporters are a
loop and a writer. This is a complete one:

```python
# asienta/exporters/mysoftware.py
import csv

from .base import Exporter, split_vat


class MySoftware(Exporter):
    key = 'mysoftware'                  # [export] format = mysoftware
    label = 'My Software (CSV)'         # shown in the export menu
    extension = '.csv'
    maturity = 'beta'

    def write(self, path, invoices, ctx):
        def build(_i, data, entry, supplier):
            # one row per expense account and VAT rate; split_vat shares the printed VAT out
            return [[data['invoice_number'], entry['posting_date'], entry['supplier_account'],
                     account, rate, f'{base:.2f}', f'{vat:.2f}']
                    for account, rate, base, vat in split_vat(data, entry)]

        result, rows = self.each(invoices, ctx, build)     # collects skips as warnings
        with open(path, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f, delimiter=';').writerows(rows)
        return result
```

Register it in `asienta/exporters/__init__.py`:

```python
from .mysoftware import MySoftware
EXPORTERS = {e.key: e for e in (..., MySoftware)}
```

Useful pieces from `exporters/base.py`:

| | |
|---|---|
| `journal(data, entry, supplier, ctx)` | balanced debit/credit postings (expense, VAT, withholding, supplier); raises `Skip` if it can't |
| `split_vat(data, entry)` | `[(account, rate, base, vat)]`, VAT shared out so it adds up to the printed amount |
| `description(ctx, data, supplier)` | the entry text from `[export] description` |
| `ctx.vat_accounts`, `ctx.withholding_account` | from the ledger and config |
| `raise Skip('exp.surcharge', amount=…)` | leave one invoice out with a translated warning |

`tests/test_flow.py::test_export_every_format` runs every registered exporter on the demo
invoices, so a new one is tested the moment it's registered. Add a format-specific assertion
(record length, column count…) and send a pull request with a note on how you verified the
import.

## A reader (another AI provider or an OCR)

```python
from . import ReadError, Reading
from .schema import unwrap


class MyReader:
    name = 'My model'
    model = 'my-model-1'
    ready = True

    def __init__(self, settings):
        self.key = settings.secret('reader', 'api_key', 'MY_API_KEY')

    def read(self, content, mime, prompt, schema, categories):
        answer = call_my_model(content, mime, prompt, schema)      # must return the schema's JSON
        if not answer:
            raise ReadError('my model returned nothing')
        return Reading(unwrap(answer, categories), tokens_in=0, tokens_out=0, seconds=0.0, model=self.model)
```

Register it in `open_reader()` in `asienta/extraction/__init__.py`. (Before writing one, check
whether the provider offers an OpenAI-compatible endpoint: then `provider = openai` with its
`base_url` already works.) `unwrap()` normalizes the
answer, so the model only has to follow the schema. Compare it with the others on your own
documents with `asienta bench`.

## A ledger source

Any object with `kind` and `load()`:

```python
class MySource:
    kind = 'mysoftware'

    def load(self):
        return {
            'names': {'400000001': 'SUPPLIER S.L.', '600000100': 'Purchases', ...},
            'tax_ids': {'400000001': 'B46182739'},
            'usual': {'400000001': {'600000100': (18450.20, 42)}},      # (amount, invoices) this year
            'invoices': {'400000001': [{'number': 'A/1', 'date': '2026-09-01', 'base': 100.0}]},
        }
```

Optionally `entry_for(supplier_account, date, total)` returns the entry number of an imported
invoice (used to rename PDFs). Register it in `asienta/ledger/__init__.py`.

## Another country

Spanish specifics live in `asienta/spain.py` (tax-ID check digits, VAT filing deadlines) and in a
few defaults (`400/410` supplier accounts, `472` input VAT, `6`/`2` expense and asset accounts,
all configurable in `[ledger]`). Porting to another country means a sibling of `spain.py` and
choosing it from config; the rest of the pipeline is country-agnostic.
