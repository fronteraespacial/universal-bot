"""Gemini 4 Argon prefix: 4 / argon, default low."""

from universal_bot.agy_prefix import (
    ARGON_SLUGS,
    is_bare_argon_invocation,
    split_argon_prefix,
)


def test_default_low():
    slug, effort, rest = split_argon_prefix("4 revisá el router")
    assert slug == "gemini-4-argon-low" and effort == "low" and rest == "revisá el router"
    slug, effort, rest = split_argon_prefix("argon revisá")
    assert slug == ARGON_SLUGS["low"] and rest == "revisá"
    slug, effort, rest = split_argon_prefix("AGY 4, hola")
    assert slug == "gemini-4-argon-low" and rest == "hola"
    slug, effort, rest = split_argon_prefix("4 argon")
    assert slug == "gemini-4-argon-low" and rest == ""


def test_efforts():
    assert split_argon_prefix("4 low x")[:2] == ("gemini-4-argon-low", "low")
    assert split_argon_prefix("4 medium x")[0] == "gemini-4-argon-medium"
    assert split_argon_prefix("argon high x")[0] == "gemini-4-argon-high"
    assert split_argon_prefix("AGY argon medium, hacé esto") == (
        "gemini-4-argon-medium",
        "medium",
        "hacé esto",
    )
    assert split_argon_prefix("gemini-4-argon-high hola")[0] == "gemini-4-argon-high"
    assert split_argon_prefix("4 argon high hola")[2] == "hola"


def test_does_not_steal_other_prefixes():
    assert split_argon_prefix("3.8 hola") is None
    assert split_argon_prefix("40 cosas") is None
    assert split_argon_prefix("4.2 cosas") is None
    assert split_argon_prefix("argonite hola") is None
    assert split_argon_prefix("4argon") is None
    assert split_argon_prefix("high revisá") is None
    assert split_argon_prefix("AGY hola") is None
    assert split_argon_prefix("Sonnet hola") is None
    assert split_argon_prefix("4 revisá", allow_bare_4=False) is None
    assert split_argon_prefix("argon high x", allow_bare_4=False)[0] == "gemini-4-argon-high"


def test_bare_invocation():
    assert is_bare_argon_invocation("4 high hola")
    assert is_bare_argon_invocation("argon hola")
    assert not is_bare_argon_invocation("AGY 4 hola")
    assert not is_bare_argon_invocation("40 hola")
    assert not is_bare_argon_invocation("hola")
