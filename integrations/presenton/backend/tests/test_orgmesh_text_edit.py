"""Check concise text edits in the authenticated embedded workspace."""

import unittest
from unittest.mock import patch

from services.chat.slide_ui_helpers import _update_text_element


class TextEditTests(unittest.TestCase):
    def element(self) -> dict[str, object]:
        return {"name": "body_copy", "min_length": 105, "max_length": 275}

    def test_embedded_editor_accepts_concise_chinese(self) -> None:
        element = self.element()
        text = "把分散文档连接为企业知识库，让员工快速找到有来源的答案。"
        with patch(
            "services.chat.slide_ui_helpers.is_orgmesh_bridge_configured",
            return_value=True,
            create=True,
        ):
            _update_text_element(element, text)
        self.assertEqual(element["text"], text)

    def test_embedded_editor_keeps_nonempty_and_maximum(self) -> None:
        with patch(
            "services.chat.slide_ui_helpers.is_orgmesh_bridge_configured",
            return_value=True,
            create=True,
        ):
            for text in ("", "字" * 276):
                with self.subTest(text_length=len(text)):
                    with self.assertRaises(ValueError):
                        _update_text_element(self.element(), text)

    def test_standalone_editor_preserves_original_minimum(self) -> None:
        with patch(
            "services.chat.slide_ui_helpers.is_orgmesh_bridge_configured",
            return_value=False,
            create=True,
        ):
            with self.assertRaises(ValueError):
                _update_text_element(self.element(), "Short content")


if __name__ == "__main__":
    unittest.main()
