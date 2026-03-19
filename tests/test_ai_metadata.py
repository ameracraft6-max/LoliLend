from __future__ import annotations

import unittest

from lolilend.ai_metadata import is_popular_model, normalize_task_name, schema_defaults


class AiMetadataTests(unittest.TestCase):
    def test_normalize_task_name_supports_cloudflare_labels(self) -> None:
        task = normalize_task_name("Text-to-Speech")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.key, "text_to_speech")

    def test_schema_defaults_excludes_primary_known_fields(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "text": {"type": "string", "default": "ignored"},
                "temperature": {"type": "number", "default": 0.4},
                "voice": {"type": "string", "default": "alloy"},
            },
        }
        defaults = schema_defaults(schema, exclude_keys={"text"})
        self.assertEqual(defaults, {"temperature": 0.4, "voice": "alloy"})

    def test_popular_model_registry_marks_pinned_models(self) -> None:
        self.assertTrue(is_popular_model("text_generation", "@cf/openai/gpt-oss-20b"))
        self.assertFalse(is_popular_model("text_generation", "@cf/example/not-pinned"))


if __name__ == "__main__":
    unittest.main()
