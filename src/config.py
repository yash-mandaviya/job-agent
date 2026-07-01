from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    resend_api_key: str
    email_to: str
    email_from: str
    model_filter: str
    model_scorer: str
    model_digest: str
    # LLM backend selection: "anthropic" (cloud) or "ollama" (local, private).
    llm_backend: str
    ollama_host: str
    ollama_model: str
    ollama_num_ctx: int

    @classmethod
    def from_env(cls) -> "Config":
        def req(k: str) -> str:
            v = os.environ.get(k)
            if not v:
                raise RuntimeError(f"Missing required env var: {k}")
            return v

        backend = os.environ.get("LLM_BACKEND", "anthropic").lower()
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if backend == "anthropic" and not anthropic_key:
            raise RuntimeError(
                "Missing required env var: ANTHROPIC_API_KEY "
                "(or set LLM_BACKEND=ollama to run a local model instead)"
            )

        return cls(
            anthropic_api_key=anthropic_key,
            resend_api_key=os.environ.get("RESEND_API_KEY", ""),
            email_to=req("EMAIL_TO"),
            email_from=os.environ.get("EMAIL_FROM", "onboarding@resend.dev"),
            model_filter=os.environ.get("MODEL_FILTER", "claude-haiku-4-5-20251001"),
            model_scorer=os.environ.get("MODEL_SCORER", "claude-sonnet-4-6"),
            model_digest=os.environ.get("MODEL_DIGEST", "claude-sonnet-4-6"),
            llm_backend=backend,
            ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.1:8b"),
            # The profile + job prompt runs ~8K tokens; Ollama defaults to ~4K
            # and would silently truncate. 16K gives comfortable headroom.
            ollama_num_ctx=int(os.environ.get("OLLAMA_NUM_CTX", "16384")),
        )
