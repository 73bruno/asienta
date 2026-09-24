import datetime

from asienta import spain


def test_tax_ids():
    assert spain.tax_id_valid('12345678Z')
    assert spain.tax_id_valid('B98765431')
    assert spain.tax_id_valid('X1234567L')
    assert spain.tax_id_valid('B98765432') is False
    assert spain.tax_id_valid('DE123456789') is None          # foreign VAT number: can't check
    assert spain.normalize_tax_id('ES-B98.765.431') == 'B98765431'


def test_misread_candidates():
    good = 'B31069420'
    assert good in spain.tax_id_candidates('B31068420')
    assert spain.near_miss('B31068420', good)
    assert not spain.near_miss(good, good)


def test_cif_check_digit_roundtrip():
    for letter, digits in [('B', '4618273'), ('A', '3920156'), ('Q', '2826000')]:
        assert spain.tax_id_valid(letter + digits + spain.cif_check_digit(letter, digits))


def test_vat_filed_until_follows_deadlines():
    d = datetime.date
    assert spain.vat_filed_until(d(2026, 7, 19)) == (2026, 3)      # Q2 not due until 20 July
    assert spain.vat_filed_until(d(2026, 7, 20)) == (2026, 6)
    assert spain.vat_filed_until(d(2026, 1, 29)) == (2025, 9)      # Q4 due 30 January
    assert spain.vat_filed_until(d(2026, 1, 30)) == (2025, 12)
    assert spain.vat_filed_until(d(2026, 9, 24), '2026-06') == (2026, 6)


def test_posting_date_moves_out_of_closed_quarter():
    closed = (2026, 6)
    assert spain.posting_date('2026-06-28', closed) == '2026-07-01'
    assert spain.posting_date('2026-09-15', closed) == '2026-09-15'
    assert spain.posting_date('2025-12-31', (2025, 12)) == '2026-01-01'
