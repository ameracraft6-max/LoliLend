from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TEXT_GENERATION = "text_generation"
TEXT_EMBEDDINGS = "text_embeddings"
TEXT_CLASSIFICATION = "text_classification"
TEXT_TO_IMAGE = "text_to_image"
TEXT_TO_SPEECH = "text_to_speech"
AUTOMATIC_SPEECH_RECOGNITION = "automatic_speech_recognition"
IMAGE_TO_TEXT = "image_to_text"
IMAGE_CLASSIFICATION = "image_classification"
TRANSLATION = "translation"
SUMMARIZATION = "summarization"


@dataclass(frozen=True, slots=True)
class AiTaskDefinition:
    key: str
    label: str
    cloudflare_names: tuple[str, ...]
    output_kind: str
    supports_system_prompt: bool = False
    supports_file_input: bool = False
    supports_streaming: bool = False
    short_example_label: str = "Пример"


@dataclass(frozen=True, slots=True)
class AiTaskExample:
    title: str
    body: str
    apply_text: str


TASK_DEFINITIONS: tuple[AiTaskDefinition, ...] = (
    AiTaskDefinition(
        key=TEXT_GENERATION,
        label="Генерация текста",
        cloudflare_names=("text generation",),
        output_kind="text",
        supports_system_prompt=True,
        supports_streaming=True,
        short_example_label="Системный промт",
    ),
    AiTaskDefinition(
        key=TEXT_EMBEDDINGS,
        label="Текстовые эмбеддинги",
        cloudflare_names=("text embeddings",),
        output_kind="embedding",
        short_example_label="Пример ввода",
    ),
    AiTaskDefinition(
        key=TEXT_CLASSIFICATION,
        label="Классификация текста",
        cloudflare_names=("text classification",),
        output_kind="classification",
        short_example_label="Пример ввода",
    ),
    AiTaskDefinition(
        key=TEXT_TO_IMAGE,
        label="Текст в изображение",
        cloudflare_names=("text-to-image",),
        output_kind="image",
        short_example_label="Пример промта",
    ),
    AiTaskDefinition(
        key=TEXT_TO_SPEECH,
        label="Текст в речь",
        cloudflare_names=("text-to-speech",),
        output_kind="audio",
        short_example_label="Пример ввода",
    ),
    AiTaskDefinition(
        key=AUTOMATIC_SPEECH_RECOGNITION,
        label="Распознавание речи",
        cloudflare_names=("automatic speech recognition",),
        output_kind="text",
        supports_file_input=True,
        short_example_label="Пример ввода",
    ),
    AiTaskDefinition(
        key=IMAGE_TO_TEXT,
        label="Изображение в текст",
        cloudflare_names=("image-to-text",),
        output_kind="text",
        supports_file_input=True,
        short_example_label="Пример инструкции",
    ),
    AiTaskDefinition(
        key=IMAGE_CLASSIFICATION,
        label="Классификация изображений",
        cloudflare_names=("image classification",),
        output_kind="classification",
        supports_file_input=True,
        short_example_label="Пример ввода",
    ),
    AiTaskDefinition(
        key=TRANSLATION,
        label="Перевод",
        cloudflare_names=("translation",),
        output_kind="text",
        short_example_label="Пример ввода",
    ),
    AiTaskDefinition(
        key=SUMMARIZATION,
        label="Суммаризация",
        cloudflare_names=("summarization",),
        output_kind="text",
        short_example_label="Пример ввода",
    ),
)


TASKS_BY_KEY = {task.key: task for task in TASK_DEFINITIONS}
TASKS_BY_NAME = {
    alias: task
    for task in TASK_DEFINITIONS
    for alias in task.cloudflare_names
}


PINNED_MODELS_BY_TASK: dict[str, tuple[str, ...]] = {
    TEXT_GENERATION: (
        "@cf/openai/gpt-oss-20b",
        "@cf/meta/llama-3.2-3b-instruct",
        "@cf/meta/llama-3.2-11b-vision-instruct",
    ),
    TEXT_EMBEDDINGS: (
        "@cf/qwen/qwen3-embedding-0.6b",
        "@cf/baai/bge-base-en-v1.5",
        "@cf/google/embeddinggemma-300m",
    ),
    TEXT_CLASSIFICATION: (
        "@cf/huggingface/distilbert-sst-2-int8",
        "@cf/baai/bge-reranker-base",
    ),
    TEXT_TO_IMAGE: (
        "@cf/black-forest-labs/flux-1-schnell",
        "@cf/black-forest-labs/flux-2-klein-4b",
        "@cf/leonardo/phoenix-1.0",
    ),
    TEXT_TO_SPEECH: (
        "@cf/myshell-ai/melotts",
        "@cf/deepgram/aura-2-en",
    ),
    AUTOMATIC_SPEECH_RECOGNITION: (
        "@cf/openai/whisper-large-v3-turbo",
        "@cf/openai/whisper",
    ),
    IMAGE_TO_TEXT: (
        "@cf/llava-hf/llava-1.5-7b-hf",
        "@cf/unum/uform-gen2-qwen-500m",
    ),
    IMAGE_CLASSIFICATION: (
        "@cf/microsoft/resnet-50",
    ),
    TRANSLATION: (
        "@cf/meta/m2m100-1.2b",
    ),
    SUMMARIZATION: (
        "@cf/facebook/bart-large-cnn",
    ),
}


TASK_EXAMPLES: dict[str, AiTaskExample] = {
    TEXT_GENERATION: AiTaskExample(
        title="Подробный пример системного промта",
        apply_text=(
            "Ты AI-ассистент внутри приложения LoliLend.\n"
            "\n"
            "Что пользователь может менять:\n"
            "- цель ответа;\n"
            "- стиль и тон;\n"
            "- формат результата;\n"
            "- ограничения по длине.\n"
            "\n"
            "Что лучше оставить как структуру:\n"
            "1. Роль ассистента.\n"
            "2. Правила качества.\n"
            "3. Формат ответа.\n"
            "4. Ограничения.\n"
            "\n"
            "Базовый шаблон:\n"
            "Ты помогаешь пользователю приложения LoliLend.\n"
            "Отвечай кратко, по делу и на русском языке.\n"
            "Если данных недостаточно, сначала укажи чего не хватает.\n"
            "Если пользователь просит инструкцию, давай шаги списком.\n"
            "Если пользователь просит сравнение, используй таблицу или короткий список.\n"
            "Не придумывай факты и явно отмечай предположения.\n"
        ),
        body=(
            "Редактируйте цель, стиль и формат ответа.\n"
            "Сохраняйте роль ассистента и базовые правила качества, чтобы модель отвечала стабильно."
        ),
    ),
    IMAGE_TO_TEXT: AiTaskExample(
        title="Подробный пример инструкции",
        apply_text=(
            "Опиши изображение на русском языке.\n"
            "\n"
            "Что можно менять:\n"
            "- язык ответа;\n"
            "- уровень детализации;\n"
            "- просить OCR, описание сцены, поиск объектов или стиль.\n"
            "\n"
            "Что лучше оставить:\n"
            "- просьбу сначала перечислить ключевые объекты;\n"
            "- просьбу явно отмечать неуверенность.\n"
            "\n"
            "Шаблон:\n"
            "1. Сначала перечисли основные объекты на изображении.\n"
            "2. Затем кратко опиши сцену целиком.\n"
            "3. Если есть текст на изображении, перепиши его отдельно.\n"
            "4. Если что-то не видно точно, напиши это явно.\n"
        ),
        body="Используйте инструкцию вместо системного промта: модель получает изображение и текстовый запрос.",
    ),
    SUMMARIZATION: AiTaskExample(
        title="Подробный пример для суммаризации",
        apply_text=(
            "Сделай краткое резюме текста на русском языке.\n"
            "Сохрани факты и цифры.\n"
            "Убери повторы и воду.\n"
            "В конце дай 3 ключевых вывода отдельным списком.\n"
        ),
        body="Меняйте язык, длину резюме и формат итогового блока, но оставляйте требование сохранять факты.",
    ),
    TRANSLATION: AiTaskExample(
        title="Подробный пример для перевода",
        apply_text=(
            "Переведи текст аккуратно и естественно.\n"
            "Сохрани имена собственные, числа, ссылки и форматирование.\n"
            "Если встречаются термины, переведи их последовательно по всему тексту.\n"
            "Не добавляй комментарии от себя.\n"
        ),
        body="Меняйте стиль перевода и язык, но оставляйте правило не добавлять лишние пояснения.",
    ),
    TEXT_TO_IMAGE: AiTaskExample(
        title="Подробный пример промта для изображения",
        apply_text=(
            "Сцена: неоновый киберпанк-город ночью после дождя.\n"
            "Главный объект: девушка-механик у ремонтного стола.\n"
            "Композиция: средний план, камера на уровне глаз.\n"
            "Свет: холодный синий плюс теплые оранжевые акценты.\n"
            "Стиль: cinematic, high detail, sharp focus.\n"
            "Избегать: blur, extra fingers, low quality, distorted face.\n"
        ),
        body="Пользователь может менять сцену, стиль, свет и ограничения. Структура промта помогает получить более стабильный результат.",
    ),
    TEXT_EMBEDDINGS: AiTaskExample(
        title="Пример пакетного ввода",
        apply_text="Новый ноутбук для дизайна\nИгровая мышь с низкой задержкой\nБюджетный монитор 144 Гц",
        body="Каждая строка станет отдельным текстом для пакетного режима эмбеддингов.",
    ),
    TEXT_CLASSIFICATION: AiTaskExample(
        title="Пример запроса",
        apply_text="Этот релиз наконец-то работает стабильно и без лагов.",
        body="Подходит для тональности, intent или модели-ранкера, если выбрана соответствующая модель классификации.",
    ),
    TEXT_TO_SPEECH: AiTaskExample(
        title="Пример текста для озвучки",
        apply_text="Привет. Это демонстрация синтеза речи внутри приложения LoliLend.",
        body="Меняйте язык, длину и стиль фразы. Для некоторых моделей дополнительные параметры доступны в расширенных параметрах.",
    ),
    AUTOMATIC_SPEECH_RECOGNITION: AiTaskExample(
        title="Пример настройки распознавания",
        apply_text="Загрузите аудиофайл и при необходимости добавьте в расширенные параметры language, task или initial_prompt.",
        body="Системный промт здесь не используется: модель получает аудио и опциональные параметры распознавания.",
    ),
    IMAGE_CLASSIFICATION: AiTaskExample(
        title="Пример классификации изображения",
        apply_text="Загрузите изображение и запустите классификацию. Результат покажет метки и confidence score.",
        body="Подходит для быстрого top-N распознавания категорий на изображении.",
    ),
}


def normalize_task_name(task_name: str) -> AiTaskDefinition | None:
    normalized = str(task_name).strip().lower()
    if not normalized:
        return None
    return TASKS_BY_NAME.get(normalized)


def get_task_definition(task_key: str) -> AiTaskDefinition:
    return TASKS_BY_KEY[task_key]


def supported_task_keys() -> tuple[str, ...]:
    return tuple(task.key for task in TASK_DEFINITIONS)


def is_popular_model(task_key: str, model_name: str) -> bool:
    return str(model_name).strip() in PINNED_MODELS_BY_TASK.get(task_key, ())


def task_example(task_key: str) -> AiTaskExample:
    return TASK_EXAMPLES[task_key]


def schema_defaults(schema: dict[str, Any], exclude_keys: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude_keys or set()
    return _defaults_from_schema(schema, exclude)


def _defaults_from_schema(schema: Any, exclude_keys: set[str]) -> Any:
    if not isinstance(schema, dict):
        return {}
    if "default" in schema:
        return schema["default"]

    schema_type = schema.get("type")
    if schema_type == "object":
        result: dict[str, Any] = {}
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, value in properties.items():
                key_name = str(key)
                if key_name in exclude_keys:
                    continue
                nested = _defaults_from_schema(value, exclude_keys)
                if nested not in ({}, [], None):
                    result[key_name] = nested
        return result
    if schema_type == "array":
        items = schema.get("items", {})
        default_item = _defaults_from_schema(items, exclude_keys)
        if default_item in ({}, None):
            return []
        return [default_item]
    if "oneOf" in schema and isinstance(schema["oneOf"], list):
        for variant in schema["oneOf"]:
            defaults = _defaults_from_schema(variant, exclude_keys)
            if defaults not in ({}, [], None):
                return defaults
        return {}
    return {}
