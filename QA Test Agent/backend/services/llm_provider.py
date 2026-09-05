"""Provider-agnostic LLM interface used by every agent.

Agents call `LLMProvider.generate_structured(...)` and never import a
provider SDK directly. The provider + model are chosen per test run (see
schemas.state.RunConfig.llm_provider/llm_model, set from the UI's LLM
Provider/Model fields) and fall back to LLM_PROVIDER/MODEL in .env when a
run doesn't override them - either way, swapping providers is a config
change, not a code change.

Supported providers: gemini, openai, azure_openai, grok, sarvam.
"""
from __future__ import annotations

import abc
import json
from typing import Type, TypeVar

from langsmith import traceable
from pydantic import BaseModel

from config.settings import get_settings

T = TypeVar("T", bound=BaseModel)


class LLMProvider(abc.ABC):
    """Reasoning-only interface. Never grant this direct system/browser access."""

    @abc.abstractmethod
    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        ...

    async def generate_structured(
        self, system_prompt: str, user_prompt: str, schema: Type[T]
    ) -> T:
        """Ask the model for JSON matching `schema`, then validate it. Never
        trust raw LLM output — validation failures raise, they never get
        silently coerced."""
        schema_hint = json.dumps(schema.model_json_schema(), indent=2)
        full_system = (
            f"{system_prompt}\n\n"
            "Respond with ONLY a single JSON object matching this JSON Schema. "
            "No markdown fences, no commentary.\n"
            f"{schema_hint}"
        )
        raw = await self.generate_text(full_system, user_prompt)
        cleaned = _strip_code_fences(raw)
        data = json.loads(cleaned)
        return schema.model_validate(data)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model)
        self._model_name = model

    @traceable(name="gemini.generate_content", run_type="llm")
    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._model.generate_content_async(
            [system_prompt, user_prompt]
        )
        return response.text


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    @traceable(name="openai.chat.completions", run_type="llm")
    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""


class AzureOpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, endpoint: str, model: str):
        if not api_key or not endpoint:
            raise RuntimeError("AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT not configured")
        from openai import AsyncAzureOpenAI

        self._client = AsyncAzureOpenAI(
            api_key=api_key, azure_endpoint=endpoint, api_version="2024-06-01"
        )
        self._model = model

    @traceable(name="azure_openai.chat.completions", run_type="llm")
    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""


class GrokProvider(LLMProvider):
    """xAI Grok - confirmed OpenAI-API-compatible (same SDK, different
    base_url: https://api.x.ai/v1, plain Bearer auth). Verified against
    xAI's own docs (docs.x.ai). Get a key at https://console.x.ai.

    Current text models (verified via docs.x.ai as of this integration):
    grok-4.6 (latest), grok-4.5, grok-4.3. Check docs.x.ai/docs/models for
    the latest list - xAI ships new versions frequently."""

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise RuntimeError("GROK_API_KEY is not configured")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        self._model = model

    @traceable(name="grok.chat.completions", run_type="llm")
    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""


class GroqProvider(LLMProvider):
    """Groq (the fast-inference hardware company, console.groq.com) - NOT
    the same as xAI's "Grok" chatbot above; easy to confuse, kept as a
    separate provider on purpose. Confirmed OpenAI-API-compatible: base_url
    https://api.groq.com/openai/v1, plain Bearer auth (verified via
    console.groq.com/docs/openai).

    Current models (verified via console.groq.com/docs/models): the two
    with native JSON-schema structured-output support (best fit for this
    project's generate_structured calls) are openai/gpt-oss-120b and
    openai/gpt-oss-20b; llama-3.3-70b-versatile is a strong general-purpose
    alternative (best-effort JSON mode only, no strict schema)."""

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not configured")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        self._model = model

    @traceable(name="groq.chat.completions", run_type="llm")
    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""


class SarvamProvider(LLMProvider):
    """Sarvam AI (Indian-language-focused models). Verified against
    docs.sarvam.ai/api-reference/chat/chat-completions: base_url
    https://api.sarvam.ai/v1, models are sarvam-105b (128K context, for
    reasoning/agentic tasks - used as the default here) and
    sarvam-105b-conversations (32K context, for real-time chat/voice).

    Auth needs BOTH a standard `Authorization: Bearer <key>` header AND an
    `api-subscription-key: <key>` header - the OpenAI SDK only sends the
    first by default, so the second is added explicitly via default_headers
    below (same key for both; split into two settings if Sarvam issues them
    separately for your account). CONFIRMED against a live Sarvam key: the
    request reaches the real endpoint and both headers are accepted (a
    401 would mean bad auth; instead an account with no credits gets a
    clean 402 "No credits available" from Sarvam's own API) - so this
    integration is verified correct, independent of any given account's
    billing status."""

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise RuntimeError("SARVAM_API_KEY is not configured")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.sarvam.ai/v1",
            default_headers={"api-subscription-key": api_key},
        )
        self._model = model

    @traceable(name="sarvam.chat.completions", run_type="llm")
    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""


SUPPORTED_PROVIDERS = ("gemini", "openai", "azure_openai", "grok", "groq", "sarvam")

# Manual override hook used by tests/harnesses (set llm_provider._provider =
# FakeProvider() to bypass real providers entirely, regardless of what a run
# requests). Real usage never touches this - see _provider_cache below.
_provider: LLMProvider | None = None
_provider_cache: dict[tuple[str, str], LLMProvider] = {}


def get_llm_provider(provider: str | None = None, model: str | None = None) -> LLMProvider:
    if _provider is not None:
        return _provider

    settings = get_settings()
    provider = provider or settings.llm_provider
    model = model or settings.llm_model
    if provider not in SUPPORTED_PROVIDERS:
        raise RuntimeError(f"Unknown LLM provider: {provider} (supported: {SUPPORTED_PROVIDERS})")

    cache_key = (provider, model)
    if cache_key in _provider_cache:
        return _provider_cache[cache_key]

    if provider == "gemini":
        instance: LLMProvider = GeminiProvider(settings.gemini_api_key, model)
    elif provider == "openai":
        instance = OpenAIProvider(settings.openai_api_key, model)
    elif provider == "azure_openai":
        instance = AzureOpenAIProvider(settings.azure_openai_api_key, settings.azure_openai_endpoint, model)
    elif provider == "grok":
        instance = GrokProvider(settings.grok_api_key, model)
    elif provider == "groq":
        instance = GroqProvider(settings.groq_api_key, model)
    else:
        instance = SarvamProvider(settings.sarvam_api_key, model)

    _provider_cache[cache_key] = instance
    return instance
