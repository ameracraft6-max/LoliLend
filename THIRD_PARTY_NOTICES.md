# Third-Party Notices

## Flowseal tg-ws-proxy

- Source: <https://github.com/Flowseal/tg-ws-proxy>
- Upstream License: MIT
- Local usage in this project:
  - `lolilend/tg_ws_proxy_core.py` contains the embedded proxy core adapted from upstream `proxy/tg_ws_proxy.py`.
- Copyright:
  - Copyright (c) Flowseal contributors

The upstream MIT license applies to the embedded source and must be preserved with attribution.

## markterence discord-quest-completer

- Source: <https://github.com/markterence/discord-quest-completer>
- Upstream License: MIT
- Local usage in this project:
  - `lolilend/assets/runtime/discord_quest/runner_template.exe` is bundled from upstream release artifacts (`data/src-win.exe`) and used as dummy runner template.
  - `lolilend/assets/runtime/discord_quest/detectable.snapshot.json` is derived from upstream detectable catalog mirror for offline fallback.
  - `lolilend/discord_quests.py` and Discord Quest tab behavior in `lolilend/ui.py` adapt upstream completion flow concepts (detectable catalog fetching, game list actions, install/play/stop, experimental RPC toggle).
- Copyright:
  - Copyright (c) Mark Terence Tiglao

The upstream MIT license applies to bundled/derived runtime resources and attribution must be preserved.
