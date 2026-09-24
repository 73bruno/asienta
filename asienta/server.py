"""The web interface: a small JSON API plus a static single-page app (asienta/web). Standard
library only.

Security, since invoices are sensitive:
  * Listens on 127.0.0.1 by default. Anything else (LAN, Docker, Tailscale) needs an access token.
  * Host header check against DNS rebinding.
  * Every state-changing request needs the X-Asienta header, which another website open in the
    same browser cannot send without a CORS permission that is never granted.
  * Uploads are accepted only if their bytes are a PDF or an image; 15 MB max.
  * Invoice text is always rendered as text in the browser, never as HTML.
"""
import hmac
import json
import os
import re
import secrets
import socket
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .app import MAX_FILE

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
STATIC = {'/app.css': 'text/css; charset=utf-8', '/app.js': 'text/javascript; charset=utf-8',
          '/i18n.js': 'text/javascript; charset=utf-8', '/favicon.svg': 'image/svg+xml'}
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
       "frame-src 'self'; frame-ancestors 'none'")


class Handler(BaseHTTPRequestHandler):
    server_version = f'Asienta/{__version__}'
    app = None
    hosts = set()
    token = ''
    session = secrets.token_urlsafe(24)       # value of the login cookie for this run

    def log_message(self, *a):
        pass

    # ------------------------------------------------------------------ plumbing
    def _host_ok(self):
        if '*' in self.hosts:              # listening on all interfaces: the token protects it
            return True
        h = (self.headers.get('Host') or '').rsplit(':', 1)[0].strip('[]').lower()
        return h in self.hosts or h.endswith('.ts.net')

    def _authed(self):
        if not self.token:
            return True
        auth = self.headers.get('Authorization') or ''          # scripts: Authorization: Bearer <token>
        if auth.startswith('Bearer ') and hmac.compare_digest(auth[7:].strip(), self.token):
            return True
        cookie = self.headers.get('Cookie') or ''
        m = re.search(r'asienta_session=([\w-]+)', cookie)
        return bool(m) and hmac.compare_digest(m.group(1), self.session)

    def _lang(self, q=None):
        lang = (self.headers.get('X-Lang') or (q or {}).get('lang', [''])[0] or '').lower()
        return lang if lang in ('es', 'en') else self.app.s.language

    def _headers(self, code, kind, length, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(length))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _json(self, obj, code=200, extra=None):
        b = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self._headers(code, 'application/json; charset=utf-8', len(b), extra)
        self.wfile.write(b)

    def _error(self, text, code=400):
        self._json({'error': text}, code)

    def _file(self, path, kind, extra=None):
        with open(path, 'rb') as f:
            b = f.read()
        self._headers(200, kind, len(b), extra)
        self.wfile.write(b)

    def _body(self, limit=MAX_FILE + 1):
        n = int(self.headers.get('Content-Length') or 0)
        if n > limit:
            raise ValueError('too large')
        return self.rfile.read(n)

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        if not self._host_ok():
            return self._error('host not allowed', 403)
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        p = u.path
        A = self.app
        try:
            if p in ('/', '/index.html'):
                return self._file(os.path.join(WEB, 'index.html'), 'text/html; charset=utf-8',
                                  {'Content-Security-Policy': CSP})
            if p in STATIC:
                return self._file(os.path.join(WEB, p[1:]), STATIC[p])
            if p == '/logo':
                custom = A.s.logo_path()
                if custom:
                    kind = 'image/svg+xml' if custom.endswith('.svg') else 'image/png'
                    return self._file(custom, kind)
                return self._file(os.path.join(WEB, 'favicon.svg'), 'image/svg+xml')
            if p == '/api/version':
                return self._json({'version': __version__})
            if p == '/api/session':
                return self._json({'needs_login': not self._authed()})
            if not self._authed():
                return self._error('login required', 401)
            lang = self._lang(q)
            view = q.get('view', ['review'])[0]
            if p == '/api/state':
                return self._json(A.state(lang))
            if p == '/api/invoices':
                return self._json(A.listing(view))
            m = re.fullmatch(r'/api/invoices/(\d+)', p)
            if m:
                d = A.detail(int(m.group(1)), view, lang)
                return self._json(d) if d else self._error('not found', 404)
            m = re.fullmatch(r'/api/invoices/(\d+)/file', p)
            if m:
                f = A.db.invoice(int(m.group(1)))
                if not f:
                    return self._error('not found', 404)
                return self._file(A.path(f['file']), f['mime'], {
                    'Content-Disposition': "inline; filename*=UTF-8''" + urllib.parse.quote(f['filename'])})
            if p == '/api/suppliers':
                return self._json(A.ledger.search(q.get('q', [''])[0]))
            if p == '/api/accounts':
                return self._json(A.ledger.expense_accounts())
            if p == '/api/mailbox':
                offset = max(0, min(5000, int((q.get('offset') or ['0'])[0] or 0)))
                return self._json(A.db.mailbox(20, offset, (q.get('filter') or ['all'])[0]))
            m = re.fullmatch(r'/api/set_aside/(\d+)/file', p)
            if m:
                a = A.db.set_aside_item(int(m.group(1)))
                if not a:
                    return self._error('not found', 404)
                return self._file(A.path(a['file']), a['mime'] or 'application/octet-stream')
            if p == '/api/batches':
                return self._json(A.db.batches())
            if p == '/api/batches/latest/file':
                last = A.db.last_batch()
                if not last:
                    return self._error('no export file yet', 404)
                same_type = A.fixed_name and A.fixed_name.lower().endswith(os.path.splitext(last['file'])[1])
                return self._send_batch(last, A.fixed_name if same_type else last['file'])
            m = re.fullmatch(r'/api/batches/(\d+)/file', p)
            if m:
                b = A.db.batch(int(m.group(1)))
                return self._send_batch(b, b['file']) if b else self._error('not found', 404)
            m = re.fullmatch(r'/api/batches/(\d+)/pdfs', p)
            if m:
                n = int(m.group(1))
                if not A.db.batch(n):
                    return self._error('not found', 404)
                data = A.batch_pdfs(n)
                self._headers(200, 'application/zip', len(data),
                              {'Content-Disposition': f'attachment; filename="invoices_{n}.zip"'})
                return self.wfile.write(data)
            return self._error('not found', 404)
        except (OSError, ValueError) as e:
            return self._error(str(e), 500)

    def _send_batch(self, b, filename):
        from .exporters import EXPORTERS
        kind = getattr(EXPORTERS.get(b['format']), 'mime', 'application/octet-stream')
        return self._file(self.app.path(os.path.join('batches', b['file'])), kind,
                          {'Content-Disposition': f'attachment; filename="{filename}"'})

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        if not self._host_ok():
            return self._error('host not allowed', 403)
        if self.headers.get('X-Asienta') != '1':
            return self._error('request not allowed', 403)
        p = urllib.parse.urlparse(self.path).path
        A = self.app
        try:
            if p == '/api/login':
                body = json.loads(self._body(10_000) or b'{}')
                if self.token and hmac.compare_digest(str(body.get('token', '')), self.token):
                    return self._json({'ok': True}, extra={
                        'Set-Cookie': f'asienta_session={self.session}; HttpOnly; SameSite=Strict; Path=/'})
                return self._error('wrong token', 401)
            if not self._authed():
                return self._error('login required', 401)
            lang = self._lang()
            if p == '/api/upload':
                content = self._body()
                name = urllib.parse.unquote(self.headers.get('X-Filename') or 'invoice')
                i, known = A.receive(content, name, 'upload')
                return self._json({'id': i, 'known': known})
            body = json.loads(self._body(2_000_000) or b'{}')
            if p == '/api/demo/samples' and getattr(A.reader, 'model', '') == 'demo':
                return self._json({'added': A.load_samples()})
            if p == '/api/demo/email' and getattr(A.reader, 'model', '') == 'demo':
                return self._json({'taken': A.simulate_email()})
            if p == '/api/batches':
                batch, warnings, path = A.export(body.get('format'), lang)
                return self._json({'batch': batch, 'warnings': warnings, 'path': path})
            m = re.fullmatch(r'/api/batches/(\d+)/undo', p)
            if m:
                return self._json({'invoices': A.undo_batch(int(m.group(1)))})
            m = re.fullmatch(r'/api/set_aside/(\d+)/(take|dismiss)', p)
            if m:
                if m.group(2) == 'take':
                    inv, known = A.take_set_aside(int(m.group(1)))
                    return self._json({'invoice': inv, 'known': known})
                A.db.dismiss_set_aside(int(m.group(1)))
                return self._json({'ok': True})
            m = re.fullmatch(r'/api/invoices/(\d+)/(\w+)', p)
            if not m:
                return self._error('not found', 404)
            i, action = int(m.group(1)), m.group(2)
            f = A.db.invoice(i)
            if not f:
                return self._error('not found', 404)
            view = body.get('view', 'review')
            if action == 'save':
                A.save(i, body)
                return self._json(A.detail(i, view, lang))
            if action == 'propose':
                A.repropose(i, body)
                return self._json(A.detail(i, view, lang))
            if action == 'approve':
                errors = A.approve(i, body, lang)
                if errors:
                    return self._json({'errors': errors, 'detail': A.detail(i, view, lang)}, 409)
                ids = [r['id'] for r in A.db.listing('review') if r['status'] == 'review']
                return self._json({'ok': True, 'next': next((x for x in ids if x > i), ids[0] if ids else None)})
            if action == 'discard' and f['status'] in ('review', 'error', 'approved'):
                A.db.set_status(i, 'discarded', 'discarded')
                return self._json({'ok': True})
            if action == 'reopen' and f['status'] in ('approved', 'discarded'):
                A.db.set_status(i, 'review' if f['data'] else 'error', 'back to review')
                return self._json(A.detail(i, 'review', lang))
            if action == 'reread' and f['status'] in ('review', 'error', 'discarded'):
                A.db.set_status(i, 'reading', 'read again')
                A.pool.submit(A.read, i)
                return self._json({'ok': True})
            if action == 'booked' and f['status'] == 'exported':
                A.db.set_status(i, 'posted', 'marked as booked by hand', f['batch'])
                return self._json({'ok': True})
            return self._error('not possible with this invoice', 409)
        except ValueError as e:
            return self._error(str(e), 400)
        except Exception as e:
            traceback.print_exc()
            return self._error(f'{e.__class__.__name__}: {e}', 500)


def tailscale_ip():
    """This machine's Tailscale IP (100.64.0.0/10), or None."""
    import subprocess
    ips = []
    for exe in ('tailscale', r'C:\Program Files\Tailscale\tailscale.exe',
                '/Applications/Tailscale.app/Contents/MacOS/Tailscale'):
        try:
            ips += subprocess.run([exe, 'ip', '-4'], capture_output=True, text=True, timeout=8).stdout.split()
            break
        except (OSError, subprocess.SubprocessError):
            continue
    for ip in ips:
        p = ip.split('.')
        if len(p) == 4 and p[0] == '100' and p[1].isdigit() and 64 <= int(p[1]) <= 127:
            return ip
    return None


def make_server(app, host, port):
    Handler.app = app
    Handler.token = app.s.token
    extra = {h.strip().lower() for h in app.s.get('app', 'allowed_hosts').split(',') if h.strip()}
    Handler.hosts = {host, 'localhost', '127.0.0.1', socket.gethostname().lower()} | extra
    if host in ('0.0.0.0', '::') and Handler.token and not extra:
        Handler.hosts.add('*')
    return ThreadingHTTPServer((host, port), Handler)
