from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import json
import mimetypes
import os
from pathlib import Path
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from lolilend.ai_client import (
    AiModelInfo,
    AiRequestOptions,
    AiTaskRequest,
    AiTaskResult,
    ChatMessagePayload,
    CloudflareAiClient,
    OPENAI_COMPATIBLE,
    WORKERS_AI_RUN,
)
from lolilend.ai_history import AiHistoryStore, AiTaskRun, ChatMessage
from lolilend.ai_metadata import (
    TASK_DEFINITIONS,
    TEXT_EMBEDDINGS,
    TEXT_GENERATION,
    TEXT_TO_IMAGE,
    TEXT_TO_SPEECH,
    TRANSLATION,
    get_task_definition,
    schema_defaults,
    supported_task_keys,
    task_example,
)
from lolilend.ai_security import BootstrapTokenProvider, CF_ACCOUNT_ID, WindowsCredentialStore
from lolilend.ai_services import AiChatService, AiModelCatalogService, AiSchemaService, AiTaskService
from lolilend.general_settings import GeneralSettingsStore
from lolilend.ui_state import decode_qbytearray, encode_qbytearray

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:  # pragma: no cover
    QAudioOutput = None
    QMediaPlayer = None


@dataclass(slots=True)
class _ActiveAssistantView:
    message_id: int
    label: QLabel
    full_text: str = ""


class _StreamSignals(QObject):
    chunk = Signal(str)
    done = Signal(str)
    error = Signal(str)
    finished = Signal()


class _ModelsSignals(QObject):
    loaded = Signal(object)
    error = Signal(str)
    finished = Signal()


class _SchemaSignals(QObject):
    loaded = Signal(object)
    error = Signal(str)


class _TaskSignals(QObject):
    done = Signal(object)
    error = Signal(str)
    finished = Signal()


class _TextGenerationPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._message_bubbles: list[QFrame] = []
        self._active_assistant: _ActiveAssistantView | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.example_title = QLabel("")
        self.example_title.setProperty("role", "ref_section")
        self.example_title.setContentsMargins(10, 8, 10, 0)
        layout.addWidget(self.example_title)

        self.example_body = QLabel("")
        self.example_body.setWordWrap(True)
        self.example_body.setContentsMargins(10, 2, 10, 0)
        layout.addWidget(self.example_body)

        self.apply_example_button = QPushButton("Подставить пример")
        apply_row = QHBoxLayout()
        apply_row.setContentsMargins(10, 4, 10, 0)
        apply_row.addWidget(self.apply_example_button, 0, Qt.AlignmentFlag.AlignLeft)
        apply_row.addStretch(1)
        layout.addLayout(apply_row)

        # ── Collapsible system prompt ────────────────────────────
        self._sysprompt_toggle = QToolButton()
        self._sysprompt_toggle.setText("▸  Системный промт")
        self._sysprompt_toggle.setObjectName("AiSysPromptToggle")
        self._sysprompt_toggle.setCheckable(True)
        self._sysprompt_toggle.setChecked(False)
        self._sysprompt_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        layout.addWidget(self._sysprompt_toggle)

        self._sysprompt_body = QWidget()
        self._sysprompt_body.setObjectName("AiSysPromptBody")
        sysprompt_layout = QVBoxLayout(self._sysprompt_body)
        sysprompt_layout.setContentsMargins(8, 4, 8, 4)
        sysprompt_layout.setSpacing(0)
        self.system_prompt_edit = QPlainTextEdit()
        self.system_prompt_edit.setObjectName("AiSystemPrompt")
        self.system_prompt_edit.setMinimumHeight(110)
        sysprompt_layout.addWidget(self.system_prompt_edit)
        self._sysprompt_body.setVisible(False)
        layout.addWidget(self._sysprompt_body)

        self._sysprompt_toggle.toggled.connect(self._on_sysprompt_toggled)

        # ── Messages scroll area ─────────────────────────────────
        self.messages_scroll = QScrollArea()
        self.messages_scroll.setObjectName("AiMessagesScroll")
        self.messages_scroll.setWidgetResizable(True)
        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(8, 10, 8, 10)
        self.messages_layout.setSpacing(8)
        self.messages_layout.addStretch(1)
        self.messages_scroll.setWidget(self.messages_container)
        layout.addWidget(self.messages_scroll, 1)

        # ── Composer (input + send/stop, unified frame) ──────────
        composer = QFrame()
        composer.setObjectName("AiComposer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(8, 8, 8, 8)
        composer_layout.setSpacing(6)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setObjectName("AiInput")
        self.input_edit.setMinimumHeight(80)
        self.input_edit.setMaximumHeight(200)
        self.input_edit.setPlaceholderText("Введите сообщение...")
        composer_layout.addWidget(self.input_edit)

        send_row = QHBoxLayout()
        send_row.setContentsMargins(0, 0, 0, 0)
        send_row.setSpacing(8)
        self.send_button = QPushButton("Отправить")
        self.send_button.setObjectName("AiSendButton")
        self.stop_button = QPushButton("Стоп")
        self.stop_button.setObjectName("AiStopButton")
        self.stop_button.setEnabled(False)
        send_row.addStretch(1)
        send_row.addWidget(self.stop_button)
        send_row.addWidget(self.send_button)
        composer_layout.addLayout(send_row)

        layout.addWidget(composer)

    def _on_sysprompt_toggled(self, checked: bool) -> None:
        self._sysprompt_body.setVisible(checked)
        self._sysprompt_toggle.setText("▾  Системный промт" if checked else "▸  Системный промт")

    def set_example(self, title: str, body: str) -> None:
        self.example_title.setText(title)
        self.example_body.setText(body)

    def apply_example(self, text: str) -> None:
        self.system_prompt_edit.setPlainText(text)

    def render_messages(self, messages: list[ChatMessage]) -> None:
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item is None:
                continue
            layout = item.layout()
            if layout is not None:
                while layout.count():
                    child = layout.takeAt(0)
                    widget = child.widget()
                    if widget is not None:
                        widget.deleteLater()
                layout.deleteLater()
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._message_bubbles.clear()
        self._active_assistant = None
        for message in messages:
            self.append_message(message.role, message.content)
        self.scroll_to_bottom()

    def append_message(self, role: str, content: str) -> QLabel:
        outer = QHBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bubble = QFrame()
        bubble.setObjectName("AiMessageBubbleUser" if role == "user" else "AiMessageBubbleAssistant")
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 10, 12, 10)
        bubble_layout.setSpacing(5)

        role_row = QHBoxLayout()
        role_row.setContentsMargins(0, 0, 0, 0)
        role_row.setSpacing(6)
        dot = QLabel("●")
        dot.setObjectName("AiMessageDotUser" if role == "user" else "AiMessageDotAssistant")
        role_label = QLabel("Вы" if role == "user" else "Ассистент")
        role_label.setProperty("role", "ref_section")
        role_row.addWidget(dot)
        role_row.addWidget(role_label)
        role_row.addStretch(1)
        bubble_layout.addLayout(role_row)

        text_label = QLabel(content)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble_layout.addWidget(text_label)

        if role == "user":
            outer.addStretch(1)
            outer.addWidget(bubble, 0, Qt.AlignmentFlag.AlignRight)
        else:
            outer.addWidget(bubble, 0, Qt.AlignmentFlag.AlignLeft)
            outer.addStretch(1)

        self._message_bubbles.append(bubble)
        self.messages_layout.insertLayout(self.messages_layout.count() - 1, outer)
        self.refresh_bubble_widths()
        self.scroll_to_bottom()
        return text_label

    def start_assistant_response(self, message_id: int) -> None:
        label = self.append_message("assistant", "")
        self._active_assistant = _ActiveAssistantView(message_id=message_id, label=label, full_text="")
        self.stop_button.setEnabled(True)

    def append_stream_chunk(self, chunk: str) -> None:
        if self._active_assistant is None:
            return
        self._active_assistant.full_text += chunk
        self._active_assistant.label.setText(self._active_assistant.full_text)
        self.scroll_to_bottom()

    def current_stream_message_id(self) -> int | None:
        if self._active_assistant is None:
            return None
        return self._active_assistant.message_id

    def finish_stream(self, full_text: str, canceled: bool) -> str:
        if self._active_assistant is None:
            return full_text
        final_text = (full_text or self._active_assistant.full_text).strip()
        if not final_text:
            final_text = "[остановлено]" if canceled else "(пустой ответ)"
        self._active_assistant.label.setText(final_text)
        self._active_assistant = None
        self.stop_button.setEnabled(False)
        return final_text

    def set_stream_error(self, message: str) -> None:
        if self._active_assistant is not None:
            self._active_assistant.label.setText(f"[ошибка] {message}")
            self._active_assistant = None
        self.stop_button.setEnabled(False)

    def refresh_bubble_widths(self) -> None:
        viewport_width = max(320, self.messages_scroll.viewport().width())
        bubble_width = max(240, int(viewport_width * 0.78))
        for bubble in self._message_bubbles:
            bubble.setMaximumWidth(bubble_width)

    def scroll_to_bottom(self) -> None:
        bar = self.messages_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())


class _TaskRunPanel(QWidget):
    def __init__(self, task_key: str, asset_resolver: Callable[[str], Path | None]) -> None:
        super().__init__()
        self.task_key = task_key
        self.task_definition = get_task_definition(task_key)
        self._asset_resolver = asset_resolver
        self._runs_by_id: dict[int, AiTaskRun] = {}
        self._selected_output_path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.example_title = QLabel("")
        self.example_title.setProperty("role", "ref_section")
        layout.addWidget(self.example_title)

        self.example_body = QLabel("")
        self.example_body.setWordWrap(True)
        layout.addWidget(self.example_body)

        self.apply_example_button = QPushButton("Подставить пример")
        layout.addWidget(self.apply_example_button, 0, Qt.AlignmentFlag.AlignLeft)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(8)

        self.text_edit = QPlainTextEdit(form_widget)
        self.text_edit.setMinimumHeight(110)
        self.batch_edit = QPlainTextEdit(form_widget)
        self.batch_edit.setMinimumHeight(110)
        self.file_path_edit = QLineEdit(form_widget)
        self.file_path_edit.setReadOnly(True)
        self.file_browse_button = QPushButton("Обзор", form_widget)
        self.source_lang_edit = QLineEdit(form_widget)
        self.source_lang_edit.setPlaceholderText("auto")
        self.target_lang_edit = QLineEdit(form_widget)
        self.target_lang_edit.setPlaceholderText("ru")
        # Hide all optional controls first; each task branch explicitly enables
        # only the controls that are part of that task form.
        self.text_edit.hide()
        self.batch_edit.hide()
        self.file_path_edit.hide()
        self.file_browse_button.hide()
        self.source_lang_edit.hide()
        self.target_lang_edit.hide()

        file_row = QHBoxLayout()
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.setSpacing(8)
        file_row.addWidget(self.file_path_edit, 1)
        file_row.addWidget(self.file_browse_button)
        file_container = QWidget(form_widget)
        file_container.setLayout(file_row)
        file_container.hide()

        if task_key == TEXT_EMBEDDINGS:
            self.batch_edit.show()
            form_layout.addRow("Тексты (по одному на строку)", self.batch_edit)
        elif task_key == TRANSLATION:
            self.text_edit.show()
            self.source_lang_edit.show()
            self.target_lang_edit.show()
            form_layout.addRow("Текст", self.text_edit)
            form_layout.addRow("Язык источника", self.source_lang_edit)
            form_layout.addRow("Язык перевода", self.target_lang_edit)
        elif self.task_definition.supports_file_input:
            self.file_path_edit.show()
            self.file_browse_button.show()
            file_container.show()
            form_layout.addRow("Файл", file_container)
            if task_key == "image_to_text":
                self.text_edit.show()
                form_layout.addRow("Инструкция", self.text_edit)
        else:
            self.text_edit.show()
            label = "Промт" if task_key in {TEXT_TO_IMAGE, TEXT_TO_SPEECH} else "Текст"
            form_layout.addRow(label, self.text_edit)
        layout.addWidget(form_widget)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Расширенные параметры")
        self.advanced_toggle.setCheckable(True)
        layout.addWidget(self.advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.advanced_edit = QPlainTextEdit()
        self.advanced_edit.setMinimumHeight(100)
        self.advanced_edit.setVisible(False)
        layout.addWidget(self.advanced_edit)

        self.run_button = QPushButton("Запустить")
        layout.addWidget(self.run_button, 0, Qt.AlignmentFlag.AlignLeft)

        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.setChildrenCollapsible(False)
        self.history_list = QListWidget()
        self.history_list.setMinimumWidth(240)
        content_splitter.addWidget(self.history_list)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(8)

        details_layout.addWidget(QLabel("Запрос"))
        self.request_preview = QPlainTextEdit()
        self.request_preview.setReadOnly(True)
        self.request_preview.setMinimumHeight(90)
        details_layout.addWidget(self.request_preview)

        details_layout.addWidget(QLabel("Результат"))
        self.result_preview = QPlainTextEdit()
        self.result_preview.setReadOnly(True)
        self.result_preview.setMinimumHeight(140)
        details_layout.addWidget(self.result_preview)

        self.image_preview = QLabel("Нет медиа")
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setMinimumHeight(220)
        self.image_preview.setFrameShape(QFrame.Shape.StyledPanel)
        details_layout.addWidget(self.image_preview)

        media_row = QHBoxLayout()
        media_row.setContentsMargins(0, 0, 0, 0)
        media_row.setSpacing(8)
        self.open_asset_button = QPushButton("Открыть")
        self.save_asset_button = QPushButton("Сохранить как")
        self.play_asset_button = QPushButton("Воспроизвести")
        media_row.addWidget(self.open_asset_button)
        media_row.addWidget(self.save_asset_button)
        media_row.addWidget(self.play_asset_button)
        media_row.addStretch(1)
        details_layout.addLayout(media_row)

        content_splitter.addWidget(details)
        content_splitter.setSizes([280, 760])
        layout.addWidget(content_splitter, 1)

        self.advanced_toggle.toggled.connect(self.advanced_edit.setVisible)
        self.history_list.currentItemChanged.connect(self._on_history_selected)
        self._sync_media_buttons(False, False, False)

    def set_example(self, title: str, body: str) -> None:
        self.example_title.setText(title)
        self.example_body.setText(body)

    def apply_example(self, text: str) -> None:
        if self.task_key == TEXT_EMBEDDINGS:
            self.batch_edit.setPlainText(text)
            return
        self.text_edit.setPlainText(text)

    def input_text(self) -> str:
        if self.task_key == TEXT_EMBEDDINGS:
            return self.batch_edit.toPlainText().strip()
        return self.text_edit.toPlainText().strip()

    def input_texts(self) -> list[str]:
        raw = self.batch_edit.toPlainText().strip()
        if not raw:
            return []
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def file_path(self) -> str:
        return self.file_path_edit.text().strip()

    def source_language(self) -> str:
        return self.source_lang_edit.text().strip()

    def target_language(self) -> str:
        return self.target_lang_edit.text().strip()

    def set_file_path(self, path: str) -> None:
        self.file_path_edit.setText(path)

    def advanced_params(self) -> dict[str, Any]:
        raw = self.advanced_edit.toPlainText().strip()
        if not raw:
            return {}
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Расширенные параметры должны быть JSON-объектом")
        return payload

    def set_advanced_defaults(self, payload: dict[str, Any]) -> None:
        self.advanced_edit.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))

    def set_runs(self, runs: list[AiTaskRun]) -> None:
        self._runs_by_id = {run.id: run for run in runs}
        self.history_list.blockSignals(True)
        self.history_list.clear()
        for run in runs:
            item = QListWidgetItem(f"{run.created_at}  {run.model_name}")
            item.setData(Qt.ItemDataRole.UserRole, run.id)
            self.history_list.addItem(item)
        self.history_list.blockSignals(False)
        if runs:
            self.history_list.setCurrentRow(0)
        else:
            self.request_preview.clear()
            self.result_preview.clear()
            self.image_preview.setText("Запусков пока нет")
            self.image_preview.setPixmap(QPixmap())
            self._selected_output_path = ""
            self._sync_media_buttons(False, False, False)

    def selected_output_path(self) -> str:
        return self._selected_output_path

    def _on_history_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        run_id = int(current.data(Qt.ItemDataRole.UserRole))
        run = self._runs_by_id.get(run_id)
        if run is None:
            return
        self.request_preview.setPlainText(run.request_text)
        self.result_preview.setPlainText(run.response_text)
        asset_path = run.output_asset_path or run.input_asset_path
        self._selected_output_path = asset_path
        resolved = self._asset_resolver(asset_path) if asset_path else None
        kind = _asset_kind(resolved) if resolved is not None else ""
        if resolved is not None and kind == "image":
            pixmap = _load_image_pixmap(resolved)
            if pixmap is not None:
                self.image_preview.setPixmap(
                    pixmap.scaled(420, 260, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
                self.image_preview.setText("")
                self._sync_media_buttons(True, True, False)
                return
        self.image_preview.setPixmap(QPixmap())
        self.image_preview.setText(resolved.name if resolved is not None else "Нет медиа")
        is_audio = kind == "audio"
        can_open = resolved is not None
        self._sync_media_buttons(can_open, can_open, is_audio)

    def _sync_media_buttons(self, can_open: bool, can_save: bool, can_play: bool) -> None:
        self.open_asset_button.setEnabled(can_open)
        self.save_asset_button.setEnabled(can_save)
        self.play_asset_button.setEnabled(can_play)


class AiTabPage(QWidget):
    def __init__(self, on_status: Callable[[str], None]) -> None:
        super().__init__()
        self._on_status = on_status
        self._settings_store = GeneralSettingsStore()
        self._history = AiHistoryStore()
        token_provider = BootstrapTokenProvider(WindowsCredentialStore())
        token = token_provider.resolve_token()
        self._client = CloudflareAiClient(CF_ACCOUNT_ID, token)
        self._catalog_service = AiModelCatalogService(self._client)
        self._schema_service = AiSchemaService(self._client)
        self._chat_service = AiChatService(self._client)
        self._task_service = AiTaskService(self._client)
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lolilend-ai")
        self._model_future: Future | None = None
        self._chat_future: Future | None = None
        self._task_future: Future | None = None
        self._schema_future: Future | None = None
        self._cancel_event: Event | None = None
        self._models: list[AiModelInfo] = []
        self._filtered_models: list[AiModelInfo] = []
        self._selected_models_by_task: dict[str, str] = {}
        self._current_session_id: int | None = None
        self._is_loading = False
        self._media_player = QMediaPlayer() if QMediaPlayer is not None else None
        self._audio_output = QAudioOutput() if QAudioOutput is not None else None
        if self._media_player is not None and self._audio_output is not None:
            self._media_player.setAudioOutput(self._audio_output)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)

        self.root_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.root_splitter.setChildrenCollapsible(False)
        root.addWidget(self.root_splitter, 1)

        left = QFrame()
        left.setObjectName("AiSessionsPanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # ── Header bar ──────────────────────────────────────────
        sessions_header = QFrame()
        sessions_header.setObjectName("AiSessionsHeader")
        header_layout = QHBoxLayout(sessions_header)
        header_layout.setContentsMargins(12, 10, 8, 10)
        header_layout.setSpacing(4)
        sessions_head = QLabel("Сессии")
        sessions_head.setProperty("role", "ref_section")
        header_layout.addWidget(sessions_head, 1)

        self.new_chat_button = QToolButton()
        self.new_chat_button.setText("+")
        self.new_chat_button.setObjectName("AiSessionActionButton")
        self.new_chat_button.setToolTip("Новая сессия")

        self.rename_chat_button = QToolButton()
        self.rename_chat_button.setText("✎")
        self.rename_chat_button.setObjectName("AiSessionActionButton")
        self.rename_chat_button.setToolTip("Переименовать")

        self.delete_chat_button = QToolButton()
        self.delete_chat_button.setText("✕")
        self.delete_chat_button.setObjectName("AiSessionActionButton")
        self.delete_chat_button.setToolTip("Удалить")

        header_layout.addWidget(self.new_chat_button)
        header_layout.addWidget(self.rename_chat_button)
        header_layout.addWidget(self.delete_chat_button)
        left_layout.addWidget(sessions_header)

        self.sessions_list = QListWidget()
        self.sessions_list.setObjectName("AiSessionsList")
        left_layout.addWidget(self.sessions_list, 1)
        self.root_splitter.addWidget(left)

        self.chat_splitter = QSplitter(Qt.Orientation.Vertical)
        self.chat_splitter.setChildrenCollapsible(False)
        self.root_splitter.addWidget(self.chat_splitter)

        controls = QFrame()
        controls.setObjectName("AiControlsPanel")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(0)

        # ── Settings toggle header ───────────────────────────────
        controls_header = QHBoxLayout()
        controls_header.setContentsMargins(0, 0, 0, 0)
        self._settings_toggle = QToolButton()
        self._settings_toggle.setText("▾  Настройки модели")
        self._settings_toggle.setObjectName("AiSettingsToggle")
        self._settings_toggle.setCheckable(True)
        self._settings_toggle.setChecked(True)
        self._settings_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        controls_header.addWidget(self._settings_toggle, 1)
        controls_layout.addLayout(controls_header)

        # ── Collapsible settings body ────────────────────────────
        self._settings_body = QWidget()
        self._settings_body.setObjectName("AiSettingsBody")
        body_layout = QVBoxLayout(self._settings_body)
        body_layout.setContentsMargins(10, 6, 10, 10)
        body_layout.setSpacing(8)

        protocol_row = QHBoxLayout()
        protocol_row.setContentsMargins(0, 0, 0, 0)
        protocol_row.setSpacing(8)
        protocol_row.addWidget(QLabel("Протокол"))
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItem("Совместимый с OpenAI", OPENAI_COMPATIBLE)
        self.protocol_combo.addItem("Workers AI /ai/run", WORKERS_AI_RUN)
        protocol_row.addWidget(self.protocol_combo, 1)
        self.refresh_models_button = QPushButton("Обновить модели")
        protocol_row.addWidget(self.refresh_models_button)
        body_layout.addLayout(protocol_row)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("Модель"))
        self.model_combo = QComboBox()
        filter_row.addWidget(self.model_combo, 1)
        self.popular_only_checkbox = QCheckBox("Только популярные")
        filter_row.addWidget(self.popular_only_checkbox)
        body_layout.addLayout(filter_row)

        tune_row = QHBoxLayout()
        tune_row.setContentsMargins(0, 0, 0, 0)
        tune_row.setSpacing(8)
        tune_row.addWidget(QLabel("Макс. токенов"))
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(64, 8192)
        self.max_tokens_spin.setSingleStep(64)
        tune_row.addWidget(self.max_tokens_spin)
        tune_row.addStretch(1)
        body_layout.addLayout(tune_row)

        self.model_hint_label = QLabel("")
        self.model_hint_label.setWordWrap(True)
        self.model_hint_label.setProperty("role", "ref_section")
        body_layout.addWidget(self.model_hint_label)

        controls_layout.addWidget(self._settings_body)
        self.chat_splitter.addWidget(controls)

        self.task_tabs = QTabWidget()
        self.task_tabs.setObjectName("AiTaskTabs")
        self.task_tabs.setDocumentMode(True)
        self.chat_panel = _TextGenerationPanel()
        self.task_panels: dict[str, _TaskRunPanel] = {}
        self.task_tabs.addTab(self.chat_panel, get_task_definition(TEXT_GENERATION).label)
        for task_def in TASK_DEFINITIONS:
            if task_def.key == TEXT_GENERATION:
                continue
            panel = _TaskRunPanel(task_def.key, self._history.resolve_asset_path)
            self.task_panels[task_def.key] = panel
            self.task_tabs.addTab(panel, task_def.label)
        self.chat_splitter.addWidget(self.task_tabs)

        footer = QFrame()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 8, 10, 8)
        footer_layout.setSpacing(8)
        self.status_label = QLabel("Готово")
        self.status_label.setProperty("role", "ref_section")
        footer_layout.addWidget(self.status_label, 1)
        self.chat_splitter.addWidget(footer)

        self.send_button = self.chat_panel.send_button
        self.stop_button = self.chat_panel.stop_button

        self._wire_events()
        self._load_state()
        self._apply_task_examples()
        if os.getenv("LOLILEND_AI_DISABLE_AUTO_FETCH", "").strip() == "1":
            self.model_hint_label.setText("Загрузка моделей отключена переменной окружения.")
        else:
            self._refresh_models(force_refresh=False)

    def on_shown(self) -> None:
        return

    def on_hidden(self) -> None:
        self._stop_streaming(show_status=False)
        self._save_splitter_state()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_streaming(show_status=False)
        self._save_splitter_state()
        self._history.close()
        self._executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.chat_panel.refresh_bubble_widths()

    def _wire_events(self) -> None:
        self.new_chat_button.clicked.connect(self._create_chat)
        self.rename_chat_button.clicked.connect(self._rename_chat)
        self.delete_chat_button.clicked.connect(self._delete_chat)
        self.sessions_list.currentItemChanged.connect(self._on_session_selected)
        self.refresh_models_button.clicked.connect(lambda: self._refresh_models(force_refresh=True))
        self.protocol_combo.currentIndexChanged.connect(self._on_options_changed)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.max_tokens_spin.valueChanged.connect(self._on_options_changed)
        self.popular_only_checkbox.toggled.connect(self._on_popular_toggled)
        self.task_tabs.currentChanged.connect(self._on_task_changed)
        self._settings_toggle.toggled.connect(self._on_settings_toggled)
        self.root_splitter.splitterMoved.connect(lambda *_: self._save_splitter_state())
        self.chat_splitter.splitterMoved.connect(lambda *_: self._save_splitter_state())

        self.chat_panel.send_button.clicked.connect(self._send_chat_message)
        self.chat_panel.stop_button.clicked.connect(lambda: self._stop_streaming(show_status=True))
        self.chat_panel.system_prompt_edit.textChanged.connect(self._on_options_changed)
        self.chat_panel.apply_example_button.clicked.connect(lambda: self.chat_panel.apply_example(task_example(TEXT_GENERATION).apply_text))

        for task_key, panel in self.task_panels.items():
            panel.run_button.clicked.connect(lambda _checked=False, key=task_key: self._run_task(key))
            if panel.task_definition.supports_file_input:
                panel.file_browse_button.clicked.connect(lambda _checked=False, key=task_key: self._browse_task_file(key))
            panel.apply_example_button.clicked.connect(lambda _checked=False, key=task_key: self._apply_task_example(key))
            panel.open_asset_button.clicked.connect(lambda _checked=False, key=task_key: self._open_panel_asset(key))
            panel.save_asset_button.clicked.connect(lambda _checked=False, key=task_key: self._save_panel_asset(key))
            panel.play_asset_button.clicked.connect(lambda _checked=False, key=task_key: self._play_panel_asset(key))

    def _on_settings_toggled(self, checked: bool) -> None:
        self._settings_body.setVisible(checked)
        self._settings_toggle.setText("▾  Настройки модели" if checked else "▸  Настройки модели")

    def _load_state(self) -> None:
        self._is_loading = True
        settings = self._settings_store.load_settings()
        self.protocol_combo.setCurrentIndex(0 if settings.ai_protocol != WORKERS_AI_RUN else 1)
        self.max_tokens_spin.setValue(max(64, min(8192, int(settings.ai_max_tokens))))
        self.popular_only_checkbox.setChecked(bool(settings.ai_popular_only))
        self.task_tabs.setCurrentIndex(self._task_tab_index(settings.ai_active_task))
        self.chat_panel.system_prompt_edit.setPlainText(settings.ai_system_prompt)
        self._reload_sessions(preferred_id=_parse_int(settings.ai_last_session_id))
        self._restore_splitter_state(settings.ai_splitter_state)
        self._is_loading = False
        self._sync_protocol_for_task()
        self._update_model_hint()

    def _apply_task_examples(self) -> None:
        chat_example = task_example(TEXT_GENERATION)
        self.chat_panel.set_example(chat_example.title, chat_example.body)
        for task_key, panel in self.task_panels.items():
            example = task_example(task_key)
            panel.set_example(example.title, example.body)

    def _task_tab_index(self, task_key: str) -> int:
        keys = list(supported_task_keys())
        return keys.index(task_key) if task_key in keys else 0

    def _panel_for_task(self, task_key: str) -> _TaskRunPanel | None:
        index = self._task_tab_index(task_key)
        if index < 0 or index >= self.task_tabs.count():
            return None

        widget = self.task_tabs.widget(index)
        if isinstance(widget, _TaskRunPanel):
            self.task_panels[task_key] = widget
            return widget

        panel = self.task_panels.get(task_key)
        if panel is None:
            return None
        try:
            panel.isEnabled()
        except RuntimeError:
            return None
        return panel

    def _active_task_key(self) -> str:
        return list(supported_task_keys())[self.task_tabs.currentIndex()]

    def _reload_sessions(self, preferred_id: int | None = None) -> None:
        sessions = self._history.list_sessions()
        if not sessions:
            sessions = [self._history.create_session("Сессия 1")]
        self.sessions_list.blockSignals(True)
        self.sessions_list.clear()
        target_row = 0
        for idx, session in enumerate(sessions):
            item = QListWidgetItem(session.title)
            item.setData(Qt.ItemDataRole.UserRole, session.id)
            self.sessions_list.addItem(item)
            if preferred_id is not None and session.id == preferred_id:
                target_row = idx
            elif preferred_id is None and self._current_session_id is not None and session.id == self._current_session_id:
                target_row = idx
        self.sessions_list.setCurrentRow(target_row)
        self.sessions_list.blockSignals(False)
        selected = self.sessions_list.item(target_row)
        if selected is not None:
            self._activate_session(int(selected.data(Qt.ItemDataRole.UserRole)))

    def _activate_session(self, session_id: int) -> None:
        self._current_session_id = session_id
        self._save_options()
        self._render_session(session_id)

    def _render_session(self, session_id: int) -> None:
        self.chat_panel.render_messages(self._history.get_messages(session_id))
        for task_key, panel in self.task_panels.items():
            panel.set_runs(self._history.list_task_runs(session_id, task_key))

    def _create_chat(self) -> None:
        title = f"Сессия {len(self._history.list_sessions()) + 1}"
        session = self._history.create_session(title)
        self._reload_sessions(preferred_id=session.id)
        self.status_label.setText("Создана новая сессия")
        self._on_status("Создана новая AI-сессия")

    def _rename_chat(self) -> None:
        item = self.sessions_list.currentItem()
        if item is None:
            return
        session_id = int(item.data(Qt.ItemDataRole.UserRole))
        title, ok = QInputDialog.getText(self, "Переименовать сессию", "Название:", text=item.text())
        if not ok:
            return
        self._history.rename_session(session_id, title.strip() or "Новая сессия")
        self._reload_sessions(preferred_id=session_id)
        self._on_status("AI-сессия переименована")

    def _delete_chat(self) -> None:
        item = self.sessions_list.currentItem()
        if item is None:
            return
        session_id = int(item.data(Qt.ItemDataRole.UserRole))
        self._history.delete_session(session_id)
        self._reload_sessions(preferred_id=None)
        self.status_label.setText("Сессия удалена")
        self._on_status("AI-сессия удалена")

    def _on_session_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        self._activate_session(int(current.data(Qt.ItemDataRole.UserRole)))

    def _refresh_models(self, force_refresh: bool) -> None:
        if self._model_future is not None and not self._model_future.done():
            return
        self.refresh_models_button.setEnabled(False)
        self.model_hint_label.setText("Загрузка моделей из Cloudflare...")
        signals = _ModelsSignals(self)
        signals.loaded.connect(self._on_models_loaded)
        signals.error.connect(self._on_models_error)
        signals.finished.connect(lambda: self.refresh_models_button.setEnabled(True))

        def worker() -> None:
            try:
                if not self._client.verify_token():
                    raise RuntimeError("Не удалось проверить токен Cloudflare")
                models = self._catalog_service.get_models(force_refresh=force_refresh)
                signals.loaded.emit(models)
            except Exception as exc:  # noqa: BLE001
                signals.error.emit(str(exc))
            finally:
                signals.finished.emit()

        self._model_future = self._executor.submit(worker)

    def _on_models_loaded(self, models: object) -> None:
        self._models = list(models) if isinstance(models, list) else []
        self._refresh_model_combo()
        self._on_status(f"Загружено моделей Cloudflare: {len(self._models)}")

    def _on_models_error(self, message: str) -> None:
        self.model_hint_label.setText(f"Не удалось загрузить модели: {message}")
        self.status_label.setText(f"Ошибка: {message}")
        self._on_status(f"Ошибка загрузки AI-моделей: {message}")

    def _refresh_model_combo(self) -> None:
        task_key = self._active_task_key()
        settings = self._settings_store.load_settings()
        preferred = self._selected_models_by_task.get(task_key) or settings.ai_model
        self._filtered_models = self._catalog_service.get_models(
            force_refresh=False,
            task_key=task_key,
            popular_only=self.popular_only_checkbox.isChecked(),
        )
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        chosen_index = 0
        for idx, model in enumerate(self._filtered_models):
            suffix = " [популярная]" if model.is_popular else ""
            self.model_combo.addItem(f"{model.name}{suffix}", model)
            if model.name == preferred:
                chosen_index = idx
        if self._filtered_models:
            self.model_combo.setCurrentIndex(chosen_index)
            self._selected_models_by_task[task_key] = self._filtered_models[chosen_index].name
        self.model_combo.blockSignals(False)
        self._sync_protocol_for_task()
        self._update_model_hint()
        self._load_schema_for_current_model()
        self._save_options()

    def _selected_model(self) -> AiModelInfo | None:
        data = self.model_combo.currentData()
        return data if isinstance(data, AiModelInfo) else None

    def _selected_model_name(self) -> str:
        model = self._selected_model()
        if model is not None:
            return model.name
        settings = self._settings_store.load_settings()
        return settings.ai_model

    def _on_model_changed(self) -> None:
        model = self._selected_model()
        if model is not None:
            self._selected_models_by_task[self._active_task_key()] = model.name
        self._update_model_hint()
        self._load_schema_for_current_model()
        self._save_options()

    def _on_popular_toggled(self) -> None:
        self._refresh_model_combo()

    def _on_task_changed(self) -> None:
        self._sync_protocol_for_task()
        self._refresh_model_combo()
        self._save_options()

    def _sync_protocol_for_task(self) -> None:
        if self._active_task_key() != TEXT_GENERATION:
            self.protocol_combo.blockSignals(True)
            self.protocol_combo.setCurrentIndex(1)
            self.protocol_combo.blockSignals(False)
            self.protocol_combo.setEnabled(False)
        else:
            self.protocol_combo.setEnabled(True)

    def _update_model_hint(self) -> None:
        task_key = self._active_task_key()
        model = self._selected_model()
        if model is None:
            self.model_hint_label.setText(f"Для задачи «{get_task_definition(task_key).label}» модели недоступны.")
            self.send_button.setEnabled(False)
            panel = self.task_panels.get(task_key)
            if panel is not None:
                panel.run_button.setEnabled(False)
            return
        protocol_label = "Workers AI /ai/run" if str(self.protocol_combo.currentData()) == WORKERS_AI_RUN else "Совместимый с OpenAI"
        note = "Популярная модель." if model.is_popular else "Модель не входит в популярный список."
        self.model_hint_label.setText(
            f"Задача: {model.task_label}. Протокол: {protocol_label}. {note}\n{model.description or 'Описание отсутствует.'}"
        )
        if task_key == TEXT_GENERATION:
            self.send_button.setEnabled(self._chat_future is None or self._chat_future.done())
        else:
            panel = self.task_panels.get(task_key)
            if panel is not None:
                panel.run_button.setEnabled(self._task_future is None or self._task_future.done())

    def _load_schema_for_current_model(self) -> None:
        model = self._selected_model()
        task_key = self._active_task_key()
        panel = self.task_panels.get(task_key)
        if model is None or panel is None:
            return
        if self._schema_future is not None and not self._schema_future.done():
            return
        signals = _SchemaSignals(self)
        signals.loaded.connect(self._on_schema_loaded)
        signals.error.connect(self._on_schema_error)

        def worker() -> None:
            try:
                schema = self._schema_service.get_schema(model.name)
                signals.loaded.emit((task_key, model.name, schema))
            except Exception as exc:  # noqa: BLE001
                signals.error.emit(str(exc))

        self._schema_future = self._executor.submit(worker)

    def _on_schema_loaded(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 3:
            return
        task_key, model_name, schema_payload = payload
        model = self._selected_model()
        if model is None or task_key != self._active_task_key() or model.name != model_name:
            return
        panel = self.task_panels.get(str(task_key))
        if panel is None:
            return
        input_schema = _extract_input_schema(schema_payload)
        panel.set_advanced_defaults(schema_defaults(input_schema, exclude_keys=_known_input_keys(str(task_key))))

    def _on_schema_error(self, message: str) -> None:
        panel = self.task_panels.get(self._active_task_key())
        if panel is not None:
            panel.set_advanced_defaults({})
        self._on_status(f"Ошибка загрузки схемы: {message}")

    def _build_chat_options(self) -> AiRequestOptions:
        return AiRequestOptions(
            protocol=str(self.protocol_combo.currentData()),
            model=self._selected_model_name(),
            max_tokens=int(self.max_tokens_spin.value()),
            system_prompt=self.chat_panel.system_prompt_edit.toPlainText().strip(),
        )

    def _send_chat_message(self) -> None:
        if self._chat_future is not None and not self._chat_future.done():
            return
        if self._selected_model() is None:
            self.status_label.setText("Сначала загрузите модели")
            return
        if self._current_session_id is None:
            session = self._history.create_session("Сессия 1")
            self._reload_sessions(preferred_id=session.id)

        text = self.chat_panel.input_edit.toPlainText().strip()
        if not text:
            return

        assert self._current_session_id is not None
        self._history.add_message(self._current_session_id, "user", text, status="complete")
        self.chat_panel.append_message("user", text)
        self.chat_panel.input_edit.clear()

        assistant_msg = self._history.add_message(self._current_session_id, "assistant", "", status="streaming")
        self.chat_panel.start_assistant_response(assistant_msg.id)
        context = [
            ChatMessagePayload(role=message.role, content=message.content)
            for message in self._history.get_messages(self._current_session_id)
            if message.id != assistant_msg.id and message.role in {"user", "assistant"} and message.content.strip()
        ]
        options = self._build_chat_options()
        self._cancel_event = Event()

        signals = _StreamSignals(self)
        signals.chunk.connect(self._on_stream_chunk)
        signals.done.connect(self._on_stream_done)
        signals.error.connect(self._on_stream_error)
        signals.finished.connect(self._on_stream_finished)

        self.send_button.setEnabled(False)
        self.status_label.setText("Генерация...")
        self._on_status(f"Отправка запроса в {options.model}")

        def worker() -> None:
            try:
                total = ""
                for chunk in self._chat_service.stream_reply(context, options, cancel_event=self._cancel_event):
                    if self._cancel_event is not None and self._cancel_event.is_set():
                        break
                    total += chunk
                    signals.chunk.emit(chunk)
                signals.done.emit(total)
            except Exception as exc:  # noqa: BLE001
                signals.error.emit(str(exc))
            finally:
                signals.finished.emit()

        self._chat_future = self._executor.submit(worker)

    def _on_stream_chunk(self, chunk: str) -> None:
        self.chat_panel.append_stream_chunk(chunk)

    def _on_stream_done(self, full_text: str) -> None:
        canceled = self._cancel_event.is_set() if self._cancel_event is not None else False
        message_id = self.chat_panel.current_stream_message_id()
        final_text = self.chat_panel.finish_stream(full_text, canceled)
        if message_id is not None:
            self._history.update_message(message_id, final_text, status="canceled" if canceled else "complete")
        self.status_label.setText("Остановлено" if canceled else "Готово")
        self._on_status("Ответ AI остановлен" if canceled else "Ответ AI получен")

    def _on_stream_error(self, message: str) -> None:
        message_id = self.chat_panel.current_stream_message_id()
        self.chat_panel.set_stream_error(message)
        if message_id is not None:
            self._history.update_message(message_id, f"[error] {message}", status="error")
        self.status_label.setText(f"Ошибка: {message}")
        self._on_status(f"Ошибка AI: {message}")

    def _on_stream_finished(self) -> None:
        self._cancel_event = None
        self.chat_panel.stop_button.setEnabled(False)
        self._reload_sessions(preferred_id=self._current_session_id)
        self._update_model_hint()

    def _stop_streaming(self, show_status: bool) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            if show_status:
                self.status_label.setText("Остановка...")

    def _run_task(self, task_key: str) -> None:
        if self._task_future is not None and not self._task_future.done():
            return
        panel = self._panel_for_task(task_key)
        if panel is None:
            self.status_label.setText("Панель AI-задачи недоступна. Откройте вкладку снова.")
            return
        model = self._selected_model()
        if model is None:
            self.status_label.setText("Сначала загрузите модели")
            return
        if self._current_session_id is None:
            session = self._history.create_session("Сессия 1")
            self._reload_sessions(preferred_id=session.id)
        try:
            advanced = panel.advanced_params()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        try:
            request = AiTaskRequest(
                model=model.name,
                task_key=task_key,
                protocol=str(self.protocol_combo.currentData()),
                prompt=panel.input_text(),
                texts=panel.input_texts(),
                file_path=panel.file_path(),
                source_language=panel.source_language(),
                target_language=panel.target_language(),
                max_tokens=int(self.max_tokens_spin.value()),
                advanced_params=advanced,
            )
        except RuntimeError:
            self.status_label.setText("Панель AI-задачи была пересоздана. Повторите запуск.")
            return
        assert self._current_session_id is not None
        input_asset = self._history.copy_input_asset(self._current_session_id, task_key, request.file_path) if request.file_path else ""

        signals = _TaskSignals(self)
        signals.done.connect(self._on_task_done)
        signals.error.connect(self._on_task_error)
        signals.finished.connect(self._on_task_finished)
        panel.run_button.setEnabled(False)
        self.status_label.setText(f"Выполняется: {get_task_definition(task_key).label}...")

        def worker() -> None:
            try:
                result = self._task_service.run(request)
                signals.done.emit((request, result, input_asset))
            except Exception as exc:  # noqa: BLE001
                signals.error.emit(str(exc))
            finally:
                signals.finished.emit()

        self._task_future = self._executor.submit(worker)

    def _on_task_done(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 3 or self._current_session_id is None:
            return
        request, result, input_asset = payload
        if not isinstance(request, AiTaskRequest) or not isinstance(result, AiTaskResult):
            return
        output_asset = ""
        if result.image_bytes:
            output_asset = self._history.save_output_asset(
                self._current_session_id,
                request.task_key,
                result.image_bytes,
                _mime_to_suffix(result.image_mime_type, ".png", data=result.image_bytes),
                "output",
            )
        elif result.audio_bytes:
            output_asset = self._history.save_output_asset(
                self._current_session_id,
                request.task_key,
                result.audio_bytes,
                _mime_to_suffix(result.audio_mime_type, ".mp3", data=result.audio_bytes),
                "output",
            )
        metadata = {
            "output_kind": result.output_kind,
            "image_mime_type": result.image_mime_type,
            "audio_mime_type": result.audio_mime_type,
            "json_data": result.json_data,
        }
        self._history.add_task_run(
            self._current_session_id,
            request.task_key,
            request.model,
            request_text=_task_request_to_text(request),
            response_text=_task_result_to_text(result),
            input_asset_path=input_asset,
            output_asset_path=output_asset,
            metadata=metadata,
            status="complete",
        )
        self._render_session(self._current_session_id)
        self.status_label.setText("Готово")
        self._on_status(f"Завершено: {get_task_definition(request.task_key).label}")

    def _on_task_error(self, message: str) -> None:
        self.status_label.setText(f"Ошибка: {message}")
        self._on_status(f"Ошибка AI-задачи: {message}")

    def _on_task_finished(self) -> None:
        panel = self._panel_for_task(self._active_task_key())
        if panel is not None:
            panel.run_button.setEnabled(True)
        self._update_model_hint()

    def _browse_task_file(self, task_key: str) -> None:
        panel = self._panel_for_task(task_key)
        if panel is None:
            return
        filter_text = "Все файлы (*.*)"
        if "image" in task_key:
            filter_text = "Изображения (*.png *.jpg *.jpeg *.webp *.bmp)"
        elif "speech" in task_key or "recognition" in task_key:
            filter_text = "Аудио (*.mp3 *.wav *.ogg *.m4a *.aac *.flac)"
        path, _ = QFileDialog.getOpenFileName(self, "Выберите файл", "", filter_text)
        if path:
            panel.set_file_path(path)

    def _apply_task_example(self, task_key: str) -> None:
        panel = self._panel_for_task(task_key)
        if panel is not None:
            panel.apply_example(task_example(task_key).apply_text)

    def _open_panel_asset(self, task_key: str) -> None:
        panel = self._panel_for_task(task_key)
        if panel is None:
            return
        path = self._history.resolve_asset_path(panel.selected_output_path())
        if path is not None:
            if self._open_asset_inline(path):
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _save_panel_asset(self, task_key: str) -> None:
        panel = self._panel_for_task(task_key)
        if panel is None:
            return
        path = self._history.resolve_asset_path(panel.selected_output_path())
        if path is None:
            return
        target, _ = QFileDialog.getSaveFileName(self, "Сохранить файл", path.name)
        if target:
            Path(target).write_bytes(path.read_bytes())
            self._on_status(f"Файл сохранён: {target}")

    def _play_panel_asset(self, task_key: str) -> None:
        panel = self._panel_for_task(task_key)
        if panel is None:
            return
        path = self._history.resolve_asset_path(panel.selected_output_path())
        if path is None:
            return
        if self._media_player is None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            return
        self._media_player.setSource(QUrl.fromLocalFile(str(path)))
        self._media_player.play()

    def _open_asset_inline(self, path: Path) -> bool:
        kind = _asset_kind(path)
        if kind == "image":
            return self._show_image_dialog(path)
        if kind == "audio" and self._media_player is not None:
            self._media_player.setSource(QUrl.fromLocalFile(str(path)))
            self._media_player.play()
            self._on_status(f"Воспроизведение: {path.name}")
            return True
        if kind == "text":
            return self._show_text_dialog(path, _read_text_file(path))
        if kind == "binary":
            return self._show_text_dialog(path, _binary_preview(path))
        return False

    def _show_image_dialog(self, path: Path) -> bool:
        pixmap = _load_image_pixmap(path)
        if pixmap is None:
            return False
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Просмотр: {path.name}")
        dialog.resize(900, 700)
        layout = QVBoxLayout(dialog)
        preview = QLabel()
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setPixmap(
            pixmap.scaled(860, 620, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
        layout.addWidget(preview, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        return True

    def _show_text_dialog(self, path: Path, content: str) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Просмотр: {path.name}")
        dialog.resize(900, 700)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(content)
        layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        return True

    def _save_options(self) -> None:
        if self._is_loading:
            return
        settings = self._settings_store.load_settings()
        settings.ai_protocol = str(self.protocol_combo.currentData())
        settings.ai_model = self._selected_model_name()
        settings.ai_active_task = self._active_task_key()
        settings.ai_popular_only = self.popular_only_checkbox.isChecked()
        settings.ai_system_prompt = self.chat_panel.system_prompt_edit.toPlainText().strip()
        settings.ai_max_tokens = int(self.max_tokens_spin.value())
        settings.ai_last_session_id = str(self._current_session_id or "")
        settings.ai_splitter_state = self._encode_splitter_state()
        self._settings_store.save_settings(settings)

    def _on_options_changed(self) -> None:
        self._save_options()
        self._update_model_hint()

    def _restore_splitter_state(self, raw_state: str) -> None:
        payload = _load_splitter_payload(raw_state)
        root_state = payload.get("root", "")
        chat_state = payload.get("chat", "")
        if root_state:
            self.root_splitter.restoreState(decode_qbytearray(root_state))
        else:
            self.root_splitter.setSizes([280, 980])
        if chat_state:
            self.chat_splitter.restoreState(decode_qbytearray(chat_state))
        else:
            self.chat_splitter.setSizes([220, 720, 60])

    def _save_splitter_state(self) -> None:
        if self._is_loading:
            return
        self._save_options()

    def _encode_splitter_state(self) -> str:
        payload = {
            "root": encode_qbytearray(self.root_splitter.saveState()),
            "chat": encode_qbytearray(self.chat_splitter.saveState()),
        }
        return json.dumps(payload, ensure_ascii=True)


def _parse_int(raw: str) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _load_splitter_payload(raw_state: str) -> dict[str, str]:
    try:
        payload = json.loads(raw_state) if raw_state else {}
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def _extract_input_schema(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("input_schema", "input", "inputSchema", "schema"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _known_input_keys(task_key: str) -> set[str]:
    if task_key == TEXT_GENERATION:
        return {"messages", "prompt", "stream", "temperature", "max_tokens"}
    if task_key == TEXT_EMBEDDINGS:
        return {"text"}
    if task_key == "text_classification":
        return {"text"}
    if task_key == TEXT_TO_IMAGE:
        return {"prompt", "temperature", "max_tokens"}
    if task_key == TEXT_TO_SPEECH:
        return {"text", "max_tokens"}
    if task_key == "automatic_speech_recognition":
        return {"audio"}
    if task_key == "image_to_text":
        return {"image", "prompt", "max_tokens"}
    if task_key == "image_classification":
        return {"image"}
    if task_key == TRANSLATION:
        return {"text", "source_lang", "target_lang"}
    return {"input_text"}


def _task_request_to_text(request: AiTaskRequest) -> str:
    if request.task_key == TEXT_EMBEDDINGS:
        return "\n".join(request.texts)
    if request.file_path:
        lines = [f"Файл: {request.file_path}"]
        if request.prompt:
            lines.extend(("", request.prompt))
        return "\n".join(lines)
    if request.task_key == TRANSLATION:
        return (
            f"Язык источника: {request.source_language or 'auto'}\n"
            f"Язык перевода: {request.target_language}\n\n"
            f"{request.prompt}"
        )
    return request.prompt


def _task_result_to_text(result: AiTaskResult) -> str:
    if result.text:
        return result.text
    if result.classifications:
        return "\n".join(f"{row['label']}: {row['score']:.4f}" for row in result.classifications)
    if result.embedding is not None:
        return json.dumps(result.embedding, ensure_ascii=False, indent=2)
    if result.image_bytes:
        return f"Сгенерировано изображение ({len(result.image_bytes)} байт)"
    if result.audio_bytes:
        return f"Сгенерировано аудио ({len(result.audio_bytes)} байт)"
    if result.json_data is not None:
        return json.dumps(result.json_data, ensure_ascii=False, indent=2)
    return ""


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".log",
    ".ini",
    ".cfg",
    ".toml",
    ".py",
    ".js",
    ".ts",
}


def _mime_to_suffix(mime_type: str, fallback: str, data: bytes | None = None) -> str:
    guess = mimetypes.guess_extension(mime_type or "")
    if guess and guess != ".bin":
        return guess
    suffix = _detect_image_suffix(data or b"") or _detect_audio_suffix(data or b"")
    if suffix:
        return suffix
    return fallback


def _detect_image_suffix(data: bytes) -> str | None:
    blob = bytes(data)
    if not blob:
        return None
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if blob.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if blob.startswith(b"RIFF") and len(blob) >= 12 and blob[8:12] == b"WEBP":
        return ".webp"
    if blob.startswith(b"BM"):
        return ".bmp"
    if blob.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    return None


def _detect_audio_suffix(data: bytes) -> str | None:
    blob = bytes(data)
    if not blob:
        return None
    if blob.startswith(b"ID3") or blob[:2] == b"\xff\xfb":
        return ".mp3"
    if blob.startswith(b"OggS"):
        return ".ogg"
    if blob.startswith(b"RIFF") and len(blob) >= 12 and blob[8:12] == b"WAVE":
        return ".wav"
    if blob.startswith(b"fLaC"):
        return ".flac"
    return None


def _asset_kind(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    suffix = path.suffix.lower()
    if suffix in _IMAGE_EXTENSIONS:
        return "image"
    if suffix in _AUDIO_EXTENSIONS:
        return "audio"
    if suffix in _TEXT_EXTENSIONS:
        return "text"

    sample = _read_prefix(path, 1024)
    if _detect_image_suffix(sample):
        return "image"
    if _detect_audio_suffix(sample):
        return "audio"
    if _looks_like_text(sample):
        return "text"
    return "binary"


def _load_image_pixmap(path: Path) -> QPixmap | None:
    if not path.exists() or not path.is_file():
        return None
    pixmap = QPixmap(str(path))
    if not pixmap.isNull():
        return pixmap
    data = path.read_bytes()
    if not data:
        return None
    loaded = QPixmap()
    if not loaded.loadFromData(data):
        return None
    if loaded.isNull():
        return None
    return loaded


def _looks_like_text(data: bytes) -> bool:
    blob = bytes(data)
    if not blob:
        return True
    if b"\x00" in blob:
        return False
    try:
        blob.decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            blob.decode("cp1251")
            return True
        except UnicodeDecodeError:
            return False


def _read_text_file(path: Path) -> str:
    max_bytes = 1_000_000
    data = _read_prefix(path, max_bytes + 1)
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    if not data:
        return ""
    for encoding in ("utf-8", "cp1251", "latin-1"):
        try:
            text = data.decode(encoding)
            return text + ("\n\n[... output truncated ...]" if truncated else "")
        except UnicodeDecodeError:
            continue
    text = data.decode("utf-8", errors="replace")
    return text + ("\n\n[... output truncated ...]" if truncated else "")


def _binary_preview(path: Path) -> str:
    total_size = path.stat().st_size
    sample = _read_prefix(path, 256)
    if not sample:
        return f"{path.name}\n\nПустой файл."
    hex_rows: list[str] = []
    for idx in range(0, len(sample), 16):
        chunk = sample[idx:idx + 16]
        hex_rows.append(f"{idx:04x}: {' '.join(f'{b:02x}' for b in chunk)}")
    return (
        f"{path.name}\n"
        f"Размер: {total_size} байт\n\n"
        "Первые байты (hex):\n"
        + "\n".join(hex_rows)
    )


def _read_prefix(path: Path, size: int) -> bytes:
    with path.open("rb") as stream:
        return stream.read(max(0, int(size)))
