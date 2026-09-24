# Connect it to anything

Invoices can reach Asienta five ways, and anything that can copy a file or make an HTTP request
can drive it.

| Way in | Set up | Good for |
|---|---|---|
| **Email** | `[mailbox]` in `config.ini` ([mailbox.md](mailbox.md)) | suppliers and colleagues forwarding invoices |
| **Watched folder** | `[inbox] folder = ~/Scans` | a scanner's *scan to folder*, a synced Dropbox / OneDrive / Google Drive, a shared drive |
| **Browser** | nothing | drag & drop, several at once |
| **Phone camera** | open the app on the phone (LAN or [Tailscale](deploy.md)) | paper tickets, on the spot |
| **HTTP API** | nothing locally; a token for anything else | n8n, Zapier, Make, cron jobs, your own scripts |

## Watched folder

```ini
[inbox]
folder = ~/Dropbox/Invoices
```

Every 30 seconds new files are taken, read like any other invoice and moved to `done/` inside the
folder. Anything that isn't a PDF or a photo goes to `skipped/`. Files still being written (changed
in the last few seconds) wait for the next round, and the same file twice is only read once.

## HTTP API

The same API the web app uses. Every write needs the `X-Asienta: 1` header; that header is what
stops another website open in the same browser from posting to it.

```bash
A=http://localhost:8760

# send an invoice (PDF, JPG, PNG, WEBP, HEIC; up to 15 MB)
curl -H 'X-Asienta: 1' -H 'X-Filename: invoice.pdf' --data-binary @invoice.pdf $A/api/upload
# → {"id": 12, "known": false}          known = the same file was already there

# what it read, the proposed entry and every check
curl $A/api/invoices/12
# → {"status": "review", "data": {…}, "entry": {…}, "findings": [{"level": "warning", …}], …}

# approve it as proposed (409 with the errors if something must be fixed first)
curl -H 'X-Asienta: 1' -d '{}' $A/api/invoices/12/approve

# export everything approved, then download the file
curl -H 'X-Asienta: 1' -d '{"format": "xero"}' $A/api/batches
curl -OJ $A/api/batches/latest/file
```

| | |
|---|---|
| `POST /api/upload` | body = the file; `X-Filename` optional |
| `GET /api/invoices?view=review` | `review`, `approved` (ready to export), `exported`, `discarded` |
| `GET /api/invoices/{id}` | reading, entry, findings (`X-Lang: en` or `es` for the texts) |
| `GET /api/invoices/{id}/file` | the original document |
| `POST /api/invoices/{id}/save` | body `{"data": {…}, "entry": {…}}`, partial is fine |
| `POST /api/invoices/{id}/approve` | same body, optional |
| `POST /api/invoices/{id}/discard`, `/reopen`, `/reread` | |
| `POST /api/batches` | body `{"format": "sage50"}` (any key from [exporters](exporters.md)); omitted = the configured one |
| `GET /api/batches` | past exports |
| `GET /api/batches/latest/file`, `/api/batches/{n}/file` | the export file |
| `GET /api/batches/{n}/pdfs` | the batch's invoices as a zip, renamed after their entries |
| `POST /api/batches/{n}/undo` | back to *ready*, while not yet imported |
| `GET /api/state` | counts, ledger status, the month's cost |

### From another machine

Off `127.0.0.1` the app requires an access token ([deploy.md](deploy.md)). Scripts send it as a
bearer token:

```bash
curl -H "Authorization: Bearer $ASIENTA_TOKEN" -H 'X-Asienta: 1' \
     -H 'X-Filename: invoice.pdf' --data-binary @invoice.pdf https://asienta.example.lan/api/upload
```

A typical automation: a mail rule or a Drive trigger in n8n/Zapier posts each new file to
`/api/upload`; someone reviews in the browser; a nightly job posts to `/api/batches` and drops the
file where the accounting software imports from (or set `[export] drop_folder` and skip that
step).
