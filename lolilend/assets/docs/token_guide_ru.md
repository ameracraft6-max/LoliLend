# LoliLend Discord Quest v3 - tokenless guide

## 1) Без OAuth и без токена

Discord Quest v3 не использует OAuth и не требует ручного Discord token.
Вкладка работает в режиме upstream-style completion через dummy executable.

## 2) Как пользоваться

1. Откройте вкладку `Discord Quest`.
2. Нажмите `Refetch Game List` (или используйте авто-загрузку при открытии вкладки).
3. Найдите игру через `Search` и нажмите `Add game to list`.
4. Выберите игру слева и executable справа.
5. Используйте:
   - `Install & Play` для первого запуска,
   - `Play` для повторного запуска,
   - `Stop` для остановки.

## 3) Источники каталога игр

LoliLend использует приоритет:

1. `https://markterence.github.io/discord-quest-completer/detectable.json`
2. Discord detectable endpoint
3. Встроенный snapshot (`lolilend/assets/runtime/discord_quest/detectable.snapshot.json`)

## 4) Экспериментальный Test RPC

- Кнопка `Test RPC` включает экспериментальную Rich Presence-активность.
- Функция может работать нестабильно и сопровождается предупреждением о рисках.
- Для RPC требуется установленный `pypresence`.

## 5) Где хранятся данные

- Конфиг вкладки: `%APPDATA%/LoliLend/discord_quest.json`
- Кэш каталога: `%APPDATA%/LoliLend/discord_quest_cache.json`
- Логи: `%APPDATA%/LoliLend/discord_quest.log`

## 6) Важно по безопасности

- Функции completion/RPC могут нарушать правила Discord.
- Используйте на свой риск.
- Рекомендуется тестовый аккаунт для экспериментов.
