<div align="center">

<img src="asienta/web/favicon.svg" width="72" alt="">

# Asienta

Reads supplier invoices with an LLM and turns them into journal entries,<br>
exported in the import format of your accounting software.

[![CI](https://github.com/73bruno/asienta/actions/workflows/ci.yml/badge.svg)](https://github.com/73bruno/asienta/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Dependencies](https://img.shields.io/badge/dependencies-0-16A34A)
![License](https://img.shields.io/badge/license-MIT-4F46E5)

<img src="docs/media/demo.gif" width="100%" alt="An emailed receipt photo is read, a misread tax ID is fixed in one click, a wholesaler's invoice is split by account and everything is exported">

<sub>The demo, with fictional data · [MP4](docs/media/demo.mp4) · [Español](README.es.md)</sub>

</div>

## What it does

1. Collects invoices (PDFs and photos) from an email inbox, a folder, the browser or an HTTP API.
2. Sends each one to an LLM that extracts supplier, tax ID, number, date, lines and VAT into a fixed JSON schema.
3. Proposes the journal entry from your ledger: supplier account, expense accounts, line split, posting date.
4. Runs checks: tax-ID check digits, totals, VAT per rate, duplicates, closed VAT periods.
5. After a person approves, writes one import file for the accounting program.

The LLM only does step 2. Steps 3 and 4 are deterministic Python, so every proposal can be traced and tested, and the model can be replaced without touching them.

## Included

- **Inputs**: IMAP inbox (forwarded mail and signature logos handled), watched folder, drag & drop, phone camera, HTTP API.
- **LLM providers**: Gemini (default), Claude, OpenAI, any OpenAI-compatible endpoint (Mistral, OpenRouter, Azure…), local models through Ollama, LM Studio or vLLM.
- **Ledger sources** (read-only): CSV files, a Sage 50 / ContaPlus accounts export, or a live connection to Sage 50's SQL Server.
- **Export formats**: Sage 50 (XDIARIO), CSV and JSON. ContaPlus, Sage 50 Excel importer, a3ASESOR, Holded, Xero and QuickBooks Online are written from their published specs and tested, but not yet imported into the real programs (beta).
- **Tax rules**: Spain (NIF/NIE/CIF check digits, IVA, IRPF withholding, equivalence surcharge, credit notes, filed VAT quarters).
- **Web UI**: review screen, English and Spanish, light and dark, your own name, colour and logo.

## Accuracy

With the default model, `gemini-3.8-flash`, it reads **160–161 of 162 fields** right on a set of 27 real supplier invoices checked by hand: handwritten invoices, thermal-printer tickets, crumpled photos, scans, credit notes and a PDF with three invoices in it. It was chosen after comparing five Gemini models on that set, where it tied for the most fields read right, at about 6 s and under one US cent per invoice.

Other providers plug in the same way but haven't been measured on that set. `asienta bench` runs the same comparison on your own invoices ([details](docs/ai-models.md)).

## Quick start

```bash
pip install "git+https://github.com/73bruno/asienta"
asienta --demo            # http://localhost:8760, fictional ledger and invoices, no API key
```

With your own data:

```bash
asienta init              # writes config.ini and ledger/ with example CSVs
export GEMINI_API_KEY=…
asienta check             # checks the model and the ledger connection
asienta
```

## Configuration

Each part is chosen in `config.ini`:

```ini
[reader]
provider = gemini              ; gemini | claude | openai | ollama
model = gemini-3.8-flash

[ledger]
source = csv                   ; csv | sage50

[export]
format = sage50                ; sage50 | contaplus | sage50xls | a3 | holded | xero | quickbooks | csv | json

[inbox]
folder = ~/Dropbox/Invoices    ; optional, [mailbox] for IMAP

; line categories the LLM assigns, and the account each one goes to
[categories]
food   = 600000100 | food, ingredients, sauces
drinks = 600000200 | wine, beer, soft drinks, water, coffee
```

To keep invoices on your network, point it at a local model:

```ini
[reader]
provider = ollama
model = llama3.2-vision
```

The minimum ledger is one CSV with your chart of accounts and suppliers; a second one with what each supplier's invoices were booked to lets it propose accounts from day one. Formats in [docs/ledger.md](docs/ledger.md).

## Adapting it

Readers, ledger sources and exporters are small classes registered in a dictionary.

**Another accounting program.** An exporter receives approved, balanced entries and writes a file:

```python
class MySoftware(Exporter):
    key, label, extension = 'mysoftware', 'My Software (CSV)', '.csv'

    def write(self, path, invoices, ctx):
        def build(_i, data, entry, supplier):
            return [[data['invoice_number'], entry['posting_date'], entry['supplier_account'],
                     account, rate, f'{base:.2f}', f'{vat:.2f}']
                    for account, rate, base, vat in split_vat(data, entry)]
        result, rows = self.each(invoices, ctx, build)
        with open(path, 'w', newline='') as f:
            csv.writer(f, delimiter=';').writerows(rows)
        return result
```

Registered in `asienta/exporters/__init__.py`, it is picked up by the test that runs every exporter over the demo invoices.

**Another LLM.** If it has an OpenAI-compatible endpoint, set `provider = openai` and `base_url`. Otherwise a reader is one class with a `read()` method that returns the schema's JSON.

**Another ledger.** Any object with a `load()` that returns account names, tax IDs and usual accounts per supplier.

**Another country.** Tax-ID validation and VAT periods live in `asienta/spain.py`; a sibling module for another country is the main change.

**Integrations.** Everything the UI does goes through a small HTTP API: upload, read the result, approve, export, download ([docs/api.md](docs/api.md)).

Step-by-step guides in [docs/extending.md](docs/extending.md).

## How it decides

- **Supplier**: tax ID in your ledger, then name. A supplier picked by hand is remembered.
- **Accounts**: the account this supplier's invoices went to most this year; lines are split by category, so the wine on a food wholesaler's invoice goes to drinks.
- **Posting date**: the invoice date, or the first open day if that VAT quarter is already filed.
- **Checks**: a tax ID that fails its check digit gets a one-click fix from the ledger; totals, VAT, dates, duplicates, withholding and possible fixed assets are flagged before approval.

More in [docs/how-it-works.md](docs/how-it-works.md).

## Project layout

```
asienta/
  extraction/   LLM readers (gemini, claude, openai_compat, demo) and the JSON schema
  ledger/       ledger sources (csv, sage50) and the supplier/account directory
  rules.py      supplier matching, account choice, line split, posting date
  checks.py     everything flagged before approval
  exporters/    one module per accounting format
  spain.py      Spanish tax IDs and VAT periods
  mailbox.py    IMAP intake
  app.py        the pipeline; server.py the HTTP API; web/ the UI (no build step)
tests/          full pipeline on the demo data, exporters, API, readers (mocked)
scripts/        demo data, demo video, speed measurement
```

Standard library only: `http.server`, `sqlite3`, `urllib`, plain JavaScript. Optional packages for Claude, Sage 50 SQL and Excel. The package is 240 KB and idles at 26 MB of RAM; rules and checks take about 2 ms per invoice (`python scripts/speed.py`).

## Development

```bash
git clone https://github.com/73bruno/asienta && cd asienta
pip install -e ".[dev]"
pytest                    # a few seconds, offline
```

Contributions are welcome, especially exporters for other programs and reports from importing the beta formats into the real ones. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE).

<sub>Sage 50, ContaPlus, a3ASESOR, Holded, Xero and QuickBooks are trademarks of their owners; this project isn't affiliated with them.</sub>
