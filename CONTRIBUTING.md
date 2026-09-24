# Contributing

Thanks for helping. The most useful contributions, in order:

1. **Field reports on beta exporters.** Imported an A3, Holded, Xero, QuickBooks or ContaPlus file?
   Open an issue with the *Exporter report* template: version of the program, what worked, what
   didn't (screenshots of error messages help a lot). Never attach real invoices.
2. **New exporters** for accounting programs people use. See [docs/extending.md](docs/extending.md).
3. **Bugs** with steps to reproduce on the demo data (`asienta --demo`).

## Development

```bash
git clone https://github.com/73bruno/asienta && cd asienta
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # a few seconds, no network, no API key
ruff check .
asienta --demo    # the app with sample data
```

Ground rules, the same the code follows:

- **The AI only reads.** Decisions (accounts, dates, matching) are rules in `rules.py`, visible
  and testable. A new decision is a new rule with a test, not a longer prompt.
- **Nothing is written into the user's ledger.** Sources are read-only; exporters write files.
- **Standard library in the core.** Optional features may use an extra (`[claude]`, `[sage50]`).
- **Every user-facing text in both languages** (`asienta/i18n.py`, `asienta/web/i18n.js`).
- **No real data** in issues, tests or fixtures. `scripts/make_demo.py` generates fictional
  invoices whose tax IDs pass the check digit; extend it if you need a new case.

Commit messages: short imperative summary; explain the *why* in the body when it isn't obvious.
