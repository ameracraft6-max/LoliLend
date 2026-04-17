"""Cloudflare-Workers-AI brain for the companion: generates short contextual speech lines.

Token is stored in the Windows Credential Vault via the existing `WindowsCredentialStore`
abstraction (never written to disk in plaintext, never logged, never committed).
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass

from lolilend.ai_security import CF_ACCOUNT_ID, WindowsCredentialStore
from lolilend.companion import CompanionState


COMPANION_TOKEN_TARGET = "LoliLend.Companion.Cloudflare.Token"
COMPANION_MODEL = "@cf/meta/llama-3.2-3b-instruct"
COMPANION_MAX_TOKENS = 32
MIN_SECONDS_BETWEEN_CALLS = 8.0
CACHE_TTL_SECONDS = 90.0

# Per-state system prompts that describe the companion's personality.
_STATE_PROMPTS: dict[CompanionState, str] = {
    CompanionState.IDLE: "расслабленное ожидание",
    CompanionState.HAPPY: "радостное приветствие новой игры",
    CompanionState.WINK: "дружеское подмигивание при запуске",
    CompanionState.SCARED: "испуг от перегрева процессора",
    CompanionState.SLEEPY: "сонливость и зевота",
    CompanionState.EXCITED: "восторг и ликование",
}

_SYSTEM_PROMPT = (
    "Ты милая аниме-чиби-девочка по имени Лоли, талисман приложения LoliLend. "
    "Говори ОДНУ короткую реплику на русском языке: 2-5 слов, без кавычек и пояснений. "
    "Допускаются эмодзи и восклицания. Никаких смайликов из символов. "
    "Никогда не начинай фразу с 'Конечно' или 'Хорошо'. "
    "Только сама реплика, без префиксов."
)


class CompanionTokenStore:
    """Wraps WindowsCredentialStore with the companion-specific target."""

    def __init__(self) -> None:
        self._store = WindowsCredentialStore(target=COMPANION_TOKEN_TARGET)

    def load(self) -> str:
        return (self._store.read() or "").strip()

    def save(self, token: str) -> bool:
        return self._store.write(token.strip())

    def clear(self) -> bool:
        # WindowsCredentialStore has no delete — overwrite with a placeholder.
        # Read() will still return it, so we treat empty string as "not set".
        return self._store.write("")

    def has_token(self) -> bool:
        return bool(self.load())


@dataclass(slots=True)
class _CacheEntry:
    phrase: str
    stored_at: float


class CompanionAiBrain:
    """Lazy, throttled client that asks Cloudflare Workers AI for short in-character lines.

    - Falls back to a hard-coded phrase when the token is missing or the request fails.
    - Caches per-state phrases for CACHE_TTL_SECONDS to avoid hammering the API.
    - Runs requests on a worker thread so the UI never blocks.
    """

    FALLBACKS: dict[CompanionState, list[str]] = {
        CompanionState.IDLE: ["Ня~", "Всё спокойно", "Я здесь"],
        CompanionState.HAPPY: ["Поиграем!", "Ура, игра!", "Давай играть!"],
        CompanionState.WINK: ["Let's play!", "Привет!", "Готова!"],
        CompanionState.SCARED: ["CPU горит!", "Ой-ой!", "Жарко!!"],
        CompanionState.SLEEPY: ["zZ...", "Спать хочется", "Тихо..."],
        CompanionState.EXCITED: ["Ура!", "Да!", "Супер!"],
    }

    def __init__(self, token_store: CompanionTokenStore | None = None) -> None:
        self._token_store = token_store or CompanionTokenStore()
        self._cache: dict[CompanionState, _CacheEntry] = {}
        self._last_call_at = 0.0
        self._lock = threading.Lock()
        self._client = None

    # ---------- token plumbing ----------
    def is_configured(self) -> bool:
        return self._token_store.has_token()

    def set_token(self, token: str) -> tuple[bool, str]:
        token = token.strip()
        if not token:
            self._token_store.clear()
            self._client = None
            return True, "Токен компаньона очищен"
        ok = self._token_store.save(token)
        if not ok:
            return False, "Не удалось сохранить токен в Windows Credentials"
        self._client = None  # rebuild on next call
        return True, "Токен сохранён в Windows Credentials Vault"

    def _client_or_none(self):
        token = self._token_store.load()
        if not token:
            return None
        if self._client is not None:
            return self._client
        try:
            from lolilend.ai_client import CloudflareAiClient
            self._client = CloudflareAiClient(CF_ACCOUNT_ID, token, timeout_seconds=15)
            return self._client
        except Exception:
            return None

    # ---------- phrase lookup ----------
    def fallback_phrase(self, state: CompanionState) -> str:
        return random.choice(self.FALLBACKS.get(state, ["..."]))

    def cached_phrase(self, state: CompanionState) -> str | None:
        entry = self._cache.get(state)
        if entry is None:
            return None
        if time.monotonic() - entry.stored_at > CACHE_TTL_SECONDS:
            return None
        return entry.phrase

    def generate_async(self, state: CompanionState, on_ready) -> None:
        """Generates a phrase on a worker thread. Calls on_ready(state, phrase) when done.

        If rate-limited or the API is unreachable, delivers a fallback instead.
        """
        cached = self.cached_phrase(state)
        if cached is not None:
            on_ready(state, cached)
            return

        now = time.monotonic()
        with self._lock:
            if now - self._last_call_at < MIN_SECONDS_BETWEEN_CALLS:
                # Throttled — serve fallback immediately.
                on_ready(state, self.fallback_phrase(state))
                return
            self._last_call_at = now

        client = self._client_or_none()
        if client is None:
            on_ready(state, self.fallback_phrase(state))
            return

        def _worker():
            phrase = self._request(client, state) or self.fallback_phrase(state)
            self._cache[state] = _CacheEntry(phrase=phrase, stored_at=time.monotonic())
            try:
                on_ready(state, phrase)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True, name="companion-ai").start()

    def _request(self, client, state: CompanionState) -> str | None:
        from lolilend.ai_client import AiRequestOptions, ChatMessagePayload, OPENAI_COMPATIBLE
        context = _STATE_PROMPTS.get(state, "нейтральное состояние")
        options = AiRequestOptions(
            protocol=OPENAI_COMPATIBLE,
            model=COMPANION_MODEL,
            temperature=0.85,
            max_tokens=COMPANION_MAX_TOKENS,
            system_prompt=_SYSTEM_PROMPT,
        )
        user_msg = f"Состояние: {context}. Реплика:"
        messages = [
            ChatMessagePayload(role="system", content=_SYSTEM_PROMPT),
            ChatMessagePayload(role="user", content=user_msg),
        ]
        try:
            raw = client.send_chat(messages, options)
        except Exception:
            return None
        if not raw:
            return None
        phrase = _sanitize_phrase(raw)
        return phrase or None


def _sanitize_phrase(raw: str) -> str:
    text = str(raw).strip()
    # Strip surrounding quotes the model sometimes adds.
    for pair in (('"', '"'), ("«", "»"), ("'", "'"), ("'", "'"), ("“", "”")):
        if text.startswith(pair[0]) and text.endswith(pair[1]):
            text = text[1:-1].strip()
    # Keep only first line.
    text = text.splitlines()[0].strip() if text else ""
    # Drop trailing punctuation drift.
    text = text.rstrip(".,;:")
    # Cap at 40 chars so it fits the bubble.
    if len(text) > 40:
        text = text[:37].rstrip() + "..."
    return text
