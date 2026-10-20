"""Tabla de la máquina de estados de Project."""

import pytest

from universal_bot.code_mode.models import ProjectState
from universal_bot.code_mode.project_machine import IllegalTransition, transition

_ALLOWED = (
    ("PROPOSED", "DECLINED"),
    ("PROPOSED", "PENDING_ADMIN"),
    ("PROPOSED", "PROVISIONING"),
    ("PENDING_ADMIN", "PROVISIONING"),
    ("PENDING_ADMIN", "DECLINED"),
    ("PROVISIONING", "SANDBOX_CHECK"),
    ("SANDBOX_CHECK", "LAB_RUNNING"),
    ("SANDBOX_CHECK", "WAITING_HUMAN"),
    ("SANDBOX_CHECK", "RUNNING"),
    ("LAB_RUNNING", "SANDBOX_CHECK"),
    ("LAB_RUNNING", "PLAN_READY"),
    ("LAB_RUNNING", "LAB_RUNNING"),
    ("LAB_RUNNING", "WAITING_HUMAN"),
    ("PLAN_READY", "RUNNING"),
    ("RUNNING", "SANDBOX_CHECK"),
    ("RUNNING", "WAITING_HUMAN"),
    ("RUNNING", "ESCALATED"),
    ("RUNNING", "DONE"),
    ("RUNNING", "PENDING_PROD_APPROVAL"),
    ("RUNNING", "CANCELLED"),
    ("WAITING_HUMAN", "RUNNING"),
    ("WAITING_HUMAN", "PAUSED"),
    ("PAUSED", "RUNNING"),
    ("PAUSED", "CANCELLED"),
    ("ESCALATED", "RUNNING"),
    ("PENDING_PROD_APPROVAL", "DEPLOYING"),
    ("PENDING_PROD_APPROVAL", "RUNNING"),
    ("PENDING_PROD_APPROVAL", "PAUSED"),
    ("DEPLOYING", "DONE"),
    ("DEPLOYING", "ESCALATED"),
    ("DONE", "ARCHIVED"),
)

_FORBIDDEN = (
    ("PROPOSED", "DONE"),
    ("PROPOSED", "PLAN_READY"),
    ("RUNNING", "PLAN_READY"),
    ("PLAN_READY", "DONE"),
    ("DONE", "RUNNING"),
    ("DECLINED", "PROPOSED"),
    ("SANDBOX_CHECK", "PLAN_READY"),
    ("DEPLOYING", "RUNNING"),
)


@pytest.mark.parametrize(("src", "dst"), _ALLOWED)
def test_allowed_transition(src, dst):
    assert transition(ProjectState(src), ProjectState(dst)) == ProjectState(dst)


@pytest.mark.parametrize(("src", "dst"), _FORBIDDEN)
def test_forbidden_transition(src, dst):
    with pytest.raises(IllegalTransition):
        transition(ProjectState(src), ProjectState(dst))
