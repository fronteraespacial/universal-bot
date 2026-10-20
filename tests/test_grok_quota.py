"""Cuota de grok leída del modal `/usage` de la TUI (sin llamar al modelo) y escrita fuera del repo."""

import json
import sys
import time
from pathlib import Path

from universal_bot.code_mode.cli_adapters import FileQuotaReader
from universal_bot.code_mode.grok_quota import parse_usage_screen, probe_grok_usage, write_quota_file

FIXTURE = Path(__file__).parent / "fixtures" / "grok_usage_modal.txt"
FAKE = Path(__file__).parent / "fakes" / "fake_grok_tui.py"


def test_parse_the_real_usage_modal():
    usage = parse_usage_screen(FIXTURE.read_text(encoding="utf-8"))
    assert usage == {"used": 0.58, "grok_remaining": 0.42, "plan": "SuperGrok", "resets": "October 24, 08:22"}


def test_parse_returns_none_without_the_limit():
    assert parse_usage_screen("Context usage\n 1.8K / 2M") is None
    assert parse_usage_screen("") is None


def test_write_is_atomic_and_readable_by_the_selector(tmp_path):
    out = tmp_path / "state" / "quota.json"
    write_quota_file(out, {"used": 0.58, "grok_remaining": 0.42, "plan": "SuperGrok", "resets": "x"}, now=1000.0)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["grok_remaining"] == 0.42 and data["as_of"] == 1000.0 and data["source"] == "grok /usage"
    assert not list(out.parent.glob("*.tmp"))


def test_probe_reads_usage_from_the_tui_without_prompting_the_model(tmp_path, monkeypatch):
    log = tmp_path / "typed.log"
    monkeypatch.setenv("FAKE_GROK_LOG", str(log))
    out = tmp_path / "quota.json"
    usage = probe_grok_usage([sys.executable, str(FAKE)], out=out, cwd=tmp_path / "work", timeout_s=15, settle_s=0.3)
    assert usage["grok_remaining"] == 0.42
    assert log.read_text(encoding="utf-8").split() == ["/usage"], "solo /usage: ninguna llamada al modelo"
    assert FileQuotaReader(out, max_age_s=600).grok_remaining() == 0.42


def test_probe_without_data_writes_nothing(tmp_path):
    out = tmp_path / "quota.json"
    usage = probe_grok_usage([sys.executable, "-c", "import time; print('sin tui'); time.sleep(30)"], out=out,
                             cwd=tmp_path / "work", timeout_s=2, settle_s=0.2)
    assert usage is None and not out.exists()
