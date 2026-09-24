# Connecting your ledger

Asienta needs to *read* a few things from your accounting: the chart of accounts (to know names and
which accounts are suppliers, expenses and input VAT), the suppliers' tax IDs, and ideally what each
supplier was booked to this year and which invoices are already in. It never writes.

Choose one source in `config.ini`:

```ini
[ledger]
source = csv          ; csv | sage50
```

## CSV files (any accounting program)

A folder (`[ledger] folder = ledger`) with up to three files. UTF-8 or Windows-1252, comma or
semicolon; headers in English or Spanish (`cuenta`, `nombre`, `nif` also work). `asienta init`
creates the folder with the demo files as a template.

**`accounts.csv`** (required): the chart of accounts, suppliers included.

```csv
account,name,tax_id,vat_rate
600000100,Food purchases,,
472000021,Input VAT 21%,,21
400000001,MEDITERRANEAN FOODS DEMO S.L.,B46182739,
```

`vat_rate` is optional: input VAT accounts are also recognised by the rate in their name.

**`history.csv`** (recommended): what each supplier's invoices were booked to. This is what makes
proposals right from day one.

```csv
supplier_account,expense_account,amount,invoices
400000001,600000100,18450.20,42
400000001,600000200,3120.50,15
```

Most programs can export a ledger by account or a journal; sum it by (supplier, expense account).

**`booked.csv`** (optional): invoices already in the books, to catch duplicates.

```csv
supplier_account,number,date,base
400000003,SC/0388,2026-09-10,172.55
```

Refresh them as often as you like; Asienta reloads every `refresh_minutes`.

## Sage 50 / ContaPlus accounts export (no SQL)

Sage 50's free add-on *Importación / Exportación de asientos* can **export** the subaccounts file
(ContaPlus `XSUBCTA` structure, `.csv`). Point Asienta at it:

```ini
[ledger]
source = csv
contaplus_accounts = C:\exports\XSUBCTA.csv
```

It brings account names, suppliers' tax IDs and — the valuable part — the VAT type and rate Sage
has configured on each 472 account, which is more reliable than guessing from names. You can still
add `history.csv` and `booked.csv` next to it.

## Sage 50 live (read-only)

Sage 50 (Spain) stores each company in a SQL Server database. Asienta can read it directly: suppliers
by tax ID, the usual expense accounts per supplier from this year's entries, the VAT book (to detect
invoices already booked) and entry numbers (to rename PDFs for attaching).

```bash
pip install "asienta[sage50]"      # pymssql
```

1. **Create a read-only login** in SQL Server Management Studio, on the instance Sage uses:

   ```sql
   CREATE LOGIN asienta_reader WITH PASSWORD = '…a long one…', CHECK_POLICY = ON;
   USE [YourCompanyDatabase];
   CREATE USER asienta_reader FOR LOGIN asienta_reader;
   ALTER ROLE db_datareader ADD MEMBER asienta_reader;
   ```

   `db_datareader` cannot modify anything. Mixed-mode authentication and TCP/IP must be enabled on
   the instance; give it a fixed port.

2. **Configure** (password better in `ASIENTA_SAGE50_PASSWORD`):

   ```ini
   [ledger]
   source = sage50
   [sage50]
   server = 192.168.1.20
   port = 1433
   user = asienta_reader
   database = 2026AB
   ```

3. `asienta check` shows how many suppliers and tax IDs it found and which input VAT accounts it
   will use.

Notes from real installations:

- The supplier tax ID usually lives in `proveed.CIF`. If `tax_id_table` is left empty, Asienta
  searches the schema and keeps the table that covers the most supplier accounts.
- Sage stores only the **digits** of the supplier's invoice number in the VAT book (`ivasopor.NUMFRA`),
  without its prefix: `A/26001234` becomes `001234`. Duplicate detection therefore also compares
  the last six digits.
- A company can have two 472 accounts for the same rate; the most used one wins. Override with
  `[accounts] input_vat = 21:472000021, 10:472000010`.
- If the SQL Server is on another site, a VPN such as Tailscale between the two machines is simpler
  and safer than opening ports.

## Writing another source

A source is a class with `kind` and `load()` returning plain dicts; see the docstring in
`asienta/ledger/directory.py` and [extending](extending.md).
