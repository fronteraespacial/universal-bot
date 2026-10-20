"""La hipótesis del lab no repite la frase ni el comando de activación."""

import pytest

from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.text_rules import strip_activation

CONFIG = CodeModeConfig()


@pytest.mark.parametrize(
    ("raw", "clean"),
    (
        ("pasemos a modo código: ¿se puede?", "¿se puede?"),
        ("PASÉMOS A MODO CODIGO, seguimos", "seguimos"),
        ("modo programación. el detalle", "el detalle"),
        ("activá modo código — listo", "listo"),
        ("/modo-codigo probá el parser", "probá el parser"),
        ("/MODO-CÓDIGO: probá", "probá"),
        ("/modo-codigo 1h: hacer el cambio", "hacer el cambio"),
        ("hola", "hola"),
        ("no pasemos a modo código", "no pasemos a modo código"),
        ("", ""),
    ),
)
def test_strip_activation_drops_only_the_leading_trigger(raw, clean):
    assert strip_activation(raw, CONFIG) == clean
