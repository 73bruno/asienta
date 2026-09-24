"""Ledger connectors (read-only). See directory.py for the interface a source implements."""
import os

from ..config import PACKAGE, parse_list
from .directory import Directory

DEMO_LEDGER = os.path.join(PACKAGE, 'demo', 'ledger')


def open_ledger(settings):
    kind = settings.get('ledger', 'source', 'csv').lower()
    prefixes = tuple(parse_list(settings.get('ledger', 'supplier_prefixes', '400,410')))
    if kind == 'sage50':
        from .sage50 import Sage50Source
        cfg = settings.section('sage50')
        cfg['password'] = settings.secret('sage50', 'password', 'ASIENTA_SAGE50_PASSWORD')
        source = Sage50Source(cfg, prefixes)
    elif kind in ('csv', 'demo'):
        from .csv_source import CSVSource
        folder = DEMO_LEDGER if kind == 'demo' else settings.path_('ledger', 'folder', 'ledger')
        source = CSVSource(folder, settings.path_('ledger', 'contaplus_accounts'))
        if kind == 'demo':
            source.kind = 'demo'
    else:
        raise SystemExit(f'Unknown ledger source: {kind} (use csv, sage50 or demo)')
    return Directory(source, settings.int('ledger', 'refresh_minutes', 30), prefixes,
                     tuple(parse_list(settings.get('ledger', 'expense_prefixes', '6,2'))),
                     settings.get('ledger', 'vat_prefix', '472'))
