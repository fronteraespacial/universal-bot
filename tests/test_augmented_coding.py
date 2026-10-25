"""Augmented Coding: el MAIN exige una historia refinada y las tres alarmas son FAIL."""

from universal_bot.code_mode.augmented_alarms import (
    FAKE_TESTS,
    LOOPS,
    SCOPE_CREEP,
    ProgressSignal,
    classify,
)
from universal_bot.code_mode.orchestrator import MAIN_SYSTEM_PROMPT


def test_alarm_names_match_the_three_sister_rules():
    assert (LOOPS, SCOPE_CREEP, FAKE_TESTS) == ("loops", "scope_creep", "fake_tests")


def test_main_prompt_has_augmented_coding_alarm_rules():
    text = MAIN_SYSTEM_PROMPT
    for piece in (
        "Augmented Coding",
        "una historia refinada",
        "code-backlog",
        "code-story",
        "code-pair",
        "aceptación",
        "fuera de alcance",
        "slice vertical",
        "Spec Driven",
        "Alarmas = FAIL",
        "loops",
        "scope creep",
        "fake tests",
        "reportala y frená",
        "orquestador-sx",
        "no los reemplazan",
    ):
        assert piece in text, piece


def signal(**overrides) -> ProgressSignal:
    payload = {
        "story": "documentar Augmented Coding y frenar las tres alarmas",
        "acceptance": ("el MAIN pide aceptación y fuera de alcance",),
        "out_of_scope": ("SpecKit", "OpenSpec"),
        "approach": "slice-alarms",
        "prior_approaches": ("explore",),
        "changed_paths": ("src/universal_bot/code_mode/augmented_alarms.py",),
        "allowed_paths": ("src/universal_bot/code_mode/", "tests/"),
        "tests_changed": ("tests/test_augmented_coding.py",),
        "production_changed": ("src/universal_bot/code_mode/augmented_alarms.py",),
        "tests_proven_wrong": False,
        "evidence": "tests",
        "new_info": False,
    }
    payload.update(overrides)
    return ProgressSignal(**payload)


def test_loops_fail():
    verdict = classify(signal(approach="retry-a", prior_approaches=("retry-a",)))
    assert verdict.ok is False
    assert verdict.alarms == ("loops",)
    assert "repeated_approach" in verdict.reasons


def test_scope_creep_fails_when_a_path_leaves_the_allowlist():
    leaked = "src/universal_bot/code_mode_backup/x.py"
    verdict = classify(signal(changed_paths=(
        "src/universal_bot/code_mode/augmented_alarms.py",
        leaked,
    )))
    assert verdict.ok is False
    assert verdict.alarms == ("scope_creep",)
    assert f"outside:{leaked}" in verdict.reasons


def test_scope_creep_fails_when_a_path_is_named_out_of_scope():
    parked = "src/universal_bot/code_mode/orchestrator.py"
    verdict = classify(signal(
        out_of_scope=(parked,),
        changed_paths=(parked,),
        production_changed=(parked,),
        tests_changed=("tests/test_augmented_coding.py",),
    ))
    assert verdict.ok is False
    assert verdict.alarms == ("scope_creep",)
    assert f"outside:{parked}" in verdict.reasons


def test_fake_tests_fail_when_only_tests_change_to_go_green():
    verdict = classify(signal(
        tests_changed=("tests/test_augmented_coding.py",),
        production_changed=(),
        changed_paths=("tests/test_augmented_coding.py",),
    ))
    assert verdict.ok is False
    assert verdict.alarms == ("fake_tests",)
    assert "tests_edited_to_pass" in verdict.reasons


def test_lists_every_alarm_together():
    verdict = classify(signal(
        approach="retry-a",
        prior_approaches=("retry-a",),
        changed_paths=("README.md",),
        tests_changed=("tests/test_augmented_coding.py",),
        production_changed=(),
    ))
    assert verdict.ok is False
    assert verdict.alarms == ("loops", "scope_creep", "fake_tests")


def test_happy_path_passes_without_alarms():
    verdict = classify(signal())
    assert verdict.ok is True
    assert verdict.alarms == ()
    assert verdict.reasons == ()


def test_same_approach_with_new_info_is_not_a_loop():
    verdict = classify(signal(approach="retry-a", prior_approaches=("retry-a",), new_info=True))
    assert verdict.ok is True
    assert verdict.alarms == ()


def test_editing_a_proven_wrong_test_is_not_fake():
    verdict = classify(signal(
        tests_changed=("tests/test_augmented_coding.py",),
        production_changed=(),
        tests_proven_wrong=True,
        changed_paths=("tests/test_augmented_coding.py",),
    ))
    assert verdict.ok is True
    assert verdict.alarms == ()


def test_empty_signal_fails_closed():
    verdict = classify(ProgressSignal())
    assert verdict.ok is False
    assert verdict.alarms == ()
    assert set(verdict.reasons) == {
        "missing_story",
        "missing_acceptance",
        "missing_out_of_scope",
        "missing_approach",
        "missing_changes",
        "missing_test_evidence",
    }


def test_design_doc_evidence_fails_closed():
    verdict = classify(signal(evidence="doc"))
    assert verdict.ok is False
    assert verdict.alarms == ()
    assert "missing_test_evidence" in verdict.reasons


def test_missing_acceptance_fails_closed():
    verdict = classify(signal(acceptance=()))
    assert verdict.ok is False
    assert verdict.alarms == ()
    assert "missing_acceptance" in verdict.reasons
