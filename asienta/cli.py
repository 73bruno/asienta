"""Command line.

    asienta                     start the web app with ./config.ini
    asienta --demo              try it now: sample invoices and ledger, no API key, no setup
    asienta init                write a commented config.ini and a sample ledger/ folder here
    asienta check               test the reader key and the ledger connection
    asienta bench FOLDER        read a folder of invoices and score them against a truth file
"""
import argparse
import glob
import os
import shutil
import sys
import tempfile
import threading
import webbrowser

from . import __version__
from .config import PACKAGE, Settings

DEMO_INI = os.path.join(PACKAGE, 'demo', 'demo.ini')
DEMO_INVOICES = os.path.join(PACKAGE, 'demo', 'invoices')
EXAMPLE_INI = os.path.join(PACKAGE, 'config.example.ini')
LOOPBACK = ('127.0.0.1', 'localhost', '::1')


def demo_settings(reset=True):
    data = os.path.join(tempfile.gettempdir(), 'asienta-demo')
    if reset:
        shutil.rmtree(data, ignore_errors=True)
    return Settings(DEMO_INI, overrides={'app': {'data': data}})


def serve(args):
    from .app import App
    from .server import make_server, tailscale_ip
    if args.demo:
        settings = demo_settings(reset=not args.keep)
        if args.real:
            settings.cfg.set('reader', 'provider', 'gemini')
    else:
        path = args.config
        if not os.path.exists(path):
            sys.exit(f'No {path} here. Run `asienta init` to create one, or `asienta --demo` to try it first.')
        settings = Settings(path)
    host = args.host or settings.get('app', 'host', '127.0.0.1')
    if args.tailscale:
        host = tailscale_ip() or sys.exit('No Tailscale IP found on this machine. Is Tailscale connected?')
    port = args.port or settings.int('app', 'port', 8760)
    if host not in LOOPBACK and not settings.token and not args.tailscale:
        sys.exit(f'Refusing to listen on {host} without an access token: invoices are sensitive.\n'
                 'Set ASIENTA_TOKEN (or [app] access_token), or use --tailscale.')
    app = App(settings)
    app.log(f'Asienta {__version__} · reader: {app.reader.name} · ledger: {app.ledger.source.kind}')
    if app.ledger.refresh():
        st = app.ledger.status()
        app.log(f'ledger: {st["suppliers"]} suppliers, {st["with_tax_id"]} with tax ID')
    else:
        app.log(f'ledger not answering: {app.ledger.error} (retrying in the background)')
    app.resume()
    threading.Thread(target=app.background, daemon=True).start()
    if args.demo and args.seed:
        for path in sorted(glob.glob(os.path.join(DEMO_INVOICES, '*.pdf')))[:args.seed]:
            with open(path, 'rb') as f:
                app.receive(f.read(), os.path.basename(path), 'upload')
    srv = make_server(app, host, port)
    url = f'http://{"localhost" if host in LOOPBACK else host}:{port}'
    app.log(f'open {url}   (Ctrl+C to stop)')
    if args.demo and not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('stopped.')
    finally:
        srv.server_close()


def init(args):
    target = os.path.abspath(args.dir)
    os.makedirs(target, exist_ok=True)
    cfg = os.path.join(target, 'config.ini')
    if os.path.exists(cfg) and not args.force:
        sys.exit(f'{cfg} already exists (use --force to overwrite).')
    shutil.copy(EXAMPLE_INI, cfg)
    ledger = os.path.join(target, 'ledger')
    if not os.path.exists(ledger):
        shutil.copytree(os.path.join(PACKAGE, 'demo', 'ledger'), ledger)
    print(f'Created {cfg} and {ledger}/ (sample data: replace it with your own export).\n'
          'Next: edit config.ini, set GEMINI_API_KEY and run `asienta`.')


def check(args):
    from .extraction import open_reader
    from .ledger import open_ledger
    settings = demo_settings() if args.demo else Settings(args.config)
    ledger = open_ledger(settings)
    ok = ledger.refresh()
    st = ledger.status()
    print(f'ledger ({st["kind"]}): ' + (f'OK, {st["suppliers"]} suppliers, {st["with_tax_id"]} with tax ID'
                                         if ok else f'FAILED: {ledger.error}'))
    vat = ledger.input_vat_accounts()
    print('input VAT accounts found: ' + (', '.join(f'{r:g}% -> {a}' for r, a in sorted(vat.items())) or 'none '
                                           '(set [accounts] input_vat)'))
    reader = open_reader(settings)
    print(f'reader: {reader.name} · ' + ('key present' if getattr(reader, 'ready', True) else 'NO API KEY'))


def main(argv=None):
    ap = argparse.ArgumentParser(prog='asienta', description='AI invoice reader for Spanish accounting software.')
    ap.add_argument('--version', action='version', version=f'asienta {__version__}')
    sub = ap.add_subparsers(dest='cmd')

    def serve_args(p):
        p.add_argument('--config', default='config.ini')
        p.add_argument('--host')
        p.add_argument('--port', type=int)
        p.add_argument('--tailscale', action='store_true', help="listen only on this machine's Tailscale IP")
        p.add_argument('--demo', action='store_true', help='sample invoices and ledger, no API key needed')
        p.add_argument('--real', action='store_true', help='in demo mode, read with Gemini (needs GEMINI_API_KEY)')
        p.add_argument('--seed', type=int, nargs='?', const=99, default=0, help='demo: preload sample invoices')
        p.add_argument('--keep', action='store_true', help="demo: don't reset the demo data")
        p.add_argument('--no-browser', action='store_true')

    serve_args(ap)
    serve_args(sub.add_parser('serve', help='start the web app (default)'))
    p = sub.add_parser('init', help='create config.ini and a sample ledger folder')
    p.add_argument('dir', nargs='?', default='.')
    p.add_argument('--force', action='store_true')
    p = sub.add_parser('check', help='test the reader and ledger configuration')
    p.add_argument('--config', default='config.ini')
    p.add_argument('--demo', action='store_true')
    p = sub.add_parser('bench', help='score AI readings against a hand-checked truth file')
    p.add_argument('folder')
    p.add_argument('--truth', required=True)
    p.add_argument('--config', default='config.ini')
    p.add_argument('--demo', action='store_true', help='use the demo settings (and demo reader)')
    p.add_argument('--models', default='', help='comma-separated models to compare (same provider)')
    args = ap.parse_args(argv)
    if args.cmd == 'init':
        return init(args)
    if args.cmd == 'check':
        return check(args)
    if args.cmd == 'bench':
        from .bench import run
        return run(args)
    return serve(args)


if __name__ == '__main__':
    main()
