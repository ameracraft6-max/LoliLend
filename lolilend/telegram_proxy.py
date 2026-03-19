from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib
import json
import logging
import os
from pathlib import Path
import socket
import threading
import time
from types import ModuleType
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import asyncio


DEFAULT_DC_IP = ["2:149.154.167.220", "4:149.154.167.220"]
_LOGGER_NAME = "tg-ws-proxy"


def _asyncio_module():
    import asyncio

    return asyncio


@dataclass(slots=True)
class TelegramProxyConfig:
    host: str = "127.0.0.1"
    port: int = 1080
    dc_ip: list[str] | None = None
    verbose: bool = False

    def normalized(self) -> TelegramProxyConfig:
        host = str(self.host).strip() or "127.0.0.1"
        try:
            port = int(self.port)
        except (TypeError, ValueError):
            port = 1080
        port = max(1, min(65535, port))
        dc_raw = self.dc_ip if isinstance(self.dc_ip, list) else list(DEFAULT_DC_IP)
        dc_values = [str(value).strip() for value in dc_raw if str(value).strip()]
        if not dc_values:
            dc_values = list(DEFAULT_DC_IP)
        return TelegramProxyConfig(
            host=host,
            port=port,
            dc_ip=dc_values,
            verbose=bool(self.verbose),
        )


@dataclass(slots=True)
class TelegramProxyStatus:
    running: bool
    endpoint: str
    last_error: str
    log_path: str


class TelegramProxyStore:
    def __init__(self, app_name: str = "LoliLend") -> None:
        base = Path(os.getenv("APPDATA", Path.home())) / app_name
        base.mkdir(parents=True, exist_ok=True)
        self.base_dir = base
        self.config_path = base / "telegram_proxy.json"
        self.log_path = base / "telegram_proxy.log"

    def load_config(self) -> TelegramProxyConfig:
        raw = self._load_raw()
        config = TelegramProxyConfig(
            host=str(raw.get("host", "127.0.0.1")),
            port=raw.get("port", 1080),
            dc_ip=raw.get("dc_ip", list(DEFAULT_DC_IP)),
            verbose=bool(raw.get("verbose", False)),
        )
        return config.normalized()

    def save_config(self, config: TelegramProxyConfig) -> None:
        normalized = config.normalized()
        self.config_path.write_text(
            json.dumps(asdict(normalized), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_raw(self) -> dict:
        if not self.config_path.exists():
            return {}
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}


class TelegramProxyCore(Protocol):
    def parse_dc_ip_list(self, dc_ip_list: list[str]) -> dict[int, str]: ...

    def create_run_coroutine(
        self,
        port: int,
        dc_opt: dict[int, str],
        stop_event: asyncio.Event,
        host: str,
    ): ...


class DefaultTelegramProxyCore:
    def __init__(self, module_name: str = "lolilend.tg_ws_proxy_core") -> None:
        self._module_name = module_name
        self._module: ModuleType | None = None

    def _load(self) -> ModuleType:
        if self._module is not None:
            return self._module
        try:
            self._module = importlib.import_module(self._module_name)
            return self._module
        except ModuleNotFoundError as exc:
            if exc.name and "cryptography" in exc.name:
                raise RuntimeError(
                    "Missing dependency 'cryptography'. Install requirements to run Telegram Proxy."
                ) from exc
            raise

    def parse_dc_ip_list(self, dc_ip_list: list[str]) -> dict[int, str]:
        module = self._load()
        return module.parse_dc_ip_list(dc_ip_list)

    def create_run_coroutine(
        self,
        port: int,
        dc_opt: dict[int, str],
        stop_event: asyncio.Event,
        host: str,
    ):
        module = self._load()
        return module._run(port=port, dc_opt=dc_opt, stop_event=stop_event, host=host)


class TelegramProxyService:
    def __init__(
        self,
        store: TelegramProxyStore | None = None,
        core: TelegramProxyCore | None = None,
    ) -> None:
        self._store = store or TelegramProxyStore()
        self._core = core or DefaultTelegramProxyCore()
        self._logger = logging.getLogger(_LOGGER_NAME)
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._last_error = ""
        self._stopping = False
        self._active_config = self._store.load_config()

    @staticmethod
    def validate_config(config: TelegramProxyConfig) -> TelegramProxyConfig:
        normalized = config.normalized()
        host = normalized.host.strip()
        if not host:
            raise ValueError("Host is required.")
        if host not in {"localhost"}:
            try:
                socket.inet_aton(host)
            except OSError:
                raise ValueError("Host must be a valid IPv4 address or localhost.") from None
        if not (1 <= int(normalized.port) <= 65535):
            raise ValueError("Port must be in range 1..65535.")
        return normalized

    def start(self, config: TelegramProxyConfig) -> tuple[bool, str]:
        try:
            validated = self.validate_config(config)
            dc_opt = self._core.parse_dc_ip_list(list(validated.dc_ip or []))
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = str(exc)
            return False, f"Telegram Proxy config error: {exc}"

        with self._lock:
            thread = self._thread
            if thread is not None and thread.is_alive():
                self._active_config = validated
                return True, f"Telegram Proxy already running at {self._endpoint(validated)}"
            self._active_config = validated
            self._stopping = False
            self._last_error = ""
            self._configure_logging(validated.verbose)
            worker = threading.Thread(
                target=self._run_worker,
                args=(validated, dc_opt),
                daemon=True,
                name="lolilend-telegram-proxy",
            )
            self._thread = worker
            worker.start()

        time.sleep(0.05)
        with self._lock:
            thread_after = self._thread
            if thread_after is None or not thread_after.is_alive():
                message = self._last_error or "Failed to start Telegram Proxy."
                return False, message
        return True, f"Telegram Proxy started at {self._endpoint(validated)}"

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            thread = self._thread
            if thread is None or not thread.is_alive():
                self._thread = None
                self._close_logging_handlers()
                return True, "Telegram Proxy is not running."
            loop = self._loop
            stop_event = self._stop_event
            self._stopping = True

        if loop is not None and stop_event is not None:
            try:
                loop.call_soon_threadsafe(stop_event.set)
            except RuntimeError:
                pass

        thread.join(timeout=4.0)
        if thread.is_alive():
            with self._lock:
                self._last_error = "Telegram Proxy did not stop in time."
                self._stopping = False
            return False, "Telegram Proxy did not stop in time."

        with self._lock:
            self._stopping = False
            self._close_logging_handlers()
        return True, "Telegram Proxy stopped."

    def restart(self, config: TelegramProxyConfig) -> tuple[bool, str]:
        stopped, stop_message = self.stop()
        if not stopped:
            return False, stop_message
        return self.start(config)

    def is_running(self) -> bool:
        with self._lock:
            thread = self._thread
            return thread is not None and thread.is_alive()

    def status(self) -> TelegramProxyStatus:
        with self._lock:
            config = self._active_config
            return TelegramProxyStatus(
                running=self.is_running(),
                endpoint=self._endpoint(config),
                last_error=self._last_error,
                log_path=str(self._store.log_path),
            )

    def shutdown(self) -> None:
        self.stop()
        with self._lock:
            self._close_logging_handlers()

    @staticmethod
    def telegram_proxy_url(config: TelegramProxyConfig) -> str:
        validated = config.normalized()
        return f"tg://socks?server={validated.host}&port={validated.port}"

    @staticmethod
    def _endpoint(config: TelegramProxyConfig) -> str:
        validated = config.normalized()
        return f"{validated.host}:{validated.port}"

    def _configure_logging(self, verbose: bool) -> None:
        self._store.base_dir.mkdir(parents=True, exist_ok=True)
        self._close_logging_handlers()
        file_handler = logging.FileHandler(self._store.log_path, encoding="utf-8")
        file_handler._lolilend_proxy_handler = True  # type: ignore[attr-defined]
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        self._logger.addHandler(file_handler)
        self._logger.setLevel(logging.DEBUG if verbose else logging.INFO)
        self._logger.propagate = False

    def _close_logging_handlers(self) -> None:
        for handler in list(self._logger.handlers):
            if not getattr(handler, "_lolilend_proxy_handler", False):
                continue
            self._logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # pragma: no cover - defensive cleanup
                pass

    def _run_worker(self, config: TelegramProxyConfig, dc_opt: dict[int, str]) -> None:
        asyncio = _asyncio_module()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stop_event = asyncio.Event()
        with self._lock:
            self._loop = loop
            self._stop_event = stop_event
        try:
            coroutine = self._core.create_run_coroutine(
                port=config.port,
                dc_opt=dc_opt,
                stop_event=stop_event,
                host=config.host,
            )
            loop.run_until_complete(coroutine)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                if not self._stopping:
                    self._last_error = f"Telegram Proxy crashed: {exc}"
            try:
                self._logger.exception("Telegram Proxy crashed")
            except Exception:
                pass
        finally:
            pending = [task for task in asyncio.all_tasks(loop=loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            with self._lock:
                self._loop = None
                self._stop_event = None
                self._thread = None
