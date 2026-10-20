"""Cada job del inbox entra por acá. El reloj y el lab se inyectan."""

from __future__ import annotations


def confidence_for(decision):
    raise NotImplementedError


def should_propose(tier, confidence, threshold, tiers):
    raise NotImplementedError


def author_roles(author_id, config):
    raise NotImplementedError
