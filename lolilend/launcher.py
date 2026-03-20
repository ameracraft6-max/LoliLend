from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
import math
import os
from pathlib import Path
import queue
import subprocess
import sys

from lolilend.bootstrap import APP_MODE_FLAG, configure_qt_environment, prime_qt_library_paths

configure_qt_environment()

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lolilend.general_settings import GeneralSettingsStore
from lolilend.runtime import asset_path
from lolilend.updater import (
    ReleaseConfig,
    UpdateState,
    download_release_asset,
    fetch_latest_release,
    is_newer_version,
    spawn_install_and_relaunch,
    terminate_processes_by_name,
)
from lolilend.version import APP_EXE_NAME, APP_NAME, APP_VERSION

_FONT_PATH = asset_path("fonts", "Rajdhani-Medium.ttf")
_DEFAULT_PREVIEW_PATH = asset_path("launcher_default.png")
_DEFAULT_PREVIEW_FALLBACK_PATH = asset_path("background_ref.png")


def _install_hud_font() -> None:
    if _FONT_PATH.exists():
        QFontDatabase.addApplicationFont(str(_FONT_PATH))


def run_launcher(argv: list[str] | None = None) -> int:
    raw_argv = list(argv or sys.argv)
    prime_qt_library_paths()
    app = QApplication(raw_argv[:1])
    _install_hud_font()
    window = LauncherWindow()
    window.show()
    return app.exec()


class NeonBackdrop(QFrame):
    def __init__(self) -> None:
        super().__init__()
        background_path = _DEFAULT_PREVIEW_PATH if _DEFAULT_PREVIEW_PATH.exists() else _DEFAULT_PREVIEW_FALLBACK_PATH
        self._pixmap = QPixmap(str(background_path)) if background_path.exists() else QPixmap()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self.rect()

        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            dx = (scaled.width() - rect.width()) // 2
            dy = (scaled.height() - rect.height()) // 2
            painter.drawPixmap(0, 0, scaled, dx, dy, rect.width(), rect.height())

        overlay = QLinearGradient(0, 0, rect.width(), rect.height())
        overlay.setColorAt(0.0, QColor(6, 8, 12, 240))
        overlay.setColorAt(0.45, QColor(28, 4, 14, 210))
        overlay.setColorAt(1.0, QColor(5, 6, 10, 245))
        painter.fillRect(rect, overlay)

        painter.setPen(QPen(QColor(255, 40, 110, 40), 1))
        for y in range(0, rect.height(), 4):
            painter.drawLine(0, y, rect.width(), y)

        painter.fillRect(0, 0, rect.width(), 72, QColor(0, 0, 0, 70))
        painter.fillRect(0, rect.height() - 92, rect.width(), 92, QColor(0, 0, 0, 95))


class PulseSpinner(QWidget):
    """Three pulsing dots — indicates an active background operation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(72, 24)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.08) % (2 * math.pi)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() // 2, self.height() // 2
        if not self._timer.isActive():
            return
        for i in range(3):
            s = 0.4 + 0.6 * math.sin(self._phase + i * 2.1)
            r = int(4 + 3 * s)
            alpha = int(60 + 195 * s)
            painter.setBrush(QColor(255, 45, 130, alpha))
            painter.setPen(Qt.PenStyle.NoPen)
            ox = (i - 1) * 22
            painter.drawEllipse(cx + ox - r, cy - r, r * 2, r * 2)


class StageBar(QWidget):
    """Three-step progress indicator: ПРОВЕРКА → СКАЧИВАНИЕ → УСТАНОВКА."""

    _STEPS = ["ПРОВЕРКА", "СКАЧИВАНИЕ", "УСТАНОВКА"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._labels: list[QLabel] = []
        for i, name in enumerate(self._STEPS):
            lbl = QLabel(f"○ {name}")
            lbl.setObjectName("LauncherStepLabel")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._labels.append(lbl)
            layout.addWidget(lbl)
            if i < len(self._STEPS) - 1:
                sep = QLabel("───")
                sep.setObjectName("LauncherStepSep")
                sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(sep)

        self._set_all_pending()

    def _set_all_pending(self) -> None:
        for lbl, name in zip(self._labels, self._STEPS):
            lbl.setText(f"○ {name}")
            lbl.setStyleSheet("color: #664466; font-weight: 400;")

    def set_step(self, active: int, *, failed: bool = False) -> None:
        """Set active step (0/1/2). Steps before active are done, rest pending."""
        for i, (lbl, name) in enumerate(zip(self._labels, self._STEPS)):
            if i < active:
                lbl.setText(f"✓ {name}")
                lbl.setStyleSheet("color: #56ff98; font-weight: 600;")
            elif i == active:
                if failed:
                    lbl.setText(f"✕ {name}")
                    lbl.setStyleSheet("color: #ff5a5a; font-weight: 700;")
                else:
                    lbl.setText(f"● {name}")
                    lbl.setStyleSheet("color: #ff4f92; font-weight: 700;")
            else:
                lbl.setText(f"○ {name}")
                lbl.setStyleSheet("color: #664466; font-weight: 400;")

    def set_all_done(self) -> None:
        for lbl, name in zip(self._labels, self._STEPS):
            lbl.setText(f"✓ {name}")
            lbl.setStyleSheet("color: #56ff98; font-weight: 600;")

    def set_checking_done(self) -> None:
        """Mark only CHECKING as done; leave DOWNLOADING and INSTALLING pending."""
        for i, (lbl, name) in enumerate(zip(self._labels, self._STEPS)):
            if i == 0:
                lbl.setText(f"✓ {name}")
                lbl.setStyleSheet("color: #56ff98; font-weight: 600;")
            else:
                lbl.setText(f"○ {name}")
                lbl.setStyleSheet("color: #664466; font-weight: 400;")

    def reset(self) -> None:
        self._set_all_pending()


class LauncherWindow(QMainWindow):
    def __init__(self, *, auto_start_check: bool = True) -> None:
        super().__init__()
        self._store = GeneralSettingsStore()
        self._settings = self._store.load_settings()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lolilend-launcher")
        self._worker_future: Future[None] | None = None
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._intro_animated = False
        self._border_phase = 0.0
        self._last_active_step = 0

        self._build_ui()
        self._bind_signals()
        self._apply_settings_to_controls()
        self._load_preview_image()

        # Smooth progress animation
        self._prog_anim = QPropertyAnimation(self.progress_bar, b"value", self)
        self._prog_anim.setDuration(350)
        self._prog_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Pulsing border timer
        self._border_timer = QTimer(self)
        self._border_timer.setInterval(30)
        self._border_timer.timeout.connect(self._pulse_border)

        self._set_update_state(UpdateState.UP_TO_DATE, f"Текущая версия: {APP_VERSION}")
        self._append_log("Launcher initialized.")

        self._event_timer = QTimer(self)
        self._event_timer.setInterval(120)
        self._event_timer.timeout.connect(self._drain_events)
        self._event_timer.start()

        if auto_start_check and self._settings.auto_update_enabled:
            QTimer.singleShot(450, lambda: self.start_update_flow(auto_install=True))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        if self._intro_animated:
            return
        self._intro_animated = True
        QTimer.singleShot(120, self._animate_home_cards)

    def _build_ui(self) -> None:
        self.setWindowTitle(f"{APP_NAME} Launcher")
        self.setMinimumSize(1140, 680)
        self.resize(1380, 820)

        root = NeonBackdrop()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(24, 24, 24, 24)
        root_layout.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("LauncherShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        root_layout.addWidget(shell, 1)

        top_bar = QFrame()
        top_bar.setObjectName("LauncherTopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(22, 16, 22, 16)
        top_layout.setSpacing(14)
        shell_layout.addWidget(top_bar)

        logo = QLabel("LL")
        logo.setObjectName("LauncherLogoMark")
        logo.setFixedSize(44, 44)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_layout.addWidget(logo)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title_label = QLabel("LOLILEND LAUNCHER")
        title_label.setObjectName("LauncherTitle")
        subtitle_label = QLabel("Neon Bootstrap • GitHub Auto Update")
        subtitle_label.setObjectName("LauncherSubtitle")
        title_col.addWidget(title_label)
        title_col.addWidget(subtitle_label)
        top_layout.addLayout(title_col)
        top_layout.addSpacing(16)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self.home_nav = self._make_nav_button("Главная")
        self.settings_nav = self._make_nav_button("Настройки")
        self.logs_nav = self._make_nav_button("Логи")
        self._nav_group.addButton(self.home_nav, 0)
        self._nav_group.addButton(self.settings_nav, 1)
        self._nav_group.addButton(self.logs_nav, 2)
        top_layout.addWidget(self.home_nav)
        top_layout.addWidget(self.settings_nav)
        top_layout.addWidget(self.logs_nav)
        top_layout.addStretch(1)

        self.launch_app_button = QPushButton("Запустить лаунчер")
        self.launch_app_button.setObjectName("LauncherPlayButton")
        self.launch_app_button.setCursor(Qt.CursorShape.PointingHandCursor)
        top_layout.addWidget(self.launch_app_button)

        content = QFrame()
        content.setObjectName("LauncherContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 18, 20, 20)
        content_layout.setSpacing(14)
        shell_layout.addWidget(content, 1)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)

        self.home_page = self._build_home_page()
        self.settings_page = self._build_settings_page()
        self.logs_page = self._build_logs_page()
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.logs_page)

        self.status_tip = QLabel("Состояние: готово к запуску.")
        self.status_tip.setObjectName("LauncherFooter")
        content_layout.addWidget(self.status_tip)

        self.setCentralWidget(root)
        self.setStyleSheet(self._launcher_stylesheet())
        self.home_nav.setChecked(True)
        self.stack.setCurrentIndex(0)

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(14)

        self.hero_card = QFrame()
        self.hero_card.setObjectName("LauncherHeroCard")
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(18, 18, 18, 18)
        hero_layout.setSpacing(10)

        self.state_chip = QLabel("READY")
        self.state_chip.setObjectName("LauncherStateChip")
        self.state_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_chip.setFixedWidth(170)
        hero_layout.addWidget(self.state_chip, 0, Qt.AlignmentFlag.AlignLeft)

        self.stage_bar = StageBar()
        hero_layout.addWidget(self.stage_bar)

        heading = QLabel("Автоматический апдейтер")
        heading.setObjectName("LauncherHeroTitle")
        hero_layout.addWidget(heading)

        self.version_label = QLabel(f"Установленная версия: {APP_VERSION}")
        self.version_label.setObjectName("LauncherMetaLabel")
        hero_layout.addWidget(self.version_label)

        self.latest_label = QLabel("Последний релиз: проверяется...")
        self.latest_label.setObjectName("LauncherMetaLabel")
        hero_layout.addWidget(self.latest_label)

        self.status_label = QLabel("Инициализация лаунчера.")
        self.status_label.setObjectName("LauncherStatusLabel")
        self.status_label.setWordWrap(True)
        hero_layout.addWidget(self.status_label)

        self.pulse_spinner = PulseSpinner()
        self.pulse_spinner.setVisible(False)
        hero_layout.addWidget(self.pulse_spinner, 0, Qt.AlignmentFlag.AlignLeft)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("LauncherProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.progress_pct_label = QLabel("  0%")
        self.progress_pct_label.setObjectName("LauncherProgressPct")
        self.progress_pct_label.setFixedWidth(44)
        self.progress_pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_pct_label.setVisible(False)

        prog_row = QHBoxLayout()
        prog_row.setSpacing(6)
        prog_row.addWidget(self.progress_bar, 1)
        prog_row.addWidget(self.progress_pct_label)
        hero_layout.addLayout(prog_row)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.check_button = QPushButton("Проверить обновления")
        self.check_button.setObjectName("LauncherCheckButton")
        self.retry_button = QPushButton("Повторить")
        self.retry_button.setObjectName("LauncherRetryButton")
        self.retry_button.setVisible(False)
        controls.addWidget(self.check_button)
        controls.addWidget(self.retry_button)
        controls.addStretch(1)
        hero_layout.addLayout(controls)
        hero_layout.addStretch(1)

        self.image_card = QFrame()
        self.image_card.setObjectName("LauncherImageCard")
        image_layout = QVBoxLayout(self.image_card)
        image_layout.setContentsMargins(16, 16, 16, 16)
        image_layout.setSpacing(10)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("LauncherPreviewLabel")
        self.preview_label.setMinimumSize(360, 220)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_layout.addWidget(self.preview_label, 1)

        layout.addWidget(self.hero_card, 0, 0)
        layout.addWidget(self.image_card, 0, 1)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        settings_card = QFrame()
        settings_card.setObjectName("LauncherSettingsCard")
        settings_layout = QGridLayout(settings_card)
        settings_layout.setContentsMargins(18, 18, 18, 18)
        settings_layout.setHorizontalSpacing(14)
        settings_layout.setVerticalSpacing(12)

        repo_label = QLabel("GitHub repo (owner/repo)")
        settings_layout.addWidget(repo_label, 0, 0)
        self.repo_edit = QLineEdit()
        self.repo_edit.setObjectName("LauncherRepoEdit")
        settings_layout.addWidget(self.repo_edit, 0, 1)

        pattern_label = QLabel("Паттерн installer файла")
        settings_layout.addWidget(pattern_label, 1, 0)
        self.asset_pattern_edit = QLineEdit()
        self.asset_pattern_edit.setObjectName("LauncherAssetPatternEdit")
        settings_layout.addWidget(self.asset_pattern_edit, 1, 1)

        self.auto_update_checkbox = QCheckBox("Автообновление при старте")
        self.auto_update_checkbox.setObjectName("LauncherAutoUpdateCheck")
        settings_layout.addWidget(self.auto_update_checkbox, 2, 1)

        actions = QHBoxLayout()
        self.save_settings_button = QPushButton("Сохранить")
        self.save_settings_button.setObjectName("LauncherSaveSettingsButton")
        self.open_data_folder_button = QPushButton("Папка данных")
        self.open_data_folder_button.setObjectName("LauncherOpenDataButton")
        actions.addWidget(self.save_settings_button)
        actions.addWidget(self.open_data_folder_button)
        actions.addStretch(1)
        settings_layout.addLayout(actions, 3, 1)

        layout.addWidget(settings_card)
        layout.addStretch(1)
        return page

    def _build_logs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.logs_view = QPlainTextEdit()
        self.logs_view.setObjectName("LauncherLogsView")
        self.logs_view.setReadOnly(True)
        layout.addWidget(self.logs_view, 1)
        return page

    def _bind_signals(self) -> None:
        self._nav_group.idClicked.connect(self._switch_page)
        self.check_button.clicked.connect(lambda: self.start_update_flow(auto_install=True))
        self.retry_button.clicked.connect(lambda: self.start_update_flow(auto_install=True))
        self.launch_app_button.clicked.connect(self._launch_main_app)
        self.save_settings_button.clicked.connect(self._save_launcher_settings)
        self.open_data_folder_button.clicked.connect(self._open_data_folder)

    def _make_nav_button(self, title: str) -> QPushButton:
        button = QPushButton(title)
        button.setObjectName("LauncherNavButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _switch_page(self, index: int) -> None:
        if index < 0 or index >= self.stack.count():
            return
        self.stack.setCurrentIndex(index)
        current = self.stack.currentWidget()
        if current is None:
            return
        effect = QGraphicsOpacityEffect(current)
        current.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", current)
        animation.setDuration(190)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        animation.finished.connect(lambda: current.setGraphicsEffect(None))
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _animate_home_cards(self) -> None:
        self._animate_card_entry(self.hero_card, delay_ms=0)
        self._animate_card_entry(self.image_card, delay_ms=110)

    def _animate_card_entry(self, card: QWidget, *, delay_ms: int) -> None:
        target = card.pos()
        start = target + QPoint(0, 18)
        card.move(start)
        effect = QGraphicsOpacityEffect(card)
        card.setGraphicsEffect(effect)
        effect.setOpacity(0.0)

        def start_animation() -> None:
            slide = QPropertyAnimation(card, b"pos", card)
            slide.setStartValue(start)
            slide.setEndValue(target)
            slide.setDuration(240)
            slide.setEasingCurve(QEasingCurve.Type.OutCubic)

            fade = QPropertyAnimation(effect, b"opacity", card)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setDuration(220)
            fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
            fade.finished.connect(lambda: card.setGraphicsEffect(None))

            slide.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        QTimer.singleShot(delay_ms, start_animation)

    def _apply_settings_to_controls(self) -> None:
        self.repo_edit.setText(self._settings.github_repo)
        self.asset_pattern_edit.setText(self._settings.release_asset_pattern)
        self.auto_update_checkbox.setChecked(self._settings.auto_update_enabled)

    def _save_launcher_settings(self) -> None:
        self._settings.github_repo = self.repo_edit.text().strip() or self._settings.github_repo
        self._settings.release_asset_pattern = self.asset_pattern_edit.text().strip() or self._settings.release_asset_pattern
        self._settings.auto_update_enabled = bool(self.auto_update_checkbox.isChecked())
        self._store.save_settings(self._settings)
        self._append_log("Launcher settings saved.")
        self.status_tip.setText("Состояние: настройки сохранены.")

    def _load_preview_image(self) -> None:
        path = _DEFAULT_PREVIEW_PATH if _DEFAULT_PREVIEW_PATH.exists() else _DEFAULT_PREVIEW_FALLBACK_PATH
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.preview_label.setText("")
            return
        scaled = pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        self.preview_label.setText("")

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._load_preview_image()

    def start_update_flow(self, *, auto_install: bool) -> None:
        if self._worker_future is not None and not self._worker_future.done():
            return
        self._save_launcher_settings()
        self.check_button.setEnabled(False)
        self.retry_button.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._worker_future = self._executor.submit(self._update_worker, auto_install)

    def _update_worker(self, auto_install: bool) -> None:
        try:
            config = ReleaseConfig(
                repo=self._settings.github_repo,
                asset_pattern=self._settings.release_asset_pattern,
                stable_only=True,
            )
            self._events.put(("state", (UpdateState.CHECKING, "Проверка релизов на GitHub...")))
            release = fetch_latest_release(config)
            if release is None:
                self._events.put(("state", (UpdateState.UP_TO_DATE, "Стабильных обновлений не найдено.")))
                return

            self._events.put(("latest", release.version))
            if not is_newer_version(release.version, APP_VERSION):
                self._events.put(("state", (UpdateState.UP_TO_DATE, f"Установлена актуальная версия ({APP_VERSION}).")))
                return

            self._events.put(("state", (UpdateState.DOWNLOADING, f"Найдено обновление {release.version}. Скачивание...")))
            destination = self._store.temp_dir / "updates" / release.asset_name

            def on_progress(downloaded: int, total: int | None) -> None:
                self._events.put(("progress", (downloaded, total)))

            download_release_asset(release, destination, progress=on_progress)
            if not auto_install:
                self._events.put(("state", (UpdateState.FAILED, "Доступно обновление. Установите вручную.")))
                return

            self._events.put(("state", (UpdateState.INSTALLING, "Запуск тихой установки...")))
            terminate_processes_by_name(APP_EXE_NAME, skip_pid=os.getpid())
            spawn_install_and_relaunch(destination, self._launcher_relaunch_command())
            self._events.put(("log", "Installer launched in silent mode."))
            self._events.put(("close", None))
        except Exception as exc:
            self._events.put(("state", (UpdateState.FAILED, f"Ошибка обновления: {exc}")))
        finally:
            self._events.put(("worker_done", None))

    def _drain_events(self) -> None:
        while not self._events.empty():
            event, payload = self._events.get_nowait()
            if event == "state":
                state, message = payload
                self._set_update_state(state, str(message))
            elif event == "progress":
                downloaded, total = payload
                if total and total > 0:
                    percent = max(0, min(100, int((downloaded / total) * 100)))
                    self.progress_bar.setRange(0, 100)
                    self._set_progress_smooth(percent)
                    self.progress_pct_label.setText(f"{percent}%")
                else:
                    self.progress_bar.setRange(0, 0)
            elif event == "latest":
                self.latest_label.setText(f"Последний релиз: {payload}")
            elif event == "log":
                self._append_log(str(payload))
            elif event == "close":
                QTimer.singleShot(350, self.close)
            elif event == "worker_done":
                self.check_button.setEnabled(True)

    def _set_update_state(self, state: UpdateState | str, message: str) -> None:
        state_name = state.value if isinstance(state, UpdateState) else str(state)
        palette = {
            UpdateState.CHECKING.value: ("CHECKING", "#f5bd54"),
            UpdateState.UP_TO_DATE.value: ("READY", "#56ff98"),
            UpdateState.DOWNLOADING.value: ("DOWNLOADING", "#ff6aa5"),
            UpdateState.INSTALLING.value: ("INSTALLING", "#ff4f88"),
            UpdateState.FAILED.value: ("FAILED", "#ff5a5a"),
        }
        text, color = palette.get(state_name, ("READY", "#56ff98"))
        self.state_chip.setText(text)
        self.state_chip.setStyleSheet(f"background: rgba(0,0,0,0.32); border: 1px solid {color}; color: {color};")
        self.status_label.setText(message)
        self.status_tip.setText(f"Состояние: {message}")
        self._append_log(message)
        self.retry_button.setVisible(state_name == UpdateState.FAILED.value)

        _active = {UpdateState.CHECKING.value, UpdateState.DOWNLOADING.value, UpdateState.INSTALLING.value}

        # Spinner + border pulse
        if state_name in _active:
            self.pulse_spinner.setVisible(True)
            self.pulse_spinner.start()
            if not self._border_timer.isActive():
                self._border_timer.start()
        else:
            self.pulse_spinner.stop()
            self.pulse_spinner.setVisible(False)
            self._border_timer.stop()
            self.hero_card.setStyleSheet("")

        # StageBar
        if state_name == UpdateState.CHECKING.value:
            self._last_active_step = 0
            self.stage_bar.set_step(0)
        elif state_name == UpdateState.DOWNLOADING.value:
            self._last_active_step = 1
            self.stage_bar.set_step(1)
        elif state_name == UpdateState.INSTALLING.value:
            self._last_active_step = 2
            self.stage_bar.set_step(2)
        elif state_name == UpdateState.UP_TO_DATE.value:
            self.stage_bar.set_checking_done()
        elif state_name == UpdateState.FAILED.value:
            self.stage_bar.set_step(self._last_active_step, failed=True)

        # Progress bar visibility
        if state_name in _active:
            self.progress_pct_label.setVisible(True)
        else:
            self.progress_pct_label.setVisible(False)
            self.progress_pct_label.setText("  0%")

        if state_name in {UpdateState.UP_TO_DATE.value, UpdateState.FAILED.value}:
            self._prog_anim.stop()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)

    def _set_progress_smooth(self, value: int) -> None:
        self._prog_anim.stop()
        self._prog_anim.setStartValue(self.progress_bar.value())
        self._prog_anim.setEndValue(value)
        self._prog_anim.start()

    def _pulse_border(self) -> None:
        self._border_phase = (self._border_phase + 0.05) % (2 * math.pi)
        alpha = int(100 + 80 * math.sin(self._border_phase))
        self.hero_card.setStyleSheet(
            f"QFrame#LauncherHeroCard {{ border: 1px solid rgba(255, 59, 134, {alpha / 255:.2f}); "
            f"background: rgba(8, 10, 16, 0.78); }}"
        )

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs_view.appendPlainText(f"[{timestamp}] {message}")

    def _open_data_folder(self) -> None:
        target = self._store.base_dir
        target.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            QMessageBox.information(self, APP_NAME, f"Data folder: {target}")

    def _launch_main_app(self) -> None:
        command = self._app_launch_command()
        try:
            subprocess.Popen(command, close_fds=True, env=self._child_process_env())
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Не удалось запустить приложение: {exc}")
            return
        self._append_log("Main application launched.")
        self.close()

    def _app_launch_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [str(Path(sys.executable).resolve()), APP_MODE_FLAG]
        script = Path(sys.argv[0]).resolve()
        return [str(Path(sys.executable).resolve()), str(script), APP_MODE_FLAG]

    def _child_process_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if getattr(sys, "frozen", False):
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        return env

    def _launcher_relaunch_command(self) -> str:
        if getattr(sys, "frozen", False):
            executable = Path(sys.executable).resolve()
            return f"\"{executable}\""
        script = Path(sys.argv[0]).resolve()
        python = Path(sys.executable).resolve()
        return f"\"{python}\" \"{script}\""

    @staticmethod
    def _launcher_stylesheet() -> str:
        return """
QWidget {
    color: #f3f0f6;
    font-family: "Rajdhani Medium", "Bahnschrift", "Segoe UI";
    font-size: 13px;
    background: transparent;
}
QFrame#LauncherShell {
    background: rgba(8, 8, 12, 218);
    border: 1px solid #922347;
}
QFrame#LauncherTopBar {
    background: rgba(6, 6, 11, 220);
    border-bottom: 1px solid rgba(255, 63, 140, 0.38);
}
QLabel#LauncherLogoMark {
    border: 1px solid #ff2d82;
    color: #ffd2e6;
    background: rgba(255, 24, 104, 0.22);
    font-size: 20px;
    font-weight: 700;
}
QLabel#LauncherTitle {
    font-size: 22px;
    font-weight: 700;
    color: #ffe3ef;
}
QLabel#LauncherSubtitle {
    font-size: 12px;
    color: #cc9cb6;
}
QPushButton#LauncherNavButton {
    min-height: 34px;
    min-width: 110px;
    background: rgba(10, 10, 15, 0.75);
    border: 1px solid rgba(255, 66, 143, 0.5);
    color: #f7dbe7;
    padding: 0 14px;
}
QPushButton#LauncherNavButton:hover {
    border: 1px solid #ff4f92;
    background: rgba(255, 22, 100, 0.16);
}
QPushButton#LauncherNavButton:checked {
    border: 1px solid #ff6aa5;
    background: rgba(255, 22, 100, 0.28);
}
QPushButton#LauncherPlayButton {
    min-height: 38px;
    min-width: 170px;
    background: rgba(255, 40, 118, 0.18);
    border: 1px solid #ff4f92;
    color: #ffe7f1;
    font-size: 15px;
    font-weight: 700;
    padding: 0 16px;
}
QPushButton#LauncherPlayButton:hover {
    background: rgba(255, 40, 118, 0.32);
}
QFrame#LauncherHeroCard,
QFrame#LauncherImageCard,
QFrame#LauncherSettingsCard {
    background: rgba(8, 10, 16, 0.78);
    border: 1px solid rgba(255, 59, 134, 0.5);
}
QLabel#LauncherStateChip {
    min-height: 28px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#LauncherHeroTitle {
    font-size: 24px;
    font-weight: 700;
    color: #ffe1ee;
}
QLabel#LauncherMetaLabel {
    color: #dcb4c7;
    font-size: 13px;
}
QLabel#LauncherStatusLabel {
    color: #f7dae8;
    font-size: 14px;
}
QProgressBar#LauncherProgress {
    border: 1px solid rgba(255, 71, 145, 0.45);
    background: rgba(6, 8, 12, 0.84);
    text-align: center;
}
QProgressBar#LauncherProgress::chunk {
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #ff2d82, stop: 1 #ff7ab0);
}
QPushButton#LauncherCheckButton,
QPushButton#LauncherRetryButton,
QPushButton#LauncherSaveSettingsButton,
QPushButton#LauncherOpenDataButton {
    min-height: 34px;
    background: rgba(255, 24, 104, 0.08);
    border: 1px solid rgba(255, 66, 143, 0.55);
    color: #ffe5ef;
    padding: 0 14px;
}
QPushButton#LauncherCheckButton:hover,
QPushButton#LauncherRetryButton:hover,
QPushButton#LauncherSaveSettingsButton:hover,
QPushButton#LauncherOpenDataButton:hover {
    background: rgba(255, 24, 104, 0.24);
}
QLabel#LauncherPreviewLabel {
    border: 1px solid rgba(255, 85, 152, 0.56);
    background: rgba(4, 5, 8, 0.72);
}
QLineEdit#LauncherRepoEdit,
QLineEdit#LauncherAssetPatternEdit {
    min-height: 30px;
    padding: 0 8px;
    border: 1px solid rgba(255, 70, 146, 0.55);
    background: rgba(7, 8, 12, 0.75);
}
QLineEdit#LauncherRepoEdit:focus,
QLineEdit#LauncherAssetPatternEdit:focus {
    border: 1px solid #ff6ca9;
}
QPlainTextEdit#LauncherLogsView {
    border: 1px solid rgba(255, 70, 146, 0.55);
    background: rgba(7, 8, 12, 0.75);
    color: #ffd9e8;
}
QLabel#LauncherFooter {
    color: #d8a8bf;
    font-size: 12px;
}
QLabel#LauncherProgressPct {
    color: #ff6aa5;
    font-size: 14px;
    font-weight: 700;
}
QLabel#LauncherStepLabel {
    font-size: 12px;
    letter-spacing: 0.5px;
    padding: 2px 4px;
}
QLabel#LauncherStepSep {
    color: #442233;
    font-size: 11px;
}
"""
