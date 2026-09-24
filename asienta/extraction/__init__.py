"""Invoice readers. Each one takes the bytes of a PDF or photo and returns normalized invoices.

A reader is any object with:

    name: str                                  shown in the UI ("Gemini 3.8 Flash")
    read(content, mime, prompt, schema, categories) -> Reading

Built in: Gemini, Claude, any OpenAI-compatible API (OpenAI, Mistral, OpenRouter, Azure, and
local models through Ollama, LM Studio or vLLM) and the demo reader. Add another (an OCR service,
a provider SDK) by writing one class and registering it in open_reader(). See docs/extending.md.
"""
from dataclasses import dataclass, field


class ReadError(Exception):
    """A reading failed in a way the user should see (quota, timeout, unreadable file)."""


@dataclass
class Reading:
    invoices: list
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    model: str = ''
    extra: dict = field(default_factory=dict)


def open_reader(settings):
    provider = settings.get('reader', 'provider', 'gemini').lower()
    if provider == 'gemini':
        from .gemini import GeminiReader
        return GeminiReader(settings)
    if provider == 'claude':
        from .claude import ClaudeReader
        return ClaudeReader(settings)
    if provider in ('openai', 'openai-compatible', 'ollama', 'local'):
        from .openai_compat import OpenAICompatReader
        return OpenAICompatReader(settings)
    if provider == 'demo':
        from .demo import DemoReader
        return DemoReader(settings)
    raise SystemExit(f'Unknown reader provider: {provider} (use gemini, claude, openai or demo)')


def pretty_model(m):
    """'gemini-3.8-flash' -> 'Gemini 3.8 Flash', 'claude-opus-5' -> 'Claude Opus 5'."""
    words = str(m or '').replace('-', ' ').split()
    return ' '.join(w if any(c.isdigit() for c in w) else w.capitalize() for w in words)
