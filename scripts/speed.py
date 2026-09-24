#!/usr/bin/env python3
"""The speed numbers in the README, measured on your machine.

    python scripts/speed.py

Everything except the AI reading, which depends on the model (see `asienta bench`): start-up,
memory, rules and checks per invoice, and exporting 1,000 invoices to each format. Runs on the
demo data, offline.
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from asienta import exporters  # noqa: E402
from asienta.app import App  # noqa: E402
from asienta.cli import DEMO_INI  # noqa: E402
from asienta.config import Settings  # noqa: E402
from asienta.extraction.demo import SAMPLES, DemoReader  # noqa: E402
from asienta.extraction.schema import unwrap  # noqa: E402


def startup(port=8799):
    t = time.perf_counter()
    env = dict(os.environ, TMPDIR=tempfile.mkdtemp(prefix='asienta-speed-'))    # leave a running demo alone
    p = subprocess.Popen([sys.executable, '-m', 'asienta', '--demo', '--port', str(port)], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        while True:
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/api/version', timeout=0.2)
                break
            except OSError:
                time.sleep(0.01)
        ready = time.perf_counter() - t
        time.sleep(1)
        rss = None
        try:
            rss = int(subprocess.check_output(['ps', '-o', 'rss=', '-p', str(p.pid)]).strip()) / 1024
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
        return ready, rss
    finally:
        p.terminate()
        p.wait()


def main():
    ready, rss = startup()
    print(f'start-up to first response   {ready:.2f} s')
    if rss:
        print(f'memory, idle                 {rss:.0f} MB')

    s = Settings(DEMO_INI, overrides={'app': {'data': tempfile.mkdtemp(prefix='asienta-speed-')}})
    app = App(s, reader=DemoReader(delay=(0, 0)), log=lambda m: None)
    app.ledger.refresh()
    cats = app.category_names()
    readings = []
    for p in sorted(glob.glob(os.path.join(SAMPLES, '*.json'))):
        with open(p, encoding='utf-8') as f:
            readings += [unwrap({'invoices': [x]}, cats)[0] for x in json.load(f)['invoices']]

    rounds = 200
    t = time.perf_counter()
    for _ in range(rounds):
        for d in readings:
            app.findings(0, d, app.propose(d))
    per = (time.perf_counter() - t) / (rounds * len(readings))
    print(f'rules + checks, per invoice  {per * 1000:.1f} ms')

    ok = []
    for d in readings:
        e = app.propose(d)
        if not any(a['level'] == 'error' for a in app.findings(0, d, e)):
            ok.append((d, e, app.ledger.supplier(e['supplier_account']) or {}))
    batch = (ok * (1000 // len(ok) + 1))[:1000]
    ctx = app.context()
    for key in exporters.EXPORTERS:
        try:
            exporter = exporters.get(key, s)
        except Exception as e:             # an optional dependency missing (openpyxl for Excel)
            print(f'export 1,000 · {key:<12}  skipped ({e})')
            continue
        path = tempfile.mktemp()
        t = time.perf_counter()
        exporter.write(path, batch, ctx)
        print(f'export 1,000 · {key:<12}  {(time.perf_counter() - t) * 1000:.0f} ms')


if __name__ == '__main__':
    main()
