# Security

Asienta handles invoices and connects to accounting data, so reports are taken seriously.

**Please report vulnerabilities privately** through GitHub's *Report a vulnerability* button in the
Security tab of this repository, not in a public issue. You'll get an answer within a week.

What the app does to protect itself, for context:

- Listens on `127.0.0.1` unless given an access token or `--tailscale`.
- Checks the `Host` header (DNS rebinding) and requires an `X-Asienta` header on every write
  (cross-site requests from other tabs can't set it).
- Accepts uploads only when their bytes are a PDF or an image, up to 15 MB; files are stored under
  content-hash names inside the data folder, with path checks.
- Renders invoice content as text, never HTML; strict Content-Security-Policy on the page.
- Reads the ledger with read-only credentials; never writes into it.
- Keeps secrets in environment variables; API keys are masked in error messages.
