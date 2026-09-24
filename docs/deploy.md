# Deploying

Asienta is one Python process with a SQLite file. It is meant to run on a machine you control: the
office PC, a small server, a NAS.

## On one computer

```bash
pip install "git+https://github.com/73bruno/asienta"
asienta init && asienta
```

It listens on `127.0.0.1:8760` only. Nothing else can reach it.

## For a team

Invoices are sensitive and the app is powerful (it can approve and export), so anything beyond
localhost requires a way in:

**A token**, for a LAN:

```bash
export ASIENTA_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
asienta --host 0.0.0.0
```

People sign in once per browser with the token; the session is an HttpOnly, SameSite=Strict cookie.
Scripts send it as `Authorization: Bearer …` ([API](api.md)).
Put it behind HTTPS (Caddy, nginx) if the network isn't yours.

**Tailscale**, for people in different places (the accounting PC at the office, the app on a
server): `asienta --tailscale` listens only on the machine's Tailscale IP, so only devices in your
tailnet can reach it.

Asienta refuses to listen on a non-local address without one of the two.

## Docker

```bash
docker build -t asienta .
docker run -d --name asienta -p 8760:8760 \
  -e ASIENTA_TOKEN=change-me -e GEMINI_API_KEY=… \
  -v $PWD/asienta-data:/data asienta
```

`/data` holds `config.ini` (created on first run from the example), the ledger CSVs, the database,
the documents and the export files. `docker compose up -d` does the same with `docker-compose.yml`.

## As a Windows service

The typical Sage 50 office runs Windows. Create a scheduled task that starts at boot, runs as a
service account and restarts on failure:

```powershell
$action  = New-ScheduledTaskAction -Execute "py" -Argument "-m asienta --tailscale" -WorkingDirectory "C:\Asienta"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "Asienta" -Action $action -Trigger $trigger -Settings $settings -User "SYSTEM"
```

Keep `GEMINI_API_KEY` as a system environment variable rather than in `config.ini`.

## Backups

Everything is in the data folder: `asienta.db` (SQLite, WAL mode), `files/` (the documents),
`batches/` (every export). Copy the folder; for a hot copy use `sqlite3 asienta.db ".backup x.db"`.

## Privacy checklist

- Use a **paid-tier** AI key: free tiers of some providers may use the data to improve models.
- The ledger connection should be **read-only** (`db_datareader` on Sage 50).
- Documents never leave the machine except for the reading request to the AI provider you chose.
- `asienta --demo` never contacts anything.
