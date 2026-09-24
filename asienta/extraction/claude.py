"""Anthropic Claude, through the official SDK (pip install "asienta[claude]").

Claude reads PDFs natively (text and page images), so scanned and handwritten invoices work
without OCR. Structured outputs guarantee the answer matches the schema.
"""
import base64
import json
import time

from . import ReadError, Reading, pretty_model
from .schema import unwrap


class ClaudeReader:
    def __init__(self, settings):
        self.model = settings.get('reader', 'model', 'claude-opus-5')
        if self.model.startswith('gemini'):
            self.model = 'claude-opus-5'
        self.key = settings.secret('reader', 'api_key', 'ANTHROPIC_API_KEY')
        self.timeout = settings.int('reader', 'timeout', 120)
        self.effort = settings.get('reader', 'effort', '')
        self.name = pretty_model(self.model)
        self.fallbacks = (settings.get('reader', 'fallbacks', 'default') != 'off'
                          and self.model.startswith(('claude-opus-5', 'claude-fable')))
        self._client = None

    @property
    def ready(self):
        return True                     # the SDK also finds credentials from `ant auth login`

    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise ReadError('the Claude reader needs the SDK: pip install "asienta[claude]"') from None
            kwargs = {'timeout': self.timeout, 'max_retries': 3}
            if self.key:
                kwargs['api_key'] = self.key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def read(self, content, mime, prompt, schema, categories):
        import anthropic
        data = base64.standard_b64encode(content).decode()
        if mime == 'application/pdf':
            block = {'type': 'document', 'source': {'type': 'base64', 'media_type': mime, 'data': data}}
        elif mime in ('image/jpeg', 'image/png', 'image/webp', 'image/gif'):
            block = {'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': data}}
        else:
            raise ReadError(f'Claude cannot read {mime} files: convert the photo to JPEG or PDF')
        output_config = {'format': {'type': 'json_schema', 'schema': schema}}
        if self.effort:
            output_config['effort'] = self.effort
        request = dict(
            model=self.model,
            max_tokens=16000,
            system=prompt,
            messages=[{'role': 'user', 'content': [block, {'type': 'text', 'text': 'Extract the data of this invoice.'}]}],
            output_config=output_config,
        )
        t0 = time.time()
        try:
            if self.fallbacks:
                # If a safety classifier declines, the API re-runs the request on a fallback model
                # inside the same call instead of failing. Set [reader] fallbacks = off to disable.
                resp = self.client().beta.messages.create(
                    betas=['server-side-fallback-2026-07-01'], fallbacks='default', **request)
            else:
                resp = self.client().messages.create(**request)
        except anthropic.RateLimitError:
            raise ReadError('Claude rate limit reached: try again in a minute') from None
        except anthropic.AuthenticationError:
            raise ReadError('Claude rejected the API key (ANTHROPIC_API_KEY)') from None
        except anthropic.BadRequestError as e:
            raise ReadError(f'Claude could not process this file: {e.message}') from None
        except anthropic.APIStatusError as e:
            raise ReadError(f'Claude answered {e.status_code}: {e.message}') from None
        except anthropic.APIConnectionError:
            raise ReadError('no connection with the Claude API') from None
        seconds = time.time() - t0
        if resp.stop_reason == 'refusal':
            raise ReadError('Claude declined to read this document')
        if resp.stop_reason == 'max_tokens':
            raise ReadError('the reading was cut off (document too long)')
        text = ''.join(b.text for b in resp.content if b.type == 'text')
        try:
            parsed = json.loads(text)
        except ValueError:
            raise ReadError('the reading is not valid JSON') from None
        invoices = unwrap(parsed, categories)
        if not invoices:
            raise ReadError('no invoice found in the document')
        return Reading(invoices, resp.usage.input_tokens, resp.usage.output_tokens, seconds, self.model)
