"""The language model behind one small interface, so the provider is a config choice.

openai_compatible works with any service that implements the OpenAI
chat-completions format, including Ollama running locally.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from .config import get_settings


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatLLM(Protocol):
    name: str

    def complete(self, system: str, user: str) -> LLMResult: ...


class FakeLLM:
    """No model at all: quotes the first sentence of the top source and cites it.

    It exists so the demo, the tests and CI run with no API key and no cost.
    It never refuses, so do not use it to measure answer quality.
    """

    name = "fake"

    def complete(self, system: str, user: str) -> LLMResult:
        match = re.search(r"SOURCE \[([^\]]+)\][^\n]*\n(.+)", user)
        if not match:
            return LLMResult("NOT_FOUND")
        first_sentence = re.split(r"(?<=[.!?])\s", match.group(2).strip())[0]
        return LLMResult(f"{first_sentence} [{match.group(1)}]")


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, api_key: str, model: str, transport: httpx.BaseTransport | None = None) -> None:
        if not base_url or not model:
            raise ValueError("Set LLM_BASE_URL and LLM_MODEL in .env to use LLM_PROVIDER=openai_compatible.")
        self.name = model
        self._model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=120.0, transport=transport)

    def complete(self, system: str, user: str) -> LLMResult:
        response = self._client.post(
            "/chat/completions",
            json={
                "model": self._model,
                "temperature": 0,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        return LLMResult(
            text=(data["choices"][0]["message"]["content"] or "").strip(),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )


def get_llm(provider: str | None = None) -> ChatLLM:
    settings = get_settings()
    provider = provider or settings.llm_provider
    if provider == "fake":
        return FakeLLM()
    if provider == "openai_compatible":
        return OpenAICompatibleLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    raise ValueError(f"Unknown LLM_PROVIDER '{provider}'. Use 'fake' or 'openai_compatible'.")
