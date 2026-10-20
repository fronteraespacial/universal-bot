"""Tabla del custom_id ublab:<kind>:<id>:<opt>."""

import pytest

from universal_bot.code_mode.custom_id import CustomId, CustomIdError, build_custom_id, parse_custom_id


def test_valid_ids_roundtrip():
    cases = (
        ("pq", "PQ-1", "seguir", "ublab:pq:PQ-1:seguir"),
        ("propose", "req-1", "create_channel", "ublab:propose:req-1:create_channel"),
        ("Kind_1", "id-2", "opt.3", "ublab:Kind_1:id-2:opt.3"),
    )
    for kind, item_id, opt, raw in cases:
        assert build_custom_id(kind, item_id, opt) == raw
        assert parse_custom_id(raw) == CustomId(kind, item_id, opt)
        assert parse_custom_id(raw).is_stop is False


def test_stop_is_valid_and_foreign_ub_stop_is_rejected():
    raw = build_custom_id("stop", "job-1", "ahora")
    assert raw == "ublab:stop:job-1:ahora"
    parsed = parse_custom_id(raw)
    assert parsed == CustomId("stop", "job-1", "ahora")
    assert parsed.is_stop is True
    with pytest.raises(CustomIdError, match="ajeno"):
        parse_custom_id("ub:stop:job-1:ahora")


@pytest.mark.parametrize(
    "raw",
    (
        "ublab::id:opt",
        "ublab:kind::opt",
        "ublab:kind:id:",
        "ublab:kind:id",
        "ublab:kind:id:opt:extra",
        "ublab:ki nd:id:opt",
        "ublab:kind:id:opt!",
        "ublab:kind:id:ópt",
        "ublab:kind:id:a/b",
    ),
)
def test_empty_parts_or_invalid_chars_are_rejected(raw):
    with pytest.raises(CustomIdError, match="inválido"):
        parse_custom_id(raw)


def test_builder_rejects_empty_and_invalid_parts():
    with pytest.raises(CustomIdError):
        build_custom_id("", "id", "opt")
    with pytest.raises(CustomIdError):
        build_custom_id("kind", "a b", "opt")
    with pytest.raises(CustomIdError):
        build_custom_id("a" * 65, "id", "opt")


def test_total_over_100_is_rejected():
    with pytest.raises(CustomIdError, match="100"):
        build_custom_id("k" * 40, "i" * 40, "o" * 20)
    ok = build_custom_id("k" * 30, "i" * 30, "o" * 30)
    assert len(ok) <= 100
    too_long = "ublab:" + ("k" * 30) + ":" + ("i" * 30) + ":" + ("o" * 40)
    assert len(too_long) > 100
    with pytest.raises(CustomIdError, match="100"):
        parse_custom_id(too_long)
    with pytest.raises(CustomIdError):
        parse_custom_id("ublab:" + ("a" * 65) + ":b:c")
