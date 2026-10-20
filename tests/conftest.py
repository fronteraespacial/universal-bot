"""Los tests nunca leen el config/local.yaml de la máquina (puede tener el MAIN prendido o ids reales)."""

import pytest


@pytest.fixture(autouse=True)
def _no_local_config(monkeypatch):
    monkeypatch.setenv("UBLAB_CONFIG", "")
