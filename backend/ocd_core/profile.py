"""User profile → a personalization block for the system prompt.

Closes the onboarding/profile gap (and removes the old hard-coded identity): the user
tells the assistant their name, what to call them, their role, and response
preferences; these are rendered into the `# USER PROFILE` section by prompts.py.
"""
from __future__ import annotations

# Fields persisted under settings["profile"].
FIELDS = ("name", "call_me", "role", "about", "preferences")


def render(profile: dict | None) -> str:
    """Render a stored profile dict into prompt text (empty string if nothing set)."""
    if not profile:
        return ""
    lines: list[str] = []
    call_me = (profile.get("call_me") or profile.get("name") or "").strip()
    if call_me:
        lines.append(f"Address the user as {call_me}.")
    role = (profile.get("role") or "").strip()
    if role:
        lines.append(f"The user's role or work: {role}.")
    about = (profile.get("about") or "").strip()
    if about:
        lines.append(f"About the user: {about}")
    prefs = (profile.get("preferences") or "").strip()
    if prefs:
        lines.append(f"Response preferences to honor: {prefs}")
    return "\n".join(lines)


def sanitize(profile: dict | None) -> dict:
    """Keep only known string fields (trimmed) — what /settings persists."""
    if not isinstance(profile, dict):
        return {}
    out: dict = {}
    for k in FIELDS:
        v = profile.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out
