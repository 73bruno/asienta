"""Demo reader: no API key, no network. It recognizes the sample invoices shipped in
asienta/demo/invoices by their fingerprint and returns the reading stored next to each one, after
a short pause so the live-reading screen looks like the real thing.

Any other file fails with a clear message, so nobody mistakes the demo for real reading.
"""
import glob
import hashlib
import json
import os
import random
import time

from . import ReadError, Reading
from .schema import unwrap

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'demo', 'invoices')
BY_EMAIL = {'08_cafe_norte_ticket.jpg'}          # arrives through the simulated mailbox, not "Load samples"


def tiny_png(width, height, rgb):
    """A plain PNG without dependencies: the logo in the demo email's signature."""
    import struct
    import zlib
    raw = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def demo_email(to):
    """A forwarded receipt, as it would come from a colleague's phone: the photo as an attachment
    and a logo inside the signature (which the mailbox filter must set aside)."""
    import email.utils
    from email.message import EmailMessage
    with open(os.path.join(SAMPLES, '08_cafe_norte_ticket.jpg'), 'rb') as f:
        photo = f.read()
    msg = EmailMessage()
    msg['From'] = 'Laura Gómez <laura@demobistro.example>'
    msg['To'] = to
    msg['Subject'] = 'Fwd: lunch receipt, Café Norte'
    msg['Message-ID'] = email.utils.make_msgid(domain='demobistro.example')
    msg.set_content('Receipt from yesterday’s working lunch.\n\n--\nLaura Gómez\nDemo Bistro')
    msg.add_alternative('<p>Receipt from yesterday’s working lunch.</p>'
                        '<p>--<br><img src="cid:logo@demobistro" alt="logo"><br>Laura Gómez</p>', subtype='html')
    msg.get_payload()[1].add_related(tiny_png(180, 48, (79, 70, 229)), 'image', 'png', cid='<logo@demobistro>',
                                     filename='logo.png')
    msg.add_attachment(photo, maintype='image', subtype='jpeg', filename='IMG_2041.jpg')
    return msg


class DemoReader:
    name = 'Demo reader'
    model = 'demo'
    ready = True

    def __init__(self, settings=None, delay=(2.2, 3.6)):
        self.delay = delay
        self.known = {}
        for path in glob.glob(os.path.join(SAMPLES, '*.json')):
            for ext in ('.pdf', '.jpg', '.png'):
                doc = path[:-5] + ext
                if os.path.exists(doc):
                    with open(doc, 'rb') as f:
                        self.known[hashlib.sha256(f.read()).hexdigest()] = path

    def read(self, content, mime, prompt, schema, categories):
        path = self.known.get(hashlib.sha256(content).hexdigest())
        t0 = time.time()
        time.sleep(random.uniform(*self.delay))
        if not path:
            raise ReadError('demo mode only reads the sample invoices in demo/invoices. '
                            'Set GEMINI_API_KEY (or use the Claude reader) to read your own.')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        invoices = unwrap(data, categories)
        return Reading(invoices, 2600 + len(content) // 400, 700, time.time() - t0, 'demo')
