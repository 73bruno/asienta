"""Sage 50 (Spain) live, READ-ONLY, straight from its SQL Server database.

Sage 50 keeps each company in a SQL Server database (instance usually SQLSAGE50 or similar).
Create a login with db_datareader only on that database and point [sage50] at it: Asienta can
then find suppliers by tax ID, learn which account each supplier usually goes to, detect invoices
already booked and tell the entry number of an imported invoice. Nothing is ever written.

Needs: pip install "asienta[sage50]"   (pymssql)

Tables used: cuentas (CODIGO, NOMBRE), asientos (NUMERO, CUENTA, DEBE, HABER, FECHA),
ivasopor (CUENTA, NUMFRA, FECHA, BIMPO) and the supplier table with the tax ID (proveed.CIF by
default; auto-discovered when left empty).
"""
import re
from collections import defaultdict


class Sage50Source:
    kind = 'sage50'

    def __init__(self, cfg, supplier_prefixes=('400', '410')):
        self.cfg = cfg
        self.prefixes = supplier_prefixes
        self.tax_id_location = None         # (table, code_column, tax_id_column)

    def _connect(self):
        try:
            import pymssql
        except ImportError:
            raise RuntimeError('the Sage 50 connector needs pymssql: pip install "asienta[sage50]"') from None
        c = self.cfg
        return pymssql.connect(server=c['server'], port=int(c.get('port') or 1433), user=c['user'],
                               password=c['password'], database=c['database'],
                               login_timeout=10, timeout=120)

    def _likes(self):
        return ' OR '.join(['CUENTA LIKE %s'] * len(self.prefixes)), tuple(p + '%' for p in self.prefixes)

    def load(self):
        con = self._connect()
        try:
            cur = con.cursor()
            cur.execute('SELECT CODIGO, NOMBRE FROM cuentas')
            names = {str(c).strip(): (n or '').strip() for c, n in cur.fetchall()}
            tax_ids = self._tax_ids(cur)
            where, args = self._likes()
            # which expense/asset accounts each supplier goes to: the 6xx/2xx lines of its entries
            cur.execute(f"""
                WITH sup AS (SELECT NUMERO, MIN(CUENTA) c FROM asientos WHERE {where} GROUP BY NUMERO)
                SELECT sup.c, e.CUENTA, CAST(SUM(e.DEBE-e.HABER) AS decimal(14,2)), COUNT(DISTINCT e.NUMERO)
                FROM asientos e JOIN sup ON sup.NUMERO = e.NUMERO
                WHERE e.CUENTA LIKE %s OR e.CUENTA LIKE %s
                GROUP BY sup.c, e.CUENTA""", args + ('6%', '2%'))
            usual = defaultdict(dict)
            for sup, acc, amount, n in cur.fetchall():
                usual[str(sup).strip()][str(acc).strip()] = (float(amount or 0), int(n or 0))
            col = re.sub(r'\W', '', self.cfg.get('number_column') or 'NUMFRA')
            cur.execute(f"""SELECT CUENTA, LTRIM(RTRIM({col})), CONVERT(varchar(10), FECHA, 23),
                                   CAST(SUM(BIMPO) AS decimal(14,2))
                            FROM ivasopor GROUP BY CUENTA, {col}, CONVERT(varchar(10), FECHA, 23)""")
            booked = defaultdict(list)
            for acc, number, date, base in cur.fetchall():
                booked[str(acc).strip()].append({'number': number or '', 'date': date or '', 'base': float(base or 0)})
            cur.execute('SELECT CUENTA, COUNT(*) FROM asientos WHERE CUENTA LIKE %s GROUP BY CUENTA', ('472%',))
            vat_usage = {str(c).strip(): int(n or 0) for c, n in cur.fetchall()}
            return {'names': names, 'tax_ids': tax_ids, 'usual': dict(usual), 'invoices': dict(booked),
                    'vat_usage': vat_usage}
        finally:
            con.close()

    def entry_for(self, supplier_account, date, total):
        """The entry with that supplier, date and credit amount. Ambiguous -> ''."""
        con = self._connect()
        try:
            cur = con.cursor()
            cur.execute("""SELECT DISTINCT NUMERO FROM asientos
                           WHERE CUENTA = %s AND FECHA = %s AND HABER BETWEEN %s AND %s""",
                        (supplier_account, date, round(total - 0.005, 3), round(total + 0.005, 3)))
            found = cur.fetchall()
            return str(found[0][0]).strip() if len(found) == 1 else ''
        finally:
            con.close()

    def _tax_ids(self, cur):
        if self.tax_id_location is None:
            c = self.cfg
            if c.get('tax_id_table') and c.get('tax_id_code') and c.get('tax_id_column'):
                self.tax_id_location = (c['tax_id_table'], c['tax_id_code'], c['tax_id_column'])
            else:
                self.tax_id_location = discover_tax_id(cur, self.prefixes) or ()
        if not self.tax_id_location:
            return {}
        table, col_code, col_tid = (re.sub(r'\W', '', x) for x in self.tax_id_location)
        where = ' OR '.join([f'[{col_code}] LIKE %s'] * len(self.prefixes))
        cur.execute(f"""SELECT [{col_code}], [{col_tid}] FROM [{table}]
                        WHERE ({where}) AND LTRIM(RTRIM(ISNULL([{col_tid}], ''))) <> ''""",
                    tuple(p + '%' for p in self.prefixes))
        return {str(c).strip(): re.sub(r'[^0-9A-Z]', '', str(t).upper()) for c, t in cur.fetchall()}


def discover_tax_id(cur, prefixes=('400', '410')):
    """Find the table holding supplier account + tax ID. Keeps the one that covers MORE suppliers:
    some tables (tax models 347/349...) carry a few stray tax IDs and would give an empty directory."""
    cur.execute("""SELECT c.TABLE_NAME, c.COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS c
                   JOIN INFORMATION_SCHEMA.TABLES t ON t.TABLE_NAME = c.TABLE_NAME AND t.TABLE_TYPE = 'BASE TABLE'
                   WHERE UPPER(c.COLUMN_NAME) IN ('CIF', 'NIF', 'DNI', 'CIFDNI', 'NIFCIF', 'CIF_NIF', 'NIF_CIF')""")
    best = None
    for table, col_tid in cur.fetchall():
        cur.execute('SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s', (table,))
        cols = {r[0].upper(): r[0] for r in cur.fetchall()}
        for candidate in ('CODIGO', 'CUENTA', 'PROVEEDOR', 'CODPRO'):
            if candidate not in cols:
                continue
            where = ' OR '.join([f'[{cols[candidate]}] LIKE %s'] * len(prefixes))
            try:
                cur.execute(f"""SELECT COUNT(DISTINCT LTRIM(RTRIM([{cols[candidate]}]))) FROM [{table}]
                                WHERE ({where}) AND LTRIM(RTRIM(ISNULL([{col_tid}], ''))) <> ''""",
                            tuple(p + '%' for p in prefixes))
                n = cur.fetchone()[0] or 0
            except Exception:
                break
            if n and (best is None or n > best[0]):
                best = (n, table, cols[candidate], col_tid)
            break
    return best[1:] if best else None
