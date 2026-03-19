from __future__ import annotations

from threading import Event

from lolilend.ai_client import (
    AiModelInfo,
    AiRequestOptions,
    AiTaskRequest,
    AiTaskResult,
    ChatMessagePayload,
    CloudflareAiClient,
)


class AiModelCatalogService:
    def __init__(self, client: CloudflareAiClient) -> None:
        self._client = client
        self._cache: list[AiModelInfo] | None = None

    def get_models(
        self,
        force_refresh: bool = False,
        task_key: str | None = None,
        popular_only: bool = False,
    ) -> list[AiModelInfo]:
        if self._cache is None or force_refresh:
            self._cache = self._client.fetch_models()
        models = list(self._cache)
        if task_key is not None:
            models = [model for model in models if model.task_key == task_key]
        if popular_only:
            models = [model for model in models if model.is_popular]
        return models


class AiSchemaService:
    def __init__(self, client: CloudflareAiClient) -> None:
        self._client = client
        self._cache: dict[str, dict] = {}

    def get_schema(self, model_name: str, force_refresh: bool = False) -> dict:
        if not force_refresh and model_name in self._cache:
            return dict(self._cache[model_name])
        schema = self._client.fetch_model_schema(model_name, force_refresh=force_refresh)
        self._cache[model_name] = dict(schema)
        return dict(schema)


class AiChatService:
    def __init__(self, client: CloudflareAiClient) -> None:
        self._client = client

    def stream_reply(
        self,
        messages: list[ChatMessagePayload],
        options: AiRequestOptions,
        cancel_event: Event | None = None,
    ):
        return self._client.stream_chat(messages, options, cancel_event=cancel_event)

    def send_reply(self, messages: list[ChatMessagePayload], options: AiRequestOptions) -> str:
        return self._client.send_chat(messages, options)


class AiTaskService:
    def __init__(self, client: CloudflareAiClient) -> None:
        self._client = client

    def run(self, request: AiTaskRequest) -> AiTaskResult:
        return self._client.run_task(request)
