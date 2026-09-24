"""Spanish tax rules that do not need AI: NIF/NIE/CIF check digits, the characters that get
misread on thermal paper, and which VAT quarters are already filed.

Everything here is deterministic and unit-tested. If you adapt Asienta to another country, this
is the module to replace.
"""
import datetime
import re

DNI_LETTERS = 'TRWAGMYFPDXBNJZSQVHLCKE'


def normalize_tax_id(value):
    """'ES-B46.182.739' -> 'B46182739'."""
    s = re.sub(r'[^0-9A-Za-z]', '', str(value or '')).upper()
    if s.startswith('ES') and len(s) == 11:
        s = s[2:]
    return s


def tax_id_valid(n):
    """True / False, or None when it is not a Spanish ID (a foreign VAT number) and cannot be checked."""
    n = (n or '').upper()
    if len(n) != 9:
        return None if len(n) > 9 and n[:2].isalpha() else False
    if n[:8].isdigit():                                               # DNI
        return n[8] == DNI_LETTERS[int(n[:8]) % 23]
    if n[0] in 'XYZ' and n[1:8].isdigit():                            # NIE
        return n[8] == DNI_LETTERS[int(str('XYZ'.index(n[0])) + n[1:8]) % 23]
    if n[0] in 'ABCDEFGHJNPQRSUVW' and n[1:8].isdigit():              # CIF (companies)
        even = sum(int(n[i]) for i in (2, 4, 6))
        odd = sum(sum(divmod(2 * int(n[i]), 10)) for i in (1, 3, 5, 7))
        d = (10 - (even + odd) % 10) % 10
        return n[8] in (str(d), 'JABCDEFGHI'[d])
    if n[0] in 'KLM' and n[1:8].isdigit():
        return n[8] == DNI_LETTERS[int(n[1:8]) % 23]
    return False


def cif_check_digit(letter, digits):
    """The control character of a CIF: cif_check_digit('B', '1234567') -> '4'. Useful for fixtures."""
    n = letter + digits + '0'
    even = sum(int(n[i]) for i in (2, 4, 6))
    odd = sum(sum(divmod(2 * int(n[i]), 10)) for i in (1, 3, 5, 7))
    d = (10 - (even + odd) % 10) % 10
    return 'JABCDEFGHI'[d] if letter in 'NPQRSW' else str(d)


# Characters that get confused when reading an invoice (thermal printers, photos, handwriting). On
# real thermal tickets, every model tested misread the same 8 as a 6: one digit off, and the check
# digit fails. That is exactly what tax_id_candidates() undoes.
CONFUSIONS = {'0': '869DO', '1': '7I', '2': 'Z7', '3': '85', '4': '9', '5': '63S', '6': '805G',
              '7': '12', '8': '6309B', '9': '48', 'B': '8', 'Z': '2', 'S': '5', 'O': '0', 'G': '6', 'I': '1'}


def tax_id_candidates(n):
    """Valid IDs obtained by changing ONE commonly-confused character."""
    n = (n or '').upper()
    out = set()
    for i, ch in enumerate(n):
        for alt in CONFUSIONS.get(ch, ''):
            m = n[:i] + alt + n[i + 1:]
            if m != n and tax_id_valid(m):
                out.add(m)
    return sorted(out)


def near_miss(a, b, max_diff=2):
    """Same length and at most two different characters: the same ID, misread."""
    a, b = (a or '').upper(), (b or '').upper()
    return len(a) == len(b) and 0 < sum(x != y for x, y in zip(a, b, strict=True)) <= max_diff


# ---------------------------------------------------------------------------- VAT periods
def vat_filed_until(today, setting='auto'):
    """(year, month) of the last month whose VAT return is already filed.

    'auto' = the last quarter whose deadline has passed (20 April, July and October; 30 January
    for Q4). 'YYYY-MM' = set by hand. 'off' = nothing is considered filed.
    """
    s = (setting or 'auto').strip().lower()
    if s == 'off':
        return 1900, 1
    m = re.fullmatch(r'(\d{4})-(\d{1,2})', s)
    if m:
        return int(m.group(1)), int(m.group(2))
    y, q = today.year, (today.month - 1) // 3                   # q = current quarter (0..3)
    for _ in range(8):
        q -= 1
        if q < 0:
            y, q = y - 1, 3
        last = 3 * (q + 1)                                        # last month of that quarter
        deadline = datetime.date(y + 1, 1, 30) if last == 12 else datetime.date(y, last + 1, 20)
        if deadline <= today:
            return y, last
    return today.year - 1, 12


def first_open_day(closed):
    y, m = closed
    return datetime.date(y + (m == 12), 1 if m == 12 else m + 1, 1)


def in_closed_period(iso_date, closed):
    try:
        d = datetime.date.fromisoformat(iso_date)
    except (TypeError, ValueError):
        return False
    return (d.year, d.month) <= closed


def posting_date(iso_date, closed):
    """The date an invoice is posted with: its own, unless its quarter is already filed. Then the
    first day of the first open month, which is what Spanish bookkeepers do by hand."""
    if not iso_date:
        return ''
    return first_open_day(closed).isoformat() if in_closed_period(iso_date, closed) else iso_date


def quarter_label(closed):
    y, m = closed
    return f'Q{(m - 1) // 3 + 1} {y}'
