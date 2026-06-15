"""
Unified LLM client wrapper.
  - AIMLClient   → calls AI/ML API  (Gap Analyst, HR Reporter) with Anthropic fallback
  - FeatherlessClient → calls Featherless AI  (Curriculum Architect, Progress Tracker)
  - AnthropicClient   → calls Anthropic Claude (Coach Agent)
"""

import os
import json
import requests
import anthropic
from dotenv import load_dotenv

load_dotenv()

AIML_CHAT_URL = "https://api.aimlapi.com/v1/chat/completions"


def _chat_completions_url(base_url: str) -> str:
    """Normalize provider base URLs so /chat/completions is not duplicated."""
    base = (base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _parse_json_content(raw: str) -> dict:
    cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(cleaned)


# ── AI/ML API ─────────────────────────────────────────────────────────────────

class AIMLClient:
    def __init__(self):
        self.api_key  = os.getenv("AIML_API_KEY")
        self.base_url = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")
        self.model    = os.getenv("AIML_MODEL", "google/gemma-3-4b-it")
        self._anthropic = None
        if os.getenv("ANTHROPIC_API_KEY"):
            self._anthropic = AnthropicClient()

    def _request_aiml(self, system: str, user: str, max_tokens: int) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        url = AIML_CHAT_URL if self.base_url.rstrip("/").endswith("/v1") else _chat_completions_url(self.base_url)
        resp = requests.post(url, headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def chat(self, system: str, user: str, max_tokens: int = 1500) -> str:
        try:
            return self._request_aiml(system, user, max_tokens)
        except Exception as exc:
            if self._anthropic:
                print(f"[AIMLClient] AIML API failed ({exc}); using Anthropic fallback.")
                return self._anthropic.chat(system, user, max_tokens)
            raise


# ── Featherless AI ─────────────────────────────────────────────────────────────

class FeatherlessClient:
    def __init__(self):
        self.api_key  = os.getenv("FEATHERLESS_API_KEY")
        self.base_url = os.getenv("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1")
        self.model    = "meta-llama/Meta-Llama-3-8B-Instruct"

    def chat(self, system: str, user: str, max_tokens: int = 1500) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.4,
        }
        resp = requests.post(_chat_completions_url(self.base_url), headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


# ── Anthropic Claude ───────────────────────────────────────────────────────────

class AnthropicClient:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model  = "claude-sonnet-4-6"

    def chat(self, system: str, user: str, max_tokens: int = 1500) -> str:
        msg = self.client.messages.create(
            model      = self.model,
            max_tokens = max_tokens,
            system     = system,
            messages   = [{"role": "user", "content": user}],
        )
        return msg.content[0].text.strip()
