"""The whole pipeline on the demo invoices: read, propose, check, approve, export, undo."""
import csv
import json


def by_number(app):
    out = {}
    for row in app.db.listing('review'):
        f = app.db.invoice(row['id'])
        out[f['data']['invoice_number']] = f
    return out


def keys(app, f):
    return {a['k'] for a in app.findings(f['id'], f['data'], f['entry'])}


def test_every_sample_is_read_and_proposed(loaded):
    inv = by_number(loaded)
    assert len(inv) == 10                                   # 9 documents, one PDF with two invoices
    med = inv['MED-26/0917']
    assert med['entry']['supplier_match'] == 'tax_id'
    split = {(r['account'], r['vat_rate']): r['base'] for r in med['entry']['split']}
    assert split[('600000200', 21.0)] == 154.00             # the wine, split off to drinks
    assert split[('600000100', 21.0)] == 36.00              # napkins follow the food main account
    beer = inv['LD-2026-4471']
    assert {r['account'] for r in beer['entry']['split']} == {'600000200'}   # keg deposits stay with drinks
    assert inv['BB-1183']['page'] == 2


def test_checks_catch_what_they_should(loaded):
    inv = by_number(loaded)
    assert 'chk.dup_ledger' in keys(loaded, inv['SC/0388'])            # already booked by hand
    assert {'chk.tax_id_fix', 'chk.matched_by_name'} <= keys(loaded, inv['F-2026/04192'])   # printed ID is invalid
    assert 'chk.asset' in keys(loaded, inv['T-0045'])
    assert inv['T-0045']['entry']['split'][0]['account'] == '216000000'
    assert inv['OF-26/0612']['entry']['posting_date'] == '2026-07-01'   # its quarter is filed
    assert 'chk.moved_to_open' in keys(loaded, inv['OF-26/0612'])
    assert 'chk.withholding' in keys(loaded, inv['HA-2026/091'])
    assert inv['CN-26/015']['data']['doc_type'] == 'credit_note'
    clean = [n for n, f in inv.items()
             if not any(a['level'] != 'info' for a in loaded.findings(f['id'], f['data'], f['entry']))]
    assert set(clean) >= {'MED-26/0917', 'LD-2026-4471', 'BB-1182', 'BB-1183', 'CN-26/015', 'HA-2026/091'}


def test_one_click_tax_id_fix(loaded):
    f = by_number(loaded)['F-2026/04192']
    fixed = dict(f['data'], supplier_tax_id='B87654323')
    loaded.repropose(f['id'], {'data': fixed, 'entry': dict(f['entry'], supplier_account='')})   # as the UI does
    g = loaded.db.invoice(f['id'])
    assert g['entry']['supplier_match'] == 'tax_id'
    assert not [a for a in loaded.findings(g['id'], g['data'], g['entry']) if a['level'] != 'info']


def test_approve_blocks_on_errors_and_learns_rules(loaded):
    inv = by_number(loaded)
    dup = inv['SC/0388']
    assert loaded.approve(dup['id'], {}, 'en')                 # returns the errors, stays in review
    assert loaded.db.invoice(dup['id'])['status'] == 'review'
    med = inv['MED-26/0917']
    entry = dict(med['entry'], remember_account=False)
    assert loaded.approve(med['id'], {'entry': entry}) == []
    assert loaded.db.invoice(med['id'])['status'] == 'approved'


def approve_clean(app):
    ids = []
    for n, f in by_number(app).items():
        if n in ('SC/0388', 'F-2026/04192'):
            continue
        assert app.approve(f['id'], {}) == [], n
        ids.append(f['id'])
    return ids


def test_export_sage50_then_undo(loaded):
    ids = approve_clean(loaded)
    batch, warnings, path = loaded.export('sage50')
    assert warnings == []
    lines = open(path, encoding='cp1252', newline='').read().split('\r\n')[:-1]
    assert all(len(ln.split(';')) == 116 for ln in lines)
    entries = {}
    for ln in lines:
        f = ln.split(';')
        entries.setdefault(f[0], 0.0)
        entries[f[0]] += float(f[27]) - float(f[28])
    assert len(entries) == len(ids)
    assert all(abs(v) < 0.005 for v in entries.values())       # every entry balances
    assert loaded.db.batch(batch)['invoices'] == len(ids)
    assert loaded.undo_batch(batch) == len(ids)
    assert len(loaded.db.with_status('approved')) == len(ids)


def test_export_every_format(loaded):
    from asienta.exporters import EXPORTERS
    approve_clean(loaded)
    for key in EXPORTERS:
        batch, warnings, path = loaded.export(key)
        assert warnings == [], (key, warnings)
        if key == 'a3':
            recs = open(path, encoding='cp1252', newline='').read().split('\r\n')[:-1]
            assert all(len(r) == 510 for r in recs)
            assert sum(r[14] in '12' for r in recs) == loaded.db.batch(batch)['invoices']
        if key == 'xero':
            rows = list(csv.DictReader(open(path, encoding='utf-8-sig')))
            assert rows and all(r['*AccountCode'] for r in rows)
        if key == 'holded':
            payload = json.load(open(path, encoding='utf-8'))
            assert all(p['items'] and p['invoiceNum'] for p in payload)
        loaded.undo_batch(batch)


def test_missing_vat_account_leaves_invoice_out(loaded):
    approve_clean(loaded)
    loaded.manual_vat = {}
    loaded.ledger.d['names'] = {k: v for k, v in loaded.ledger.d['names'].items() if not k.startswith('472')}
    try:
        loaded.export('sage50')
    except ValueError as e:
        assert 'input_vat' in str(e)
    else:
        raise AssertionError('should have refused')


def test_demo_email_goes_through_the_mailbox_filter(app, monkeypatch):
    monkeypatch.setattr('asienta.app.READ_INTERVAL', 0)
    from .conftest import wait_read
    assert app.simulate_email() == 1
    wait_read(app)
    box = app.db.mailbox()
    email = box['emails'][0]
    assert email['subject'].startswith('Fwd:') and len(email['invoices']) == 1
    assert [a['filename'] for a in email['set_aside']] == ['logo.png']      # the signature logo, kept aside
    assert 'signature' in email['set_aside'][0]['reason']
    inv = app.db.invoice(email['invoices'][0]['id'])
    assert inv['source'] == 'email' and inv['data']['invoice_number'] == 'F-2026/04192'
    assert app.simulate_email() == 1 and len(app.db.listing('review')) == 1   # same photo again: not duplicated


def test_inbox_folder_takes_files_and_moves_them(app, monkeypatch, tmp_path):
    import os
    import shutil
    monkeypatch.setattr('asienta.app.READ_INTERVAL', 0)
    from .conftest import samples, wait_read
    folder = tmp_path / 'scans'
    folder.mkdir()
    shutil.copy(samples()[0], folder)
    (folder / 'notes.txt').write_text('not an invoice')
    for p in folder.iterdir():
        os.utime(p, (0, 0))                          # old enough: not still being written
    app.inbox_folder = str(folder)
    assert app.check_folder() == 1
    wait_read(app)
    assert os.listdir(folder / 'done') == [os.path.basename(samples()[0])]
    assert os.listdir(folder / 'skipped') == ['notes.txt']
    inv = app.db.invoice(app.db.listing('review')[0]['id'])
    assert inv['source'] == 'folder' and inv['data']['invoice_number'] == 'MED-26/0917'
