"""Model factory: the only file that knows about LLM providers.

Any OpenAI-compatible endpoint works (Gemini, Ollama, ...); switching is a .env edit.
"""
import os

from agents import (ModelRetryBackoffSettings, ModelRetrySettings, ModelSettings, OpenAIChatCompletionsModel,
                    retry_policies, set_tracing_disabled)
from openai import AsyncOpenAI

from mishwar import config  # noqa: F401  (loads .env)

set_tracing_disabled(True)  # tracing uploads to OpenAI; without an OpenAI key it fails with 401


def model_name() -> str:
    return os.getenv("LLM_MODEL", "?")


def build_model() -> OpenAIChatCompletionsModel:
    missing = [k for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)} (copy .env.example to .env and fill it in)")
    # Retries are left to the runner (model_settings below), so they back off long enough for a rate limit.
    client = AsyncOpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"], max_retries=0)
    return OpenAIChatCompletionsModel(model=os.environ["LLM_MODEL"], openai_client=client)


def model_settings() -> ModelSettings:
    """Retry rate limits (Gemini's free tier allows 15 requests/minute), 5xx and network errors.

    Backoff 10, 20, 40, 60 s covers a full one-minute quota window.
    """
    return ModelSettings(retry=ModelRetrySettings(
        max_retries=4,
        backoff=ModelRetryBackoffSettings(initial_delay=10, max_delay=60, multiplier=2, jitter=True),
        policy=retry_policies.any(
            retry_policies.retry_after(),
            retry_policies.http_status([429, 500, 502, 503, 504]),
            retry_policies.network_error(),
        ),
    ))
