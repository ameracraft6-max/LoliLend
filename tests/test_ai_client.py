from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from lolilend.ai_client import (
    AiClientError,
    AiRequestOptions,
    AiTaskRequest,
    ChatMessagePayload,
    CloudflareAiClient,
    OPENAI_COMPATIBLE,
    WORKERS_AI_RUN,
)


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: dict | list | None = None,
        lines: list[bytes | str] | None = None,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._lines = lines or []
        self.ok = 200 <= status_code < 300
        self.encoding = None
        self.headers = headers or {}
        self.content = content

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode: bool = True):
        del decode_unicode
        for line in self._lines:
            yield line

    def close(self) -> None:
        return


class _HeadersLike:
    def __init__(self, payload: dict[str, str]) -> None:
        self._payload = dict(payload)

    def get(self, key: str, default=None):
        return self._payload.get(key, default)


class CloudflareAiClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = CloudflareAiClient("acc", "token")

    @patch("lolilend.ai_client.requests.get")
    def test_fetch_models_marks_chat_compatibility(self, mock_get) -> None:
        mock_get.return_value = _FakeResponse(
            payload={
                "success": True,
                "result": [
                    {"id": "1", "name": "m1", "task": {"name": "Text Generation"}, "description": "chat"},
                    {"id": "2", "name": "m2", "task": {"name": "Text Embeddings"}, "description": "embed"},
                ],
                "result_info": {"total_count": 2, "page": 1, "per_page": 100},
            }
        )
        models = self.client.fetch_models()
        self.assertEqual(len(models), 2)
        self.assertTrue(models[0].chat_compatible)
        self.assertFalse(models[1].chat_compatible)
        self.assertEqual(models[0].task_key, "text_generation")
        self.assertEqual(models[1].task_key, "text_embeddings")

    @patch("lolilend.ai_client.requests.post")
    def test_send_chat_openai(self, mock_post) -> None:
        mock_post.return_value = _FakeResponse(payload={"choices": [{"message": {"content": "ok"}}]})
        out = self.client.send_chat(
            [ChatMessagePayload(role="user", content="ping")],
            AiRequestOptions(protocol=OPENAI_COMPATIBLE, model="m"),
        )
        self.assertEqual(out, "ok")

    @patch("lolilend.ai_client.requests.post")
    def test_stream_chat_openai(self, mock_post) -> None:
        mock_post.return_value = _FakeResponse(
            lines=[
                b'data: {"choices":[{"delta":{"content":"Hel"}}]}',
                b'data: {"choices":[{"delta":{"content":"lo"}}]}',
                b"data: [DONE]",
            ]
        )
        chunks = list(
            self.client.stream_chat(
                [ChatMessagePayload(role="user", content="ping")],
                AiRequestOptions(protocol=OPENAI_COMPATIBLE, model="m"),
            )
        )
        self.assertEqual("".join(chunks), "Hello")

    @patch("lolilend.ai_client.requests.post")
    def test_send_chat_normalizes_mojibake(self, mock_post) -> None:
        mock_post.return_value = _FakeResponse(payload={"choices": [{"message": {"content": "РџСЂРёРІРµС‚"}}]})
        out = self.client.send_chat(
            [ChatMessagePayload(role="user", content="ping")],
            AiRequestOptions(protocol=OPENAI_COMPATIBLE, model="m"),
        )
        self.assertEqual(out, "Привет")

    @patch("lolilend.ai_client.requests.post")
    def test_workers_fallback_to_prompt(self, mock_post) -> None:
        mock_post.side_effect = [
            _FakeResponse(status_code=400, payload={"errors": [{"message": "bad payload"}]}),
            _FakeResponse(payload={"result": {"response": "done"}}),
        ]
        out = self.client.send_chat(
            [ChatMessagePayload(role="user", content="ping")],
            AiRequestOptions(protocol=WORKERS_AI_RUN, model="@cf/test/model"),
        )
        self.assertEqual(out, "done")
        self.assertEqual(mock_post.call_count, 2)
        first_payload = mock_post.call_args_list[0].kwargs["json"]
        second_payload = mock_post.call_args_list[1].kwargs["json"]
        self.assertIn("messages", first_payload)
        self.assertIn("prompt", second_payload)

    @patch("lolilend.ai_client.requests.post")
    def test_workers_endpoint_does_not_encode_model_slashes(self, mock_post) -> None:
        mock_post.return_value = _FakeResponse(payload={"result": {"data": [[0.1, 0.2]]}})
        self.client.run_task(
            AiTaskRequest(
                model="@cf/test/model",
                task_key="text_embeddings",
                texts=["hello"],
            )
        )
        url = mock_post.call_args.args[0]
        self.assertTrue(url.endswith("/ai/run/%40cf/test/model"))
        self.assertNotIn("%2F", url)

    @patch("lolilend.ai_client.requests.post")
    def test_run_task_retries_raw_endpoint_on_no_route(self, mock_post) -> None:
        mock_post.side_effect = [
            _FakeResponse(status_code=400, payload={"errors": [{"message": "No route for that URI"}]}),
            _FakeResponse(payload={"result": {"data": [[0.1, 0.2]]}}),
        ]
        result = self.client.run_task(
            AiTaskRequest(
                model="@cf/test/model",
                task_key="text_embeddings",
                texts=["hello"],
            )
        )
        self.assertEqual(result.embedding, [[0.1, 0.2]])
        self.assertEqual(mock_post.call_count, 2)
        first_url = mock_post.call_args_list[0].args[0]
        second_url = mock_post.call_args_list[1].args[0]
        self.assertTrue(first_url.endswith("/ai/run/%40cf/test/model"))
        self.assertTrue(second_url.endswith("/ai/run/@cf/test/model"))

    @patch("lolilend.ai_client.requests.post")
    def test_send_chat_retries_raw_endpoint_on_no_route(self, mock_post) -> None:
        mock_post.side_effect = [
            _FakeResponse(status_code=400, payload={"errors": [{"message": "No route for that URI"}]}),
            _FakeResponse(payload={"result": {"response": "ok"}}),
        ]
        out = self.client.send_chat(
            [ChatMessagePayload(role="user", content="ping")],
            AiRequestOptions(protocol=WORKERS_AI_RUN, model="@cf/test/model"),
        )
        self.assertEqual(out, "ok")
        self.assertEqual(mock_post.call_count, 2)
        first_url = mock_post.call_args_list[0].args[0]
        second_url = mock_post.call_args_list[1].args[0]
        self.assertTrue(first_url.endswith("/ai/run/%40cf/test/model"))
        self.assertTrue(second_url.endswith("/ai/run/@cf/test/model"))

    @patch("lolilend.ai_client.requests.post")
    def test_stream_chat_retries_raw_endpoint_on_no_route(self, mock_post) -> None:
        mock_post.side_effect = [
            _FakeResponse(status_code=400, payload={"errors": [{"message": "No route for that URI"}]}),
            _FakeResponse(
                lines=[
                    b'data: {"result":{"response":"Hel"}}',
                    b'data: {"result":{"response":"lo"}}',
                    b"data: [DONE]",
                ]
            ),
        ]
        chunks = list(
            self.client.stream_chat(
                [ChatMessagePayload(role="user", content="ping")],
                AiRequestOptions(protocol=WORKERS_AI_RUN, model="@cf/test/model"),
            )
        )
        self.assertEqual("".join(chunks), "Hello")
        self.assertEqual(mock_post.call_count, 2)
        first_url = mock_post.call_args_list[0].args[0]
        second_url = mock_post.call_args_list[1].args[0]
        self.assertTrue(first_url.endswith("/ai/run/%40cf/test/model"))
        self.assertTrue(second_url.endswith("/ai/run/@cf/test/model"))

    @patch("lolilend.ai_client.requests.get")
    def test_verify_token_error(self, mock_get) -> None:
        mock_get.return_value = _FakeResponse(status_code=403, payload={"errors": [{"message": "forbidden"}]})
        with self.assertRaises(AiClientError):
            self.client.verify_token()

    @patch("lolilend.ai_client.requests.get")
    def test_fetch_model_schema_uses_cache(self, mock_get) -> None:
        mock_get.return_value = _FakeResponse(payload={"success": True, "result": {"input_schema": {"type": "object"}}})
        first = self.client.fetch_model_schema("@cf/test/model")
        second = self.client.fetch_model_schema("@cf/test/model")
        self.assertEqual(first["input_schema"]["type"], "object")
        self.assertEqual(second["input_schema"]["type"], "object")
        self.assertEqual(mock_get.call_count, 1)

    def test_run_task_rejects_openai_for_non_chat_task(self) -> None:
        with self.assertRaises(AiClientError):
            self.client.run_task(
                AiTaskRequest(
                    model="@cf/test/model",
                    task_key="text_embeddings",
                    protocol=OPENAI_COMPATIBLE,
                    texts=["hello"],
                )
            )

    @patch("lolilend.ai_client.requests.post")
    def test_run_task_embeddings_parses_numeric_vectors(self, mock_post) -> None:
        mock_post.return_value = _FakeResponse(payload={"result": {"data": [[0.1, 0.2], [0.3, 0.4]]}})
        result = self.client.run_task(
            AiTaskRequest(
                model="@cf/test/model",
                task_key="text_embeddings",
                texts=["alpha", "beta"],
            )
        )
        self.assertEqual(result.output_kind, "embedding")
        self.assertEqual(result.embedding, [[0.1, 0.2], [0.3, 0.4]])

    @patch("lolilend.ai_client.requests.post")
    def test_run_task_classification_sorts_scores(self, mock_post) -> None:
        mock_post.return_value = _FakeResponse(
            payload={"result": [{"label": "neutral", "score": 0.2}, {"label": "positive", "score": 0.9}]}
        )
        result = self.client.run_task(
            AiTaskRequest(
                model="@cf/test/model",
                task_key="text_classification",
                prompt="good",
            )
        )
        self.assertEqual(result.classifications[0]["label"], "positive")
        self.assertIn("positive: 0.9000", result.text)

    @patch("lolilend.ai_client.requests.post")
    def test_run_task_text_to_image_reads_binary_response(self, mock_post) -> None:
        mock_post.return_value = _FakeResponse(
            headers={"Content-Type": "image/png"},
            content=b"\x89PNG",
        )
        result = self.client.run_task(
            AiTaskRequest(
                model="@cf/test/model",
                task_key="text_to_image",
                prompt="draw a fox",
            )
        )
        self.assertEqual(result.image_bytes, b"\x89PNG")
        self.assertEqual(result.image_mime_type, "image/png")

    @patch("lolilend.ai_client.requests.post")
    def test_run_task_text_to_image_reads_binary_response_with_mapping_headers(self, mock_post) -> None:
        mock_post.return_value = _FakeResponse(
            headers=_HeadersLike({"Content-Type": "image/png"}),
            content=b"\x89PNG",
        )
        result = self.client.run_task(
            AiTaskRequest(
                model="@cf/test/model",
                task_key="text_to_image",
                prompt="draw a fox",
            )
        )
        self.assertEqual(result.image_bytes, b"\x89PNG")
        self.assertEqual(result.image_mime_type, "image/png")

    @patch("lolilend.ai_client.requests.post")
    def test_run_task_image_classification_sends_uint8_image_array(self, mock_post) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "sample.bin"
            image_path.write_bytes(b"\x01\x02\x03\x04")
            mock_post.return_value = _FakeResponse(payload={"result": [{"label": "cat", "score": 0.9}]})
            self.client.run_task(
                AiTaskRequest(
                    model="@cf/test/model",
                    task_key="image_classification",
                    file_path=str(image_path),
                )
            )
            posted = mock_post.call_args.kwargs["json"]
            self.assertEqual(posted["image"], [1, 2, 3, 4])

    @patch("lolilend.ai_client.requests.post")
    def test_run_task_image_fallbacks_to_string_payload_when_schema_requires_string(self, mock_post) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "sample.bin"
            image_path.write_bytes(b"\x01\x02\x03")
            mock_post.side_effect = [
                _FakeResponse(status_code=400, payload={"errors": [{"message": "Type mismatch of '/image', 'array' not in 'string'"}]}),
                _FakeResponse(payload={"result": {"description": "ok"}}),
            ]
            result = self.client.run_task(
                AiTaskRequest(
                    model="@cf/test/model",
                    task_key="image_to_text",
                    file_path=str(image_path),
                    prompt="describe",
                )
            )
            self.assertEqual(result.text, "ok")
            self.assertEqual(mock_post.call_count, 2)
            first_payload = mock_post.call_args_list[0].kwargs["json"]
            second_payload = mock_post.call_args_list[1].kwargs["json"]
            self.assertIsInstance(first_payload["image"], list)
            self.assertIsInstance(second_payload["image"], str)


if __name__ == "__main__":
    unittest.main()
