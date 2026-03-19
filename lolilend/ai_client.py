from __future__ import annotations

import base64
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
import json
import mimetypes
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import quote

import requests

from lolilend.ai_metadata import (
    AUTOMATIC_SPEECH_RECOGNITION,
    IMAGE_CLASSIFICATION,
    IMAGE_TO_TEXT,
    SUMMARIZATION,
    TASKS_BY_KEY,
    TASK_DEFINITIONS,
    TEXT_CLASSIFICATION,
    TEXT_EMBEDDINGS,
    TEXT_GENERATION,
    TEXT_TO_IMAGE,
    TEXT_TO_SPEECH,
    TRANSLATION,
    get_task_definition,
    is_popular_model,
    normalize_task_name,
)
from lolilend.ai_text import normalize_ai_text


CF_API_BASE = "https://api.cloudflare.com/client/v4"
OPENAI_COMPATIBLE = "openai_compatible"
WORKERS_AI_RUN = "workers_ai_run"


class AiClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class AiModelInfo:
    id: str
    name: str
    task_name: str
    description: str
    task_key: str
    task_label: str
    chat_compatible: bool
    supports_system_prompt: bool
    supports_file_input: bool
    output_kind: str
    is_popular: bool


@dataclass(slots=True)
class ChatMessagePayload:
    role: str
    content: str


@dataclass(slots=True)
class AiRequestOptions:
    protocol: str = OPENAI_COMPATIBLE
    model: str = "@cf/meta/llama-3.2-3b-instruct"
    temperature: float = 0.7
    max_tokens: int = 1024
    system_prompt: str = ""


@dataclass(slots=True)
class AiTaskRequest:
    model: str
    task_key: str
    protocol: str = WORKERS_AI_RUN
    prompt: str = ""
    texts: list[str] = field(default_factory=list)
    file_path: str = ""
    source_language: str = ""
    target_language: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024
    advanced_params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AiTaskResult:
    task_key: str
    output_kind: str
    text: str = ""
    json_data: Any = None
    embedding: list[float] | list[list[float]] | None = None
    classifications: list[dict[str, Any]] = field(default_factory=list)
    image_bytes: bytes = b""
    image_mime_type: str = "image/png"
    audio_bytes: bytes = b""
    audio_mime_type: str = "audio/mpeg"
    metadata: dict[str, Any] = field(default_factory=dict)


class CloudflareAiClient:
    def __init__(self, account_id: str, token: str, timeout_seconds: int = 60) -> None:
        self._account_id = account_id.strip()
        self._token = token.strip()
        self._timeout = timeout_seconds
        self._schema_cache: dict[str, dict[str, Any]] = {}
        if not self._account_id:
            raise ValueError("Cloudflare account_id is required")
        if not self._token:
            raise ValueError("Cloudflare API token is required")

    def verify_token(self) -> bool:
        url = f"{CF_API_BASE}/user/tokens/verify"
        response = requests.get(url, headers=self._auth_headers(), timeout=self._timeout)
        payload = self._read_json(response)
        return bool(payload.get("success", False))

    def fetch_models(self) -> list[AiModelInfo]:
        models: list[AiModelInfo] = []
        page = 1
        per_page = 100

        while True:
            response = requests.get(
                f"{CF_API_BASE}/accounts/{self._account_id}/ai/models/search",
                headers=self._auth_headers(),
                params={"page": page, "per_page": per_page},
                timeout=self._timeout,
            )
            payload = self._read_json(response)
            result = payload.get("result", [])
            if not isinstance(result, list) or not result:
                break

            for row in result:
                if not isinstance(row, dict):
                    continue
                task = row.get("task", {})
                task_name = str(task.get("name", "")).strip()
                task_def = normalize_task_name(task_name)
                if task_def is None:
                    continue
                model_name = str(row.get("name", "")).strip()
                if not model_name:
                    continue
                models.append(
                    AiModelInfo(
                        id=str(row.get("id", "")),
                        name=model_name,
                        task_name=task_name,
                        description=str(row.get("description", "")),
                        task_key=task_def.key,
                        task_label=task_def.label,
                        chat_compatible=task_def.key == TEXT_GENERATION,
                        supports_system_prompt=task_def.supports_system_prompt,
                        supports_file_input=task_def.supports_file_input,
                        output_kind=task_def.output_kind,
                        is_popular=is_popular_model(task_def.key, model_name),
                    )
                )

            info = payload.get("result_info", {})
            total_count = int(info.get("total_count", 0) or 0)
            if page * per_page >= total_count:
                break
            page += 1

        return sorted(models, key=lambda model: model.name.lower())

    def fetch_model_schema(self, model: str, force_refresh: bool = False) -> dict[str, Any]:
        model_name = str(model).strip()
        if not model_name:
            raise AiClientError("Model name is required for schema lookup")
        if not force_refresh and model_name in self._schema_cache:
            return dict(self._schema_cache[model_name])

        response = requests.get(
            f"{CF_API_BASE}/accounts/{self._account_id}/ai/models/schema",
            headers=self._auth_headers(),
            params={"model": model_name},
            timeout=self._timeout,
        )
        payload = self._read_json(response)
        result = payload.get("result", payload)
        if not isinstance(result, dict):
            raise AiClientError("Cloudflare API returned unsupported model schema", response.status_code)
        self._schema_cache[model_name] = dict(result)
        return dict(result)

    def send_chat(self, messages: Sequence[ChatMessagePayload], options: AiRequestOptions) -> str:
        prepared = self._prepare_messages(messages, options.system_prompt)
        protocol = self._normalize_protocol(options.protocol)
        if protocol == OPENAI_COMPATIBLE:
            response = requests.post(
                f"{CF_API_BASE}/accounts/{self._account_id}/ai/v1/chat/completions",
                headers=self._auth_headers(),
                json={
                    "model": options.model,
                    "messages": prepared,
                    "temperature": float(options.temperature),
                    "max_tokens": int(options.max_tokens),
                    "stream": False,
                },
                timeout=self._timeout,
            )
            payload = self._read_json(response)
            text = _extract_openai_text(payload)
            if not text:
                raise AiClientError("Cloudflare AI returned an empty response")
            return normalize_ai_text(text)

        response = self._post_workers(
            options.model,
            self._workers_payload(prepared, options, stream=False, prompt_fallback=False),
            stream=False,
        )
        if response.status_code == 400:
            response = self._post_workers(
                options.model,
                self._workers_payload(prepared, options, stream=False, prompt_fallback=True),
                stream=False,
            )
        payload = self._read_json(response)
        text = _extract_workers_text(payload)
        if not text:
            raise AiClientError("Cloudflare Workers AI returned an empty response")
        return normalize_ai_text(text)

    def stream_chat(
        self,
        messages: Sequence[ChatMessagePayload],
        options: AiRequestOptions,
        cancel_event: Event | None = None,
    ) -> Iterator[str]:
        prepared = self._prepare_messages(messages, options.system_prompt)
        protocol = self._normalize_protocol(options.protocol)
        if protocol == OPENAI_COMPATIBLE:
            yield from self._stream_openai(prepared, options, cancel_event)
            return
        yield from self._stream_workers(prepared, options, cancel_event)

    def run_task(self, request: AiTaskRequest) -> AiTaskResult:
        task_def = TASKS_BY_KEY.get(request.task_key)
        if task_def is None:
            raise AiClientError(f"Unsupported task: {request.task_key}")
        self._normalize_task_protocol(request.protocol, request.task_key)
        payload = self._build_task_payload(request)
        response = self._post_workers(request.model, payload, stream=False)
        if (
            not response.ok
            and request.task_key in {IMAGE_TO_TEXT, IMAGE_CLASSIFICATION}
            and _expects_string_image_payload(response)
        ):
            # Some models accept only string-binary payloads for `image`.
            # Retry with the legacy data-uri shape when schema validation says so.
            retry_payload = dict(payload)
            retry_payload["image"] = _file_data_uri(request.file_path)
            response = self._post_workers(request.model, retry_payload, stream=False)
        if not response.ok:
            _raise_http_error(response)
        return self._parse_task_response(request.task_key, response)

    def _stream_openai(
        self,
        messages: list[dict[str, str]],
        options: AiRequestOptions,
        cancel_event: Event | None,
    ) -> Iterator[str]:
        response = requests.post(
            f"{CF_API_BASE}/accounts/{self._account_id}/ai/v1/chat/completions",
            headers=self._auth_headers(),
            json={
                "model": options.model,
                "messages": messages,
                "temperature": float(options.temperature),
                "max_tokens": int(options.max_tokens),
                "stream": True,
            },
            timeout=self._timeout,
            stream=True,
        )
        if not response.ok:
            _raise_http_error(response)
        response.encoding = "utf-8"

        for payload in _iter_sse_payloads(response, cancel_event):
            text = _extract_openai_stream_text(payload)
            if text:
                yield normalize_ai_text(text)

    def _stream_workers(
        self,
        messages: list[dict[str, str]],
        options: AiRequestOptions,
        cancel_event: Event | None,
    ) -> Iterator[str]:
        response = self._post_workers(
            options.model,
            self._workers_payload(messages, options, stream=True, prompt_fallback=False),
            stream=True,
        )
        if not response.ok and response.status_code == 400:
            response.close()
            response = self._post_workers(
                options.model,
                self._workers_payload(messages, options, stream=True, prompt_fallback=True),
                stream=True,
            )
        if not response.ok:
            _raise_http_error(response)
        response.encoding = "utf-8"

        for payload in _iter_sse_payloads(response, cancel_event):
            text = _extract_workers_stream_text(payload)
            if text:
                yield normalize_ai_text(text)

    def _parse_task_response(self, task_key: str, response: requests.Response) -> AiTaskResult:
        output_kind = get_task_definition(task_key).output_kind
        content_type = _response_content_type(response)
        if content_type.startswith("image/"):
            return AiTaskResult(
                task_key=task_key,
                output_kind=output_kind,
                image_bytes=getattr(response, "content", b""),
                image_mime_type=content_type,
            )
        if content_type.startswith("audio/"):
            return AiTaskResult(
                task_key=task_key,
                output_kind=output_kind,
                audio_bytes=getattr(response, "content", b""),
                audio_mime_type=content_type,
            )

        payload = self._read_json(response)
        result = payload.get("result", payload)
        text = _extract_workers_text(payload)
        if task_key == TEXT_EMBEDDINGS:
            embedding = _extract_embedding_payload(result)
            return AiTaskResult(
                task_key=task_key,
                output_kind=output_kind,
                embedding=embedding,
                json_data=result,
                text=json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, (dict, list)) else "",
            )
        if task_key in {TEXT_CLASSIFICATION, IMAGE_CLASSIFICATION}:
            classifications = _extract_classifications(result)
            return AiTaskResult(
                task_key=task_key,
                output_kind=output_kind,
                classifications=classifications,
                json_data=result,
                text=_classifications_to_text(classifications),
            )
        if task_key == TEXT_TO_IMAGE:
            image_blob = _extract_media_blob(result, "image")
            if image_blob is not None:
                return AiTaskResult(
                    task_key=task_key,
                    output_kind=output_kind,
                    image_bytes=image_blob[0],
                    image_mime_type=image_blob[1],
                    json_data=result,
                )
        if task_key == TEXT_TO_SPEECH:
            audio_blob = _extract_media_blob(result, "audio")
            if audio_blob is not None:
                return AiTaskResult(
                    task_key=task_key,
                    output_kind=output_kind,
                    audio_bytes=audio_blob[0],
                    audio_mime_type=audio_blob[1],
                    json_data=result,
                )

        final_text = text or _extract_text_fields(result)
        return AiTaskResult(
            task_key=task_key,
            output_kind=output_kind,
            text=normalize_ai_text(final_text) if final_text else "",
            json_data=result,
        )

    def _build_task_payload(self, request: AiTaskRequest) -> dict[str, Any]:
        task_key = request.task_key
        advanced = dict(request.advanced_params)
        payload: dict[str, Any]
        if task_key == TEXT_EMBEDDINGS:
            if not request.texts:
                raise AiClientError("Embeddings input is empty")
            payload = {"text": request.texts if len(request.texts) > 1 else request.texts[0]}
        elif task_key == TEXT_CLASSIFICATION:
            payload = {"text": _require_text(request.prompt, "Text classification input is empty")}
        elif task_key == TEXT_TO_IMAGE:
            payload = {"prompt": _require_text(request.prompt, "Text-to-image prompt is empty")}
        elif task_key == TEXT_TO_SPEECH:
            payload = {"text": _require_text(request.prompt, "Text-to-speech input is empty")}
        elif task_key == AUTOMATIC_SPEECH_RECOGNITION:
            payload = {"audio": _file_data_uri(request.file_path)}
        elif task_key == IMAGE_TO_TEXT:
            payload = {
                "image": _file_uint8_array(request.file_path),
                "prompt": _require_text(request.prompt, "Image-to-text instruction is empty"),
            }
        elif task_key == IMAGE_CLASSIFICATION:
            payload = {"image": _file_uint8_array(request.file_path)}
        elif task_key == TRANSLATION:
            payload = {
                "text": _require_text(request.prompt, "Translation input is empty"),
                "source_lang": str(request.source_language).strip() or "auto",
                "target_lang": _require_text(request.target_language, "Target language is required"),
            }
        elif task_key == SUMMARIZATION:
            payload = {"input_text": _require_text(request.prompt, "Summarization input is empty")}
        elif task_key == TEXT_GENERATION:
            messages = self._prepare_messages([ChatMessagePayload(role="user", content=request.prompt)], request.system_prompt)
            payload = self._workers_payload(
                messages,
                AiRequestOptions(
                    protocol=WORKERS_AI_RUN,
                    model=request.model,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    system_prompt=request.system_prompt,
                ),
                stream=False,
                prompt_fallback=False,
            )
        else:
            raise AiClientError(f"Unsupported task: {task_key}")

        merged = dict(advanced)
        merged.update(payload)
        if task_key in {TEXT_GENERATION, TEXT_TO_IMAGE, TEXT_TO_SPEECH, IMAGE_TO_TEXT, SUMMARIZATION, TEXT_CLASSIFICATION}:
            merged.setdefault("max_tokens", int(request.max_tokens))
        if task_key in {TEXT_GENERATION, TEXT_TO_IMAGE}:
            merged.setdefault("temperature", float(request.temperature))
        return merged

    def _workers_endpoint(self, model: str) -> str:
        encoded_model = quote(model.strip(), safe="/")
        return f"{CF_API_BASE}/accounts/{self._account_id}/ai/run/{encoded_model}"

    def _workers_endpoint_raw(self, model: str) -> str:
        return f"{CF_API_BASE}/accounts/{self._account_id}/ai/run/{model.strip()}"

    def _workers_endpoints(self, model: str) -> tuple[str, ...]:
        primary = self._workers_endpoint(model)
        fallback = self._workers_endpoint_raw(model)
        if fallback == primary:
            return (primary,)
        return (primary, fallback)

    def _post_workers(self, model: str, payload: dict[str, Any], stream: bool) -> requests.Response:
        last_response: requests.Response | None = None
        for endpoint in self._workers_endpoints(model):
            response = requests.post(
                endpoint,
                headers=self._auth_headers(),
                json=payload,
                timeout=self._timeout,
                stream=stream,
            )
            last_response = response
            if _is_no_route_error(response):
                response.close()
                continue
            return response
        assert last_response is not None
        return last_response

    @staticmethod
    def _normalize_protocol(protocol: str) -> str:
        if protocol == WORKERS_AI_RUN:
            return WORKERS_AI_RUN
        return OPENAI_COMPATIBLE

    def _normalize_task_protocol(self, protocol: str, task_key: str) -> str:
        normalized = self._normalize_protocol(protocol)
        if task_key != TEXT_GENERATION and normalized != WORKERS_AI_RUN:
            raise AiClientError("OpenAI compatible protocol is only available for Text Generation")
        return normalized

    @staticmethod
    def _workers_payload(
        messages: list[dict[str, str]],
        options: AiRequestOptions,
        stream: bool,
        prompt_fallback: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stream": bool(stream),
            "temperature": float(options.temperature),
            "max_tokens": int(options.max_tokens),
        }
        if prompt_fallback:
            payload["prompt"] = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        else:
            payload["messages"] = messages
        return payload

    @staticmethod
    def _prepare_messages(
        messages: Sequence[ChatMessagePayload],
        system_prompt: str,
    ) -> list[dict[str, str]]:
        prepared: list[dict[str, str]] = []
        prompt = system_prompt.strip()
        if prompt:
            prepared.append({"role": "system", "content": prompt})

        for message in messages:
            role = str(message.role).strip().lower()
            content = str(message.content).strip()
            if role not in {"system", "user", "assistant"} or not content:
                continue
            prepared.append({"role": role, "content": content})

        if not prepared:
            raise AiClientError("Chat payload is empty")
        return prepared

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _read_json(self, response: requests.Response) -> dict[str, Any]:
        response.encoding = "utf-8"
        if not response.ok:
            _raise_http_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AiClientError("Cloudflare API returned invalid JSON", response.status_code) from exc
        if isinstance(payload, dict) and payload.get("success") is False:
            errors = payload.get("errors", [])
            message = "Cloudflare API request failed"
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, dict):
                    message = str(first.get("message", message))
            raise AiClientError(message, response.status_code)
        if not isinstance(payload, dict):
            raise AiClientError("Cloudflare API returned unsupported payload", response.status_code)
        return payload


def _iter_sse_payloads(response: requests.Response, cancel_event: Event | None) -> Iterator[dict[str, Any]]:
    for raw_line in response.iter_lines(decode_unicode=False):
        if cancel_event is not None and cancel_event.is_set():
            break
        if not raw_line:
            continue
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace").strip()
        else:
            line = str(raw_line).strip()
        if not line.startswith("data:"):
            continue
        data_raw = line[5:].strip()
        if data_raw == "[DONE]":
            break
        if not data_raw:
            continue
        try:
            payload = json.loads(data_raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield payload


def _extract_openai_stream_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta", {})
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content", "")
    return _content_to_text(content)


def _extract_openai_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message", {})
    if not isinstance(message, dict):
        return ""
    return _content_to_text(message.get("content", ""))


def _extract_workers_stream_text(payload: dict[str, Any]) -> str:
    openai_style = _extract_openai_stream_text(payload)
    if openai_style:
        return openai_style

    result = payload.get("result", payload)
    if not isinstance(result, dict):
        return ""
    for key in ("response", "text", "delta"):
        if key in result:
            return _content_to_text(result.get(key, ""))
    return ""


def _extract_workers_text(payload: dict[str, Any]) -> str:
    openai_style = _extract_openai_text(payload)
    if openai_style:
        return openai_style

    result = payload.get("result", payload)
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return ""
    for key in ("response", "text", "translated_text", "summary", "transcript", "description"):
        if key in result:
            return _content_to_text(result.get(key, ""))
    return ""


def _extract_text_fields(result: Any) -> str:
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return ""
    for key in (
        "response",
        "text",
        "translated_text",
        "translation",
        "summary",
        "transcript",
        "transcription",
        "description",
        "caption",
        "result",
    ):
        if key in result:
            return _content_to_text(result.get(key, ""))
    return ""


def _extract_embedding_payload(result: Any) -> list[float] | list[list[float]] | None:
    if isinstance(result, list):
        if all(isinstance(item, (int, float)) for item in result):
            return [float(item) for item in result]
        if all(isinstance(item, list) for item in result):
            output: list[list[float]] = []
            for item in result:
                if not isinstance(item, list):
                    continue
                output.append([float(value) for value in item if isinstance(value, (int, float))])
            return output
    if isinstance(result, dict):
        for key in ("data", "embeddings", "embedding"):
            value = result.get(key)
            extracted = _extract_embedding_payload(value)
            if extracted is not None:
                return extracted
    return None


def _extract_classifications(result: Any) -> list[dict[str, Any]]:
    rows = result if isinstance(result, list) else result.get("labels", []) if isinstance(result, dict) else []
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label", row.get("name", ""))).strip()
        if not label:
            continue
        score = row.get("score", row.get("confidence", 0.0))
        try:
            normalized.append({"label": label, "score": float(score)})
        except (TypeError, ValueError):
            normalized.append({"label": label, "score": 0.0})
    normalized.sort(key=lambda item: item["score"], reverse=True)
    return normalized


def _classifications_to_text(classifications: list[dict[str, Any]]) -> str:
    if not classifications:
        return ""
    return "\n".join(f"{row['label']}: {row['score']:.4f}" for row in classifications)


def _extract_media_blob(result: Any, key: str) -> tuple[bytes, str] | None:
    if isinstance(result, dict):
        value = result.get(key)
        if isinstance(value, str):
            decoded = _decode_maybe_base64(value)
            if decoded is not None:
                return decoded
    if isinstance(result, str):
        decoded = _decode_maybe_base64(result)
        if decoded is not None:
            return decoded
    return None


def _decode_maybe_base64(value: str) -> tuple[bytes, str] | None:
    text = str(value).strip()
    if not text:
        return None
    mime_type = "application/octet-stream"
    encoded = text
    if text.startswith("data:") and "," in text:
        meta, encoded = text.split(",", 1)
        if ";" in meta:
            mime_type = meta[5:].split(";", 1)[0] or mime_type
    try:
        return base64.b64decode(encoded, validate=False), mime_type
    except (ValueError, base64.binascii.Error):
        return None


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)
    return ""


def _require_text(text: str, error_message: str) -> str:
    value = str(text).strip()
    if not value:
        raise AiClientError(error_message)
    return value


def _file_data_uri(path: str) -> str:
    raw_path = str(path).strip()
    if not raw_path:
        raise AiClientError("File path is required")
    file_path = Path(raw_path)
    if not file_path.exists() or not file_path.is_file():
        raise AiClientError(f"File not found: {file_path}")
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if not mime_type:
        mime_type = "application/octet-stream"
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _file_uint8_array(path: str) -> list[int]:
    raw_path = str(path).strip()
    if not raw_path:
        raise AiClientError("File path is required")
    file_path = Path(raw_path)
    if not file_path.exists() or not file_path.is_file():
        raise AiClientError(f"File not found: {file_path}")
    return list(file_path.read_bytes())


def _response_content_type(response: requests.Response) -> str:
    headers = getattr(response, "headers", {}) or {}
    if not isinstance(headers, Mapping) and not hasattr(headers, "get"):
        return ""
    raw = headers.get("Content-Type", headers.get("content-type", ""))  # type: ignore[union-attr]
    return str(raw).split(";", 1)[0].strip().lower()


def _expects_string_image_payload(response: requests.Response) -> bool:
    if getattr(response, "status_code", 0) != 400:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    errors = payload.get("errors", [])
    if not isinstance(errors, list):
        return False
    for row in errors:
        if not isinstance(row, dict):
            continue
        message = str(row.get("message", "")).lower()
        if "/image" in message and "array" in message and "string" in message:
            return True
    return False


def _is_no_route_error(response: requests.Response) -> bool:
    if getattr(response, "status_code", 0) != 400:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    errors = payload.get("errors", [])
    if not isinstance(errors, list):
        return False
    for row in errors:
        if not isinstance(row, dict):
            continue
        message = str(row.get("message", ""))
        if "No route for that URI" in message:
            return True
    return False


def _raise_http_error(response: requests.Response) -> None:
    message = f"Cloudflare API error ({response.status_code})"
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        errors = payload.get("errors", [])
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                message = str(first.get("message", message))
        elif "result" in payload and not payload.get("success", True):
            message = str(payload.get("messages", message))
    raise AiClientError(message, response.status_code)
