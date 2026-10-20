"""Única aprobación obligatoria: el pase a producción."""

from __future__ import annotations


class NeedsProductionApproval(Exception):
    pass


def request_production(*args, **kwargs):
    raise NotImplementedError("request_production")


def may_execute(*args, **kwargs):
    raise NotImplementedError("may_execute")


def can_approve(*args, **kwargs):
    raise NotImplementedError("can_approve")


def approve(*args, **kwargs):
    raise NotImplementedError("approve")


def reject_production(*args, **kwargs):
    raise NotImplementedError("reject_production")


def complete_without_production(*args, **kwargs):
    raise NotImplementedError("complete_without_production")


def intercept_irreversible(*args, **kwargs):
    raise NotImplementedError("intercept_irreversible")
