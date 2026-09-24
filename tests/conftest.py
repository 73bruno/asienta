import glob
import os
import time

import pytest

from asienta.app import App
from asienta.cli import DEMO_INI
from asienta.config import Settings
from asienta.extraction.demo import SAMPLES, DemoReader


@pytest.fixture
def settings(tmp_path):
    return Settings(DEMO_INI, overrides={'app': {'data': str(tmp_path / 'data')}})


@pytest.fixture
def app(settings):
    a = App(settings, reader=DemoReader(delay=(0, 0)), log=lambda m: None)
    a.ledger.refresh()
    return a


def samples():
    return sorted(p for p in glob.glob(os.path.join(SAMPLES, '*')) if not p.endswith('.json'))


def wait_read(app, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if not app.db.with_status('reading'):
            return
        time.sleep(0.05)
    raise AssertionError('readings did not finish')


@pytest.fixture
def loaded(app, monkeypatch):
    monkeypatch.setattr('asienta.app.READ_INTERVAL', 0)
    for p in samples():
        with open(p, 'rb') as f:
            app.receive(f.read(), os.path.basename(p), 'upload')
    wait_read(app)
    return app
