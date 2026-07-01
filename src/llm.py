"""LLM backend abstraction.

The scorer needs one thing from a model: given some system instructions + the
candidate profile and a per-job user message, return a JSON string. Two backends
implement that:

- AnthropicClient — cloud Claude via the official SDK (prompt-caches the profile).
- OllamaClient — a local model served by Ollama (fully private; nothing leaves
  the machine). Uses Ollama's /api/chat with format=json to force valid JSON.

Selected via Config.llm_backend (env LLM_BACKEND=anthropic|ollama).
"""
from __future__ import annotations

import logging

import httpx

from .config import Config

log = logging.getLogger(__name__)


class LLMClient:
    async def complete(
        self, *, model: str, system_texts: list[str], user: str, max_tokens: int
    ) -> str:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)

    async def complete(
        self, *, model: str, system_texts: list[str], user: str, max_tokens: int
    ) -> str:
        # Cache the last system block (the profile) so per-job calls stay cheap.
        system = []
        for i, text in enumerate(system_texts):
            block: dict = {"type": "text", "text": text}
            if i == len(system_texts) - 1:
                block["cache_control"] = {"type": "ephemeral"}
            system.append(block)
        resp = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text


class OllamaClient(LLMClient):
    def __init__(self, host: str, model: str, num_ctx: int = 16384, timeout: float = 180.0) -> None:
        self._host = host.rstrip("/")
        self._model = model
        self._num_ctx = num_ctx
        self._timeout = timeout

    async def complete(
        self, *, model: str, system_texts: list[str], user: str, max_tokens: int
    ) -> str:
        # Ollama has no prompt-cache control; concatenate system blocks.
        system = "\n\n".join(t for t in system_texts if t)
        payload = {
            "model": self._model,  # local model name; per-stage Claude model ignored
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",  # force valid JSON output
            "options": {
                "temperature": 0,
                "num_predict": max_tokens,
                "num_ctx": self._num_ctx,  # avoid Ollama's small default truncating the prompt
            },
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._host}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["message"]["content"]


def build_llm(cfg: Config) -> LLMClient:
    if cfg.llm_backend == "ollama":
        log.info("LLM backend: ollama (model=%s, host=%s, num_ctx=%d)",
                 cfg.ollama_model, cfg.ollama_host, cfg.ollama_num_ctx)
        return OllamaClient(cfg.ollama_host, cfg.ollama_model, num_ctx=cfg.ollama_num_ctx)
    log.info("LLM backend: anthropic")
    return AnthropicClient(cfg.anthropic_api_key)
