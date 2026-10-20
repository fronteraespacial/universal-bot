"""Frases de activación y charla trivial. No decide el tier del trabajo."""

from __future__ import annotations

import unicodedata

from universal_bot.contracts import Tier, TriageInput
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.triage.classify import classify

_TRIVIAL = frozenset(
    {
        "gracias",
        "muchas gracias",
        "que hora es",
        "ok",
        "dale",
        "jaja",
        "buen dia",
        "buenas",
        "todo bien",
    }
)


def normalize_text(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in folded if not unicodedata.combining(char))
    cleaned = stripped.strip().lower().strip("¿?¡!.,")
    return " ".join(cleaned.split())


def is_manual_trigger(text: str, config: CodeModeConfig) -> bool:
    norm = normalize_text(text)
    command = normalize_text(config.manual_trigger_command)
    if norm == command or norm.startswith(command + " "):
        return True
    phrases = {normalize_text(phrase) for phrase in config.manual_trigger_phrases}
    return norm in phrases


def is_command(text: str, config: CodeModeConfig) -> bool:
    norm = normalize_text(text)
    command = normalize_text(config.manual_trigger_command)
    return norm == command or norm.startswith(command + " ")


def duration_from_text(text: str, config: CodeModeConfig) -> str:
    norm = normalize_text(text)
    command = normalize_text(config.manual_trigger_command)
    if norm.startswith(command + " "):
        return norm[len(command) + 1 :]
    return config.default_duration


def is_trivial_message(text: str) -> bool:
    if normalize_text(text) in _TRIVIAL:
        return True
    decision = classify(TriageInput(text=text))
    if decision.signals == ("typo",):
        return True
    return decision.tier == Tier.T0 and not decision.is_code
