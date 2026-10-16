"""Claude API klientas su JSON atsakymais. TRENDMAP_MOCK_LLM=1 naudoja imitaciją testams."""
import json
import os
import re

from .common import log


def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ValueError("atsakyme nėra JSON")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])


class LLM:
    def __init__(self, model):
        self.model = model
        self.mock = os.environ.get("TRENDMAP_MOCK_LLM") == "1"
        self.calls = 0
        if not self.mock:
            import anthropic
            self.client = anthropic.Anthropic()

    def json(self, system, prompt, mock_fn, max_tokens=8000):
        self.calls += 1
        if self.mock:
            return mock_fn()
        last_err = None
        for attempt in range(3):
            try:
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
                return extract_json(text)
            except (ValueError, json.JSONDecodeError) as e:
                last_err = e
                log(f"  LLM atsakymas neperskaitomas (bandymas {attempt + 1}): {e}")
        raise RuntimeError(f"Nepavyko gauti JSON iš Claude: {last_err}")
