# AI models

The model only has one job here: turn a document into the JSON schema in
`asienta/extraction/schema.py`. Everything else is rules, so any model that can read an image
or a PDF and follow a schema will do. Pick one in `config.ini`; nothing else changes.

| Provider | `[reader]` | Key | Notes |
|---|---|---|---|
| **Google Gemini** | `provider = gemini`<br>`model = gemini-3.8-flash` | `GEMINI_API_KEY` | Plain REST, no extra package. Flash models are the cheapest cloud option for invoices. |
| **Anthropic Claude** | `provider = claude`<br>`model = claude-opus-5` (or `claude-sonnet-5`, `claude-haiku-4-5`) | `ANTHROPIC_API_KEY` | `pip install "asienta[claude]"`. Reads PDFs natively, structured outputs guarantee the schema. |
| **OpenAI** | `provider = openai`<br>`model = <a vision model>` | `OPENAI_API_KEY` | Chat Completions with `json_schema`; PDFs are sent as files. |
| **Any OpenAI-compatible API** — Azure OpenAI, Mistral, OpenRouter, Together, Groq… | `provider = openai`<br>`base_url = <their /v1 URL>`<br>`model = …` | `OPENAI_API_KEY` (their key) | Same code, different URL. |
| **Local models** — Ollama, LM Studio, vLLM | `provider = ollama`<br>`model = llama3.2-vision` (any vision model you pulled)<br>`base_url = http://localhost:11434/v1` | none | Invoices never leave your network. PDFs are rendered to images first (`pip install pymupdf`). |
| **Demo** | `provider = demo` | none | Replays stored readings of the sample invoices. |

## Choosing one: measure, don't guess

Accuracy on *your* documents is what matters, and the cost of a wrong value depends on whether
anything warns about it. `asienta bench` reads a folder of your invoices with one or more models,
runs the same proposal and checks as the app, and compares the result with a truth file you wrote
by hand:

```bash
asienta bench my_invoices/ --truth truth.json --models gemini-3.8-flash,gemini-3.5-flash-lite
```

It reports, per model: fields read right, perfect invoices, supplier and accounts proposed right,
cost and time per document, and **silent errors** — wrong values with no warning. A model with a
few visible errors and zero silent ones is safer than a slightly more accurate one that fails
quietly. The truth format is documented at the top of `asienta/bench.py`; the demo has one
(`asienta bench asienta/demo/invoices --truth asienta/demo/truth.json --demo`).

Rules of thumb from real use:

- Thermal tickets and phone photos are where models differ most (digits like 8/6, 1/7).
  The tax-ID check digit catches most of those, whatever the model.
- Small local models read clean PDFs well and struggle more with crumpled photos; benchmark them
  on your worst documents before switching.
- Use paid tiers for real invoices: some providers may use free-tier data for training.

## Cost display

The app shows the cost of each reading and the month's total. Prices for common models are
built in; set `[reader] price_input` and `price_output` ($ per million tokens) for others.

## Adding another provider

A reader is one class with `read()`; see [extending](extending.md#a-reader-another-ai-provider-or-an-ocr).
