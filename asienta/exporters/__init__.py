"""Exporters: approved invoices -> the file your accounting program imports.

To add one, subclass base.Exporter, implement write() and add it to EXPORTERS. See
docs/extending.md: most take 30-60 lines.
"""
from .a3 import A3
from .base import Context, Exporter, Result
from .bills import Holded, QuickBooks, Xero
from .generic import GenericCSV, GenericJSON, Sage50Excel
from .sage50 import ContaPlus, Sage50

EXPORTERS = {e.key: e for e in (Sage50, ContaPlus, Sage50Excel, A3, Holded, Xero, QuickBooks, GenericCSV, GenericJSON)}


def get(key, settings=None):
    cls = EXPORTERS.get((key or '').lower())
    if not cls:
        raise ValueError(f'unknown export format: {key} (available: {", ".join(EXPORTERS)})')
    return cls(settings)


__all__ = ['EXPORTERS', 'Context', 'Exporter', 'Result', 'get']
