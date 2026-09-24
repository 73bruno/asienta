"""Invoice mailbox: every few minutes Asienta checks an IMAP inbox (an address only for invoices:
forward them there) and takes the PDF and photo attachments.

It only reads and marks messages as seen. It never deletes or moves anything. A processed message
is remembered by its Message-ID and never taken twice, even if someone marks it unread.

Not every attachment is an invoice: a forwarded email carries the original sender's SIGNATURE
(logos, social icons, a contact card). Those are set aside before spending an AI reading on them.
Set-aside files are NOT thrown away: they show up in the Mailbox screen with the reason and a
button to take them in if the filter got it wrong.
"""
import email
import email.policy
import email.utils
import imaplib
import re
import struct

EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif')
TYPES = {'application/pdf', 'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'}
MIN_IMAGE_BYTES = 40_000          # below this an image is a logo, not an invoice
MIN_SIDE = 400                    # pixels on the longest side
SIGNATURE_NAMES = re.compile(r'\b(logo|firma|signature|banner|icono?|icon|footer|cabecera|header|linkedin|'
                             r'facebook|twitter|instagram|whatsapp|youtube|tiktok)\b', re.I)


def image_size(data):
    """(width, height) of a PNG, JPEG or GIF from its header, or None. No dependencies."""
    try:
        if data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR':
            return struct.unpack('>II', data[16:24])
        if data[:3] == b'GIF':
            return struct.unpack('<HH', data[6:10])
        if data[:2] == b'\xff\xd8':                       # JPEG: look for the SOFn marker
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker, length = data[i + 1], struct.unpack('>H', data[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack('>HH', data[i + 5:i + 9])
                    return w, h
                i += 2 + length
    except Exception:
        pass
    return None


def inline_cids(msg):
    """Image IDs referenced by the email body: those are inside the text (signature, banner)."""
    cids = set()
    for part in msg.walk():
        if part.get_content_type() in ('text/html', 'text/plain'):
            try:
                body = part.get_content()
            except Exception:
                continue
            cids |= {c.lower() for c in re.findall(r'cid:([^"\'\s>)]+)', str(body))}
    return cids


def why_not(part, name, data, cids):
    """'' if the attachment looks like a real document; otherwise why it is set aside."""
    kind = (part.get_content_type() or '').lower()
    if kind == 'application/pdf' or name.lower().endswith('.pdf'):
        return ''                                         # a PDF is never an email signature
    cid = (part.get('Content-ID') or '').strip('<>').lower()
    if cid and cid in cids:
        return 'inside the email text (signature or banner)'
    if len(data) < MIN_IMAGE_BYTES:
        return f'image of only {len(data) // 1024} KB: looks like a logo or icon'
    wh = image_size(data)
    if wh and max(wh) < MIN_SIDE:
        return f'{wh[0]}x{wh[1]} px image: too small to be an invoice'
    if SIGNATURE_NAMES.search(name):
        return f'named "{name}": a signature or logo name'
    return ''


def attachments(msg):
    """(part, name, bytes) of every PDF or photo, also inside forwarded messages."""
    for part in msg.walk():
        if part.is_multipart():
            continue
        name = part.get_filename() or ''
        if part.get_content_type() in TYPES or name.lower().endswith(EXTENSIONS):
            data = part.get_payload(decode=True)
            if data:
                yield part, name or 'attachment', data


def allowed(sender, allow_list):
    """allow_list: addresses or domains separated by commas; empty = everyone."""
    allowed_ = [x.strip().lower() for x in (allow_list or '').split(',') if x.strip()]
    if not allowed_:
        return True
    addr = email.utils.parseaddr(sender)[1].lower()
    return any(addr == a or addr.endswith('@' + a.lstrip('@')) for a in allowed_)


def process(msg, mid, cfg, db, receive, log=print, set_aside=None):
    """One email: take the documents, set the rest aside, remember it. Returns how many were taken.
    Used for every IMAP message and, in demo mode, for a simulated one."""
    if db.email_seen(mid):
        return 0
    sender, subject = str(msg.get('From', '')), str(msg.get('Subject', ''))
    n, aside = 0, 0
    if allowed(sender, cfg.get('allowed_senders')):
        cids = inline_cids(msg)
        for part, name, content in attachments(msg):
            reason = why_not(part, name, content, cids)
            if reason and set_aside:
                set_aside(content, name, part.get_content_type(), reason,
                          {'mid': mid, 'sender': sender, 'subject': subject})
                aside += 1
                continue
            receive(content, name, 'email', f'{sender} · {subject}', mid)
            n += 1
        if not n:
            log(f'email without invoices: {sender} · {subject}' + (f' ({aside} set aside)' if aside else ''))
    else:
        log(f'email from a sender not allowed, ignored: {sender}')
    db.add_email(mid, sender, subject, n)
    return n


def check(cfg, db, receive, log=print, set_aside=None):
    """Process unseen messages. receive(bytes, name, source, detail, message_id) takes each
    attachment; set_aside(bytes, name, mime, reason, email_info) keeps the ones that are not
    documents. Returns how many attachments were taken."""
    m = imaplib.IMAP4_SSL(cfg['server'], int(cfg.get('port') or 993), timeout=60)
    taken = 0
    try:
        m.login(cfg['user'], cfg['password'])
        m.select(cfg.get('folder') or 'INBOX')
        _t, found = m.uid('search', None, 'UNSEEN')
        unseen = (found[0] or b'').split()
        # A few at a time: if someone marks 300 messages unread, or a spam wave arrives, they go in
        # over the next passes instead of queueing 300 readings at once.
        cap = int(cfg.get('max_per_pass') or 20)
        if len(unseen) > cap:
            log(f'mailbox: {len(unseen)} unseen; taking {cap} now and the rest later')
            unseen = unseen[:cap]
        for uid in unseen:
            _t, d = m.uid('fetch', uid, '(BODY.PEEK[])')
            raw = next((x[1] for x in d if isinstance(x, tuple)), None)
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            mid = (msg.get('Message-ID') or f'uid-{uid.decode()}').strip()
            taken += process(msg, mid, cfg, db, receive, log, set_aside)
            m.uid('store', uid, '+FLAGS', '(\\Seen)')
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return taken
