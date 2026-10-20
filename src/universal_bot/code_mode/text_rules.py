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


def strip_activation(text: str, config: CodeModeConfig) -> str:
    folded, indexes = _fold_map(text)
    if not folded:
        return text
    cut = _trigger_cut(folded, config)
    if cut is None:
        return text
    start = indexes[cut] if cut < len(indexes) else len(text)
    rest = text[start:].lstrip(" \t:,.;-—–")
    return rest


def _fold_map(text: str) -> tuple[str, list[int]]:
    folded: list[str] = []
    indexes: list[int] = []
    for index, char in enumerate(text):
        plain = "".join(
            piece for piece in unicodedata.normalize("NFKD", char) if not unicodedata.combining(piece)
        )
        for piece in plain.lower():
            folded.append(piece)
            indexes.append(index)
    return "".join(folded), indexes


def _trigger_cut(folded: str, config: CodeModeConfig) -> int | None:
    command = _fold_map(config.manual_trigger_command)[0]
    phrases = [_fold_map(phrase)[0] for phrase in config.manual_trigger_phrases]
    for phrase in phrases:
        if phrase and folded.startswith(phrase):
            return len(phrase)
    if command and folded.startswith(command):
        cursor = len(command)
        if folded.startswith(command + " "):
            cursor += 1
            for duration in config.duration_options:
                token = _fold_map(duration)[0]
                if folded.startswith(token, cursor):
                    cursor += len(token)
                    break
        return cursor
    return None


def is_manual_trigger(text: str, config: CodeModeConfig) -> bool:
    norm = normalize_text(text)
    command = normalize_text(config.manual_trigger_command)
    if norm == command or norm.startswith(command + " "):
        return True
    phrases = {normalize_text(phrase) for phrase in config.manual_trigger_phrases}
    if norm in phrases:
        return True
    return any(_phrase_prefix(norm, phrase) for phrase in phrases)


def _phrase_prefix(norm: str, phrase: str) -> bool:
    if not norm.startswith(phrase) or len(norm) == len(phrase):
        return False
    return norm[len(phrase)] in " :,;-"


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
