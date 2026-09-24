from asienta.config import Category
from asienta.extraction.gemini import to_gemini
from asienta.extraction.schema import build_prompt, invoice_schema, normalize, num


def test_numbers():
    assert num('1.234,56') == 1234.56
    assert num('1,234.56') == 1234.56
    assert num('12,5 €') == 12.5
    assert num(None) == 0.0


def test_credit_note_takes_the_sign_of_the_total():
    d = normalize({'doc_type': 'credit_note', 'total': 121,
                   'vat_breakdown': [{'vat_rate': 21, 'base': 100, 'vat': 21}],
                   'lines': [{'description': 'x', 'amount': 100, 'vat_rate': 21, 'category': 'food'}]}, ['food'])
    assert d['total'] == -121
    assert d['vat_breakdown'][0]['base'] == -100 and d['vat_breakdown'][0]['vat'] == -21
    assert d['lines'][0]['amount'] == -100


def test_negative_total_makes_it_a_credit_note_and_merges_rates():
    d = normalize({'total': -10, 'vat_breakdown': [{'vat_rate': 10, 'base': 5, 'vat': .5},
                                                  {'vat_rate': 10, 'base': 4.09, 'vat': .41}]})
    assert d['doc_type'] == 'credit_note'
    assert d['vat_breakdown'] == [{'vat_rate': 10.0, 'base': -9.09, 'vat': -0.91}]


def test_unknown_category_becomes_other_and_dates_normalize():
    d = normalize({'invoice_date': '15/09/2026', 'accounting_date': '2026-09-15',
                   'lines': [{'description': ' a  b ', 'amount': '1,5', 'vat_rate': 21, 'category': 'weird'}]}, ['food'])
    assert d['invoice_date'] == '2026-09-15' and d['accounting_date'] == ''
    assert d['lines'][0] == {'description': 'a b', 'amount': 1.5, 'vat_rate': 21.0, 'category': 'other'}


def test_schemas():
    s = invoice_schema(['food', 'drinks'])
    item = s['properties']['invoices']['items']
    assert item['properties']['lines']['items']['properties']['category']['enum'] == ['food', 'drinks', 'other']
    g = to_gemini(s)
    assert g['type'] == 'OBJECT'
    assert g['properties']['invoices']['items']['properties']['accounting_date'] == {'type': 'STRING', 'nullable': True}


def test_prompt_mentions_categories_and_accounts():
    p = build_prompt('ACME', 'B1', 'bakery', [Category('flour', '600', 'flour and grains')], [('600000100', 'Compras')])
    assert 'flour: flour and grains' in p and '600000100 Compras' in p and 'a bakery' in p
