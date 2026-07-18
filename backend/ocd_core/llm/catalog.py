"""Model capability catalog (Phase 1).

A best-effort, offline capability lookup keyed by model-name patterns: context
window, max output, and whether the model supports vision, tool calling, and
native reasoning/thinking. The agent uses this to adapt (e.g. skip tools for a
model that can't call them, size the context budget, map effort to native
thinking). Values are conservative defaults; a provider's live /models endpoint
can refine them later.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capabilities:
    context_window: int = 8192
    max_output: int = 4096
    vision: bool = False
    tools: bool = True
    reasoning: bool = False


# Ordered (substring-or-prefix, Capabilities) rules; first match wins. Patterns are
# lowercased and matched against the bare model name (any 'provider/' prefix stripped).
_RULES: tuple[tuple[str, Capabilities], ...] = (
    ("gpt-5", Capabilities(400_000, 128_000, vision=True, tools=True, reasoning=True)),
    ("gpt-4o", Capabilities(128_000, 16_384, vision=True, tools=True)),
    ("o3", Capabilities(200_000, 100_000, tools=True, reasoning=True)),
    ("o1", Capabilities(200_000, 100_000, tools=True, reasoning=True)),
    ("claude-fable", Capabilities(1_000_000, 128_000, vision=True, tools=True, reasoning=True)),
    ("claude-mythos", Capabilities(1_000_000, 128_000, vision=True, tools=True, reasoning=True)),
    ("claude-opus-4", Capabilities(1_000_000, 128_000, vision=True, tools=True, reasoning=True)),
    ("claude-sonnet-5", Capabilities(1_000_000, 128_000, vision=True, tools=True, reasoning=True)),
    ("claude-sonnet-4-6", Capabilities(1_000_000, 128_000, vision=True, tools=True, reasoning=True)),
    ("claude-haiku-4", Capabilities(200_000, 64_000, vision=True, tools=True, reasoning=True)),
    ("claude", Capabilities(200_000, 64_000, vision=True, tools=True, reasoning=True)),
    ("glm-5", Capabilities(200_000, 128_000, tools=True, reasoning=True)),
    ("glm-4v", Capabilities(8_192, 4_096, vision=True, tools=True)),
    ("glm-4-plus", Capabilities(128_000, 4_096, tools=True)),
    ("glm-4-long", Capabilities(1_000_000, 4_096, tools=True)),
    ("glm-4.5", Capabilities(128_000, 4_096, tools=True, reasoning=True)),
    ("glm-4", Capabilities(128_000, 4_096, tools=True)),
    ("deepseek-reasoner", Capabilities(64_000, 8_192, tools=False, reasoning=True)),
    ("deepseek", Capabilities(64_000, 8_192, tools=True)),
    ("qwen", Capabilities(131_072, 8_192, tools=True)),
    ("llama-3.3", Capabilities(131_072, 8_192, tools=True)),
    ("llama3.1", Capabilities(131_072, 8_192, tools=True)),
    ("llama", Capabilities(8_192, 4_096, tools=True)),
    ("mistral", Capabilities(131_072, 8_192, tools=True)),
    ("mixtral", Capabilities(32_768, 8_192, tools=True)),
)

_DEFAULT = Capabilities()


def capabilities(model: str) -> Capabilities:
    """Best-effort capabilities for a model name (offline heuristic)."""
    name = (model or "").split("/")[-1].strip().lower()
    for pattern, caps in _RULES:
        if pattern in name:
            return caps
    return _DEFAULT


def context_window(model: str) -> int:
    return capabilities(model).context_window


def supports_tools(model: str) -> bool:
    return capabilities(model).tools


def supports_vision(model: str) -> bool:
    return capabilities(model).vision


def supports_reasoning(model: str) -> bool:
    return capabilities(model).reasoning
