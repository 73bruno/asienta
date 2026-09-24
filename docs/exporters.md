# Exporters

Approved invoices leave Asienta in **batches**: one file with all of them, in the format your
program imports. Pick the default in `config.ini` and change it per batch in the interface.

```ini
[export]
format = sage50        ; sage50 | contaplus | sage50xls | a3 | holded | xero | quickbooks | csv | json
drop_folder =          ; optional: also copy each file here (a shared folder the accounting PC sees)
fixed_name =           ; optional: and once more with a fixed name, e.g. PARA_IMPORTAR.csv
```

Every exporter starts from the same balanced postings (`exporters/base.py::journal`):

```
expense accounts   DEBIT   base        one line per account of the split
input VAT          DEBIT   VAT         one line per rate, carrying the VAT-book data
withholding        CREDIT  IRPF        only if the invoice has it
supplier           CREDIT  total
```

An invoice that cannot be expressed cleanly — no input VAT account for a rate, a surcharge the
format can't carry, an entry that doesn't balance — is **left out whole**, with a warning, and
stays in *Ready to export*. A batch can be undone until it is imported.

> **Before the first real import**, whatever the format: import a first file into a test company
> (or a copy) and compare the entries and the VAT book with what you expect.

## Sage 50

**`sage50` — XDIARIO `.csv` for the free add-on** *(primary)*

Sage 50's free add-on *Importación / Exportación de asientos* (enable it in the add-ons area, then
**Archivos › Importación de asientos**) reads files with ContaPlus's `XDIARIO` structure. Asienta
writes the `.csv` variant: one line per posting, **116 fields** separated by `;`, all present even
when empty, Windows-1252, CRLF, amounts in euros (`MonedaUso = 2`, `EuroDebe`/`EuroHaber`).

What turns an entry into a **VAT-book record** in Sage are the auxiliary fields of the VAT line:
`Contra` (supplier), `BaseEuro`, `IVA` (rate), `Factura` (the number's digits), `FacturaEx` (the full
number), `TipoFac = R`, `TipoIVA = O` and `TerNif`/`TerNom`. Asienta fills all of them, and marks
`OpBienes = 2` when the split includes an asset account (2xx).

Settings: `description` (the entry text, with `{number}`, `{supplier}`, `{date}`),
`description_length` (25 in the protocol; many installations accept more), `first_entry`.

The input VAT accounts come from the ledger (Sage's own configuration if you use the `XSUBCTA`
export or the SQL connector) or from `[accounts] input_vat = 21:472000021, 10:472000010, 4:472000004`.

Tip: set `drop_folder` to a folder the accounting PC can see and `fixed_name = PARA_IMPORTAR.csv`.
Sage's import wizard remembers the last path, so importing becomes: open the wizard, next, next.
In *Exported*, **Invoices (PDF)** downloads the batch's documents renamed
`<entry number> - <supplier> - <invoice>.pdf` (entry numbers read live from Sage), to attach them
to their entries with one drag.

**`sage50xls` — the paid add-on** *(beta)*: the `.xlsx` for *Importador Excel de facturas en
asientos*. One row per VAT rate and expense account. If your installation expects a VAT code
instead of the percentage, map it: `[sage50xls] vat_codes = 21:3, 10:2, 4:1`.

## ContaPlus

**`contaplus` — classic `XDIARIO.TXT`** *(beta)*: the fixed-width layout (287 characters per line)
of older ContaPlus versions. It has no room for the full invoice number, the third party's tax ID or
the invoice type, so the VAT book is poorer than with the `.csv`: prefer `sage50` when the version
accepts it.

## a3ASESOR eco / con

**`a3` — `SUENLACE.DAT`** *(beta)*: Wolters Kluwer's accounting link, imported from
**Utilidades › Importación/Exportación › Enlace contable**. Fixed-width records of 512 bytes
(510 + CRLF), Windows-1252. Each invoice is a type-1 header (supplier account, total, tax ID, name,
dates, full number; type 2 for credit notes) followed by one type-9 detail per expense account and
VAT rate (base, rate, VAT, withholding and the input-VAT and withholding accounts). Invoice type is
`2` (purchases) or `3` (asset purchases).

```ini
[a3]
company_code = 00001
```

Positions follow the published record description, cross-checked against two independent open
implementations. Please report how the import went.

## Holded

**`holded` — purchase documents** *(beta)*: a JSON array with one body per invoice for
`POST https://api.holded.com/api/invoicing/v1/documents/purchase` (contact by name and tax ID,
invoice number, date, one item per account and rate with its `account`, `tax` and IRPF
`retention`). Set `[holded] push = true` and `HOLDED_API_KEY` to have Asienta send them itself;
the file is written either way and failures are reported per invoice.

## Xero

**`xero` — Import bills CSV** *(beta)*: Xero's bill template (`*ContactName`, `*InvoiceNumber`,
`*InvoiceDate`, `*DueDate`, `*AccountCode`, `*TaxType`, …), one row per split line. Import from
**Business › Bills to pay › Import**. Tax types are per organisation; map them:
`[xero] tax_types = 21:INPUT21, 10:INPUT10`.

## QuickBooks Online

**`quickbooks` — bills CSV** *(beta)*: `Bill No`, `Supplier`, `Bill Date`, `Due Date`, `Account`,
`Line Amount`, `Line Tax Code`… one row per split line. Map tax codes with
`[quickbooks] tax_codes = 21:IVA 21, 10:IVA 10`.

## CSV and JSON

**`csv`** *(stable)*: one row per expense account and VAT rate with every field (number, dates,
supplier account, name and tax ID, account, rate, base, VAT, withholding, total, type, due date).
For spreadsheets, programs with a configurable importer (Contasol, Odoo, Factusol…) or your own
script.

**`json`** *(stable)*: the reviewed invoice, its posting and the supplier, as they are inside
Asienta.

## Add yours

See [extending](extending.md#an-exporter). The tests in `tests/test_flow.py` run every exporter on
the demo invoices; a new one gets the same coverage by being registered.
