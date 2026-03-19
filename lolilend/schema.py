from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ControlSpec:
    type: str
    label: str
    default: Any = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SectionSpec:
    title: str
    controls: list[ControlSpec]


@dataclass(slots=True)
class TabSpec:
    id: str
    title: str
    icon: str
    sections: list[SectionSpec]


tabs_schema: list[TabSpec] = [
    TabSpec(
        id="general",
        title="Общее",
        icon="general",
        sections=[
            SectionSpec(
                title="Основные параметры",
                controls=[
                    ControlSpec("slider", "Яркость интерфейса", default=72, options={"min": 0, "max": 100, "suffix": "%"}),
                    ControlSpec("checkbox", "Показывать подсказки", default=True),
                    ControlSpec("checkbox", "Плавная анимация", default=True),
                    ControlSpec(
                        "combo",
                        "Режим запуска",
                        default="Стандартный",
                        options={"items": ["Стандартный", "Быстрый", "Тихий"]},
                    ),
                    ControlSpec("button", "Применить базовый шаблон"),
                    ControlSpec("button", "Очистить временные данные"),
                ],
            ),
            SectionSpec(
                title="Параметры",
                controls=[
                    ControlSpec("checkbox", "Защищённый режим", default=True),
                    ControlSpec("checkbox", "Скрывать уведомления", default=False),
                    ControlSpec("checkbox", "Автозапуск с Windows", default=False),
                ],
            ),
            SectionSpec(
                title="Пресеты",
                controls=[
                    ControlSpec("combo", "Профиль", default="Стандарт", options={"items": ["Стандарт", "Работа", "Тихий режим"]}),
                    ControlSpec("button", "Загрузить"),
                    ControlSpec("button", "Сохранить"),
                    ControlSpec("button", "Сброс"),
                    ControlSpec("button", "Выгрузить"),
                ],
            ),
        ],
    ),
    TabSpec(
        id="performance",
        title="Производительность",
        icon="performance",
        sections=[
            SectionSpec(
                title="Профиль производительности",
                controls=[
                    ControlSpec("slider", "Ограничение CPU", default=80, options={"min": 10, "max": 100, "suffix": "%"}),
                    ControlSpec("slider", "Ограничение GPU", default=75, options={"min": 10, "max": 100, "suffix": "%"}),
                    ControlSpec("checkbox", "Умный баланс нагрузки", default=True),
                    ControlSpec("checkbox", "Приоритет активного окна", default=True),
                    ControlSpec("combo", "План питания", default="Сбалансированный", options={"items": ["Эко", "Сбалансированный", "Максимум"]}),
                    ControlSpec("button", "Оптимизировать сейчас"),
                ],
            ),
            SectionSpec(
                title="Параметры",
                controls=[
                    ControlSpec("checkbox", "Мониторинг в фоне", default=True),
                    ControlSpec("checkbox", "Ограничение при простое", default=False),
                    ControlSpec("checkbox", "Журнал производительности", default=True),
                ],
            ),
            SectionSpec(
                title="Пресеты",
                controls=[
                    ControlSpec("combo", "Профиль", default="Сбалансированный", options={"items": ["Эко", "Сбалансированный", "Максимум"]}),
                    ControlSpec("button", "Загрузить"),
                    ControlSpec("button", "Сохранить"),
                    ControlSpec("button", "Сброс"),
                    ControlSpec("button", "Выгрузить"),
                ],
            ),
        ],
    ),
    TabSpec(
        id="fps",
        title="FPS монитор",
        icon="fps",
        sections=[
            SectionSpec(
                title="FPS мониторинг",
                controls=[
                    ControlSpec("checkbox", "Автовыбор активного окна", default=True),
                    ControlSpec("button", "Запустить FPS захват"),
                    ControlSpec("button", "Остановить FPS захват"),
                ],
            ),
            SectionSpec(
                title="Overlay",
                controls=[
                    ControlSpec("button", "Запустить overlay"),
                    ControlSpec("button", "Остановить overlay"),
                    ControlSpec("combo", "Позиция overlay", default="top_left", options={"items": ["top_left", "top_right", "bottom_left", "bottom_right"]}),
                ],
            ),
            SectionSpec(
                title="Диагностика",
                controls=[
                    ControlSpec("checkbox", "Windows only", default=True),
                ],
            ),
        ],
    ),
    TabSpec(
        id="crosshair",
        title="Прицелы",
        icon="crosshair",
        sections=[],
    ),
    TabSpec(
        id="autostart",
        title="Автозапуск",
        icon="autostart",
        sections=[],
    ),
    TabSpec(
        id="temperature",
        title="Температуры",
        icon="temperature",
        sections=[],
    ),
    TabSpec(
        id="ping_monitor",
        title="Пинг",
        icon="ping_monitor",
        sections=[],
    ),
    TabSpec(
        id="netspeed_monitor",
        title="Скорость сети",
        icon="netspeed_monitor",
        sections=[],
    ),
    TabSpec(
        id="task_scheduler",
        title="Планировщик",
        icon="task_scheduler",
        sections=[],
    ),
    TabSpec(
        id="hosts_manager",
        title="Хосты",
        icon="hosts_manager",
        sections=[],
    ),
    TabSpec(
        id="clipboard_manager",
        title="Буфер обмена",
        icon="clipboard_manager",
        sections=[],
    ),
    TabSpec(
        id="analytics",
        title="Analytics",
        icon="analytics",
        sections=[
            SectionSpec(
                title="Game analytics",
                controls=[],
            ),
            SectionSpec(
                title="Settings",
                controls=[],
            ),
            SectionSpec(
                title="Actions",
                controls=[],
            ),
        ],
    ),
    TabSpec(
        id="network",
        title="Сеть",
        icon="network",
        sections=[
            SectionSpec(
                title="Сетевые настройки",
                controls=[
                    ControlSpec("slider", "Лимит исходящего канала", default=65, options={"min": 1, "max": 100, "suffix": "%"}),
                    ControlSpec("slider", "Лимит входящего канала", default=85, options={"min": 1, "max": 100, "suffix": "%"}),
                    ControlSpec("checkbox", "Приоритет голосового трафика", default=True),
                    ControlSpec("checkbox", "Авто-подбор DNS", default=True),
                    ControlSpec("combo", "Профиль сети", default="Домашний", options={"items": ["Домашний", "Офисный", "Публичный"]}),
                    ControlSpec("button", "Перепроверить соединение"),
                ],
            ),
            SectionSpec(
                title="Параметры",
                controls=[
                    ControlSpec("checkbox", "Блокировка фоновых обновлений", default=False),
                    ControlSpec("checkbox", "Снижение пинга (экспериментально)", default=True),
                    ControlSpec("checkbox", "Локальный кэш DNS", default=True),
                ],
            ),
            SectionSpec(
                title="Пресеты",
                controls=[
                    ControlSpec("combo", "Профиль", default="Домашний", options={"items": ["Домашний", "Офисный", "Публичный"]}),
                    ControlSpec("button", "Загрузить"),
                    ControlSpec("button", "Сохранить"),
                    ControlSpec("button", "Сброс"),
                    ControlSpec("button", "Выгрузить"),
                ],
            ),
        ],
    ),
    TabSpec(
        id="telegram_proxy",
        title="Telegram Proxy",
        icon="telegram_proxy",
        sections=[
            SectionSpec(
                title="Telegram proxy",
                controls=[],
            ),
            SectionSpec(
                title="Settings",
                controls=[],
            ),
            SectionSpec(
                title="Status",
                controls=[],
            ),
        ],
    ),
    TabSpec(
        id="discord_quest",
        title="Discord Quest",
        icon="discord_quest",
        sections=[
            SectionSpec(
                title="Discord quests",
                controls=[],
            ),
            SectionSpec(
                title="Settings",
                controls=[],
            ),
            SectionSpec(
                title="Status",
                controls=[],
            ),
        ],
    ),
    TabSpec(
        id="yandex_music_rpc",
        title="Яндекс Музыка",
        icon="yandex_music_rpc",
        sections=[],
    ),
    TabSpec(
        id="security",
        title="Безопасность",
        icon="security",
        sections=[
            SectionSpec(
                title="Контроль безопасности",
                controls=[
                    ControlSpec("checkbox", "Проверка целостности при старте", default=True),
                    ControlSpec("checkbox", "Защита настроек паролем", default=False),
                    ControlSpec("checkbox", "Скрывать данные в логах", default=True),
                    ControlSpec("slider", "Уровень контроля", default=3, options={"min": 1, "max": 5}),
                    ControlSpec("combo", "Политика доступа", default="Стандартная", options={"items": ["Стандартная", "Строгая", "Кастомная"]}),
                    ControlSpec("button", "Запустить проверку"),
                ],
            ),
            SectionSpec(
                title="Параметры",
                controls=[
                    ControlSpec("checkbox", "Уведомлять о рисках", default=True),
                    ControlSpec("checkbox", "Авто-блокировка после простоя", default=False),
                    ControlSpec("checkbox", "Резервная копия конфигурации", default=True),
                ],
            ),
            SectionSpec(
                title="Пресеты",
                controls=[
                    ControlSpec("combo", "Профиль", default="Стандартная", options={"items": ["Стандартная", "Строгая", "Кастомная"]}),
                    ControlSpec("button", "Загрузить"),
                    ControlSpec("button", "Сохранить"),
                    ControlSpec("button", "Сброс"),
                    ControlSpec("button", "Выгрузить"),
                ],
            ),
        ],
    ),
    TabSpec(
        id="ai",
        title="AI Chat",
        icon="ai",
        sections=[
            SectionSpec(
                title="Cloudflare Workers AI",
                controls=[],
            ),
            SectionSpec(
                title="Models",
                controls=[],
            ),
            SectionSpec(
                title="Conversations",
                controls=[],
            ),
        ],
    ),
    TabSpec(
        id="profiles",
        title="Профили",
        icon="profiles",
        sections=[
            SectionSpec(
                title="Управление профилями",
                controls=[
                    ControlSpec("combo", "Текущий профиль", default="Профиль 1", options={"items": ["Профиль 1", "Профиль 2", "Профиль 3"]}),
                    ControlSpec("checkbox", "Авто-применение при запуске", default=True),
                    ControlSpec("checkbox", "Синхронизировать локальные пресеты", default=False),
                    ControlSpec("button", "Создать новый профиль"),
                    ControlSpec("button", "Дублировать текущий"),
                    ControlSpec("button", "Удалить выбранный"),
                ],
            ),
            SectionSpec(
                title="Параметры",
                controls=[
                    ControlSpec("checkbox", "Подтверждать удаление", default=True),
                    ControlSpec("checkbox", "Сохранять историю изменений", default=True),
                    ControlSpec("checkbox", "Быстрое переключение профилей", default=True),
                ],
            ),
            SectionSpec(
                title="Пресеты",
                controls=[
                    ControlSpec("combo", "Профиль", default="Профиль 1", options={"items": ["Профиль 1", "Профиль 2", "Профиль 3"]}),
                    ControlSpec("button", "Загрузить"),
                    ControlSpec("button", "Сохранить"),
                    ControlSpec("button", "Сброс"),
                    ControlSpec("button", "Выгрузить"),
                ],
            ),
        ],
    ),
]


