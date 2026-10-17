"""Gemini 4 Argon prefixes for AGY.

``4`` and ``argon`` select ``gemini-4-argon-{low,medium,high}``.
The default effort is low. Effort is baked into the slug; callers must not
also pass a conflicting ``--effort``.
"""

from __future__ import annotations

import re

ARGON_EFFORTS = ("low", "medium", "high")
ARGON_DEFAULT_EFFORT = "low"
ARGON_SLUGS = {effort: f"gemini-4-argon-{effort}" for effort in ARGON_EFFORTS}

# Optional leading AGY / Gemini, then 4 or argon, then an optional effort word.
# ``4`` must not swallow ``40`` or ``4.2``. ``argon`` must not swallow ``argonite``.
_ARGON_RE = re.compile(
    r"^(?:agy[\s_-]+)?"
    r"(?:gemini[\s_-]*)?"
    r"(?:4(?![\d.])(?:[\s_-]+argon)?|argon)"
    r"(?:[\s_-]+(?P<effort>low|medium|high))?"
    r"\b[\s:,.\-]*",
    re.I,
)
_BARE_ARGON_RE = re.compile(r"^(?:4(?![\d.])|argon)\b", re.I)


def split_argon_prefix(
    text: str,
    *,
    allow_bare_4: bool = True,
) -> tuple[str, str, str] | None:
    """Return ``(slug, effort, rest)`` when ``text`` starts with 4/argon.

    ``allow_bare_4=False`` ignores a lone ``4`` that does not say argon or
    gemini (used when the brain is already Claude).
    """
    t = (text or "").strip()
    if not t:
        return None
    match = _ARGON_RE.match(t)
    if not match:
        return None
    effort = (match.group("effort") or ARGON_DEFAULT_EFFORT).lower()
    if effort not in ARGON_SLUGS:
        effort = ARGON_DEFAULT_EFFORT
    head = t[: match.end()]
    if not allow_bare_4 and not re.search(r"argon|gemini", head, re.I):
        return None
    rest = t[match.end() :].strip()
    return ARGON_SLUGS[effort], effort, rest


def is_bare_argon_invocation(text: str) -> bool:
    """True when the message itself opens with ``4`` or ``argon`` (not ``AGY``)."""
    t = (text or "").strip()
    if not _BARE_ARGON_RE.match(t):
        return False
    return split_argon_prefix(t) is not None


def argon_slug(model: str | None) -> bool:
    """True when ``model`` is a Gemini 4 Argon slug (effort baked in)."""
    return str(model or "").strip().lower() in ARGON_SLUGS.values()
