# Changelog

## 0.1.0 — 2026-09-24

First public release.

- AI readers: Gemini (REST, no dependencies), Claude (official SDK), any OpenAI-compatible API
  including local models (Ollama, LM Studio, vLLM), demo.
- Ledger sources: CSV, Sage 50 / ContaPlus `XSUBCTA` export, Sage 50 live (read-only SQL).
- Rules: supplier matching, usual account, split by line category, closed VAT quarters.
- Checks with one-click fixes, including tax-ID check-digit repair.
- Exporters: Sage 50 XDIARIO (primary); ContaPlus, Sage 50 Excel, A3 SUENLACE.DAT, Holded,
  Xero, QuickBooks (beta); CSV and JSON.
- Web interface in Spanish and English, light and dark, brandable.
- Ways in: IMAP mailbox (with signature and logo filtering), a watched folder, drag & drop, the
  phone camera, and an HTTP API (bearer token off localhost). A simulated email in demo mode.
- `asienta bench` to measure readings and silent errors on your own invoices;
  `scripts/speed.py` for start-up, memory, rules and export timings.
- Demo in English: a fictional bistro, its ledger and nine sample invoices.
