"""The real readers, with the network replaced by canned answers."""
import io
import json
import types

import pytest

from asienta.extraction import ReadError
from asienta.extraction.claude import ClaudeReader
from asienta.extraction.gemini import GeminiReader
from asienta.extraction.openai_compat import OpenAICompatReader
from asienta.extraction.schema import invoice_schema

ANSWER = {'invoices': [{'start_page': 1, 'doc_type': 'invoice', 'supplier_name': 'X, S.L.',
                        'supplier_tax_id': 'ES-B46182739', 'invoice_number': 'A / 1', 'invoice_date': '15/09/2026',
                        'accounting_date': None, 'lines': [], 'surcharge': 0, 'withholding': 0, 'total': 121,
                        'vat_breakdown': [{'vat_rate': 21, 'base': 100, 'vat': 21}], 'due_dates': [],
                        'possible_asset': False, 'suggested_account': '', 'notes': []}]}


def test_gemini_request_and_parsing(settings, monkeypatch):
    settings.cfg.set('reader', 'api_key', ' "k3y" ')
    seen = {}

    def fake_urlopen(req, timeout):
        seen['url'], seen['body'], seen['key'] = req.full_url, json.loads(req.data), req.headers['X-goog-api-key']
        payload = {'candidates': [{'content': {'parts': [{'text': json.dumps(ANSWER)}]}}],
                   'usageMetadata': {'promptTokenCount': 1000, 'candidatesTokenCount': 200}}
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)
    r = GeminiReader(settings).read(b'%PDF', 'application/pdf', 'prompt', invoice_schema(['food']), ['food'])
    assert seen['key'] == 'k3y' and 'gemini' in seen['url']
    assert seen['body']['generationConfig']['responseSchema']['type'] == 'OBJECT'
    inv = r.invoices[0]
    assert inv['supplier_tax_id'] == 'B46182739' and inv['invoice_number'] == 'A/1' and inv['invoice_date'] == '2026-09-15'
    assert (r.tokens_in, r.tokens_out) == (1000, 200)


def test_gemini_without_key_fails_clearly(settings, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with pytest.raises(ReadError, match='GEMINI_API_KEY'):
        GeminiReader(settings).read(b'%PDF', 'application/pdf', '', {}, [])


class FakeMessages:
    def __init__(self, stop='end_turn'):
        self.stop, self.kwargs = stop, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return types.SimpleNamespace(
            stop_reason=self.stop, content=[types.SimpleNamespace(type='text', text=json.dumps(ANSWER))],
            usage=types.SimpleNamespace(input_tokens=1500, output_tokens=300))


def claude(settings, model, stop='end_turn'):
    pytest.importorskip('anthropic')
    settings.cfg.set('reader', 'model', model)
    reader = ClaudeReader(settings)
    msgs = FakeMessages(stop)
    reader._client = types.SimpleNamespace(messages=msgs, beta=types.SimpleNamespace(messages=msgs))
    return reader, msgs


def test_claude_sends_the_pdf_and_the_schema(settings):
    reader, msgs = claude(settings, 'claude-opus-5')
    r = reader.read(b'%PDF-1.4', 'application/pdf', 'the prompt', invoice_schema(['food']), ['food'])
    block = msgs.kwargs['messages'][0]['content'][0]
    assert block['type'] == 'document' and block['source']['media_type'] == 'application/pdf'
    assert msgs.kwargs['output_config']['format']['type'] == 'json_schema'
    assert msgs.kwargs['fallbacks'] == 'default'            # server-side fallback on Opus
    assert r.invoices[0]['total'] == 121 and r.tokens_in == 1500


def test_claude_refusal_is_a_read_error(settings):
    reader, _ = claude(settings, 'claude-sonnet-5', stop='refusal')
    with pytest.raises(ReadError):
        reader.read(b'\xff\xd8\xff', 'image/jpeg', '', invoice_schema([]), [])


def test_openai_compatible_local_model(settings, monkeypatch):
    settings.cfg.set('reader', 'provider', 'ollama')
    settings.cfg.set('reader', 'model', 'llama3.2-vision')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    seen = {}

    def fake_urlopen(req, timeout):
        seen['url'], seen['body'], seen['headers'] = req.full_url, json.loads(req.data), dict(req.headers)
        payload = {'choices': [{'message': {'content': '```json\n' + json.dumps(ANSWER) + '\n```'}}],
                   'usage': {'prompt_tokens': 900, 'completion_tokens': 150}}
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)
    reader = OpenAICompatReader(settings)
    assert reader.ready                                    # a local server needs no key
    r = reader.read(b'\xff\xd8\xff', 'image/jpeg', 'p', invoice_schema([]), [])
    assert seen['url'] == 'http://localhost:11434/v1/chat/completions' and 'Authorization' not in seen['headers']
    content = seen['body']['messages'][1]['content']
    assert content[0]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert seen['body']['response_format']['type'] == 'json_schema'
    assert r.invoices[0]['total'] == 121 and r.tokens_out == 150
