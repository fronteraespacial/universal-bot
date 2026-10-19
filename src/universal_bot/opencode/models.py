"""Model id helpers: Free remap and provider/model#variant formatting."""

from __future__ import annotations

DEFAULT_FREE_MODEL = "deepseek-v4.1-flash-free"

# Free ids that must stay as-is on the CLI path. Any other Free pin remaps
# to DEFAULT_FREE_MODEL (or UB_OPENCODE_FREE_MODEL) when using shared serve.
CLI_ONLY_FREE_MODELS = frozenset(
    {
        "deepseek-v4.1-flash-free",
        "glm-5.3-flash-free",
    }
)


def effort_to_variant(effort: str | None) -> str:
    """Map reasoning effort to OpenCode V2 #variant (low|high)."""
    e = (effort or "high").strip().lower()
    if e in {"low", "minimal", "medium"}:
        return "low"
    if e in {"high", "max", "extra", "xhigh", "extra-high"}:
        return "high"
    return "low"


def remap_free_model(model: str, free_model: str = DEFAULT_FREE_MODEL) -> str:
    """Remap a Free pin for shared serve.

    CLI-only Free ids pass through; everything else becomes ``free_model``.
    """
    raw = (model or "").strip()
    mid = raw.split("/", 1)[-1] if raw else ""
    if mid in CLI_ONLY_FREE_MODELS:
        return mid
    return (free_model or DEFAULT_FREE_MODEL).strip() or DEFAULT_FREE_MODEL


def format_go_model(model: str) -> str:
    """Normalize a Go model id to ``opencode-go/<id>``."""
    raw = (model or "").strip()
    if not raw:
        raise ValueError("model is required")
    pin = raw.split("/", 1)[-1]
    if raw.startswith("opencode-go/"):
        return raw
    return f"opencode-go/{pin}"


def format_model_arg(
    model: str,
    *,
    provider: str | None = None,
    variant: str | None = None,
) -> str:
    """Build ``provider/model#variant`` for ``opencode run -m``.

    If ``model`` already contains a ``/``, it is used as-is for the provider part.
    """
    raw = (model or "").strip()
    if not raw:
        raise ValueError("model is required")
    if "/" in raw:
        base = raw
    else:
        pref = (provider or "opencode").strip() or "opencode"
        base = f"{pref}/{raw}"
    if variant:
        return f"{base}#{variant}"
    return base
