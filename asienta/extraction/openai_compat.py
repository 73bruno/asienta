"""Any model behind an OpenAI-compatible Chat Completions API, with the standard library only.

That covers OpenAI itself and the many services and local servers that speak the same protocol:
Azure OpenAI, Mistral, OpenRouter, Together, Groq… and, for invoices that must never leave the
building, local models through Ollama, LM Studio or vLLM.

    [reader]
    provider = openai
    base_url = http://localhost:11434/v1     ; Ollama. Default: https://api.openai.com/v1
    model = llama3.2-vision                  ; any model that accepts images
    api_key =                                ; or OPENAI_API_KEY (not needed for local servers)
    pdf = images                             ; file (send the PDF) | images (render pages, needs pymupdf)

The answer is constrained with `response_format: json_schema`. Servers that ignore it still
work if the model returns the JSON; a wrong shape is caught by normalize() and by the checks.
"""
import base64
import json
import time
import urllib.error
import urllib.request

from . import ReadError, Reading, pretty_model
from .schema import unwrap


def pdf_pages(content, dpi=150, max_pages=6):
    """Render PDF pages to PNG for models that only take images (needs pymupdf)."""
    try:
        import fitz
    except ImportError:
        raise ReadError('this model needs PDF pages as images: pip install pymupdf, '
                        'or set [reader] pdf = file') from None
    doc = fitz.open(stream=content, filetype='pdf')
    return [page.get_pixmap(dpi=dpi).tobytes('png') for page in list(doc)[:max_pages]]


class OpenAICompatReader:
    def __init__(self, settings):
        local_default = settings.get('reader', 'provider', '').lower() in ('ollama', 'local')
        self.base = settings.get('reader', 'base_url', 'http://localhost:11434/v1' if local_default
                                 else 'https://api.openai.com/v1').rstrip('/')
        self.model = settings.get('reader', 'model', '')
        if not self.model or self.model.startswith(('gemini', 'claude', 'demo')):
            raise SystemExit('Set [reader] model to a model your OpenAI-compatible server offers.')
        self.key = settings.secret('reader', 'api_key', 'OPENAI_API_KEY')
        self.timeout = settings.int('reader', 'timeout', 120)
        self.pdf = settings.get('reader', 'pdf', 'file' if 'openai.com' in self.base else 'images').lower()
        self.local = self.base.startswith(('http://localhost', 'http://127.0.0.1'))
        self.name = pretty_model(self.model)

    @property
    def ready(self):
        return bool(self.key) or self.local

    def parts(self, content, mime):
        if mime == 'application/pdf' and self.pdf == 'file':
            return [{'type': 'file', 'file': {'filename': 'invoice.pdf',
                                               'file_data': 'data:application/pdf;base64,' + base64.b64encode(content).decode()}}]
        images = pdf_pages(content) if mime == 'application/pdf' else [content]
        kind = 'image/png' if mime == 'application/pdf' else mime
        return [{'type': 'image_url', 'image_url': {'url': f'data:{kind};base64,' + base64.b64encode(b).decode()}}
                for b in images]

    def read(self, content, mime, prompt, schema, categories, attempts=3, wait=5):
        if not self.ready:
            raise ReadError('missing API key: set OPENAI_API_KEY or [reader] api_key')
        body = json.dumps({
            'model': self.model,
            'messages': [{'role': 'system', 'content': prompt},
                         {'role': 'user', 'content': self.parts(content, mime)
                          + [{'type': 'text', 'text': 'Extract the data of this invoice.'}]}],
            'response_format': {'type': 'json_schema',
                                'json_schema': {'name': 'invoices', 'schema': schema, 'strict': True}},
        }).encode()
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['Authorization'] = f'Bearer {self.key}'
        t0 = time.time()
        for n in range(attempts):
            req = urllib.request.Request(f'{self.base}/chat/completions', data=body, method='POST', headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    resp = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode('utf-8', 'replace')[:300]
                if self.key:
                    detail = detail.replace(self.key, '***')
                if e.code in (429, 500, 502, 503, 504) and n < attempts - 1:
                    time.sleep(wait * (n + 1))
                    continue
                raise ReadError(f'{self.base} answered {e.code}: {detail}') from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if n < attempts - 1:
                    time.sleep(wait * (n + 1))
                    continue
                raise ReadError(f'no connection with {self.base}: {e}') from None
        seconds = time.time() - t0
        choice = (resp.get('choices') or [{}])[0]
        message = choice.get('message') or {}
        if message.get('refusal'):
            raise ReadError(f'the model declined: {message["refusal"][:200]}')
        text = message.get('content') or ''
        if isinstance(text, list):                       # some servers return content parts
            text = ''.join(p.get('text', '') for p in text if isinstance(p, dict))
        text = text.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
        try:
            data = json.loads(text)
        except ValueError:
            raise ReadError('the reading is not valid JSON') from None
        invoices = unwrap(data, categories)
        if not invoices:
            raise ReadError('no invoice found in the document')
        u = resp.get('usage') or {}
        return Reading(invoices, u.get('prompt_tokens') or 0, u.get('completion_tokens') or 0, seconds, self.model)
