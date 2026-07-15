"""Make attached images usable by ANY chat model (BYOK, model-agnostic).

The model a user picked for a turn is often text-only (most open models are). When an
image is attached, `run_turn` passes it as native vision input ONLY if the model can see
images; otherwise the provider silently ignores it and the model hallucinates "I can't
see the image." That is the root cause of attached images being invisible.

This module closes the gap: when the turn model lacks vision, describe the image(s) with
whatever vision-capable provider the user HAS configured, and inject that description as
text so a text-only model — and any sub-agent it delegates to — can reason about the
image's content. If no vision provider is available, the caller injects a clear notice so
the model tells the user instead of guessing.
"""
from __future__ import annotations

from . import config
from .llm import keys as llm_keys


# Vision-capable models we know how to reach, best first, each paired with its provider.
# A candidate is used only when that provider has a key (BYOK). Kept small and concrete
# so we never send a guessed model id that would 404.
def _candidates() -> list[tuple[str, str]]:
    from .llm import get_provider
    out: list[tuple[str, str]] = [
        ("openai", "gpt-4o"),
        ("anthropic", get_provider("anthropic").default_model),
        ("zhipu", config.VISION_MODEL or "glm-4v-plus"),
        ("openrouter", "openai/gpt-4o"),
    ]
    return [(pid, m) for pid, m in out if m]


def available() -> bool:
    """True when at least one configured provider can describe an image."""
    return _pick() is not None


def _pick() -> tuple[str, str] | None:
    for pid, model in _candidates():
        try:
            if llm_keys.has_key(pid):
                return pid, model
        except Exception:  # noqa: BLE001 - a flaky key check must not break the turn
            continue
    return None


_PROMPT = (
    "Describe the attached image(s) in thorough, faithful detail for a colleague who "
    "cannot see them. Include layout, any tables (column headers, row labels, and the "
    "numbers/values in each cell), chart axes and series, UI text and controls, and any "
    "notable figures. Do not summarize away specifics — reproduce the data you can read."
)


def describe_images(images: list[str], *, max_images: int = 4, max_tokens: int = 1500) -> str | None:
    """Return a text description of ``images`` via a configured vision model, or None when
    no vision provider is available (or the call fails). Streams and accumulates so it
    works over both the OpenAI-compatible client and the native Anthropic adapter."""
    pick = _pick()
    if not pick or not images:
        return None
    from . import llm
    pid, model = pick
    try:
        client, model, _ = llm.resolve_turn_client(model, provider=pid)
        parts: list[dict] = [{"type": "text", "text": _PROMPT}]
        for u in images[:max_images]:
            parts.append({"type": "image_url", "image_url": {"url": u}})
        stream = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": parts}],
            max_tokens=max_tokens, stream=True)
        chunks: list[str] = []
        for ev in stream:
            choices = getattr(ev, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            piece = getattr(delta, "content", None) if delta else None
            if piece:
                chunks.append(piece)
        text = "".join(chunks).strip()
        return text or None
    except Exception:  # noqa: BLE001 - fall back to the no-vision notice, never crash the turn
        return None


def image_context(images: list[str]) -> str:
    """The text block to inject into a text-only model's turn for its attached images:
    a real description when a vision provider is configured, else a clear notice so the
    model surfaces the limitation instead of pretending to see the image."""
    n = len(images)
    plural = "s" if n > 1 else ""
    desc = describe_images(images)
    if desc:
        return (f"[Attached image{plural} — the current model cannot view images, so a "
                f"vision model read {'them' if n > 1 else 'it'} and described "
                f"{'them' if n > 1 else 'it'} below. Treat this as the image content:\n"
                f"{desc}\n]")
    return (f"[The user attached {n} image{plural}, but the current model cannot view "
            "images and no vision-capable provider (e.g. OpenAI, Anthropic, or a GLM-4V "
            "key) is configured. Tell the user you can't see images with this model and "
            "offer to continue if they describe it or switch to a vision-capable model. "
            "Do NOT pretend to have seen it.]")
