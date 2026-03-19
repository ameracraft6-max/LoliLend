from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

_log = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2.0


class LicenseError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class ActivationResult:
    success: bool
    token: str
    expires_at: str
    duration_days: int | None
    hwid_resets: int
    max_hwid_resets: int
    message: str


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    expires_at: str
    status: str
    message: str


@dataclass(slots=True)
class HeartbeatResult:
    ok: bool
    screenshot_request_id: str | None
    message: str


class LicenseClient:
    """HTTP client for the LoliLend license server."""

    def __init__(self, server_url: str, timeout: int = 30) -> None:
        self._server_url = server_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def activate(self, key: str, hwid: str) -> ActivationResult:
        """Activate a license key with HWID binding."""
        data = self._post("/api/activate", {"key": key, "hwid": hwid})
        return ActivationResult(
            success=data.get("success", False),
            token=data.get("token", ""),
            expires_at=data.get("expires_at", ""),
            duration_days=data.get("duration_days"),
            hwid_resets=data.get("hwid_resets", 0),
            max_hwid_resets=data.get("max_hwid_resets", 3),
            message=data.get("message", ""),
        )

    def validate(self, token: str, hwid: str) -> ValidationResult:
        """Validate an active license token."""
        data = self._post("/api/validate", {"token": token, "hwid": hwid})
        return ValidationResult(
            valid=data.get("valid", False),
            expires_at=data.get("expires_at", ""),
            status=data.get("status", ""),
            message=data.get("message", ""),
        )

    def heartbeat(self, token: str, hwid: str, version: str) -> HeartbeatResult:
        """Send periodic heartbeat. Returns screenshot request if pending."""
        data = self._post(
            "/api/heartbeat",
            {"token": token, "hwid": hwid, "version": version},
        )
        return HeartbeatResult(
            ok=data.get("ok", False),
            screenshot_request_id=data.get("screenshot_request_id"),
            message=data.get("message", ""),
        )

    def upload_screenshot(self, request_id: str, image_data: bytes) -> bool:
        """Upload a JPEG screenshot for a pending request."""
        import base64

        data = self._post(
            "/api/screenshot",
            {
                "request_id": request_id,
                "image": base64.b64encode(image_data).decode("ascii"),
            },
        )
        return data.get("ok", False)

    # ------------------------------------------------------------------
    # Offline cache
    # ------------------------------------------------------------------

    @staticmethod
    def save_validation_cache(cache_path: Path, result: ValidationResult) -> None:
        """Persist last successful validation for offline grace period."""
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "valid": result.valid,
            "expires_at": result.expires_at,
            "status": result.status,
            "cached_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def load_validation_cache(cache_path: Path) -> dict[str, Any] | None:
        """Load cached validation result. Returns None if missing/corrupt."""
        if not cache_path.is_file():
            return None
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._server_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    timeout=self._timeout,
                    headers={"Content-Type": "application/json"},
                )
                return self._read_json(resp)
            except LicenseError:
                raise
            except requests.ConnectionError as exc:
                last_exc = exc
                _log.warning("Connection failed (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
            except requests.Timeout as exc:
                last_exc = exc
                _log.warning("Request timed out (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
            except Exception as exc:
                last_exc = exc
                _log.warning("Request error (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

        raise LicenseError(
            f"Сервер недоступен после {MAX_RETRIES} попыток: {last_exc}",
        )

    @staticmethod
    def _read_json(response: requests.Response) -> dict[str, Any]:
        if not response.ok:
            try:
                body = response.json()
                msg = body.get("error") or body.get("message") or response.text
            except Exception:
                msg = response.text or f"HTTP {response.status_code}"
            raise LicenseError(str(msg), response.status_code)

        try:
            data = response.json()
        except ValueError as exc:
            raise LicenseError(f"Неверный ответ сервера: {exc}", response.status_code)

        if not isinstance(data, dict):
            raise LicenseError("Неверный формат ответа", response.status_code)

        return data
