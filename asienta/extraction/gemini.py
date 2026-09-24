"""Google Gemini, through its REST API with the standard library only (urllib).

The cheapest option that reads Spanish invoices well: a Flash model costs fractions of a cent
per invoice. Use a paid-tier key for real invoices: on the free tier Google may use the data.
"""
import base64
import json
import time
import urllib.error
import urllib.request

from . import ReadError, Reading, pretty_model
from .schema import unwrap

URL = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
MAX_REQUEST = 18_000_000        # Google rejects requests over ~20 MB with an unhelpful HTML 400


def to_gemini(schema):
    """Standard JSON Schema -> Gemini's OpenAPI-style responseSchema."""
    if 'anyOf' in schema:
        types = [s for s in schema['anyOf'] if s.get('type') != 'null']
        out = to_gemini(types[0])
        out['nullable'] = True
        return out
    out = {'type': schema['type'].upper()}
    if 'enum' in schema:
        out['enum'] = schema['enum']
    if schema['type'] == 'object':
        out['properties'] = {k: to_gemini(v) for k, v in schema['properties'].items()}
        out['required'] = schema.get('required', [])
        out['propertyOrdering'] = list(schema['properties'])
    if schema['type'] == 'array':
        out['items'] = to_gemini(schema['items'])
    return out


def clean_key(k):
    # a key pasted with spaces, a newline or quotes breaks the HTTP header
    return (k or '').strip().strip('"\'').strip()


class GeminiReader:
    def __init__(self, settings):
        self.model = settings.get('reader', 'model', 'gemini-3.8-flash')
        if not self.model.startswith('gemini'):          # e.g. the demo config with --real
            self.model = 'gemini-3.8-flash'
        self.key = clean_key(settings.secret('reader', 'api_key', 'GEMINI_API_KEY'))
        self.timeout = settings.int('reader', 'timeout', 60)
        self.name = pretty_model(self.model)

    @property
    def ready(self):
        return bool(self.key)

    def read(self, content, mime, prompt, schema, categories, attempts=3, wait=5):
        if not self.key:
            raise ReadError('missing API key: set GEMINI_API_KEY or [reader] api_key')
        body = json.dumps({
            'system_instruction': {'parts': [{'text': prompt}]},
            'contents': [{'role': 'user', 'parts': [
                {'inline_data': {'mime_type': mime, 'data': base64.b64encode(content).decode()}},
                {'text': 'Extract the data of this invoice.'}]}],
            'generationConfig': {'responseMimeType': 'application/json',
                                 'responseSchema': to_gemini(schema)},
        }).encode()
        if len(body) > MAX_REQUEST:
            raise ReadError(f'file too large to read with AI ({len(content) / 1e6:.1f} MB). '
                            'Scan it again at a lower quality.')
        t0 = time.time()
        for n in range(attempts):
            req = urllib.request.Request(URL.format(model=self.model), data=body, method='POST',
                                         headers={'Content-Type': 'application/json',
                                                  'x-goog-api-key': self.key})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    resp = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode('utf-8', 'replace')[:300].replace(self.key, '***')
                if e.code in (429, 500, 502, 503, 504) and n < attempts - 1:
                    time.sleep(wait * (n + 1))
                    continue
                raise ReadError(f'Google answered {e.code}: {detail}') from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if n < attempts - 1:
                    time.sleep(wait * (n + 1))
                    continue
                if isinstance(e, TimeoutError) or 'timed out' in str(e):
                    raise ReadError(f'Google took more than {self.timeout} s, {attempts} times in a row. '
                                    'Try again.') from None
                raise ReadError(f'no connection with Google: {e}') from None
        seconds = time.time() - t0
        cand = (resp.get('candidates') or [{}])[0]
        parts = (cand.get('content') or {}).get('parts') or []
        text = ''.join(p.get('text', '') for p in parts if not p.get('thought'))
        if not text:
            why = cand.get('finishReason') or (resp.get('promptFeedback') or {}).get('blockReason')
            raise ReadError(f'empty reading ({why or "no reason given"})')
        try:
            data = json.loads(text)
        except ValueError:
            raise ReadError('the reading is not valid JSON') from None
        invoices = unwrap(data, categories)
        if not invoices:
            raise ReadError('no invoice found in the document')
        u = resp.get('usageMetadata') or {}
        out_tokens = (u.get('candidatesTokenCount') or 0) + (u.get('thoughtsTokenCount') or 0)
        return Reading(invoices, u.get('promptTokenCount') or 0, out_tokens, seconds, self.model)
