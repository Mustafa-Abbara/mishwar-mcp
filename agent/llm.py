"""Model factory: the only file that knows about LLM providers.

Any OpenAI-compatible endpoint works (Gemini, Ollama, ...); switching is a .env edit.
"""
import os

from agents import OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI

from mishwar import config  # noqa: F401  (loads .env)

set_tracing_disabled(True)  # tracing uploads to OpenAI; without an OpenAI key it fails with 401


def model_name() -> str:
    return os.getenv("LLM_MODEL", "?")


def build_model() -> OpenAIChatCompletionsModel:
    missing = [k for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)} (copy .env.example to .env and fill it in)")
    client = AsyncOpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
    return OpenAIChatCompletionsModel(model=os.environ["LLM_MODEL"], openai_client=client)
