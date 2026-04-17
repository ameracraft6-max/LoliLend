"""Game tunnel: SOCKS5 endpoint catalog, async ping tester, lightweight local TCP relay.

Builds on the same local-service pattern as `telegram_proxy.py`. The relay is a
protocol-agnostic TCP forwarder: clients (games, browsers) connect to a local
port, we pipe bytes to a selected remote endpoint. If the remote speaks SOCKS5,
clients can speak SOCKS5 through us — we don't interpret the traffic.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


DEFAULT_LOCAL_PORT = 1081
PING_TIMEOUT_SECONDS = 2.0
DEFAULT_ENDPOINTS: list[dict] = [
    {"id": "preset_eu_1", "label": "EU · Amsterdam", "region": "EU", "host": "example-eu.proxy.invalid", "port": 1080, "protocol": "socks5", "notes": "Пример — замени на свой"},
    {"id": "preset_us_1", "label": "US · Chicago", "region": "US", "host": "example-us.proxy.invalid", "port": 1080, "protocol": "socks5", "notes": "Пример — замени на свой"},
    {"id": "preset_as_1", "label": "Asia · Singapore", "region": "Asia", "host": "example-asia.proxy.invalid", "port": 1080, "protocol": "socks5", "notes": "Пример — замени на свой"},
]


@dataclass(slots=True)
class GameTunnelEndpoint:
    id: str
    label: str
    region: str
    host: str
    port: int
    protocol: str = "socks5"   # "socks5" or "direct" (plain TCP forward)
    notes: str = ""

    @staticmethod
    def new(label: str, region: str, host: str, port: int, protocol: str = "socks5", notes: str = "") -> "GameTunnelEndpoint":
        return GameTunnelEndpoint(
            id=uuid.uuid4().hex,
            label=label.strip() or f"{host}:{port}",
            region=region.strip() or "—",
            host=host.strip(),
            port=int(port),
            protocol=protocol if protocol in {"socks5", "direct"} else "socks5",
            notes=notes.strip(),
        )


@dataclass(slots=True)
class GameTunnelState:
    endpoints: list[GameTunnelEndpoint] = field(default_factory=list)
    active_id: str = ""
    local_port: int = DEFAULT_LOCAL_PORT
    ping_cache: dict[str, float] = field(default_factory=dict)


class GameTunnelStore:
    def __init__(self, app_name: str = "LoliLend") -> None:
        base = Path(os.getenv("APPDATA", Path.home())) / app_name
        base.mkdir(parents=True, exist_ok=True)
        self.base_dir = base
        self.path = base / "game_tunnel.json"

    def load(self) -> GameTunnelState:
        if not self.path.exists():
            state = GameTunnelState(endpoints=[GameTunnelEndpoint(**ep) for ep in DEFAULT_ENDPOINTS])
            self.save(state)
            return state
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return GameTunnelState(endpoints=[GameTunnelEndpoint(**ep) for ep in DEFAULT_ENDPOINTS])
        endpoints = []
        for item in raw.get("endpoints", []):
            try:
                endpoints.append(GameTunnelEndpoint(
                    id=str(item.get("id") or uuid.uuid4().hex),
                    label=str(item.get("label") or ""),
                    region=str(item.get("region") or "—"),
                    host=str(item.get("host") or ""),
                    port=int(item.get("port") or 1080),
                    protocol=str(item.get("protocol") or "socks5"),
                    notes=str(item.get("notes") or ""),
                ))
            except (TypeError, ValueError):
                continue
        return GameTunnelState(
            endpoints=endpoints,
            active_id=str(raw.get("active_id") or ""),
            local_port=int(raw.get("local_port") or DEFAULT_LOCAL_PORT),
            ping_cache={str(k): float(v) for k, v in (raw.get("ping_cache") or {}).items() if v is not None},
        )

    def save(self, state: GameTunnelState) -> None:
        payload = {
            "endpoints": [asdict(ep) for ep in state.endpoints],
            "active_id": state.active_id,
            "local_port": int(state.local_port),
            "ping_cache": {k: float(v) for k, v in state.ping_cache.items()},
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def measure_tcp_ping(host: str, port: int, timeout: float = PING_TIMEOUT_SECONDS) -> float | None:
    """Synchronous TCP-connect latency in milliseconds; None on failure/timeout."""
    if not host:
        return None
    try:
        addr_info = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return None
    if not addr_info:
        return None
    family, socktype, proto, _canon, sockaddr = addr_info[0]
    s = socket.socket(family, socktype, proto)
    s.settimeout(timeout)
    start = time.perf_counter()
    try:
        s.connect(sockaddr)
    except (socket.timeout, OSError):
        return None
    finally:
        try:
            s.close()
        except OSError:
            pass
    return (time.perf_counter() - start) * 1000.0


# ---------- Local TCP relay ----------

class TcpRelay:
    """Accepts inbound TCP connections on a local port and forwards them to a remote (host, port).

    Protocol-agnostic: we never parse SOCKS/HTTP. Games that support SOCKS5 pointed at us will
    speak SOCKS5 end-to-end with the remote endpoint. Direct-TCP games likewise pass through.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._lock = threading.RLock()
        self._last_error = ""
        self._bound_endpoint: tuple[str, int] = ("", 0)
        self._active_target: tuple[str, int] | None = None
        self._bytes_in = 0
        self._bytes_out = 0
        self._connections = 0

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self.is_running(),
                "bound": f"127.0.0.1:{self._bound_endpoint[1]}" if self._bound_endpoint[1] else "",
                "target": f"{self._active_target[0]}:{self._active_target[1]}" if self._active_target else "",
                "connections": self._connections,
                "bytes_in": self._bytes_in,
                "bytes_out": self._bytes_out,
                "last_error": self._last_error,
            }

    def start(self, local_port: int, remote_host: str, remote_port: int) -> tuple[bool, str]:
        if self.is_running():
            return False, "Туннель уже запущен"
        if not remote_host:
            return False, "Не указан удалённый хост"
        local_port = max(1, min(65535, int(local_port or DEFAULT_LOCAL_PORT)))
        with self._lock:
            self._last_error = ""
            self._bound_endpoint = ("127.0.0.1", local_port)
            self._active_target = (remote_host, int(remote_port))
            self._bytes_in = 0
            self._bytes_out = 0
            self._connections = 0
        ready = threading.Event()
        worker = threading.Thread(
            target=self._run_worker,
            args=(local_port, remote_host, int(remote_port), ready),
            daemon=True,
            name="lolilend-game-tunnel",
        )
        with self._lock:
            self._thread = worker
        worker.start()
        ready.wait(timeout=2.0)
        with self._lock:
            if self._last_error:
                return False, self._last_error
            if self._thread is None or not self._thread.is_alive():
                return False, self._last_error or "Не удалось запустить туннель"
        return True, f"Туннель запущен на 127.0.0.1:{local_port} → {remote_host}:{remote_port}"

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            thread = self._thread
            loop = self._loop
            stop_event = self._stop_event
        if thread is None or not thread.is_alive():
            with self._lock:
                self._thread = None
            return True, "Туннель не запущен"
        if loop is not None and stop_event is not None:
            try:
                loop.call_soon_threadsafe(stop_event.set)
            except RuntimeError:
                pass
        thread.join(timeout=3.0)
        with self._lock:
            self._thread = None
            self._loop = None
            self._stop_event = None
        if thread.is_alive():
            return False, "Туннель не остановился вовремя"
        return True, "Туннель остановлен"

    def _run_worker(self, local_port: int, remote_host: str, remote_port: int, ready: threading.Event) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stop_event = asyncio.Event()
        with self._lock:
            self._loop = loop
            self._stop_event = stop_event
        try:
            loop.run_until_complete(self._serve(local_port, remote_host, remote_port, stop_event, ready))
        except OSError as exc:
            with self._lock:
                self._last_error = f"Не удалось занять порт: {exc}"
            ready.set()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"Ошибка туннеля: {exc}"
            ready.set()
        finally:
            try:
                pending = [t for t in asyncio.all_tasks(loop=loop) if not t.done()]
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                loop.close()
            with self._lock:
                self._loop = None
                self._stop_event = None

    async def _serve(
        self,
        local_port: int,
        remote_host: str,
        remote_port: int,
        stop_event: asyncio.Event,
        ready: threading.Event,
    ) -> None:
        server = await asyncio.start_server(
            lambda r, w: self._handle_client(r, w, remote_host, remote_port),
            host="127.0.0.1",
            port=local_port,
        )
        ready.set()
        async with server:
            stop_task = asyncio.create_task(stop_event.wait())
            serve_task = asyncio.create_task(server.serve_forever())
            done, pending = await asyncio.wait(
                {stop_task, serve_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            server.close()
            try:
                await server.wait_closed()
            except Exception:
                pass

    async def _handle_client(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        remote_host: str,
        remote_port: int,
    ) -> None:
        with self._lock:
            self._connections += 1
        try:
            try:
                remote_reader, remote_writer = await asyncio.wait_for(
                    asyncio.open_connection(remote_host, remote_port), timeout=5.0
                )
            except (OSError, asyncio.TimeoutError) as exc:
                with self._lock:
                    self._last_error = f"Не удалось соединиться с удалённым: {exc}"
                client_writer.close()
                try:
                    await client_writer.wait_closed()
                except Exception:
                    pass
                return
            await asyncio.gather(
                self._pipe(client_reader, remote_writer, is_uplink=True),
                self._pipe(remote_reader, client_writer, is_uplink=False),
                return_exceptions=True,
            )
        finally:
            for w in (client_writer,):
                try:
                    w.close()
                    await w.wait_closed()
                except Exception:
                    pass

    async def _pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, is_uplink: bool) -> None:
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
                with self._lock:
                    if is_uplink:
                        self._bytes_out += len(chunk)
                    else:
                        self._bytes_in += len(chunk)
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass


# ---------- Windows system proxy toggle ----------

class SystemProxyManager:
    """Sets HKCU WinINet proxy settings (ProxyEnable, ProxyServer). Windows-only."""

    @staticmethod
    def available() -> bool:
        return os.name == "nt"

    @staticmethod
    def _key():
        import winreg  # noqa: PLC0415 — import guarded by .available()
        return winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        )

    @classmethod
    def enable(cls, host: str, port: int) -> tuple[bool, str]:
        if not cls.available():
            return False, "Системный прокси доступен только в Windows"
        import winreg  # noqa: PLC0415
        try:
            with cls._key() as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"socks={host}:{port}")
            cls._notify_change()
            return True, f"Системный прокси включён: socks={host}:{port}"
        except OSError as exc:
            return False, f"Ошибка реестра: {exc}"

    @classmethod
    def disable(cls) -> tuple[bool, str]:
        if not cls.available():
            return False, "Системный прокси доступен только в Windows"
        import winreg  # noqa: PLC0415
        try:
            with cls._key() as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            cls._notify_change()
            return True, "Системный прокси выключен"
        except OSError as exc:
            return False, f"Ошибка реестра: {exc}"

    @classmethod
    def status(cls) -> tuple[bool, str]:
        if not cls.available():
            return False, ""
        import winreg  # noqa: PLC0415
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0,
                winreg.KEY_READ,
            ) as key:
                enabled_raw, _ = winreg.QueryValueEx(key, "ProxyEnable")
                try:
                    server, _ = winreg.QueryValueEx(key, "ProxyServer")
                except FileNotFoundError:
                    server = ""
                return bool(enabled_raw), str(server)
        except OSError:
            return False, ""

    @staticmethod
    def _notify_change() -> None:
        """Notifies WinINet that settings changed so Chrome/Edge pick up the new proxy."""
        try:
            import ctypes  # noqa: PLC0415
            INTERNET_OPTION_SETTINGS_CHANGED = 39
            INTERNET_OPTION_REFRESH = 37
            wininet = ctypes.windll.wininet
            wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
            wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
        except Exception:
            pass
