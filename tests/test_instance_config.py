"""Loader del yaml de modo código. Los defaults del diseño siguen si falta la clave."""

from pathlib import Path

import pytest

from universal_bot.code_mode.config import CodeModeConfig, ConfigError, load_code_mode_config, load_runtime_config
from universal_bot.code_mode.inbox_flow import author_roles

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "instances" / "frontera-labcode.example.yaml"


def test_example_quotes_production_and_starts_closed():
    text = EXAMPLE.read_text(encoding="utf-8")
    assert 'production: "requester|dev"' in text
    config = load_code_mode_config(EXAMPLE)
    assert config.approvals.production == "requester|dev"
    assert config.allowed_channels == ()
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
    assert config.allowed_channels == ()
    assert defaults.allowed_channels == ()
    assert defaults.routing_policy == ""
    assert defaults.role_map == ()
    assert config.approvals.production == "requester|dev"


def test_env_overrides_the_closed_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("UBLAB_CONFIG", "")
    monkeypatch.setenv("UBLAB_ALLOWED_CHANNELS", "100,200")
    monkeypatch.setenv("UBLAB_ADMIN_CATEGORY_ID", "300")
    monkeypatch.setenv("UBLAB_GUILD_ID", "10")
    monkeypatch.setenv("UBLAB_PROJECTS_CHANNEL_ID", "400")
    monkeypatch.setenv("UBLAB_ROUTING_POLICY", "policy.yaml")
    monkeypatch.setenv("UBLAB_ROLE_MAP", "200:@dev|@admin;201:@dev")
    config = load_runtime_config(tmp_path)
    assert config.allowed_channels == (100, 200)
    assert config.admin_category_id == 300
    assert config.guild_id == 10
    assert config.projects_channel_id == 400
    assert config.routing_policy == "policy.yaml"
    assert author_roles(200, config) == ("@dev", "@admin")
    assert author_roles(201, config) == ("@dev",)
    assert author_roles(1, config) == ()


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
