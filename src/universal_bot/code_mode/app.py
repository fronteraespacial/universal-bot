"""Orquesta el modo código sobre los servicios. Los tests usan FakeDiscord."""

from __future__ import annotations


class CodeModeApp:
    def __init__(self, db_path, discord, clock, config):
        raise NotImplementedError("CodeModeApp")
