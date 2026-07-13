"""Provider registry — the model-agnostic core (Phase 1).

Every supported backend is an OpenAI-compatible chat-completions endpoint, so a
single ``openai.OpenAI(base_url=..., api_key=...)`` client drives them all: hosted
(OpenAI, Zhipu/GLM, DeepSeek, Qwen/DashScope, OpenRouter, Together, Groq, Mistral)
and local (Ollama, vLLM, LM Studio, llama.cpp). Users bring their own key and pick
any model — the one deliberate difference from Claude Desktop.

A provider is just connection metadata: where to reach it and how to authenticate.
Capabilities (context window, vision, tools, reasoning) live in ``catalog.py``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    base_url: str | None           # None => the official OpenAI endpoint
    key_env: str = ""              # env var consulted as a fallback for the API key
    default_model: str = ""
    models: tuple[str, ...] = field(default_factory=tuple)
    requires_key: bool = True       # local runtimes accept any/no key
    is_local: bool = False
    docs: str = ""


# The built-in catalog. base_url values are the documented OpenAI-compatible
# endpoints for each provider. Local runtimes default to their standard ports.
_BUILTINS: tuple[Provider, ...] = (
    Provider("openai", "OpenAI", None, "OPENAI_API_KEY", "gpt-4o-mini",
             ("gpt-4o", "gpt-4o-mini", "o3-mini"),
             docs="https://platform.openai.com/docs"),
    # The one non-OpenAI-compatible backend: Claude models through the NATIVE
    # Messages API (llm.anthropic_native), which unlocks prompt caching and
    # provider-side extended thinking. A starter list — any Messages-API model id
    # the endpoint accepts can be typed in.
    Provider("anthropic", "Anthropic", "https://api.anthropic.com",
             "ANTHROPIC_API_KEY", "claude-sonnet-5",
             ("claude-fable-5", "claude-opus-4-8", "claude-sonnet-5",
              "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6",
              "claude-haiku-4-5", "claude-opus-4-5", "claude-sonnet-4-5"),
             docs="https://platform.claude.com/docs"),
    Provider("zhipu", "Zhipu GLM", "https://open.bigmodel.cn/api/paas/v4",
             "ZHIPU_API_KEY", "glm-4.6",
             # Newest first: GLM-5 reasoning flagships, then the GLM-4.5/4.6
             # agentic-coding family, vision variants, then the legacy GLM-4
             # line. IDs are shared across the bigmodel.cn and z.ai endpoints;
             # BYOK users may also type any model string the endpoint accepts.
             ("glm-5.2", "glm-5.1", "glm-5",
              "glm-4.7-flash",
              "glm-4.6", "glm-4.5", "glm-4.5-x", "glm-4.5-air", "glm-4.5-airx",
              "glm-4.5-flash",
              "glm-4.6v", "glm-4.5v",
              "glm-4-plus", "glm-4-long", "glm-4-flash", "glm-4v-plus"),
             docs="https://open.bigmodel.cn"),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com", "DEEPSEEK_API_KEY",
             "deepseek-chat", ("deepseek-chat", "deepseek-reasoner"),
             docs="https://platform.deepseek.com"),
    Provider("qwen", "Qwen (DashScope)",
             "https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY",
             "qwen-plus", ("qwen-max", "qwen-plus", "qwen-turbo",
                           "qwen2.5-72b-instruct", "qwq-32b-preview"),
             docs="https://help.aliyun.com/zh/dashscope"),
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1",
             "OPENROUTER_API_KEY", "openai/gpt-4o-mini",
             ("openai/gpt-4o-mini", "deepseek/deepseek-chat",
              "meta-llama/llama-3.3-70b-instruct", "qwen/qwen-2.5-72b-instruct",
              "mistralai/mistral-large", "google/gemma-2-27b-it"),
             docs="https://openrouter.ai/docs"),
    Provider("together", "Together AI", "https://api.together.xyz/v1",
             "TOGETHER_API_KEY", "meta-llama/Llama-3.3-70B-Instruct-Turbo",
             ("meta-llama/Llama-3.3-70B-Instruct-Turbo",
              "Qwen/Qwen2.5-72B-Instruct-Turbo",
              "deepseek-ai/DeepSeek-V3",
              "mistralai/Mixtral-8x7B-Instruct-v0.1"),
             docs="https://docs.together.ai"),
    Provider("groq", "Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY",
             "llama-3.3-70b-versatile",
             ("llama-3.3-70b-versatile", "llama-3.1-8b-instant",
              "mixtral-8x7b-32768", "gemma2-9b-it"),
             docs="https://console.groq.com/docs"),
    Provider("mistral", "Mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY",
             "mistral-large-latest",
             ("mistral-large-latest", "mistral-small-latest",
              "open-mixtral-8x22b", "codestral-latest"),
             docs="https://docs.mistral.ai"),
    Provider("ollama", "Ollama (local)", "http://localhost:11434/v1", "OLLAMA_API_KEY",
             "llama3.1",
             ("llama3.1", "llama3.2", "llama3", "qwen2.5",
              "mistral", "gemma2", "phi3", "deepseek-r1"),
             requires_key=False, is_local=True,
             docs="https://github.com/ollama/ollama/blob/main/docs/openai.md"),
    Provider("vllm", "vLLM (local)", "http://localhost:8000/v1", "VLLM_API_KEY",
             "", requires_key=False, is_local=True, docs="https://docs.vllm.ai"),
    Provider("lmstudio", "LM Studio (local)", "http://localhost:1234/v1",
             "LMSTUDIO_API_KEY", "", requires_key=False, is_local=True,
             docs="https://lmstudio.ai/docs/local-server"),
    Provider("llamacpp", "llama.cpp (local)", "http://localhost:8080/v1",
             "LLAMACPP_API_KEY", "", requires_key=False, is_local=True,
             docs="https://github.com/ggml-org/llama.cpp"),
)

_REGISTRY: dict[str, Provider] = {p.id: p for p in _BUILTINS}

# The default provider for the whole app. Defaults to zhipu for parity with the
# pre-Phase-1 behavior; override with LLM_PROVIDER. LLM_BASE_URL / LLM_API_KEY let
# a user point the default at any custom OpenAI-compatible endpoint.
DEFAULT_PROVIDER_ID_ENV = "LLM_PROVIDER"
CUSTOM_BASE_URL_ENV = "LLM_BASE_URL"
CUSTOM_KEY_ENV = "LLM_API_KEY"
_FALLBACK_DEFAULT = "zhipu"


def default_provider_id() -> str:
    return (os.getenv(DEFAULT_PROVIDER_ID_ENV) or _FALLBACK_DEFAULT).strip() or _FALLBACK_DEFAULT


def list_providers() -> list[Provider]:
    return list(_REGISTRY.values())


def get_provider(provider_id: str | None = None) -> Provider:
    """Resolve a provider by id. Falls back to the configured default.

    Unknown ids resolve to a synthetic 'custom' provider driven purely by the
    LLM_BASE_URL / LLM_API_KEY env vars, so a user can use any endpoint without a
    code change.
    """
    pid = (provider_id or default_provider_id()).strip()
    if pid in _REGISTRY:
        return _REGISTRY[pid]
    return Provider(pid, pid, os.getenv(CUSTOM_BASE_URL_ENV) or None,
                    CUSTOM_KEY_ENV, os.getenv("LLM_MODEL", ""), requires_key=False)
