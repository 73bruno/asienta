import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from asienta.server import make_server

from .conftest import samples, wait_read


def call(base, path, data=None, headers=None, method=None):
    req = urllib.request.Request(base + path, data=data, method=method or ('POST' if data is not None else 'GET'),
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


@pytest.fixture
def server(app):
    srv = make_server(app, '127.0.0.1', 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()


def test_state_and_static(server):
    code, body, _ = call(server, '/api/state')
    assert code == 200 and json.loads(body)['company'] == 'Demo Bistro, S.L.'
    code, body, headers = call(server, '/')
    assert code == 200 and 'Content-Security-Policy' in headers


def test_writes_need_the_header_and_uploads_are_sniffed(server, app, monkeypatch):
    monkeypatch.setattr('asienta.app.READ_INTERVAL', 0)
    code, _, _ = call(server, '/api/upload', b'%PDF-1.4')
    assert code == 403
    code, body, _ = call(server, '/api/upload', b'hello', {'X-Asienta': '1'})
    assert code == 400
    with open(samples()[0], 'rb') as f:
        code, body, _ = call(server, '/api/upload', f.read(), {'X-Asienta': '1', 'X-Filename': os.path.basename(samples()[0])})
    assert code == 200 and json.loads(body)['known'] is False
    wait_read(app)
    code, body, _ = call(server, '/api/invoices/1', headers={'X-Lang': 'en'})
    assert json.loads(body)['reason'].startswith('The most usual')


def test_dns_rebinding_is_refused(server):
    code, _, _ = call(server, '/api/state', headers={'Host': 'evil.example.com'})
    assert code == 403


def test_token(server, app, monkeypatch):
    from asienta.server import Handler
    monkeypatch.setattr(Handler, 'token', 's3cret')
    assert call(server, '/api/state')[0] == 401
    assert call(server, '/api/login', json.dumps({'token': 'nope'}).encode(), {'X-Asienta': '1'})[0] == 401
    code, _, headers = call(server, '/api/login', json.dumps({'token': 's3cret'}).encode(), {'X-Asienta': '1'})
    cookie = headers['Set-Cookie'].split(';')[0]
    assert code == 200 and call(server, '/api/state', headers={'Cookie': cookie})[0] == 200
    assert call(server, '/api/state', headers={'Authorization': 'Bearer nope'})[0] == 401
    assert call(server, '/api/state', headers={'Authorization': 'Bearer s3cret'})[0] == 200
