"""Loader del yaml de modo código. Los defaults del diseño siguen si falta la clave."""

from pathlib import Path

import pytest

from universal_bot.code_mode.config import CodeModeConfig, ConfigError, load_code_mode_config

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "instances" / "frontera-labcode.example.yaml"
ALLOWLIST = 910001


def test_example_quotes_production_and_keeps_the_allowlist():
    text = EXAMPLE.read_text(encoding="utf-8")
    assert 'production: "requester|dev"' in text
    config = load_code_mode_config(EXAMPLE)
    assert config.approvals.production == "requester|dev"
    assert config.allowed_channels == (ALLOWLIST,)
    assert config.proposal_threshold == 0.8
    assert config.default_duration == "4h"
    assert config.projects_category == "Proyectos"


def test_partial_file_keeps_defaults(tmp_path):
    path = tmp_path / "guild.yaml"
    path.write_text("code_mode:\n  proposal_threshold: 0.5\n", encoding="utf-8")
    config = load_code_mode_config(path)
    defaults = CodeModeConfig()
    assert config.proposal_threshold == 0.5
    assert config.default_duration == defaults.default_duration
    assert config.allowed_channels == defaults.allowed_channels
    assert config.approvals.production == "requester|dev"


@pytest.mark.parametrize(
    ("body", "match"),
    (
        ("code_mode:\n  approvals:\n    production: cualquiera\n", "production"),
        ("code_mode:\n  proposal_threshold: 2\n", "proposal_threshold"),
        ("code_mode:\n  security_check: off\n  host_role: vps\n", "servidor compartido"),
    ),
)
def test_invalid_config_is_rejected(tmp_path, body, match):
    path = tmp_path / "guild.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError, match=match):
        load_code_mode_config(path)
