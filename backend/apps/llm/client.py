"""
OpenRouter client (OpenAI-compatible API) that turns natural language into a RegexSpec.

The class is deliberately small and injectable: the Celery task receives an instance, and
tests substitute a FakeLLM that returns canned specs.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from django.conf import settings
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from apps.core.exceptions import AppError

from .prompts import REPAIR_PROMPT, SYSTEM_PROMPTS, build_user_prompt
from .schemas import RegexSpec

logger = logging.getLogger(__name__)


class LLMError(AppError):
    code = "LLM_ERROR"
    http_status = 502


class LLMTransientError(LLMError):
    """Rate limit / timeout / connection problems — safe to retry."""

    code = "LLM_UNAVAILABLE"


class LLMNotConfigured(LLMError):
    code = "LLM_NOT_CONFIGURED"
    http_status = 500


class RegexGenerator(Protocol):
    def generate(self, transform_type: str, prompt: str, columns: list[str], samples: dict[str, list[str]]) -> RegexSpec: ...


class OpenRouterClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.OPENROUTER_API_KEY
        self.model = model or settings.OPENROUTER_MODEL
        self.base_url = base_url or settings.OPENROUTER_BASE_URL
        self._client: OpenAI | None = None

    def _get_client(self) -> OpenAI:
        if not self.api_key or self.api_key.startswith("sk-or-v1-..."):
            raise LLMNotConfigured("OPENROUTER_API_KEY is not configured on the server.")
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=45.0,
                max_retries=2,
                default_headers={"HTTP-Referer": "https://github.com/nl-regex-platform", "X-Title": "NL Regex Platform"},
            )
        return self._client

    def generate(self, transform_type: str, prompt: str, columns: list[str], samples: dict[str, list[str]]) -> RegexSpec:
        system = SYSTEM_PROMPTS.get(transform_type)
        if system is None:
            raise LLMError(f"Unsupported transform type {transform_type!r}")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": build_user_prompt(prompt, columns, samples)},
        ]
        for attempt in range(2):
            content = self._complete(messages)
            spec = _parse_spec(content, transform_type)
            if spec is not None:
                logger.info("LLM produced pattern for %s (attempt %d): %s", transform_type, attempt + 1, spec.pattern)
                return spec
            messages += [{"role": "assistant", "content": content}, {"role": "user", "content": REPAIR_PROMPT}]
        raise LLMError("The language model did not return a usable regex. Try rephrasing the request.")

    def _complete(self, messages: list[dict]) -> str:
        client = self._get_client()
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
        except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
            raise LLMTransientError(f"The language model is temporarily unavailable ({exc.__class__.__name__}).") from exc
        except APIStatusError as exc:
            if exc.status_code in (401, 403):
                raise LLMNotConfigured("The OpenRouter API key was rejected.") from exc
            if exc.status_code >= 500:
                raise LLMTransientError(f"The language model returned HTTP {exc.status_code}.") from exc
            raise LLMError(f"The language model request failed (HTTP {exc.status_code}).") from exc
        choice = resp.choices[0] if resp.choices else None
        return (choice.message.content or "") if choice else ""


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_spec(content: str, transform_type: str) -> RegexSpec | None:
    """Tolerant JSON extraction: strips code fences and surrounding prose."""
    if not content:
        return None
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not str(data.get("pattern", "")).strip():
        return None
    if transform_type == "NORMALIZE" and not str(data.get("replacement_template", "")).strip():
        return None
    return RegexSpec.from_dict(data)


class FakeLLM:
    """Deterministic stand-in used by tests and by the LLM_FAKE=1 dev switch."""

    def __init__(self, spec: RegexSpec | None = None):
        self.spec = spec or RegexSpec(pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b", explanation="fake")
        self.calls: list[tuple] = []

    def generate(self, transform_type, prompt, columns, samples):
        self.calls.append((transform_type, prompt, tuple(columns)))
        return self.spec


def build_generator() -> RegexGenerator:
    """Pick the configured RegexGenerator (settings.LLM_PROVIDER)."""
    if settings.LLM_PROVIDER == "fake":
        logger.warning("LLM_PROVIDER=fake: using the deterministic FakeLLM (email pattern only)")
        return FakeLLM()
    return OpenRouterClient()
