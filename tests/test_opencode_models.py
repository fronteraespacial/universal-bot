"""Unit tests for Free remap and model#variant formatting."""

from __future__ import annotations

import unittest

from universal_bot.opencode.models import (
    effort_to_variant,
    format_go_model,
    format_model_arg,
    remap_free_model,
)


class TestModels(unittest.TestCase):
    def test_remap_cli_only_passthrough(self) -> None:
        self.assertEqual(remap_free_model("deepseek-v4.1-flash-free"), "deepseek-v4.1-flash-free")
        self.assertEqual(remap_free_model("opencode/glm-5.3-flash-free"), "glm-5.3-flash-free")

    def test_remap_unknown_to_default(self) -> None:
        self.assertEqual(remap_free_model("big-pickle"), "deepseek-v4.1-flash-free")
        self.assertEqual(
            remap_free_model("something", free_model="glm-5.3-flash-free"),
            "glm-5.3-flash-free",
        )

    def test_variant(self) -> None:
        self.assertEqual(effort_to_variant("low"), "low")
        self.assertEqual(effort_to_variant("high"), "high")
        self.assertEqual(effort_to_variant(None), "high")

    def test_format_model_arg(self) -> None:
        self.assertEqual(
            format_model_arg("deepseek-v4.1-flash-free", provider="opencode", variant="low"),
            "opencode/deepseek-v4.1-flash-free#low",
        )
        self.assertEqual(
            format_model_arg("opencode-go/deepseek-v4.1-flash", variant="high"),
            "opencode-go/deepseek-v4.1-flash#high",
        )

    def test_format_go(self) -> None:
        self.assertEqual(format_go_model("deepseek-v4.1-flash"), "opencode-go/deepseek-v4.1-flash")
        self.assertEqual(
            format_go_model("opencode-go/deepseek-v4.1-flash"),
            "opencode-go/deepseek-v4.1-flash",
        )


if __name__ == "__main__":
    unittest.main()
