"""Config local del adaptador cursor-sdk: launcher, archivo de key y node."""

from pathlib import Path

import pytest

from universal_bot.code_mode.cursor_sdk import CursorSdkAdapter, adapter_from_config


def make_launcher(root: Path) -> Path:
    launcher = root / "adapters" / "cursor_sdk" / "bin" / "cursor-sdk-sidecar"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n")
    return launcher


def test_defaults_use_the_repo_launcher(tmp_path):
    launcher = make_launcher(tmp_path)
    adapter = adapter_from_config({}, tmp_path)
    assert isinstance(adapter, CursorSdkAdapter)
    assert (adapter.launcher, adapter.key_file, adapter.node_bin) == (launcher, None, None)


def test_local_values_are_used(tmp_path):
    make_launcher(tmp_path)
    adapter = adapter_from_config(
        {"cursor_sdk": {"api_key_file": "~/k/cursor", "node_bin": "/opt/node/bin/node"}}, tmp_path
    )
    assert (adapter.key_file, adapter.node_bin) == (Path("~/k/cursor").expanduser(), "/opt/node/bin/node")


@pytest.mark.parametrize(
    "raw,with_launcher",
    [({"cursor_sdk": {"enabled": False}}, True), ({}, False), ({"cursor_sdk": {"launcher": "nope/x"}}, True)],
)
def test_disabled_or_missing_launcher_gives_no_adapter(tmp_path, raw, with_launcher):
    if with_launcher:
        make_launcher(tmp_path)
    assert adapter_from_config(raw, tmp_path) is None
