# Invoices by email

Most invoices already arrive by email. Give them an inbox of their own — `facturas@yourcompany.com`
— and ask suppliers and colleagues to send or forward them there. Asienta checks it every few
minutes and takes every PDF and photo in.

```ini
[mailbox]
server = imap.gmail.com           ; outlook.office365.com, imap.zoho.eu, your provider's IMAP
port = 993
user = facturas@yourcompany.com
password =                        ; an app password, better in ASIENTA_MAILBOX_PASSWORD
address = facturas@yourcompany.com   ; shown in the app: "forward invoices to…"
allowed_senders = yourcompany.com, supplier.es   ; optional: only these addresses or domains
every_minutes = 5
max_per_pass = 20
```

**App passwords.** Gmail and Outlook require one for IMAP when two-step verification is on:
Google Account › Security › App passwords; Microsoft account › Security › Advanced security
options › App passwords. Use a dedicated mailbox, not a personal one.

## What happens to each email

- Only **unread** messages are processed, then marked read. Nothing is deleted or moved.
- Each message is remembered by its `Message-ID`: marking it unread again doesn't import twice,
  and the same file arriving in two emails is recognised by its fingerprint.
- PDFs and photos are taken, including those inside forwarded messages.
- What looks like part of an email signature is **set aside, not thrown away**: images referenced
  from the email body, images under 40 KB or smaller than 400 px, and files named like logos or
  social icons. The Mailbox screen shows each one with its reason and two buttons, *It's an
  invoice* (read it) and *It isn't*.
- A big backlog (someone marks 300 emails unread) is taken 20 at a time, pass after pass.
- `allowed_senders` ignores everything else, which keeps spam from spending readings.

## Trying it without an inbox

In the demo, **Mailbox › Send a test email** builds a forwarded message with a photographed
receipt and a logo in the signature, and runs it through exactly the same code as a real IMAP
message: the photo is read, the logo is set aside.
